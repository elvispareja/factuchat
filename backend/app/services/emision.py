"""Emisión de comprobantes (fase 2.5).

Reglas de negocio en SERVIDOR (OWASP A06): totales siempre calculados aquí,
consumidor final hasta $200, confirmación explícita (borrador → emitir),
secuenciales atómicos con FOR UPDATE y máquina de estados con guardas.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

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


def _comprador_de(cliente: ClienteFinal | None) -> dict:
    if cliente is None:
        return {
            "tipo_identificacion_codigo": "07",
            "razon_social": "CONSUMIDOR FINAL",
            "identificacion": "9999999999999",
            "email": None,
        }
    return {
        "tipo_identificacion_codigo": CODIGO_IDENTIFICACION[cliente.tipo_identificacion],
        "razon_social": cliente.razon_social,
        "identificacion": cliente.identificacion,
        "email": cliente.email,
    }


def crear_factura(
    db: Session,
    tenant_id: uuid.UUID,
    cliente_final_id: uuid.UUID | None,
    items_in: list[dict],
    forma_pago: str,
    info_adicional: dict[str, str] | None = None,
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
            "comprador": _comprador_de(cliente),
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
            "forma_pago": forma_pago,
            "info_adicional": info_adicional or {},
        },
        origen="PANEL",
    )
    db.add(comprobante)
    db.flush()
    return comprobante


def asignar_secuencial(
    db: Session,
    tenant_id: uuid.UUID,
    establecimiento_codigo: str,
    punto_emision: str,
    tipo: TipoComprobante,
) -> tuple[Establecimiento, int]:
    """Incremento atómico del secuencial (FOR UPDATE) por estab+pto+tipo."""
    estab = db.scalars(
        select(Establecimiento).where(
            Establecimiento.codigo == establecimiento_codigo,
            Establecimiento.activo.is_(True),
        )
    ).first()
    if estab is None:
        raise EmisionError(f"Establecimiento {establecimiento_codigo} no existe o está inactivo")

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
        "pagos": [{"forma": p["forma_pago"], "total": Decimal(p["totales"]["importe_total"])}],
        "info_adicional": p.get("info_adicional") or None,
    }
    return emisor, factura


def ruta_almacen(tenant_id: uuid.UUID, clave_acceso: str, extension: str) -> Path:
    base = Path(get_settings().storage_dir) / str(tenant_id)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{clave_acceso}.{extension}"
