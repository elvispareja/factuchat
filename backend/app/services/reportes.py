"""Resumen fiscal (fase 3.1 / checklist F3).

Los números salen SOLO de comprobantes AUTORIZADOS: un borrador, un rechazado o
uno en proceso no es un ingreso declarable. Las notas de crédito restan.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Comprobante, Tenant
from app.db.models.enums import EstadoComprobante, TipoComprobante
from app.services import retenciones

# Fecha máxima de declaración de IVA según el noveno dígito del RUC
# (calendario del SRI). Índice 0 = dígito 1.
DIA_POR_NOVENO_DIGITO = {
    "1": 10,
    "2": 12,
    "3": 14,
    "4": 16,
    "5": 18,
    "6": 20,
    "7": 22,
    "8": 24,
    "9": 26,
    "0": 28,
}

MESES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


# Lo que suma como venta. La NOTA DE DÉBITO va aquí, con la factura: no es un
# documento aparte, es un cobro MÁS sobre una venta ya hecha (un interés de mora,
# un gasto que se repercute) y su IVA es IVA generado que hay que declarar. Si se
# queda fuera, el negocio cobra ese impuesto y el panel le dice que no lo debe.
# La nota de crédito es la que va aparte, porque resta.
TIPOS_VENTA = [
    TipoComprobante.FACTURA,
    TipoComprobante.NOTA_DEBITO,
    TipoComprobante.LIQUIDACION_COMPRA,
]


def noveno_digito(ruc: str) -> str:
    return ruc[8] if len(ruc) >= 9 else "1"


def proxima_declaracion(ruc: str, hoy: date) -> dict:
    """Fecha máxima de la próxima declaración de IVA de este contribuyente."""
    digito = noveno_digito(ruc)
    dia = DIA_POR_NOVENO_DIGITO.get(digito, 28)
    # Se declara el mes anterior; si ya pasó la fecha de este mes, toca el siguiente
    anio, mes = hoy.year, hoy.month
    if hoy.day > dia:
        mes += 1
        if mes > 12:
            mes, anio = 1, anio + 1
    limite = date(anio, mes, dia)
    return {
        "noveno_digito": digito,
        "dia_maximo": dia,
        "fecha_limite": limite.isoformat(),
        "dias_restantes": (limite - hoy).days,
        "periodo_declarado": MESES[(mes - 2) % 12],
    }


@dataclass
class ResumenFiscal:
    desde: date
    hasta: date
    ventas_gravadas: Decimal
    ventas_sin_iva: Decimal
    iva_cobrado: Decimal
    notas_credito: Decimal
    total_facturado: Decimal
    # Solo la retención de IVA: es la que descuenta del IVA a pagar
    retenciones_recibidas: Decimal
    # La de renta va aparte: es crédito de la declaración ANUAL, no del IVA
    retenciones_renta: Decimal
    a_pagar: Decimal
    comprobantes_emitidos: int


def _rango_mes(hoy: date) -> tuple[date, date]:
    desde = hoy.replace(day=1)
    hasta = date(hoy.year + 1, 1, 1) if hoy.month == 12 else date(hoy.year, hoy.month + 1, 1)
    return desde, hasta


def resumen_fiscal(
    db: Session,
    tenant_id: uuid.UUID,
    desde: date | None = None,
    hasta: date | None = None,
    hoy: date | None = None,
) -> ResumenFiscal:
    hoy = hoy or date.today()
    if desde is None or hasta is None:
        desde, hasta = _rango_mes(hoy)

    def _suma(tipos: list[TipoComprobante], columna) -> Decimal:
        valor = db.execute(
            select(func.coalesce(func.sum(columna), 0)).where(
                Comprobante.tenant_id == tenant_id,
                Comprobante.estado == EstadoComprobante.AUTORIZADO,
                Comprobante.tipo.in_(tipos),
                Comprobante.fecha_emision >= desde,
                Comprobante.fecha_emision < hasta,
            )
        ).scalar_one()
        return Decimal(str(valor))

    ventas = TIPOS_VENTA
    subtotal_ventas = _suma(ventas, Comprobante.subtotal)
    iva_ventas = _suma(ventas, Comprobante.iva)
    total_ventas = _suma(ventas, Comprobante.total)

    creditos = [TipoComprobante.NOTA_CREDITO]
    total_creditos = _suma(creditos, Comprobante.total)

    # Retenciones que le hicieron al tenant: llegan por el buzón (fase 7).
    # SOLO la retención de IVA baja el IVA a pagar; la de renta es crédito de la
    # declaración anual de impuesto a la renta y se informa aparte. Restarlas
    # juntas de un solo impuesto haría declarar de menos.
    credito = retenciones.saldo(db, tenant_id, desde, hasta)

    iva_neto = iva_ventas - _suma(creditos, Comprobante.iva)
    a_pagar = max(Decimal("0"), iva_neto - credito.iva)

    emitidos = int(
        db.execute(
            select(func.count(Comprobante.id)).where(
                Comprobante.tenant_id == tenant_id,
                Comprobante.estado == EstadoComprobante.AUTORIZADO,
                Comprobante.fecha_emision >= desde,
                Comprobante.fecha_emision < hasta,
            )
        ).scalar_one()
    )

    return ResumenFiscal(
        desde=desde,
        hasta=hasta,
        ventas_gravadas=subtotal_ventas,
        ventas_sin_iva=subtotal_ventas,
        iva_cobrado=iva_ventas,
        notas_credito=total_creditos,
        total_facturado=total_ventas - total_creditos,
        retenciones_recibidas=credito.iva,
        retenciones_renta=credito.renta,
        a_pagar=a_pagar,
        comprobantes_emitidos=emitidos,
    )


def ventas_por_dia(db: Session, tenant_id: uuid.UUID, desde: date, hasta: date) -> list[dict]:
    filas = db.execute(
        select(Comprobante.fecha_emision, func.sum(Comprobante.total))
        .where(
            Comprobante.tenant_id == tenant_id,
            Comprobante.estado == EstadoComprobante.AUTORIZADO,
            Comprobante.tipo.in_(TIPOS_VENTA),
            Comprobante.fecha_emision >= desde,
            Comprobante.fecha_emision < hasta,
        )
        .group_by(Comprobante.fecha_emision)
        .order_by(Comprobante.fecha_emision)
    ).all()
    return [{"fecha": f[0].isoformat(), "total": str(f[1])} for f in filas]


def ranking_clientes(
    db: Session, tenant_id: uuid.UUID, desde: date, hasta: date, limite: int = 5
) -> list[dict]:
    from app.db.models import ClienteFinal

    filas = db.execute(
        select(
            ClienteFinal.razon_social,
            func.sum(Comprobante.total).label("total"),
            func.count(Comprobante.id),
        )
        .join(ClienteFinal, ClienteFinal.id == Comprobante.cliente_final_id)
        .where(
            Comprobante.tenant_id == tenant_id,
            Comprobante.estado == EstadoComprobante.AUTORIZADO,
            Comprobante.tipo.in_(TIPOS_VENTA),
            Comprobante.fecha_emision >= desde,
            Comprobante.fecha_emision < hasta,
        )
        .group_by(ClienteFinal.razon_social)
        .order_by(func.sum(Comprobante.total).desc())
        .limit(limite)
    ).all()
    return [{"cliente": f[0], "total": str(f[1]), "comprobantes": int(f[2])} for f in filas]


def datos_inicio(db: Session, tenant_id: uuid.UUID, hoy: date) -> dict:
    """Todo lo que pinta la sección Inicio de la maqueta."""
    tenant = db.get(Tenant, tenant_id)
    desde, hasta = _rango_mes(hoy)
    resumen = resumen_fiscal(db, tenant_id, desde, hasta, hoy)
    return {
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "ventas_del_mes": str(resumen.total_facturado),
        "iva_cobrado": str(resumen.iva_cobrado),
        "comprobantes_emitidos": resumen.comprobantes_emitidos,
        "proxima_declaracion": proxima_declaracion(tenant.ruc if tenant else "", hoy),
        "ranking": ranking_clientes(db, tenant_id, desde, hasta),
        "ventas_por_dia": ventas_por_dia(db, tenant_id, desde, hasta),
    }
