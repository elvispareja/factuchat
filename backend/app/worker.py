"""Celery: emisión de comprobantes, WhatsApp, correos y buzón corren aquí,
nunca en el request (fase 2.5). En fase 1 solo queda montada la infraestructura."""

from celery import Celery

from app.core.config import get_settings
from app.core.observabilidad import init_sentry

settings = get_settings()

# Sentry con filtro de secretos y sin variables locales: el worker es quien
# descifra el .p12, así que aquí la protección es imprescindible (A04)
init_sentry("worker")

celery_app = Celery(
    "factuchat",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.emision",
        "app.tasks.whatsapp",
        "app.tasks.notificaciones",
        "app.tasks.buzon",
    ],
)
celery_app.conf.update(
    task_acks_late=True,  # reencolar si el worker muere (A10)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="America/Guayaquil",
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="factuchat.ping")
def ping() -> str:
    return "pong"
