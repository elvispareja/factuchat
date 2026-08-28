"""Aviso al equipo cuando entra un pedido o una consulta de la landing (fase 6.2).

El checklist F6 pide que el pedido por transferencia «cree registro y NOTIFIQUE».
El registro lo hace el endpoint; el aviso vive aquí, en un task aparte, por dos
razones:

  · Quien está en el checkout no debe esperar a que el SMTP responda, ni ver un
    error si el correo falla. Su pedido ya está guardado.
  · El aviso se reintenta solo. Un pedido pagado del que nadie se entera es
    dinero recibido sin servicio entregado, así que el reintento no es un lujo.

La marca `avisado_at` en la propia solicitud evita el aviso doble cuando el task
se reintenta después de un envío que sí salió.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.config import get_settings
from app.core.mailer import enviar_correo
from app.db.session import get_sessionmaker
from app.worker import celery_app

logger = logging.getLogger("factuchat.notificaciones")


def _escapar(v: str | None) -> str:
    """El nombre y el mensaje los escribe un desconocido: van escapados o el
    correo del equipo se convierte en un vector de inyección HTML."""
    if not v:
        return "—"
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


@celery_app.task(
    name="factuchat.notificaciones.aviso_solicitud",
    bind=True,
    max_retries=8,
    retry_backoff=True,
    retry_backoff_max=1800,
    acks_late=True,
)
def aviso_solicitud(self, solicitud_id: str) -> str:
    """Avisa al correo de ventas que entró una solicitud de la landing."""
    destino = get_settings().email_ventas
    db = get_sessionmaker()()
    try:
        # El personal interno es quien puede leer esta tabla (política RLS)
        db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        fila = db.execute(
            text(
                "SELECT nombre,email,telefono,identificacion,ciudad,provincia,pais,plan,"
                "metodo_pago,agenda_dia,agenda_hora,mensaje,comprobante_url,avisado_at "
                "FROM solicitudes_contacto WHERE id = :i"
            ),
            {"i": solicitud_id},
        ).one_or_none()
        if fila is None:
            return "no-existe"
        if fila.avisado_at is not None:
            return "ya-avisado"

        es_pedido = bool(fila.plan)
        asunto = (
            f"Nuevo pedido: plan {fila.plan} por {fila.metodo_pago}"
            if es_pedido
            else f"Consulta desde la web de {fila.nombre}"
        )
        campos = [
            ("Nombre", fila.nombre),
            ("Correo", fila.email),
            ("Teléfono", fila.telefono),
            ("Identificación", fila.identificacion),
            ("Ciudad", f"{fila.ciudad or '—'}, {fila.provincia or '—'}, {fila.pais}"),
            ("Plan", fila.plan),
            ("Forma de pago", fila.metodo_pago),
            (
                "Agenda",
                f"{fila.agenda_dia} a las {fila.agenda_hora}" if fila.agenda_dia else None,
            ),
            ("Comprobante", "adjuntó comprobante de pago" if fila.comprobante_url else None),
            ("Mensaje", fila.mensaje),
        ]
        filas_html = "".join(
            f"<tr><td style='padding:4px 10px 4px 0;color:#5A7267'>{k}</td>"
            f"<td style='padding:4px 0'><strong>{_escapar(v)}</strong></td></tr>"
            for k, v in campos
            if v
        )
        cuerpo = (
            f"<div style='font-family:system-ui,sans-serif;color:#123D2F'>"
            f"<h2 style='margin:0 0 14px'>{_escapar(asunto)}</h2>"
            f"<table style='font-size:14px'>{filas_html}</table>"
            f"<p style='font-size:12.5px;color:#5A7267;margin-top:18px'>"
            f"Referencia interna: {solicitud_id}</p></div>"
        )

        enviar_correo(destino, asunto, cuerpo)

        # La marca se escribe DESPUÉS del envío: si el correo falla, el reintento
        # vuelve a intentarlo; si sale y esto falla, el reintento lo detecta por
        # avisado_at y no manda un segundo correo.
        db.execute(
            text("UPDATE solicitudes_contacto SET avisado_at = :t WHERE id = :i"),
            {"t": datetime.now(UTC), "i": solicitud_id},
        )
        db.commit()
        return "avisado"
    except Exception as exc:  # noqa: BLE001 — el reintento es el manejo
        db.rollback()
        logger.warning("No se pudo avisar la solicitud %s: %s", solicitud_id, exc)
        raise self.retry(exc=exc) from exc
    finally:
        db.close()
