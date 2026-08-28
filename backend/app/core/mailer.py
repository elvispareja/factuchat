"""Correo saliente (fase 2.4: envío del RIDE al cliente final).

Con SMTP configurado envía por STARTTLS; sin SMTP (desarrollo/tests) escribe el
mensaje como .eml en email_outbox_dir para inspección. SMTP es uno de los únicos
destinos salientes permitidos (lista blanca A01)."""

import smtplib
import ssl
import uuid
from email.message import EmailMessage
from pathlib import Path

from app.core.config import get_settings


def enviar_correo(
    destinatario: str,
    asunto: str,
    cuerpo_html: str,
    adjuntos: list[tuple[str, bytes, str, str]] | None = None,  # (nombre, datos, tipo, subtipo)
) -> str:
    """Devuelve un identificador del envío (message-id o ruta del .eml)."""
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.email_from or "no-reply@localhost"
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg.set_content("Su comprobante electrónico está adjunto.")
    msg.add_alternative(cuerpo_html, subtype="html")
    for nombre, datos, tipo, subtipo in adjuntos or []:
        msg.add_attachment(datos, maintype=tipo, subtype=subtipo, filename=nombre)

    if s.smtp_host:
        # Contexto TLS con verificación de certificado y hostname: sin él, la
        # conexión acepta cualquier certificado y las credenciales SMTP y las
        # facturas quedan expuestas a un intermediario (OWASP A04).
        contexto = ssl.create_default_context()
        contexto.check_hostname = True
        contexto.verify_mode = ssl.CERT_REQUIRED

        if s.smtp_tls_implicito:
            # Puerto 465: cifrado desde el primer byte. Aquí NO se llama a
            # starttls(); hacerlo sobre una conexión ya cifrada da error.
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=30, context=contexto) as smtp:
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
        else:
            # Puerto 587: abre en claro y sube a TLS antes de autenticarse.
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
                if s.smtp_starttls:
                    smtp.starttls(context=contexto)
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
        return msg["Message-Id"] or "enviado"

    outbox = Path(s.email_outbox_dir)
    outbox.mkdir(parents=True, exist_ok=True)
    ruta = outbox / f"{uuid.uuid4().hex}.eml"
    ruta.write_bytes(bytes(msg))
    return str(ruta)
