"""Verificación de la firma del webhook de Meta (fase 5.1, OWASP A08).

Meta firma cada webhook con HMAC-SHA256 del CUERPO CRUDO usando el App Secret,
y lo manda en `X-Hub-Signature-256: sha256=<hex>`.

Reglas que no se negocian:
 - La firma se valida SIEMPRE. Sin firma válida el cuerpo ni se parsea.
 - Se compara en tiempo constante, para no filtrar el secreto por temporización.
 - Se firma el cuerpo EXACTO recibido, no el re-serializado: cualquier cambio de
   orden o de espacios daría otro hash y rechazaría peticiones legítimas.
"""

import hashlib
import hmac

from app.core.config import get_settings

CABECERA = "X-Hub-Signature-256"
PREFIJO = "sha256="


class FirmaInvalida(Exception):
    """El cuerpo no viene firmado por Meta. Nunca se procesa."""


def calcular(cuerpo: bytes, app_secret: str) -> str:
    return PREFIJO + hmac.new(app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()


def verificar(cuerpo: bytes, cabecera: str | None) -> None:
    """Lanza FirmaInvalida si el webhook no viene de Meta."""
    app_secret = get_settings().wa_app_secret
    if not app_secret:
        # Sin secreto configurado no se puede verificar NADA: se rechaza todo.
        # Fallar abierto aquí equivaldría a dejar el webhook público.
        raise FirmaInvalida("WhatsApp no está configurado en este entorno")
    if not cabecera or not cabecera.startswith(PREFIJO):
        raise FirmaInvalida("Falta la firma del webhook")

    esperada = calcular(cuerpo, app_secret)
    if not hmac.compare_digest(esperada, cabecera):
        raise FirmaInvalida("Firma del webhook inválida")


def verificar_suscripcion(modo: str | None, token: str | None, challenge: str | None) -> str:
    """Handshake de alta del webhook: Meta pide GET con hub.verify_token."""
    esperado = get_settings().wa_verify_token
    if not esperado:
        raise FirmaInvalida("WhatsApp no está configurado en este entorno")
    if modo != "subscribe" or not token or not hmac.compare_digest(token, esperado):
        raise FirmaInvalida("Token de verificación inválido")
    return challenge or ""
