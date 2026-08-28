"""Cliente de la WhatsApp Cloud API de Meta (fase 5).

Solo se sale hacia graph.facebook.com: la lista blanca de destinos (OWASP A01)
es la misma idea que en el SRI. Ninguna URL provista por un usuario se visita.
"""

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings

logger = logging.getLogger("factuchat.whatsapp")

HOSTS_PERMITIDOS_META = {"graph.facebook.com"}

# Los botones de WhatsApp aceptan como mucho 3; las listas, 10 por sección.
MAX_BOTONES = 3
MAX_ITEMS_LISTA = 10
MAX_TEXTO = 4096


class WhatsAppError(Exception):
    """Error definitivo de la API de Meta."""


class WhatsAppTransientError(Exception):
    """Fallo de red o 5xx: se reintenta."""


@dataclass
class Enviado:
    wa_message_id: str
    destinatario: str


def _verificar_host(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in HOSTS_PERMITIDOS_META:
        raise WhatsAppError(f"Destino no permitido: {host}")


def _url() -> str:
    s = get_settings()
    if not s.wa_phone_number_id:
        raise WhatsAppError("Falta configurar el número de WhatsApp")
    return f"https://graph.facebook.com/{s.wa_api_version}/{s.wa_phone_number_id}/messages"


def _enviar(payload: dict[str, Any]) -> Enviado:
    s = get_settings()
    url = _url()
    _verificar_host(url)
    try:
        r = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {s.wa_access_token}"},
            timeout=s.wa_timeout_seconds,
        )
    except httpx.HTTPError as e:
        raise WhatsAppTransientError(f"Sin respuesta de Meta: {type(e).__name__}") from e

    if r.status_code >= 500 or r.status_code == 429:
        raise WhatsAppTransientError(f"Meta respondió {r.status_code}")
    if r.status_code >= 400:
        # El detalle va al log, no al usuario: puede traer datos de la cuenta
        logger.error("Meta rechazó el envío (%s): %s", r.status_code, r.text[:500])
        raise WhatsAppError(f"Meta rechazó el mensaje ({r.status_code})")

    datos = r.json()
    mensajes = datos.get("messages") or [{}]
    return Enviado(
        wa_message_id=mensajes[0].get("id", ""),
        destinatario=(datos.get("contacts") or [{}])[0].get("wa_id", payload.get("to", "")),
    )


def enviar_texto(destino: str, texto: str) -> Enviado:
    return _enviar(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destino,
            "type": "text",
            "text": {"preview_url": False, "body": texto[:MAX_TEXTO]},
        }
    )


def enviar_botones(destino: str, texto: str, botones: list[tuple[str, str]]) -> Enviado:
    """botones: [(id, título)]. WhatsApp permite 3 como máximo y 20 caracteres
    por título — recortar aquí evita un rechazo de Meta en producción."""
    if not botones:
        raise WhatsAppError("Un mensaje de botones necesita al menos uno")
    return _enviar(
        {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": texto[:1024]},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": bid, "title": titulo[:20]}}
                        for bid, titulo in botones[:MAX_BOTONES]
                    ]
                },
            },
        }
    )


def enviar_lista(
    destino: str,
    texto: str,
    boton: str,
    items: list[tuple[str, str, str]],
    titulo_seccion: str = "Opciones",
) -> Enviado:
    """items: [(id, título, descripción)]."""
    if not items:
        raise WhatsAppError("Una lista necesita al menos un elemento")
    return _enviar(
        {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": texto[:1024]},
                "action": {
                    "button": boton[:20],
                    "sections": [
                        {
                            "title": titulo_seccion[:24],
                            "rows": [
                                {
                                    "id": iid,
                                    "title": t[:24],
                                    "description": d[:72],
                                }
                                for iid, t, d in items[:MAX_ITEMS_LISTA]
                            ],
                        }
                    ],
                },
            },
        }
    )


def enviar_documento(destino: str, url_documento: str, nombre: str, texto: str = "") -> Enviado:
    """El documento se sirve desde nuestro propio dominio: la URL nunca viene
    del usuario, se construye a partir del comprobante."""
    return _enviar(
        {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "document",
            "document": {
                "link": url_documento,
                "filename": nombre[:100],
                "caption": texto[:1024] if texto else None,
            },
        }
    )


def enviar_plantilla(
    destino: str, nombre_plantilla: str, idioma: str, variables: list[str]
) -> Enviado:
    """Las plantillas son el único modo de escribir primero, fuera de la ventana
    de 24 horas. Meta las cobra como conversación iniciada por la empresa."""
    return _enviar(
        {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "template",
            "template": {
                "name": nombre_plantilla,
                "language": {"code": idioma},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": v} for v in variables],
                    }
                ],
            },
        }
    )


def marcar_leido(wa_message_id: str) -> None:
    """Cortesía con el usuario: la doble palomita azul. Un fallo aquí no debe
    tumbar el procesamiento del mensaje."""
    try:
        _enviar(
            {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": wa_message_id,
            }
        )
    except (WhatsAppError, WhatsAppTransientError):
        logger.debug("No se pudo marcar como leído %s", wa_message_id)
