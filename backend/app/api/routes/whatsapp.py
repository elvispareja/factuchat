"""Webhook de WhatsApp (fase 5.1) y tablero de consumo (5.4).

El webhook es público por diseño (Meta lo llama), así que la firma se verifica
SIEMPRE y antes de mirar el cuerpo. Sin firma válida no se parsea nada.
"""

import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles
from app.core.config import get_settings
from app.db.models.enums import Rol
from app.db.session import get_db
from app.whatsapp import consumo
from app.whatsapp.firma import FirmaInvalida, verificar, verificar_suscripcion

logger = logging.getLogger("factuchat.whatsapp")
router = APIRouter(tags=["whatsapp"])
TZ = ZoneInfo("America/Guayaquil")


@router.get("/whatsapp/webhook")
def verificar_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    """Handshake de alta que hace Meta al suscribir el webhook."""
    try:
        challenge = verificar_suscripcion(hub_mode, hub_verify_token, hub_challenge)
    except FirmaInvalida as e:
        logger.warning("Verificación de webhook rechazada: %s", e)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Verificación rechazada") from e
    return Response(content=challenge, media_type="text/plain")


@router.post("/whatsapp/webhook")
async def recibir_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
):
    """Recibe eventos de Meta. Responde 200 rápido y procesa en Celery: si se
    tarda, Meta reintenta y duplicaría el trabajo."""
    cuerpo = await request.body()

    # La firma se comprueba sobre el cuerpo CRUDO, antes de interpretarlo
    try:
        verificar(cuerpo, x_hub_signature_256)
    except FirmaInvalida as e:
        logger.warning(
            "Webhook rechazado (%s) desde %s", e, request.client.host if request.client else "?"
        )
        # 403 y nada más: no se revela por qué falló ni si el número existe
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Firma inválida") from e

    from app.tasks.whatsapp import procesar_webhook

    procesar_webhook.delay(cuerpo.decode("utf-8", errors="replace"))
    return {"status": "recibido"}


# ------------------------------------------------ tablero del panel interno

SOLO_INTERNO = require_roles(Rol.SUPERADMIN, Rol.SOPORTE, Rol.LECTURA)


@router.get("/sa/whatsapp/consumo")
def consumo_whatsapp(
    user: AuthUser = Depends(SOLO_INTERNO),
    db: Session = Depends(get_db),
):
    """Consumo del mes, su costo por tarifa vigente y la proyección contra el
    presupuesto (requisito 5.4 y el checklist F5)."""
    s = get_settings()
    hoy = datetime.now(TZ).date()
    datos = consumo.proyeccion_mes(db, hoy, Decimal(s.wa_presupuesto_mensual))
    datos["alerta"] = datos["sobre_presupuesto"] or datos["pct_presupuesto"] >= s.wa_alerta_pct
    datos["umbral_alerta_pct"] = s.wa_alerta_pct
    datos["por_cliente"] = consumo.consumo_por_tenant(db, hoy)
    return datos
