"""Registro de conversaciones y su costo (fase 5.4).

Meta cobra por CONVERSACIÓN de 24 horas, no por mensaje, y distingue quién la
abrió: si la abre el usuario no se cobra; si la abre la empresa (una plantilla),
sí. Aquí se registra cada mensaje pero el costo se imputa UNA vez por ventana de
conversación, que es como factura Meta.

La tarifa se toma de `cost_rates` según la fecha del mensaje: si el alza de Meta
de octubre de 2026 entra en vigor, los mensajes de septiembre siguen valorados
al precio viejo. Reescribir el histórico falsearía el margen.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import WhatsappMsg
from app.db.models.enums import CategoriaMsg, DireccionMsg
from app.services.configuracion import tarifa_vigente

PROVEEDOR = "META_WHATSAPP"
CONCEPTO_EMPRESA = "Conversación iniciada por la empresa"
CONCEPTO_USUARIO = "Conversación iniciada por el usuario"

# Ventana de conversación de Meta
VENTANA = timedelta(hours=24)


def _concepto(categoria: CategoriaMsg) -> str:
    return CONCEPTO_EMPRESA if categoria == CategoriaMsg.EMPRESA else CONCEPTO_USUARIO


def hay_conversacion_abierta(
    db: Session, tenant_id: uuid.UUID, wa_phone: str, cuando: datetime
) -> bool:
    """¿Ya se cobró una conversación con este número en las últimas 24 h?"""
    desde = cuando - VENTANA
    existe = db.scalars(
        select(WhatsappMsg).where(
            WhatsappMsg.tenant_id == tenant_id,
            WhatsappMsg.wa_phone == wa_phone,
            WhatsappMsg.costo > 0,
            WhatsappMsg.created_at >= desde,
        )
    ).first()
    return existe is not None


def costo_de(db: Session, categoria: CategoriaMsg, cuando: date) -> Decimal:
    tarifa = tarifa_vigente(db, PROVEEDOR, _concepto(categoria), cuando)
    return Decimal(str(tarifa.costo_unitario)) if tarifa is not None else Decimal("0")


def registrar(
    db: Session,
    tenant_id: uuid.UUID,
    wa_phone: str,
    direccion: DireccionMsg,
    categoria: CategoriaMsg,
    tipo: str,
    contenido: dict,
    wa_message_id: str | None = None,
    cuando: datetime | None = None,
) -> WhatsappMsg:
    """Guarda el mensaje e imputa el costo solo si abre una conversación nueva.

    Idempotente por `wa_message_id`: Meta reenvía webhooks, y sin esta guarda un
    mismo mensaje se contaría (y se cobraría) dos veces.
    """
    cuando = cuando or datetime.now(UTC)

    if wa_message_id:
        ya = db.scalars(
            select(WhatsappMsg).where(WhatsappMsg.wa_message_id == wa_message_id)
        ).first()
        if ya is not None:
            return ya

    costo = Decimal("0")
    if categoria != CategoriaMsg.SERVICIO and not hay_conversacion_abierta(
        db, tenant_id, wa_phone, cuando
    ):
        costo = costo_de(db, categoria, cuando.date())

    msg = WhatsappMsg(
        tenant_id=tenant_id,
        wa_phone=wa_phone,
        direccion=direccion,
        categoria=categoria,
        tipo=tipo,
        wa_message_id=wa_message_id,
        contenido=contenido,
        costo=costo,
    )
    db.add(msg)
    db.flush()
    return msg


def resumen_mes(db: Session, hoy: date) -> dict:
    """Consumo del mes para el tablero del superadmin (empresa vs usuario)."""
    desde = hoy.replace(day=1)

    def _cuenta(categoria: CategoriaMsg | None, solo_cobrados: bool = False):
        consulta = select(
            func.count(WhatsappMsg.id), func.coalesce(func.sum(WhatsappMsg.costo), 0)
        ).where(func.date(WhatsappMsg.created_at) >= desde)
        if categoria is not None:
            consulta = consulta.where(WhatsappMsg.categoria == categoria)
        if solo_cobrados:
            consulta = consulta.where(WhatsappMsg.costo > 0)
        fila = db.execute(consulta).one()
        return int(fila[0]), Decimal(str(fila[1]))

    total_msgs, total_costo = _cuenta(None)
    empresa_msgs, empresa_costo = _cuenta(CategoriaMsg.EMPRESA)
    usuario_msgs, usuario_costo = _cuenta(CategoriaMsg.USUARIO)
    conversaciones, _ = _cuenta(None, solo_cobrados=True)

    return {
        "desde": desde.isoformat(),
        "mensajes": total_msgs,
        "conversaciones_cobradas": conversaciones,
        "costo_total": str(total_costo),
        "empresa": {"mensajes": empresa_msgs, "costo": str(empresa_costo)},
        "usuario": {"mensajes": usuario_msgs, "costo": str(usuario_costo)},
    }


def proyeccion_mes(db: Session, hoy: date, presupuesto: Decimal) -> dict:
    """Si el mes sigue a este ritmo, ¿cuánto se gastará? El superadmin necesita
    saberlo ANTES de pasarse, no cuando ya se pasó."""
    resumen = resumen_mes(db, hoy)
    gastado = Decimal(resumen["costo_total"])
    dia = hoy.day
    dias_mes = (hoy.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    total_dias = dias_mes.day

    proyectado = (gastado / dia * total_dias).quantize(Decimal("0.01")) if dia else gastado
    sobre_presupuesto = bool(presupuesto) and proyectado > presupuesto
    pct = int(proyectado / presupuesto * 100) if presupuesto else 0

    return {
        **resumen,
        "presupuesto": str(presupuesto),
        "gastado": str(gastado),
        "proyectado": str(proyectado),
        "pct_presupuesto": pct,
        "sobre_presupuesto": sobre_presupuesto,
        "dias_transcurridos": dia,
        "dias_del_mes": total_dias,
    }


def consumo_por_tenant(db: Session, hoy: date, limite: int = 50) -> list[dict]:
    """Cuánto cuesta cada inquilino: el dato que se cruza con lo que paga."""
    desde = hoy.replace(day=1)
    filas = db.execute(
        select(
            WhatsappMsg.tenant_id,
            func.count(WhatsappMsg.id),
            func.coalesce(func.sum(WhatsappMsg.costo), 0),
        )
        .where(func.date(WhatsappMsg.created_at) >= desde)
        .group_by(WhatsappMsg.tenant_id)
        .order_by(func.coalesce(func.sum(WhatsappMsg.costo), 0).desc())
        .limit(limite)
    ).all()
    return [
        {
            "tenant_id": str(f[0]),
            "mensajes": int(f[1]),
            "costo": str(Decimal(str(f[2]))),
        }
        for f in filas
    ]
