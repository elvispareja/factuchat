"""Configuración del sistema (fase 4.1): planes con vigencia y tarifas de costo.

REGLA CENTRAL: cambiar el precio de un plan NUNCA toca las suscripciones vivas.
Se crea una VERSIÓN nueva del plan con `vigente_desde` futuro; la versión
anterior se cierra con `vigente_hasta`. Las suscripciones existentes conservan
su `precio` congelado y siguen apuntando a la versión que contrataron.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CostRate, Plan, Suscripcion


class ConfiguracionError(Exception):
    """Motivo legible para el operador."""


# --------------------------------------------------------------- planes


def plan_vigente_por_codigo(db: Session, codigo: str, hoy: date) -> Plan | None:
    return db.scalars(
        select(Plan)
        .where(
            Plan.codigo == codigo,
            Plan.vigente_desde <= hoy,
            (Plan.vigente_hasta.is_(None)) | (Plan.vigente_hasta > hoy),
        )
        .order_by(Plan.vigente_desde.desc())
        .limit(1)
    ).first()


def versiones_de(db: Session, codigo: str) -> list[Plan]:
    return list(
        db.scalars(select(Plan).where(Plan.codigo == codigo).order_by(Plan.vigente_desde)).all()
    )


def cambiar_precio(
    db: Session,
    codigo: str,
    nuevo_precio: Decimal,
    vigente_desde: date,
    hoy: date,
    nuevos_limites: dict | None = None,
) -> Plan:
    """Crea una versión nueva del plan. Las suscripciones vivas NO cambian.

    La vigencia tiene que ser futura: retroactivar un precio significaría
    recalcular cobros ya emitidos, que es exactamente lo que no debe pasar.
    """
    if vigente_desde <= hoy:
        raise ConfiguracionError(
            "La nueva vigencia debe ser una fecha futura: los precios no se cambian "
            "hacia atrás porque ya hay cobros emitidos."
        )
    if nuevo_precio < 0:
        raise ConfiguracionError("El precio no puede ser negativo")

    actual = plan_vigente_por_codigo(db, codigo, hoy)
    if actual is None:
        raise ConfiguracionError(f"No existe un plan vigente con el código {codigo}")

    # Si ya había una versión programada para esa misma fecha, se reemplaza
    programada = db.scalars(
        select(Plan).where(Plan.codigo == codigo, Plan.vigente_desde == vigente_desde)
    ).first()
    if programada is not None:
        programada.precio_mensual = nuevo_precio
        if nuevos_limites is not None:
            programada.limites = nuevos_limites
        db.flush()
        return programada

    nueva = Plan(
        codigo=codigo,
        nombre=actual.nombre,
        precio_mensual=nuevo_precio,
        limites=nuevos_limites if nuevos_limites is not None else dict(actual.limites or {}),
        vigente_desde=vigente_desde,
        activo=True,
    )
    db.add(nueva)
    # La versión anterior deja de regir justo cuando empieza la nueva
    actual.vigente_hasta = vigente_desde
    db.flush()
    return nueva


def suscripciones_afectadas(db: Session, plan_id: uuid.UUID) -> int:
    return int(
        db.execute(
            select(func.count(Suscripcion.id)).where(Suscripcion.plan_id == plan_id)
        ).scalar_one()
    )


# ------------------------------------------------------------ cost_rates


def tarifa_vigente(db: Session, proveedor: str, concepto: str, cuando: date) -> CostRate | None:
    return db.scalars(
        select(CostRate)
        .where(
            CostRate.proveedor == proveedor,
            CostRate.concepto == concepto,
            CostRate.vigente_desde <= cuando,
            (CostRate.vigente_hasta.is_(None)) | (CostRate.vigente_hasta > cuando),
        )
        .order_by(CostRate.vigente_desde.desc())
        .limit(1)
    ).first()


def programar_tarifa(
    db: Session,
    proveedor: str,
    concepto: str,
    costo_unitario: Decimal,
    unidad: str,
    vigente_desde: date,
    notas: str | None = None,
    hoy: date | None = None,
) -> CostRate:
    """Programa una tarifa futura y cierra la anterior. Igual que los planes:
    el costo de ayer no se reescribe.

    Eso lo decía el docstring pero no lo comprobaba nadie. Sin la guarda, una
    tarifa con fecha pasada reescribía el costo de un mes ya reportado: los
    costos de IA e infraestructura se valoran con la tarifa vigente EN LA FECHA
    de cada evento, así que retroactivar la tarifa cambia el pasado. Y guardar
    dos veces la misma fecha dejaba dos filas abiertas a la vez, con lo que el
    costo del mes salía distinto en cada carga de la pantalla.
    """
    hoy = hoy or date.today()
    if vigente_desde <= hoy:
        raise ConfiguracionError(
            "La nueva vigencia debe ser una fecha futura: las tarifas no se cambian "
            "hacia atrás porque ya hay costos calculados con las anteriores."
        )
    if costo_unitario < 0:
        raise ConfiguracionError("El costo no puede ser negativo")

    # Si ya había una tarifa programada para esa misma fecha, se REEMPLAZA en
    # vez de añadir otra: es corregir un tecleo, no programar dos alzas.
    programada = db.scalars(
        select(CostRate).where(
            CostRate.proveedor == proveedor,
            CostRate.concepto == concepto,
            CostRate.vigente_desde == vigente_desde,
        )
    ).first()
    if programada is not None:
        programada.costo_unitario = costo_unitario
        programada.unidad = unidad
        if notas is not None:
            programada.notas = notas
        db.flush()
        return programada

    anterior = db.scalars(
        select(CostRate)
        .where(
            CostRate.proveedor == proveedor,
            CostRate.concepto == concepto,
            CostRate.vigente_hasta.is_(None),
        )
        .order_by(CostRate.vigente_desde.desc())
        .limit(1)
    ).first()

    nueva = CostRate(
        proveedor=proveedor,
        concepto=concepto,
        costo_unitario=costo_unitario,
        unidad=unidad,
        vigente_desde=vigente_desde,
        notas=notas,
    )
    db.add(nueva)
    if anterior is not None and anterior.vigente_desde < vigente_desde:
        anterior.vigente_hasta = vigente_desde
    db.flush()
    return nueva


# El alza de Meta de octubre de 2026 va precargada (requisito 4.1).
TARIFAS_SEMILLA: list[dict] = [
    {
        "proveedor": "META_WHATSAPP",
        "concepto": "Conversación iniciada por la empresa",
        "costo_unitario": Decimal("0.0400"),
        "unidad": "conversacion",
        "vigente_desde": date(2026, 1, 1),
        "notas": "Tarifa vigente hasta el alza anunciada por Meta.",
    },
    {
        "proveedor": "META_WHATSAPP",
        "concepto": "Conversación iniciada por la empresa",
        "costo_unitario": Decimal("0.0528"),
        "unidad": "conversacion",
        "vigente_desde": date(2026, 10, 1),
        "notas": "Alza anunciada por Meta para octubre de 2026.",
    },
    {
        "proveedor": "META_WHATSAPP",
        "concepto": "Conversación iniciada por el usuario",
        "costo_unitario": Decimal("0.0000"),
        "unidad": "conversacion",
        "vigente_desde": date(2026, 1, 1),
        "notas": "Las conversaciones que inicia el usuario no se cobran.",
    },
]


def sembrar_tarifas(db: Session) -> int:
    """Idempotente: se puede correr en cada despliegue."""
    creadas = 0
    for t in TARIFAS_SEMILLA:
        existe = db.scalars(
            select(CostRate).where(
                CostRate.proveedor == t["proveedor"],
                CostRate.concepto == t["concepto"],
                CostRate.vigente_desde == t["vigente_desde"],
            )
        ).first()
        if existe is not None:
            continue
        db.add(CostRate(**t))
        creadas += 1
    db.flush()
    # Encadena las vigencias: cada tarifa cierra cuando empieza la siguiente
    for proveedor, concepto in {(t["proveedor"], t["concepto"]) for t in TARIFAS_SEMILLA}:
        versiones = list(
            db.scalars(
                select(CostRate)
                .where(CostRate.proveedor == proveedor, CostRate.concepto == concepto)
                .order_by(CostRate.vigente_desde)
            ).all()
        )
        for previa, siguiente in zip(versiones, versiones[1:], strict=False):
            previa.vigente_hasta = siguiente.vigente_desde
    db.flush()
    return creadas
