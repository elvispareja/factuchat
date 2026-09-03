"""Emisión de comprobantes (fase 2.5).

Reglas de negocio en SERVIDOR (OWASP A06): totales siempre calculados aquí,
consumidor final hasta $200, confirmación explícita (borrador → emitir),
secuenciales atómicos con FOR UPDATE y máquina de estados con guardas.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased

from app.core.config import get_settings
from app.db.models import ClienteFinal, Comprobante, Establecimiento, Secuencial, Tenant
from app.db.models.enums import (
    AmbienteSRI,
    EstadoComprobante,
    TipoComprobante,
    TipoIdentificacion,
)
from app.services.planes import exigir_cupo_comprobantes, plan_vigente
from app.sri.clave import generar_clave_acceso
from app.sri.xml_builder import TARIFAS_IVA

TZ_ECUADOR = ZoneInfo("America/Guayaquil")

LIMITE_CONSUMIDOR_FINAL = Decimal("200.00")

CODIGO_IDENTIFICACION = {
    TipoIdentificacion.RUC: "04",
    TipoIdentificacion.CEDULA: "05",
    TipoIdentificacion.PASAPORTE: "06",
    TipoIdentificacion.CONSUMIDOR_FINAL: "07",
    TipoIdentificacion.ID_EXTERIOR: "08",
}

# Máquina de estados (fase 1.2): PENDIENTE→FIRMADO→ENVIADO_SRI→AUTORIZADO/RECHAZADO/DEVUELTO
TRANSICIONES: dict[EstadoComprobante, set[EstadoComprobante]] = {
    EstadoComprobante.PENDIENTE: {EstadoComprobante.FIRMADO, EstadoComprobante.RECHAZADO},
    EstadoComprobante.FIRMADO: {
        EstadoComprobante.ENVIADO_SRI,
        EstadoComprobante.DEVUELTO,
        EstadoComprobante.RECHAZADO,
    },
    EstadoComprobante.ENVIADO_SRI: {
        EstadoComprobante.AUTORIZADO,
        EstadoComprobante.RECHAZADO,
        EstadoComprobante.DEVUELTO,
    },
    # Reintento: rechazados/devueltos vuelven a la cola con documento nuevo
    EstadoComprobante.DEVUELTO: {EstadoComprobante.PENDIENTE},
    EstadoComprobante.RECHAZADO: {EstadoComprobante.PENDIENTE},
    EstadoComprobante.AUTORIZADO: set(),  # inmutable (A08, refuerza el trigger de BD)
}


class EmisionError(Exception):
    """Error de negocio con mensaje apto para el usuario."""


class FacturaYaAcreditadaError(EmisionError):
    """No queda nada por acreditar de esa factura: ya está anulada del todo."""


def transicionar(comprobante: Comprobante, nuevo: EstadoComprobante) -> None:
    actual = comprobante.estado
    if nuevo not in TRANSICIONES.get(actual, set()):
        raise EmisionError(f"Transición inválida: {actual.value} → {nuevo.value}")
    comprobante.estado = nuevo


@dataclass
class ItemCalculado:
    codigo: str
    descripcion: str
    cantidad: Decimal
    precio_unitario: Decimal
    descuento: Decimal
    codigo_iva: str
    tarifa_iva: Decimal
    total_sin_impuesto: Decimal
    valor_iva: Decimal


def _d2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_items(items_in: list[dict]) -> tuple[list[ItemCalculado], dict]:
    """Calcula subtotales, IVA por ítem y totales agrupados por tarifa."""
    items: list[ItemCalculado] = []
    grupos: dict[str, dict[str, Decimal]] = {}
    total_sin_impuestos = Decimal("0")
    total_descuento = Decimal("0")
    total_iva = Decimal("0")

    for it in items_in:
        cantidad = Decimal(str(it["cantidad"]))
        precio = Decimal(str(it["precio_unitario"]))
        descuento = Decimal(str(it.get("descuento", 0)))
        codigo_iva = str(it["codigo_iva"])
        if codigo_iva not in TARIFAS_IVA:
            raise EmisionError(f"Código de IVA desconocido: {codigo_iva}")
        tarifa = TARIFAS_IVA[codigo_iva]

        bruto = cantidad * precio
        if descuento > bruto:
            raise EmisionError("El descuento no puede superar el subtotal del ítem")
        base = _d2(bruto - descuento)
        valor_iva = _d2(base * tarifa / Decimal("100"))

        items.append(
            ItemCalculado(
                codigo=str(it["codigo"])[:25],
                descripcion=str(it["descripcion"])[:300],
                cantidad=cantidad,
                precio_unitario=precio,
                descuento=_d2(descuento),
                codigo_iva=codigo_iva,
                tarifa_iva=tarifa,
                total_sin_impuesto=base,
                valor_iva=valor_iva,
            )
        )
        total_sin_impuestos += base
        total_descuento += _d2(descuento)

        grupo = grupos.setdefault(codigo_iva, {"base": Decimal("0"), "tarifa": tarifa})
        grupo["base"] += base

    # El valor de cada grupo se calcula sobre la BASE AGRUPADA, no sumando el IVA
    # ya redondeado de cada ítem: el SRI recalcula base×tarifa y rechaza el
    # comprobante si no cuadra al centavo.
    impuestos = []
    for codigo, g in sorted(grupos.items()):
        base_grupo = _d2(g["base"])
        valor_grupo = _d2(base_grupo * g["tarifa"] / Decimal("100"))
        total_iva += valor_grupo
        impuestos.append(
            {
                "codigo_porcentaje": codigo,
                "tarifa": str(g["tarifa"]),
                "base": base_grupo,
                "valor": valor_grupo,
            }
        )

    totales = {
        "total_sin_impuestos": _d2(total_sin_impuestos),
        "total_descuento": _d2(total_descuento),
        "total_iva": _d2(total_iva),
        "importe_total": _d2(total_sin_impuestos + total_iva),
        "impuestos": impuestos,
    }
    return items, totales


def _comprador_de(
    cliente: ClienteFinal | None,
    email_envio: str | None = None,
    direccion: str | None = None,
) -> dict:
    """Snapshot del comprador para el payload.

    `email_envio` es el correo elegido en la pantalla de revisión para ESTA
    factura: manda sobre el del cliente, pero solo aquí (la ficha del cliente no
    se toca; su correo habitual sigue siendo el suyo).

    None y cadena vacía NO son lo mismo: None es «no se indicó nada» y usa el
    del cliente; "" es «no mandes copia», que es lo que pide quien borra el
    campo en la revisión. Por eso se compara con None y no con un `or`, que
    trataría el vacío como ausencia.

    `direccion` llega YA resuelta (ver `crear_factura`) porque solo la factura
    tiene <direccionComprador>: las notas comparten este snapshot y su XML no
    lleva el campo. Se guarda lo que de verdad se emitió, no lo que diga hoy la
    ficha: este payload es lo que reimprime el RIDE meses después.
    """
    if cliente is None:
        comprador = {
            "tipo_identificacion_codigo": "07",
            "razon_social": "CONSUMIDOR FINAL",
            "identificacion": "9999999999999",
            "email": email_envio,
        }
    else:
        comprador = {
            "tipo_identificacion_codigo": CODIGO_IDENTIFICACION[cliente.tipo_identificacion],
            "razon_social": cliente.razon_social,
            "identificacion": cliente.identificacion,
            "email": cliente.email if email_envio is None else (email_envio or None),
        }
    # Recorte a 300: es el tope del XSD y la ficha del cliente admite 1000. Sin
    # esto, una dirección larga guardada hace meses tumba la factura en recepción.
    if direccion:
        comprador["direccion"] = direccion[:300]
    return comprador


def _payload_lineas(items: list[ItemCalculado], totales: dict) -> dict:
    """Snapshot de líneas y totales para el JSONB (todo Decimal como cadena).

    Lo comparten factura y nota de crédito porque el XML de las dos lleva los
    mismos <detalles> y el mismo <totalConImpuestos>. La nota de débito lo usa
    también: su XML no tiene <detalles>, pero el RIDE y el historial sí enseñan
    la línea del recargo, y los totales se calculan igual.
    """
    return {
        "items": [
            {
                "codigo": i.codigo,
                "descripcion": i.descripcion,
                "cantidad": str(i.cantidad),
                "precio_unitario": str(i.precio_unitario),
                "descuento": str(i.descuento),
                "codigo_iva": i.codigo_iva,
                "tarifa_iva": str(i.tarifa_iva),
                "total_sin_impuesto": str(i.total_sin_impuesto),
                "valor_iva": str(i.valor_iva),
            }
            for i in items
        ],
        "totales": {
            "total_sin_impuestos": str(totales["total_sin_impuestos"]),
            "total_descuento": str(totales["total_descuento"]),
            "total_iva": str(totales["total_iva"]),
            "importe_total": str(totales["importe_total"]),
            "impuestos": [
                {
                    "codigo_porcentaje": g["codigo_porcentaje"],
                    "tarifa": g["tarifa"],
                    "base": str(g["base"]),
                    "valor": str(g["valor"]),
                }
                for g in totales["impuestos"]
            ],
        },
    }


def crear_factura(
    db: Session,
    tenant_id: uuid.UUID,
    cliente_final_id: uuid.UUID | None,
    items_in: list[dict],
    forma_pago: str,
    info_adicional: dict[str, str] | None = None,
    plazo_dias: int | None = None,
    email_envio: str | None = None,
    direccion_envio: str | None = None,
) -> Comprobante:
    """Crea el BORRADOR (PENDIENTE, sin secuencial). No envía nada al SRI:
    la emisión exige confirmación explícita aparte (A06)."""
    cliente = None
    if cliente_final_id is not None:
        cliente = db.get(ClienteFinal, cliente_final_id)  # RLS: solo del propio tenant
        if cliente is None:
            raise EmisionError("Cliente no encontrado")

    items, totales = calcular_items(items_in)

    # Límite de consumidor final sin datos: $200 (regla ya publicada en la landing).
    # Aplica tanto al caso sin cliente como a un cliente guardado como
    # CONSUMIDOR_FINAL, que de otro modo saltaría el tope.
    es_consumidor_final = (
        cliente is None or cliente.tipo_identificacion == TipoIdentificacion.CONSUMIDOR_FINAL
    )
    if es_consumidor_final and totales["importe_total"] > LIMITE_CONSUMIDOR_FINAL:
        raise EmisionError(
            f"Consumidor final permite hasta ${LIMITE_CONSUMIDOR_FINAL}; "
            "pida los datos del cliente para montos mayores"
        )

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise EmisionError("Tenant no disponible")

    # Las mismas tres formas que el correo (ver `_comprador_de`): sin indicar
    # nada vale la de la ficha, "" emite la factura SIN dirección y un texto vale
    # solo para esta. Se resuelve aquí y no dentro de `_comprador_de` porque ese
    # snapshot lo comparten las notas, y <direccionComprador> es de la factura.
    # El `.strip()` no es cosmético: `"   "` es verdadero en Python, así que una
    # dirección de solo espacios —que por la API entra sin problema— acababa
    # emitiendo <direccionComprador>   </direccionComprador>, y el XSD exige
    # contenido a un elemento que ni siquiera hacía falta mandar. Así «espacios»
    # significa lo mismo que «vacío», que es lo que dice el párrafo de arriba.
    direccion = (
        (cliente.direccion if cliente else None) if direccion_envio is None else direccion_envio
    )
    direccion = direccion.strip() if direccion else None

    hoy = datetime.now(TZ_ECUADOR).date()
    # Cupo del plan verificado en SERVIDOR antes de crear el borrador (A06)
    plan = plan_vigente(db, tenant_id)
    exigir_cupo_comprobantes(db, tenant_id, plan, hoy)
    comprobante = Comprobante(
        tenant_id=tenant_id,
        tipo=TipoComprobante.FACTURA,
        ambiente=tenant.ambiente_sri,
        cliente_final_id=cliente.id if cliente else None,
        fecha_emision=hoy,
        subtotal=totales["total_sin_impuestos"],
        iva=totales["total_iva"],
        total=totales["importe_total"],
        payload={
            "comprador": _comprador_de(cliente, email_envio, direccion),
            **_payload_lineas(items, totales),
            "forma_pago": forma_pago,
            "plazo_dias": plazo_dias,
            "info_adicional": info_adicional or {},
        },
        origen="PANEL",
    )
    db.add(comprobante)
    db.flush()
    return comprobante


# Notas de crédito que RESERVAN saldo de la factura. Cuentan también las que el
# SRI aún no autorizó: si solo contaran las AUTORIZADAS, dos borradores por el
# total pasarían la validación los dos y la factura acabaría acreditada al doble.
# Las RECHAZADAS y DEVUELTAS no reservan nada: nunca existirán para el fisco.
ESTADOS_NC_VIVAS = (
    EstadoComprobante.PENDIENTE,
    EstadoComprobante.FIRMADO,
    EstadoComprobante.ENVIADO_SRI,
    EstadoComprobante.AUTORIZADO,
)


def _acreditado_expr(factura_id):
    """Suma de las notas de crédito vivas sobre una factura.

    Sirve con un id concreto y también correlacionada con `Comprobante.id` en el
    listado de acreditables, así que la regla de «qué cuenta» vive en un solo
    sitio y las dos no pueden divergir.
    """
    nc = aliased(Comprobante)
    return (
        # El cero va como Decimal y no como 0 pelado: si no, una factura sin
        # ninguna nota devuelve el entero 0 y la API publica «acreditado: "0"»
        # junto a «pendiente: "115.00"», dos formatos de dinero en la misma fila.
        select(func.coalesce(func.sum(nc.total), Decimal("0.00")))
        .where(
            nc.comprobante_modificado_id == factura_id,
            nc.tipo == TipoComprobante.NOTA_CREDITO,
            nc.estado.in_(ESTADOS_NC_VIVAS),
        )
        .scalar_subquery()
    )


def _factura_propia_por_numero(db: Session, numero: str) -> uuid.UUID | None:
    """La factura del propio tenant que lleva ese número, si existe.

    Sirve para que teclear el número a mano no sea una puerta trasera: si el
    documento es nuestro, se valida como cualquier otro. Solo cuando de verdad no
    está en el sistema (una factura emitida en otra plataforma) se sigue sin
    poder comprobar nada, que es lo inevitable.
    """
    partes = numero.split("-")
    if len(partes) != 3:
        return None
    estab, punto, secuencial = partes
    return db.scalars(  # RLS: solo mira dentro del propio tenant
        select(Comprobante.id).where(
            Comprobante.tipo == TipoComprobante.FACTURA,
            Comprobante.establecimiento == estab,
            Comprobante.punto_emision == punto,
            Comprobante.secuencial == int(secuencial),
        )
    ).first()


def acreditado_sobre(db: Session, factura_id: uuid.UUID) -> Decimal:
    return Decimal(str(db.scalar(select(_acreditado_expr(factura_id))) or 0))


def facturas_acreditables(
    db: Session, limite: int = 100, solo_con_saldo: bool = True
) -> list[tuple[Comprobante, Decimal]]:
    """Facturas AUTORIZADAS sobre las que se puede emitir una nota, con lo ya
    acreditado.

    Una sola consulta con subconsulta correlacionada: el saldo se descuenta en
    SQL y las que ya están anuladas del todo ni siquiera se devuelven. RLS acota
    a las del propio tenant, aquí y en la subconsulta.

    `solo_con_saldo=False` es para la nota de DÉBITO: un recargo se cobra sobre
    cualquier factura autorizada, incluso sobre una ya acreditada del todo —el
    saldo por acreditar es asunto de la nota de crédito, no del recargo—. Sigue
    devolviendo `acreditado` porque cuesta lo mismo y el selector lo enseña.
    """
    acreditado = _acreditado_expr(Comprobante.id)
    filtros = [
        Comprobante.tipo == TipoComprobante.FACTURA,
        Comprobante.estado == EstadoComprobante.AUTORIZADO,
    ]
    if solo_con_saldo:
        filtros.append(Comprobante.total > acreditado)
    filas = db.execute(
        select(Comprobante, acreditado.label("acreditado"))
        .where(*filtros)
        .order_by(Comprobante.fecha_emision.desc(), Comprobante.created_at.desc())
        .limit(limite)
    ).all()
    return [(f[0], Decimal(str(f[1]))) for f in filas]


def crear_nota_credito(
    db: Session,
    tenant_id: uuid.UUID,
    cliente_final_id: uuid.UUID | None,
    items_in: list[dict],
    motivo: str,
    factura_id: uuid.UUID | None = None,
    doc_modificado: dict | None = None,
    info_adicional: dict[str, str] | None = None,
    email_envio: str | None = None,
) -> Comprobante:
    """Crea el BORRADOR de la nota que anula o corrige una factura ya emitida.

    Mismo trato que `crear_factura`: cupo del plan, totales calculados AQUÍ
    (nunca los que mande el cliente) y payload snapshot. Lo propio de la nota son
    las validaciones contra la factura de origen, que es donde está el valor:
    sin ellas se puede acreditar 900 de una factura de 689.
    """
    cliente = None
    if cliente_final_id is not None:
        cliente = db.get(ClienteFinal, cliente_final_id)  # RLS: solo del propio tenant
        if cliente is None:
            raise EmisionError("Cliente no encontrado")

    items, totales = calcular_items(items_in)

    # El número tecleado a mano NO es un camino sin reglas: si esa factura es
    # NUESTRA, se le aplican exactamente los mismos controles que si se hubiera
    # elegido del historial. Sin esto, «la factura es de otro sistema» permitía
    # acreditar dos veces la misma factura propia con solo teclear su número.
    if factura_id is None and doc_modificado is not None:
        factura_id = _factura_propia_por_numero(db, doc_modificado["numero"])

    if factura_id is not None:
        # db.get pasa por RLS; la FK de Postgres NO, así que la factura de otro
        # tenant se corta aquí y no en la base.
        # FOR UPDATE: el tope se lee y se compara sin nada que impida a otra
        # petición leer el mismo saldo a la vez. Dos envíos simultáneos —dos
        # pestañas, un reintento del móvil al recuperar la señal— pasaban los dos
        # y acreditaban el doble. El bloqueo los serializa.
        factura = db.execute(
            select(Comprobante).where(Comprobante.id == factura_id).with_for_update()
        ).scalar_one_or_none()
        if factura is None or factura.tipo != TipoComprobante.FACTURA:
            raise EmisionError("La factura que quiere modificar no existe")
        if factura.estado != EstadoComprobante.AUTORIZADO:
            raise EmisionError(
                "Solo se puede acreditar una factura AUTORIZADA por el SRI "
                f"(esta está {factura.estado.value})"
            )
        if factura.cliente_final_id != cliente_final_id:
            raise EmisionError(
                "La nota de crédito va al mismo cliente de la factura que modifica"
            )

        pendiente = Decimal(factura.total) - acreditado_sobre(db, factura.id)
        numero_factura = (
            f"{factura.establecimiento}-{factura.punto_emision}-{factura.secuencial:09d}"
        )
        if pendiente <= 0:
            raise FacturaYaAcreditadaError(
                f"La factura {numero_factura} ya está acreditada por completo"
            )
        if totales["importe_total"] > pendiente:
            raise EmisionError(
                f"De la factura {numero_factura} quedan ${pendiente} por acreditar "
                f"y esta nota suma ${totales['importe_total']}"
            )
        # La factura manda sobre lo que venga tecleado: el XML tiene que citar el
        # número y la fecha que el SRI autorizó, no los que alguien recuerde.
        doc_modificado = {"numero": numero_factura, "fecha": factura.fecha_emision}
    elif doc_modificado is None:  # lo impide el esquema; red de seguridad
        raise EmisionError("Falta la factura que modifica")

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise EmisionError("Tenant no disponible")

    hoy = datetime.now(TZ_ECUADOR).date()
    plan = plan_vigente(db, tenant_id)
    exigir_cupo_comprobantes(db, tenant_id, plan, hoy)
    fecha_doc = doc_modificado["fecha"]
    comprobante = Comprobante(
        tenant_id=tenant_id,
        tipo=TipoComprobante.NOTA_CREDITO,
        ambiente=tenant.ambiente_sri,
        cliente_final_id=cliente.id if cliente else None,
        comprobante_modificado_id=factura_id,
        fecha_emision=hoy,
        subtotal=totales["total_sin_impuestos"],
        iva=totales["total_iva"],
        total=totales["importe_total"],
        payload={
            "comprador": _comprador_de(cliente, email_envio),
            **_payload_lineas(items, totales),
            "doc_modificado": {
                "cod_doc": TipoComprobante.FACTURA.codigo_sri,  # «01»
                "numero": doc_modificado["numero"],
                "fecha": (fecha_doc if isinstance(fecha_doc, str) else fecha_doc.isoformat()),
            },
            "motivo": motivo,
            "info_adicional": info_adicional or {},
        },
        origen="PANEL",
    )
    db.add(comprobante)
    db.flush()
    return comprobante


# El recargo lleva el IVA vigente. No hay línea de producto donde elegir tarifa
# y el panel tampoco la ofrece: un interés por mora o un gasto repercutido van al
# tipo general. Si algún día hace falta un recargo exento, entra como campo del
# esquema y llega hasta aquí sin tocar nada más.
CODIGO_IVA_RECARGO = "4"  # 15%


def crear_nota_debito(
    db: Session,
    tenant_id: uuid.UUID,
    cliente_final_id: uuid.UUID | None,
    valor_recargo: Decimal,
    motivo: str,
    factura_id: uuid.UUID | None = None,
    doc_modificado: dict | None = None,
    info_adicional: dict[str, str] | None = None,
    email_envio: str | None = None,
) -> Comprobante:
    """Crea el BORRADOR de la nota que COBRA un recargo sobre una factura emitida.

    La hermana de la nota de crédito al revés: aquella resta, esta suma. Mismo
    esqueleto (cupo del plan, totales calculados AQUÍ, payload snapshot) y las
    mismas comprobaciones contra la factura de origen MENOS el tope: un interés
    por mora no está limitado por el total de la factura —una de $100 impagada
    durante dos años genera lo que genere—, así que aquí no hay saldo que
    descontar, ni factura «agotada», ni nada que reservar. Por lo mismo tampoco
    hace falta el FOR UPDATE de la nota de crédito, que solo existía para
    serializar la lectura de ese saldo.

    `valor_recargo` es lo que se quiere COBRAR, con IVA incluido; la base sale de
    dividirlo (ver NotaDebitoIn, que explica por qué es al revés que en la
    factura y por qué el total puede quedar a un centavo).
    """
    cliente = None
    if cliente_final_id is not None:
        cliente = db.get(ClienteFinal, cliente_final_id)  # RLS: solo del propio tenant
        if cliente is None:
            raise EmisionError("Cliente no encontrado")

    # El recargo es UNA línea y con eso `calcular_items` da base, IVA agrupado y
    # total cuadrados igual que los de una factura, que es como el SRI los
    # recalcula. El XML de la nota de débito no lleva <detalles> y la ignora,
    # pero el RIDE la imprime y de ella sale la columna DETALLE del historial.
    tarifa = TARIFAS_IVA[CODIGO_IVA_RECARGO]
    base = _d2(Decimal(valor_recargo) * 100 / (100 + tarifa))
    items, totales = calcular_items(
        [
            {
                "codigo": "RECARGO",
                "descripcion": motivo,
                "cantidad": 1,
                "precio_unitario": base,
                "codigo_iva": CODIGO_IVA_RECARGO,
            }
        ]
    )

    # Igual que en la nota de crédito: teclear el número a mano no es un camino
    # sin reglas. Si esa factura es NUESTRA se le aplican los mismos controles
    # que si se hubiera elegido del historial, y la nota queda ENLAZADA a ella.
    if factura_id is None and doc_modificado is not None:
        factura_id = _factura_propia_por_numero(db, doc_modificado["numero"])

    if factura_id is not None:
        # db.get pasa por RLS; la FK de Postgres NO, así que la factura de otro
        # tenant se corta aquí y no en la base.
        factura = db.get(Comprobante, factura_id)
        if factura is None or factura.tipo != TipoComprobante.FACTURA:
            raise EmisionError("La factura que quiere modificar no existe")
        if factura.estado != EstadoComprobante.AUTORIZADO:
            raise EmisionError(
                "Solo se puede recargar una factura AUTORIZADA por el SRI "
                f"(esta está {factura.estado.value})"
            )
        if factura.cliente_final_id != cliente_final_id:
            raise EmisionError(
                "La nota de débito va al mismo cliente de la factura que modifica"
            )
        # La factura manda sobre lo que venga tecleado: el XML tiene que citar el
        # número y la fecha que el SRI autorizó, no los que alguien recuerde.
        doc_modificado = {
            "numero": f"{factura.establecimiento}-{factura.punto_emision}-{factura.secuencial:09d}",
            "fecha": factura.fecha_emision,
        }
    elif doc_modificado is None:  # lo impide el esquema; red de seguridad
        raise EmisionError("Falta la factura que modifica")

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise EmisionError("Tenant no disponible")

    hoy = datetime.now(TZ_ECUADOR).date()
    plan = plan_vigente(db, tenant_id)
    exigir_cupo_comprobantes(db, tenant_id, plan, hoy)
    fecha_doc = doc_modificado["fecha"]
    comprobante = Comprobante(
        tenant_id=tenant_id,
        tipo=TipoComprobante.NOTA_DEBITO,
        ambiente=tenant.ambiente_sri,
        cliente_final_id=cliente.id if cliente else None,
        comprobante_modificado_id=factura_id,
        fecha_emision=hoy,
        subtotal=totales["total_sin_impuestos"],
        iva=totales["total_iva"],
        total=totales["importe_total"],
        payload={
            "comprador": _comprador_de(cliente, email_envio),
            **_payload_lineas(items, totales),
            "doc_modificado": {
                "cod_doc": TipoComprobante.FACTURA.codigo_sri,  # «01»
                "numero": doc_modificado["numero"],
                "fecha": (fecha_doc if isinstance(fecha_doc, str) else fecha_doc.isoformat()),
            },
            "motivo": motivo,  # el RIDE lo imprime igual que el de la nota de crédito
            # <motivos> del XML: la razón con su valor SIN IMPUESTOS. Su suma es
            # el <totalSinImpuestos> del comprobante, que es lo que el SRI
            # cuadra; el IVA va aparte en <impuestos> y el total en <valorTotal>.
            "motivos": [{"razon": motivo, "valor": str(totales["total_sin_impuestos"])}],
            "info_adicional": info_adicional or {},
        },
        origen="PANEL",
    )
    db.add(comprobante)
    db.flush()
    return comprobante


def _establecimiento(db: Session, codigo: str) -> Establecimiento:
    estab = db.scalars(
        select(Establecimiento).where(
            Establecimiento.codigo == codigo,
            Establecimiento.activo.is_(True),
        )
    ).first()
    if estab is None:
        raise EmisionError(f"Establecimiento {codigo} no existe o está inactivo")
    return estab


def siguiente_numero(
    db: Session,
    establecimiento_codigo: str,
    punto_emision: str,
    tipo: TipoComprobante,
) -> int:
    """Secuencial que le TOCARÍA al próximo comprobante. SOLO LEE.

    Nada de FOR UPDATE ni de crear la fila del secuencial: esto alimenta el pie
    del modal antes de emitir, y reservar aquí dejaría un hueco cada vez que
    alguien abre el modal y lo cierra —y los huecos de numeración son un
    problema con el SRI—. Es una previsión, no una reserva: con dos emisiones
    en paralelo el número real lo fija asignar_secuencial.
    """
    estab = _establecimiento(db, establecimiento_codigo)
    actual = db.scalars(
        select(Secuencial.secuencial_actual).where(
            Secuencial.establecimiento_id == estab.id,
            Secuencial.punto_emision == punto_emision,
            Secuencial.tipo_comprobante == tipo.value,
        )
    ).first()
    return int(actual or 0) + 1


def asignar_secuencial(
    db: Session,
    tenant_id: uuid.UUID,
    establecimiento_codigo: str,
    punto_emision: str,
    tipo: TipoComprobante,
) -> tuple[Establecimiento, int]:
    """Incremento atómico del secuencial (FOR UPDATE) por estab+pto+tipo."""
    estab = _establecimiento(db, establecimiento_codigo)

    # FOR UPDATE no puede bloquear una fila que aún no existe: se crea primero
    # de forma idempotente (ON CONFLICT DO NOTHING) y solo después se bloquea.
    # Sin esto, dos emisiones simultáneas de la PRIMERA factura chocaban con
    # IntegrityError y una de las dos moría con un 500.
    db.execute(
        pg_insert(Secuencial)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            establecimiento_id=estab.id,
            punto_emision=punto_emision,
            tipo_comprobante=tipo.value,
            secuencial_actual=0,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "establecimiento_id", "punto_emision", "tipo_comprobante"]
        )
    )
    sec = db.execute(
        select(Secuencial)
        .where(
            Secuencial.establecimiento_id == estab.id,
            Secuencial.punto_emision == punto_emision,
            Secuencial.tipo_comprobante == tipo.value,
        )
        .with_for_update()
    ).scalar_one()
    sec.secuencial_actual += 1
    return estab, int(sec.secuencial_actual)


def emitir(
    db: Session,
    tenant_id: uuid.UUID,
    comprobante_id: uuid.UUID,
    establecimiento_codigo: str = "001",
    punto_emision: str = "001",
) -> Comprobante:
    """Confirmación explícita: asigna secuencial y clave de acceso y encola la
    emisión. Devuelve el comprobante actualizado; el estado se consulta por id."""
    # FOR UPDATE: dos peticiones simultáneas sobre el mismo borrador quemarían
    # dos secuenciales y encolarían la emisión dos veces.
    comprobante = db.execute(
        select(Comprobante).where(Comprobante.id == comprobante_id).with_for_update()
    ).scalar_one_or_none()
    if comprobante is None:
        raise EmisionError("Comprobante no encontrado")
    if comprobante.estado != EstadoComprobante.PENDIENTE:
        raise EmisionError(
            f"Solo un borrador PENDIENTE puede emitirse ({comprobante.estado.value})"
        )
    if comprobante.clave_acceso is not None:
        raise EmisionError("El comprobante ya fue emitido")

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise EmisionError("Tenant no disponible")
    estab, secuencial = asignar_secuencial(
        db, tenant_id, establecimiento_codigo, punto_emision, comprobante.tipo
    )
    comprobante.establecimiento = estab.codigo
    comprobante.punto_emision = punto_emision
    comprobante.secuencial = secuencial
    comprobante.clave_acceso = generar_clave_acceso(
        fecha_emision=comprobante.fecha_emision,
        codigo_documento=comprobante.tipo.codigo_sri,
        ruc=tenant.ruc,
        ambiente="2" if comprobante.ambiente == AmbienteSRI.PRODUCCION else "1",
        establecimiento=estab.codigo,
        punto_emision=punto_emision,
        secuencial=secuencial,
    )
    payload = dict(comprobante.payload)
    payload["dir_establecimiento"] = estab.direccion or ""
    comprobante.payload = payload
    db.flush()

    _encolar_tras_commit(db, tenant_id, comprobante.id)
    return comprobante


def _encolar_tras_commit(db: Session, tenant_id: uuid.UUID, comprobante_id: uuid.UUID) -> None:
    """El task se encola DESPUÉS del commit: si se encolara antes, el worker
    podría leer el comprobante sin clave (transacción aún abierta) y abortar."""
    from app.db.session import despues_del_commit
    from app.tasks.emision import procesar_emision  # import tardío: evita ciclo

    despues_del_commit(db, lambda: procesar_emision.delay(str(tenant_id), str(comprobante_id)))


def reintentar(db: Session, tenant_id: uuid.UUID, comprobante_id: uuid.UUID) -> Comprobante:
    """Reintento tras DEVUELTO/RECHAZADO: documento NUEVO (clave nueva con otro
    código numérico); el secuencial se conserva porque el SRI nunca lo registró."""
    comprobante = db.execute(
        select(Comprobante).where(Comprobante.id == comprobante_id).with_for_update()
    ).scalar_one_or_none()
    if comprobante is None:
        raise EmisionError("Comprobante no encontrado")
    if comprobante.estado not in (EstadoComprobante.DEVUELTO, EstadoComprobante.RECHAZADO):
        raise EmisionError("Solo comprobantes devueltos o rechazados pueden reintentarse")
    if (
        comprobante.establecimiento is None
        or comprobante.punto_emision is None
        or comprobante.secuencial is None
    ):
        raise EmisionError("El comprobante nunca llegó a emitirse")

    # Una nota devuelta LIBERA el saldo que reservaba (RECHAZADO y DEVUELTO no
    # cuentan como acreditado: para el fisco no existieron). Si mientras estaba
    # muerta se emitió otra nota por ese saldo, revivir esta acreditaría la
    # factura por encima de su total. Hay que volver a comprobar el tope, no solo
    # el estado del comprobante.
    if comprobante.tipo == TipoComprobante.NOTA_CREDITO and comprobante.comprobante_modificado_id:
        factura = db.execute(
            select(Comprobante)
            .where(Comprobante.id == comprobante.comprobante_modificado_id)
            .with_for_update()
        ).scalar_one_or_none()
        if factura is not None:
            # `acreditado_sobre` no cuenta esta nota (está devuelta), así que lo
            # que devuelve es lo acreditado por LAS OTRAS.
            pendiente = Decimal(factura.total) - acreditado_sobre(db, factura.id)
            if Decimal(comprobante.total) > pendiente:
                numero = (
                    f"{factura.establecimiento}-{factura.punto_emision}-{factura.secuencial:09d}"
                )
                raise EmisionError(
                    f"No se puede reenviar: de la factura {numero} solo quedan "
                    f"${pendiente} por acreditar y esta nota es de "
                    f"${Decimal(comprobante.total)}. Se emitieron otras notas "
                    "mientras esta estaba devuelta."
                )

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise EmisionError("Tenant no disponible")
    transicionar(comprobante, EstadoComprobante.PENDIENTE)
    comprobante.clave_acceso = generar_clave_acceso(
        fecha_emision=comprobante.fecha_emision,
        codigo_documento=comprobante.tipo.codigo_sri,
        ruc=tenant.ruc,
        ambiente="2" if comprobante.ambiente == AmbienteSRI.PRODUCCION else "1",
        establecimiento=comprobante.establecimiento,
        punto_emision=comprobante.punto_emision,
        secuencial=int(comprobante.secuencial),
    )
    comprobante.xml_path = None
    comprobante.ride_path = None
    comprobante.sha256_xml = None
    # Documento nuevo: se limpian el motivo del rechazo anterior y las marcas de
    # reanudación, o el reintento se saltaría el envío creyéndolo ya despachado.
    comprobante.sri_mensajes = None
    comprobante.enviado_recepcion_at = None
    comprobante.correo_enviado_at = None
    db.flush()

    _encolar_tras_commit(db, tenant_id, comprobante.id)
    return comprobante


def datos_para_xml(tenant: Tenant, comprobante: Comprobante) -> tuple[dict, dict]:
    """Arma (emisor, factura) para el builder de XML desde el snapshot payload."""
    p = comprobante.payload
    emisor = {
        "ruc": tenant.ruc,
        "razon_social": tenant.razon_social,
        "nombre_comercial": tenant.nombre_comercial,
        "dir_matriz": tenant.direccion_matriz or "S/D",
        "obligado_contabilidad": tenant.obligado_contabilidad,
        "ambiente": "2" if comprobante.ambiente == AmbienteSRI.PRODUCCION else "1",
    }
    factura = {
        "clave_acceso": comprobante.clave_acceso,
        "establecimiento": comprobante.establecimiento,
        "punto_emision": comprobante.punto_emision,
        "secuencial": comprobante.secuencial,
        "fecha_emision": comprobante.fecha_emision,
        "dir_establecimiento": p.get("dir_establecimiento") or None,
        "comprador": p["comprador"],
        "items": [
            {
                "codigo": i["codigo"],
                "descripcion": i["descripcion"],
                "cantidad": Decimal(i["cantidad"]),
                "precio_unitario": Decimal(i["precio_unitario"]),
                "descuento": Decimal(i["descuento"]),
                "codigo_iva": i["codigo_iva"],
                "tarifa_iva": Decimal(i["tarifa_iva"]),
                "total_sin_impuesto": Decimal(i["total_sin_impuesto"]),
                "valor_iva": Decimal(i["valor_iva"]),
            }
            for i in p["items"]
        ],
        "totales": {
            "total_sin_impuestos": Decimal(p["totales"]["total_sin_impuestos"]),
            "total_descuento": Decimal(p["totales"]["total_descuento"]),
            "importe_total": Decimal(p["totales"]["importe_total"]),
            "impuestos": [
                {
                    "codigo_porcentaje": g["codigo_porcentaje"],
                    "base": Decimal(g["base"]),
                    "valor": Decimal(g["valor"]),
                }
                for g in p["totales"]["impuestos"]
            ],
        },
        # La nota de crédito no lleva <pagos> en su XML y su payload no guarda
        # forma de pago: sin el `if`, armar sus datos reventaba con KeyError
        # dentro del worker, donde el fallo solo se ve en los logs.
        "pagos": (
            [
                {
                    "forma": p["forma_pago"],
                    "total": Decimal(p["totales"]["importe_total"]),
                    "plazo": p.get("plazo_dias"),
                }
            ]
            if p.get("forma_pago")
            else []
        ),
        "info_adicional": p.get("info_adicional") or None,
    }
    # Lo propio de las notas. `pagos` sobra en sus XML y los builders lo ignoran,
    # así que no hace falta un segundo armador: el resto del documento es
    # idéntico al de la factura.
    if p.get("doc_modificado"):
        factura["doc_modificado"] = {
            "cod_doc": p["doc_modificado"]["cod_doc"],
            "numero": p["doc_modificado"]["numero"],
            "fecha": date.fromisoformat(p["doc_modificado"]["fecha"]),
        }
        factura["motivo"] = p["motivo"]
    # La nota de débito no lleva un motivo suelto sino una LISTA de motivos, cada
    # uno con su valor (ver construir_nota_debito).
    if p.get("motivos"):
        factura["motivos"] = [
            {"razon": m["razon"], "valor": Decimal(m["valor"])} for m in p["motivos"]
        ]
    return emisor, factura


def ruta_almacen(tenant_id: uuid.UUID, clave_acceso: str, extension: str) -> Path:
    base = Path(get_settings().storage_dir) / str(tenant_id)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{clave_acceso}.{extension}"
