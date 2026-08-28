"""Orquestador de la conversación de emisión (fase 5.2).

Recibe un mensaje ya verificado y decide qué responder. NO envía nada a Meta:
devuelve las respuestas y quien lo llama las despacha. Así el flujo se puede
probar entero sin red, que es como se verifica el checklist F5.

La regla que manda: emitir exige confirmación explícita del usuario (A06).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.db.models import Certificado, ClienteFinal, Comprobante, Tenant, User
from app.db.models.enums import EstadoComprobante, Rol
from app.services import emision
from app.services.emision import EmisionError
from app.services.planes import LimitePlanError, plan_vigente
from app.whatsapp import conversacion as conv
from app.whatsapp.conversacion import EstadoConversacion, Paso, Respuesta
from app.whatsapp.intents import Intent, reconocer

TZ = ZoneInfo("America/Guayaquil")


class NumeroNoAutorizado(Exception):
    """El número no está autorizado a emitir por ninguna cuenta."""


@dataclass
class Entrante:
    wa_phone: str
    texto: str
    tipo: str = "TEXTO"
    boton_id: str | None = None
    lista_id: str | None = None
    wa_message_id: str | None = None


def tenant_por_telefono(db: Session, wa_phone: str) -> Tenant:
    """Resuelve de qué cuenta es el número que escribe.

    Va por función segura y NO por consulta directa: `tenants` está cerrada
    incluso para el contexto interno (política de la migración 0002), así que
    una consulta directa desde el worker devuelve siempre vacío y todo mensaje
    legítimo acabaría rechazado como número no autorizado.

    La función devuelve solo el identificador; la ficha se lee después con el
    contexto del propio inquilino, donde RLS ya la deja ver.
    """
    normalizado = "".join(c for c in wa_phone if c.isdigit())
    fila = db.execute(
        text("SELECT id FROM sys_tenant_por_telefono(:t)"), {"t": normalizado}
    ).first()
    if fila is not None:
        tenant = db.get(Tenant, fila[0])
        if tenant is not None:
            return tenant
        # Sesión sin permiso de lectura sobre la ficha: se devuelve un objeto
        # mínimo con el id, que es lo único que el llamador necesita para abrir
        # la sesión del inquilino.
        return Tenant(id=fila[0])
    raise NumeroNoAutorizado("Este número no está asociado a ninguna cuenta de Factuchat.")


def _buscar_clientes(db: Session, consulta: str) -> list[ClienteFinal]:
    patron = f"%{consulta.strip()}%"
    return list(
        db.scalars(
            select(ClienteFinal)
            .where(
                or_(
                    ClienteFinal.razon_social.ilike(patron),
                    ClienteFinal.identificacion.ilike(patron),
                )
            )
            .order_by(ClienteFinal.razon_social)
            .limit(10)
        ).all()
    )


def _a_candidato(c: ClienteFinal) -> dict:
    etiqueta = "RUC" if c.tipo_identificacion.value == "RUC" else "Cédula"
    return {
        "id": str(c.id),
        "titulo": c.razon_social,
        "subtitulo": f"{etiqueta} {c.identificacion}",
    }


def _monto(texto: str) -> Decimal | None:
    try:
        return Decimal(texto.strip().replace("$", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


def _usuario_del_tenant(db: Session, tenant_id: uuid.UUID) -> User | None:
    return db.scalars(
        select(User).where(User.tenant_id == tenant_id, User.rol == Rol.CLIENTE)
    ).first()


def procesar(db: Session, tenant: Tenant, entrante: Entrante) -> list[Respuesta]:
    """Devuelve las respuestas a enviar, en orden."""
    estado = conv.cargar(tenant.id, entrante.wa_phone)

    if entrante.tipo in ("AUDIO", "VIDEO"):
        return [conv.SIN_AUDIO]

    # Un botón o un elemento de lista mandan más que el texto libre
    accion = entrante.boton_id or entrante.lista_id
    if accion:
        return _por_accion(db, tenant, entrante, estado, accion)

    reconocido = reconocer(entrante.texto)

    # Cancelar y confirmar mandan siempre: son las dos salidas del flujo.
    if reconocido.intent == Intent.CANCELAR:
        conv.limpiar(tenant.id, entrante.wa_phone)
        return [conv.CANCELADO]

    if reconocido.intent == Intent.CONFIRMAR and estado.paso == Paso.CONFIRMAR:
        return _autorizar(db, tenant, entrante, estado)

    # Si el asistente PREGUNTÓ algo, lo que llega es la RESPUESTA, no una
    # intención nueva. Sin esta guarda, un detalle como "Servicio de consultoría"
    # se leería como el intent CONSULTAR y descarrilaría la factura a medias.
    if estado.paso in (Paso.ESPERA_CLIENTE, Paso.ESPERA_DETALLE, Paso.ESPERA_MONTO):
        return _completar(db, tenant, entrante, estado)

    if reconocido.intent == Intent.AYUDA:
        return [conv.AYUDA]

    if reconocido.intent == Intent.REPORTE:
        return [_reporte(db, tenant)]

    if reconocido.intent == Intent.CONSULTAR:
        return [_ultimos(db, tenant)]

    if reconocido.intent == Intent.FACTURAR:
        estado = EstadoConversacion()
        if reconocido.nombre or reconocido.identificacion:
            consulta = reconocido.identificacion or reconocido.nombre or ""
            respuestas, estado = _resolver_cliente(db, estado, consulta)
            if reconocido.monto is not None:
                estado.monto = str(reconocido.monto)
            conv.guardar(tenant.id, entrante.wa_phone, estado)
            if respuestas:
                return respuestas
        else:
            if reconocido.monto is not None:
                estado.monto = str(reconocido.monto)
            estado.paso = Paso.ESPERA_CLIENTE
            conv.guardar(tenant.id, entrante.wa_phone, estado)
            return [conv.pedir("cliente")]
        return _siguiente(db, tenant, entrante, estado)

    return [conv.MENU_PRINCIPAL]


def _resolver_cliente(
    db: Session, estado: EstadoConversacion, consulta: str
) -> tuple[list[Respuesta], EstadoConversacion]:
    encontrados = _buscar_clientes(db, consulta)
    if not encontrados:
        estado.paso = Paso.ESPERA_CLIENTE
        return (
            [
                Respuesta(
                    texto=(
                        f"No encontré a nadie con “{consulta}”.\n\n"
                        "Mándame el RUC o la cédula y traigo la razón social desde el SRI."
                    )
                )
            ],
            estado,
        )
    if len(encontrados) == 1:
        c = encontrados[0]
        estado.cliente_id = str(c.id)
        estado.cliente_nombre = c.razon_social
        estado.cliente_identificacion = c.identificacion
        return [], estado
    estado.candidatos = [_a_candidato(c) for c in encontrados]
    estado.paso = Paso.ESPERA_CLIENTE
    return [conv.elegir_entre(estado.candidatos, consulta)], estado


def _completar(
    db: Session, tenant: Tenant, entrante: Entrante, estado: EstadoConversacion
) -> list[Respuesta]:
    texto = entrante.texto.strip()

    if estado.paso == Paso.ESPERA_CLIENTE:
        respuestas, estado = _resolver_cliente(db, estado, texto)
        conv.guardar(tenant.id, entrante.wa_phone, estado)
        if respuestas:
            return respuestas
    elif estado.paso == Paso.ESPERA_DETALLE:
        estado.detalle = texto[:300]
    elif estado.paso == Paso.ESPERA_MONTO:
        monto = _monto(texto)
        if monto is None or monto <= 0:
            return [
                Respuesta(texto="No entendí el valor. Escríbeme solo el número, por ejemplo 450.")
            ]
        estado.monto = str(monto)

    return _siguiente(db, tenant, entrante, estado)


def _siguiente(
    db: Session, tenant: Tenant, entrante: Entrante, estado: EstadoConversacion
) -> list[Respuesta]:
    """Pide el siguiente dato o, si ya están todos, arma el resumen."""
    falta = estado.falta()
    if falta == "cliente":
        estado.paso = Paso.ESPERA_CLIENTE
        conv.guardar(tenant.id, entrante.wa_phone, estado)
        return [conv.pedir("cliente")]
    if falta == "detalle":
        estado.paso = Paso.ESPERA_DETALLE
        conv.guardar(tenant.id, entrante.wa_phone, estado)
        return [conv.pedir("detalle")]
    if falta == "monto":
        estado.paso = Paso.ESPERA_MONTO
        conv.guardar(tenant.id, entrante.wa_phone, estado)
        return [conv.pedir("monto")]
    return _preparar_confirmacion(db, tenant, entrante, estado)


def _preparar_confirmacion(
    db: Session, tenant: Tenant, entrante: Entrante, estado: EstadoConversacion
) -> list[Respuesta]:
    """Crea el BORRADOR y muestra el resumen. No envía nada al SRI."""
    plan = plan_vigente(db, tenant.id)

    cert = db.scalars(select(Certificado).where(Certificado.activo.is_(True))).first()
    if cert is None:
        conv.limpiar(tenant.id, entrante.wa_phone)
        return [conv.sin_certificado()]

    try:
        comprobante = emision.crear_factura(
            db,
            tenant_id=tenant.id,
            cliente_final_id=uuid.UUID(estado.cliente_id) if estado.cliente_id else None,
            items_in=[
                {
                    "codigo": "SRV",
                    "descripcion": estado.detalle or "Servicio",
                    "cantidad": "1",
                    "precio_unitario": estado.monto or "0",
                    "codigo_iva": "4",
                }
            ],
            forma_pago="01",
            info_adicional={"Origen": "WhatsApp"},
        )
    except LimitePlanError:
        conv.limpiar(tenant.id, entrante.wa_phone)
        return [conv.sin_cupo(plan.tope("cupo"))]
    except EmisionError as e:
        conv.limpiar(tenant.id, entrante.wa_phone)
        return [Respuesta(texto=str(e))]

    comprobante.origen = "WHATSAPP"
    estado.comprobante_id = str(comprobante.id)
    estado.paso = Paso.CONFIRMAR
    conv.guardar(tenant.id, entrante.wa_phone, estado)

    return conv.resumen_para_confirmar(
        cliente=estado.cliente_nombre or "Consumidor final",
        identificacion=estado.cliente_identificacion or "9999999999999",
        detalle=estado.detalle or "",
        subtotal=comprobante.subtotal,
        iva=comprobante.iva,
        total=comprobante.total,
        porcentaje_iva=Decimal("15"),
    )


def _autorizar(
    db: Session, tenant: Tenant, entrante: Entrante, estado: EstadoConversacion
) -> list[Respuesta]:
    """Aquí, y solo aquí, el comprobante sale hacia el SRI."""
    if estado.paso != Paso.CONFIRMAR or not estado.comprobante_id:
        return [conv.MENU_PRINCIPAL]

    try:
        comprobante = emision.emitir(db, tenant.id, uuid.UUID(estado.comprobante_id))
    except EmisionError as e:
        return [Respuesta(texto=str(e))]

    conv.limpiar(tenant.id, entrante.wa_phone)
    numero = (
        f"{comprobante.establecimiento}-{comprobante.punto_emision}-{comprobante.secuencial:09d}"
    )
    return [conv.en_proceso(numero)]


def _por_accion(
    db: Session,
    tenant: Tenant,
    entrante: Entrante,
    estado: EstadoConversacion,
    accion: str,
) -> list[Respuesta]:
    if accion == "autorizar":
        return _autorizar(db, tenant, entrante, estado)
    if accion in ("menu", "volver"):
        conv.limpiar(tenant.id, entrante.wa_phone)
        return [conv.MENU_PRINCIPAL]
    if accion == "corregir_precio":
        estado.monto = None
        estado.paso = Paso.ESPERA_MONTO
        conv.guardar(tenant.id, entrante.wa_phone, estado)
        return [conv.pedir("monto")]
    if accion == "corregir_detalle":
        estado.detalle = None
        estado.paso = Paso.ESPERA_DETALLE
        conv.guardar(tenant.id, entrante.wa_phone, estado)
        return [conv.pedir("detalle")]
    if accion == "emitir":
        conv.guardar(tenant.id, entrante.wa_phone, EstadoConversacion(paso=Paso.ESPERA_CLIENTE))
        return [conv.pedir("cliente")]
    if accion == "reporte":
        return [_reporte(db, tenant)]
    if accion == "consultar":
        return [_ultimos(db, tenant)]

    # Un id de lista puede ser el UUID de un cliente elegido
    if estado.candidatos and any(c["id"] == accion for c in estado.candidatos):
        elegido = next(c for c in estado.candidatos if c["id"] == accion)
        estado.cliente_id = elegido["id"]
        estado.cliente_nombre = elegido["titulo"]
        estado.cliente_identificacion = elegido["subtitulo"].split()[-1]
        estado.candidatos = []
        return _siguiente(db, tenant, entrante, estado)

    return [conv.MENU_PRINCIPAL]


def _ultimos(db: Session, tenant: Tenant) -> Respuesta:
    docs = db.scalars(select(Comprobante).order_by(Comprobante.created_at.desc()).limit(3)).all()
    if not docs:
        return Respuesta(texto="Todavía no has emitido comprobantes este mes.")

    lineas = []
    for d in docs:
        numero = (
            f"{d.establecimiento}-{d.punto_emision}-{d.secuencial:09d}"
            if d.secuencial is not None
            else "Borrador"
        )
        estado_txt = {
            EstadoComprobante.AUTORIZADO: "Autorizada",
            EstadoComprobante.RECHAZADO: "Rechazada",
            EstadoComprobante.DEVUELTO: "Devuelta",
        }.get(d.estado, "En proceso")
        lineas.append(f"🧾 {numero}\n${d.total} · {estado_txt}")

    return Respuesta(
        texto="Tus últimos comprobantes:\n\n" + "\n\n".join(lineas),
        botones=[("menu", "Ver el menú")],
    )


def _reporte(db: Session, tenant: Tenant) -> Respuesta:
    from app.services.reportes import proxima_declaracion, resumen_fiscal

    hoy = datetime.now(TZ).date()
    r = resumen_fiscal(db, tenant.id, hoy=hoy)
    decl = proxima_declaracion(tenant.ruc, hoy)
    return Respuesta(
        texto=(
            f"*Tu mes hasta hoy*\n\n"
            f"Facturado: ${r.total_facturado}\n"
            f"IVA cobrado: ${r.iva_cobrado}\n"
            f"Retenciones de IVA: ${r.retenciones_recibidas}\n"
            f"*A pagar: ${r.a_pagar}*\n\n"
            + (
                f"Además llevas ${r.retenciones_renta} de retenciones de renta, "
                "que son crédito para tu declaración anual.\n\n"
                if r.retenciones_renta
                else ""
            )
            + f"Tu noveno dígito es {decl['noveno_digito']}, así que declaras hasta "
            f"el {decl['dia_maximo']} de cada mes."
        ),
        botones=[("menu", "Ver el menú")],
    )
