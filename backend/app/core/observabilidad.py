"""Inicialización de Sentry con protección de secretos (OWASP A04/A09).

Sin `include_local_variables=False`, Sentry adjunta las variables locales de
cada frame del stack: el .p12 descifrado y su contraseña viajarían fuera del
sistema en cualquier excepción durante la firma. El `before_send` es la segunda
barrera por si un valor sensible llega por otra vía (breadcrumbs, extras).
"""

from typing import Any, cast

import sentry_sdk
from sentry_sdk.types import Event

from app.core.config import get_settings

# Nombres que nunca deben salir del sistema, en cualquier envoltorio
CLAVES_SENSIBLES = {
    "password",
    "passwd",
    "contrasena",
    "contraseña",
    "secret",
    "secret_key",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "p12",
    "p12_bytes",
    "p12_data_enc",
    "p12_password_enc",
    "totp_secret",
    "totp_secret_enc",
    "totp_enc_key",
    "cert_enc_key",
    "key",
    "private_key",
    "smtp_password",
}

MASCARA = "[filtrado]"


def _limpiar(valor: Any, profundidad: int = 0) -> Any:
    if profundidad > 6:
        return valor
    if isinstance(valor, dict):
        return {
            k: (MASCARA if str(k).lower() in CLAVES_SENSIBLES else _limpiar(v, profundidad + 1))
            for k, v in valor.items()
        }
    if isinstance(valor, list):
        return [_limpiar(v, profundidad + 1) for v in valor]
    if isinstance(valor, bytes):
        return MASCARA  # material binario (un .p12 lo es) nunca se reporta
    return valor


def _before_send(event: "Event", hint: dict[str, Any]) -> "Event | None":
    return cast("Event", _limpiar(event))


def init_sentry(componente: str) -> None:
    s = get_settings()
    if not s.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=s.sentry_dsn,
        environment=s.environment,
        release=componente,
        send_default_pii=False,
        # Sin variables locales: el .p12 y su clave viven en frames de la firma
        include_local_variables=False,
        max_request_body_size="never",
        before_send=_before_send,
    )
