"""Retenciones recibidas: el crédito tributario del inquilino (fase 7).

Dos reglas de negocio que no se pueden mezclar:

  · **Renta e IVA son impuestos distintos.** La retención de IVA baja el IVA que
    se declara cada mes o semestre; la de renta es crédito para la declaración
    ANUAL de impuesto a la renta. Sumarlas y restarlas juntas del IVA a pagar
    daría un número fiscalmente falso, y el cliente declararía de menos.
  · **El flag manda, sobre el BUZÓN.** Con BUZON_ACTIVO apagado no cuenta —ni
    se ve— nada de lo que entró por correo: no se le puede cambiar el IVA a
    pagar a nadie por un módulo que todavía no se ha encendido. Lo que el propio
    contribuyente registró A MANO es otra cosa: lo subió él, sabe que está ahí,
    y esconderlo o dejarlo fuera del saldo le haría declarar de más. El
    interruptor apaga la automatización, no el archivador del cliente.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import RetencionRecibida
from app.services import parametros

ORIGENES = ("BUZON", "MANUAL", "WHATSAPP")
ORIGEN_MANUAL = "MANUAL"


@dataclass
class SaldoRetenciones:
    renta: Decimal
    iva: Decimal
    documentos: int
    agentes: int

    @property
    def total(self) -> Decimal:
        """Lo que la maqueta llama «Saldo a tu favor»: renta + IVA. Sirve para
        mostrarlo junto, nunca para restarlo de un solo impuesto."""
        return self.renta + self.iva


def activo(db: Session) -> bool:
    """El módulo puede encenderse en caliente, así que se pregunta a la base."""
    return parametros.buzon_activo(db)


def _base(
    tenant_id: uuid.UUID,
    desde: date | None,
    hasta: date | None,
    solo_verificadas: bool,
    solo_manual: bool = False,
):
    filtros = [RetencionRecibida.tenant_id == tenant_id]
    if solo_manual:
        # Módulo apagado: el buzón no existe todavía, pero lo que el cliente
        # registró a mano sigue siendo suyo.
        filtros.append(RetencionRecibida.origen == ORIGEN_MANUAL)
    if solo_verificadas:
        # Al SALDO solo entra lo que el SRI confirmó. Un XML lo escribe
        # cualquiera, y este número baja el impuesto que el cliente declara.
        filtros.append(RetencionRecibida.verificada.is_(True))
    if desde is not None:
        filtros.append(RetencionRecibida.fecha_emision >= desde)
    if hasta is not None:
        filtros.append(RetencionRecibida.fecha_emision < hasta)
    return filtros


def saldo(
    db: Session,
    tenant_id: uuid.UUID,
    desde: date | None = None,
    hasta: date | None = None,
) -> SaldoRetenciones:
    """Crédito acumulado en el período. Con el módulo apagado, solo lo manual."""
    solo_manual = not activo(db)
    fila = db.execute(
        select(
            func.coalesce(func.sum(RetencionRecibida.total_renta), 0),
            func.coalesce(func.sum(RetencionRecibida.total_iva), 0),
            func.count(RetencionRecibida.id),
            func.count(func.distinct(RetencionRecibida.ruc_agente)),
        ).where(*_base(tenant_id, desde, hasta, True, solo_manual))
    ).one()
    return SaldoRetenciones(
        renta=Decimal(str(fila[0])),
        iva=Decimal(str(fila[1])),
        documentos=int(fila[2]),
        agentes=int(fila[3]),
    )


def listar(
    db: Session,
    tenant_id: uuid.UUID,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 200,
) -> list[RetencionRecibida]:
    consulta = (
        select(RetencionRecibida)
        # La bandeja SÍ muestra las pendientes: el cliente tiene derecho a ver
        # que su documento llegó, aunque todavía no cuente para el saldo.
        .where(*_base(tenant_id, desde, hasta, False, not activo(db)))
        .order_by(RetencionRecibida.fecha_emision.desc().nullslast())
        .limit(limite)
    )
    return list(db.scalars(consulta).all())


def semestre_de(hoy: date) -> tuple[date, date]:
    """El semestre fiscal en curso. La maqueta habla de «crédito acumulado del
    semestre», que es el período en que declara el RIMPE."""
    if hoy.month <= 6:
        return date(hoy.year, 1, 1), date(hoy.year, 7, 1)
    return date(hoy.year, 7, 1), date(hoy.year + 1, 1, 1)


def a_json(r: RetencionRecibida) -> dict:
    return {
        "id": str(r.id),
        "quien": r.razon_social_agente,
        "ruc": r.ruc_agente,
        "numero": r.numero,
        "fecha": r.fecha_emision.isoformat() if r.fecha_emision else None,
        "concepto": r.concepto,
        "renta": str(r.total_renta),
        "iva": str(r.total_iva),
        "origen": r.origen,
        "verificada": r.verificada,
        # `verificada = False` son DOS cosas: «aún no se ha preguntado» y «el SRI
        # ya dijo que no». La pantalla las pintaba igual, así que un documento
        # muerto se enseñaba como si la respuesta viniera de camino, para
        # siempre. Con esto se distinguen: hay respuesta cuando ya se preguntó.
        "respondido": r.verificada_at is not None,
        "verificacion": (r.verificacion or {}).get("detalle"),
        "tiene_xml": bool(r.xml_path),
        "tiene_pdf": bool(r.pdf_path),
    }
