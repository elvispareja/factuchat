"""Códigos promocionales (fase 4.1, sección Marketing).

"Retenido" es el ingreso que la promoción NO cobró: precio de lista menos precio
cobrado, por los meses que dura el beneficio. Se CONGELA al aplicarse — describe
un hecho pasado, así que un cambio de precio posterior no lo reescribe.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import Plan, PromoCode, PromoUse
from app.db.models.enums import TipoPromo


class PromoError(Exception):
    """Motivo legible para el operador o el cliente."""


def _d2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class ResultadoPromo:
    precio_lista: Decimal
    precio_cobrado: Decimal
    descuento: Decimal
    retenido: Decimal
    meses: int


def calcular(promo: PromoCode, precio_lista: Decimal) -> ResultadoPromo:
    """Qué se cobra y cuánto se deja de cobrar. Sin tocar la base de datos."""
    if promo.tipo == TipoPromo.PRECIO_FIJO:
        cobrado = _d2(promo.valor)
    elif promo.tipo == TipoPromo.PORCENTAJE:
        cobrado = _d2(precio_lista * (Decimal("100") - promo.valor) / Decimal("100"))
    elif promo.tipo == TipoPromo.MONTO_FIJO:
        cobrado = _d2(precio_lista - promo.valor)
    else:
        raise PromoError(f"Tipo de promoción no soportado: {promo.tipo}")

    cobrado = max(Decimal("0.00"), cobrado)
    descuento = _d2(precio_lista - cobrado)
    meses = max(1, int(promo.meses or 1))
    return ResultadoPromo(
        precio_lista=_d2(precio_lista),
        precio_cobrado=cobrado,
        descuento=descuento,
        # Lo retenido es por TODOS los meses que dura el beneficio
        retenido=_d2(descuento * meses),
        meses=meses,
    )


def buscar_vigente(db: Session, codigo: str, hoy: date) -> PromoCode:
    promo = db.scalars(
        select(PromoCode).where(func.upper(PromoCode.codigo) == codigo.strip().upper())
    ).first()
    if promo is None:
        raise PromoError("Ese código no existe")
    if not promo.activo:
        raise PromoError("Ese código está desactivado")
    if promo.vigente_desde > hoy:
        raise PromoError(f"Ese código empieza a regir el {promo.vigente_desde}")
    if promo.vigente_hasta is not None and promo.vigente_hasta < hoy:
        raise PromoError("Ese código ya venció")
    if promo.max_usos is not None and promo.usos >= promo.max_usos:
        raise PromoError("Ese código agotó sus cupos")
    return promo


def aplicar(
    db: Session,
    codigo: str,
    tenant_id: uuid.UUID,
    plan: Plan,
    hoy: date,
) -> PromoUse:
    """Aplica la promoción al alta de un inquilino y registra el uso.

    El incremento del contador va bajo FOR UPDATE: dos altas simultáneas con el
    último cupo no pueden pasar las dos.
    """
    promo = db.execute(
        select(PromoCode)
        .where(func.upper(PromoCode.codigo) == codigo.strip().upper())
        .with_for_update()
    ).scalar_one_or_none()
    if promo is None:
        raise PromoError("Ese código no existe")
    # Se revalida con la fila ya bloqueada
    promo = buscar_vigente(db, promo.codigo, hoy)

    if promo.planes and plan.nombre not in promo.planes:
        permitidos = ", ".join(promo.planes)
        raise PromoError(f"Ese código solo aplica a los planes: {permitidos}")

    ya_usado = db.scalars(
        select(PromoUse).where(PromoUse.promo_code_id == promo.id, PromoUse.tenant_id == tenant_id)
    ).first()
    if ya_usado is not None:
        raise PromoError("Este cliente ya usó ese código")

    calculo = calcular(promo, plan.precio_mensual)
    uso = PromoUse(
        promo_code_id=promo.id,
        tenant_id=tenant_id,
        monto_descuento=calculo.descuento,
        retenido=calculo.retenido,
        precio_lista=calculo.precio_lista,
        precio_cobrado=calculo.precio_cobrado,
        meses_aplicados=calculo.meses,
    )
    db.add(uso)
    promo.usos += 1
    db.flush()
    return uso


def usos_de(db: Session, promo_id: uuid.UUID) -> list[dict]:
    """Tabla de usos de la sección Marketing, con su columna Retenido.

    Va por función segura porque une con `tenants`, que el personal interno no
    puede leer directamente (RLS de la fase 1)."""
    filas = (
        db.execute(text("SELECT * FROM sa_promo_usos(:p)"), {"p": str(promo_id)}).mappings().all()
    )
    return [
        {
            "id": str(f["id"]),
            "usado_at": f["usado_at"].isoformat(),
            "cliente": f["cliente"],
            "ruc": f["ruc"],
            "precio_lista": str(f["precio_lista"]) if f["precio_lista"] is not None else None,
            "precio_cobrado": (
                str(f["precio_cobrado"]) if f["precio_cobrado"] is not None else None
            ),
            "descuento": str(f["descuento"]),
            "retenido": str(f["retenido"]),
            "meses": f["meses"],
        }
        for f in filas
    ]


def resumen(db: Session, promo_id: uuid.UUID) -> dict:
    fila = db.execute(
        select(
            func.count(PromoUse.id),
            func.coalesce(func.sum(PromoUse.retenido), 0),
            func.coalesce(func.sum(PromoUse.monto_descuento), 0),
        ).where(PromoUse.promo_code_id == promo_id)
    ).one()
    return {
        "usos": int(fila[0]),
        "retenido_total": str(Decimal(str(fila[1]))),
        "descuento_total": str(Decimal(str(fila[2]))),
    }


def altas_por_origen(db: Session) -> list[dict]:
    """De dónde vienen los inquilinos: qué código promo usó cada alta."""
    filas = db.execute(text("SELECT * FROM sa_marketing_origenes()")).mappings().all()
    return [
        {
            "origen": f["origen"],
            "altas": int(f["altas"]),
            "retenido": str(Decimal(str(f["retenido"]))),
        }
        for f in filas
    ]
