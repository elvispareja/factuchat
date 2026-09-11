"""Retenciones recibidas: el crédito tributario del inquilino (fase 7).

Dos reglas de negocio que no se pueden mezclar:

  · **Renta e IVA son impuestos distintos.** La retención de IVA baja el IVA que
    se declara cada mes o semestre; la de renta es crédito para la declaración
    ANUAL de impuesto a la renta. Sumarlas y restarlas juntas del IVA a pagar
    daría un número fiscalmente falso, y el cliente declararía de menos.
  · **LO TECLEADO A MANO CUENTA, Y SE DICE QUE NO ESTÁ RESPALDADO.** Una
    retención que el contribuyente escribe sin su XML no tiene clave de acceso,
    y sin clave no hay a quién preguntarle: no es que el SRI la rechace, es que
    no se le puede preguntar. Dejarla fuera del saldo le haría declarar de más
    por un papel que sí tiene en la mano. Así que suma, y la fila va marcada
    para que se sepa cuál está respaldada y cuál no. Lo que el SRI rechaza
    EXPRESAMENTE es otra cosa y no suma nunca.
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
from decimal import Decimal, InvalidOperation

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.buzon.ingesta import TECLEADA
from app.db.models import RetencionRecibida
from app.services import parametros

ORIGENES = ("BUZON", "MANUAL", "WHATSAPP")
ORIGEN_MANUAL = "MANUAL"

# La marca que deja `registrar_tecleada`. NO es la de `buzon/verificacion.py`
# cuando un XML no trae clave de acceso: aquélla vale para cualquier fichero,
# también para uno inventado, y contarla convertía en crédito un comprobante que
# se escribe en un editor de texto. Esta solo la pone la puerta en la que el
# propio contribuyente teclea lo que dice su papel.
SIN_CLAVE = TECLEADA


@dataclass
class SaldoRetenciones:
    renta: Decimal
    iva: Decimal
    documentos: int
    agentes: int
    # De lo de arriba, cuánto todavía no tiene respaldo del SRI. No se resta:
    # se enseña, para que el contribuyente sepa qué parte de su crédito
    # defendería con un papel y cuál con el XML.
    sin_respaldo: Decimal = Decimal("0")

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
        # AL SALDO ENTRA TODO MENOS LO QUE EL SRI RECHAZÓ EXPRESAMENTE. La
        # verificada la respalda el SRI; la tecleada sin clave la respalda el
        # papel que el cliente tiene en la mano, y esconderla le haría declarar
        # de más. Lo que el SRI miró y dijo que no, no suma jamás.
        filtros.append(_cuenta())
    if desde is not None:
        filtros.append(RetencionRecibida.fecha_emision >= desde)
    if hasta is not None:
        filtros.append(RetencionRecibida.fecha_emision < hasta)
    return filtros


def _cuenta():
    """La condición de «esto es crédito»: o el SRI lo confirmó, o lo tecleó el
    propio contribuyente."""
    return or_(
        RetencionRecibida.verificada.is_(True),
        RetencionRecibida.verificacion["estado"].astext == SIN_CLAVE,
    )


def _sin_respaldo():
    """Cuenta, pero sin XML que el SRI pueda confirmar."""
    return RetencionRecibida.verificacion["estado"].astext == SIN_CLAVE


def saldo(
    db: Session,
    tenant_id: uuid.UUID,
    desde: date | None = None,
    hasta: date | None = None,
) -> SaldoRetenciones:
    """Crédito acumulado en el período. Con el módulo apagado, solo lo manual."""
    solo_manual = not activo(db)
    sin_respaldo = func.sum(
        case(
            (_sin_respaldo(), RetencionRecibida.total_renta + RetencionRecibida.total_iva),
            else_=0,
        )
    )
    fila = db.execute(
        select(
            func.coalesce(func.sum(RetencionRecibida.total_renta), 0),
            func.coalesce(func.sum(RetencionRecibida.total_iva), 0),
            func.count(RetencionRecibida.id),
            func.count(func.distinct(RetencionRecibida.ruc_agente)),
            func.coalesce(sin_respaldo, 0),
        ).where(*_base(tenant_id, desde, hasta, True, solo_manual))
    ).one()
    return SaldoRetenciones(
        renta=Decimal(str(fila[0])),
        iva=Decimal(str(fila[1])),
        documentos=int(fila[2]),
        agentes=int(fila[3]),
        sin_respaldo=Decimal(str(fila[4])),
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


def anio_de(anio: int) -> tuple[date, date]:
    """El año natural. Es el período de la bandeja: el contribuyente piensa en
    «lo que me retuvieron este año», no en semestres del RIMPE."""
    return date(anio, 1, 1), date(anio + 1, 1, 1)


def anios_con_datos(db: Session, tenant_id: uuid.UUID) -> list[int]:
    """Los años en los que hay algo, para el desplegable. Sin datos, el actual."""
    anio = func.extract("year", RetencionRecibida.fecha_emision)
    filas = db.execute(
        select(anio)
        .where(*_base(tenant_id, None, None, False, not activo(db)))
        .distinct()
        .order_by(anio.desc())
    ).all()
    return [int(f[0]) for f in filas if f[0] is not None]


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
        # La base sobre la que le retuvieron y lo que suma esta fila: las dos
        # columnas de la maqueta.
        "base": str(r.base_imponible),
        "retenido": str(r.total_renta + r.total_iva),
        # Sobre cuál de TUS facturas te retuvieron. Sale del propio comprobante
        # (documento de sustento de la primera línea) cuando viene del XML.
        "factura": _factura_de(r),
        # Los porcentajes que la maqueta enseña como «8% · 70%».
        "porcentaje_renta": _porcentaje(r, "renta"),
        "porcentaje_iva": _porcentaje(r, "iva"),
        # Si suma al crédito, y si lo hace sin respaldo del SRI.
        "cuenta": r.verificada or (r.verificacion or {}).get("estado") == SIN_CLAVE,
        "sin_respaldo": (r.verificacion or {}).get("estado") == SIN_CLAVE,
        # `verificada = False` son DOS cosas: «aún no se ha preguntado» y «el SRI
        # ya dijo que no». La pantalla las pintaba igual, así que un documento
        # muerto se enseñaba como si la respuesta viniera de camino, para
        # siempre. Con esto se distinguen: hay respuesta cuando ya se preguntó.
        "respondido": r.verificada_at is not None,
        "verificacion": (r.verificacion or {}).get("detalle"),
        "tiene_xml": bool(r.xml_path),
        "tiene_pdf": bool(r.pdf_path),
        "lineas": (r.detalle or {}).get("lineas", []),
    }


def _lineas(r: RetencionRecibida) -> list[dict]:
    return list((r.detalle or {}).get("lineas") or [])


def _factura_de(r: RetencionRecibida) -> str | None:
    """El documento de sustento: la factura tuya sobre la que te retuvieron."""
    for linea in _lineas(r):
        if linea.get("doc_sustento"):
            return str(linea["doc_sustento"])
    return None


def _porcentaje(r: RetencionRecibida, cual: str) -> str | None:
    """El porcentaje de la línea de renta o la de IVA.

    Se reconoce por el código de impuesto del SRI (tabla 20): 1 = renta,
    2 = IVA. Si el comprobante no lo trae, no se inventa.
    """
    buscado = "1" if cual == "renta" else "2"
    for linea in _lineas(r):
        if str(linea.get("codigo") or "") != buscado:
            continue
        try:
            pct = Decimal(str(linea.get("porcentaje") or "0"))
        except InvalidOperation:
            continue
        if pct == 0:
            continue
        # «8.00» se lee mejor como «8». Con `normalize()` era «8», sí, pero
        # «70.00» salía como «7E+1» —y 70 % es la retención de IVA más común
        # que existe—, porque quitar los ceros de la derecha de un entero los
        # convierte en exponente. `:f` da la forma escrita de siempre.
        return f"{pct.normalize():f}"
    return None
