"""Criptografía de autenticación (fase 1.3, OWASP A04/A07).

- Contraseñas: Argon2id con parámetros OWASP.
- Access tokens: JWT HS256 de 30 minutos.
- Refresh tokens: opacos (256 bits), almacenados solo como SHA-256, rotados en cada uso.
- Secretos TOTP: cifrados AES-256-GCM con clave maestra del entorno, nunca en claro en la BD.
"""

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

# Parámetros recomendados OWASP para Argon2id (m=64MiB, t=3, p=4)
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ---------------------------------------------------------------- JWT (access)


def create_access_token(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    rol: str,
    token_type: str = "access",  # noqa: S107 — es el TIPO de token, no una contraseña
    minutes: int | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id) if tenant_id else None,
        "rol": rol,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=minutes or s.access_token_minutes),
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any] | None:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload


# ------------------------------------------------------------- Refresh tokens


def new_refresh_token() -> tuple[str, str]:
    """Devuelve (token_en_claro, hash_sha256). Solo el hash toca la base de datos."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------------ TOTP (2FA)


def _totp_key() -> bytes:
    s = get_settings()
    if not s.totp_enc_key:
        raise RuntimeError("TOTP_ENC_KEY no configurada")
    key = base64.b64decode(s.totp_enc_key)
    if len(key) != 32:
        raise RuntimeError("TOTP_ENC_KEY debe ser 32 bytes en base64")
    return key


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def encrypt_totp_secret(secret: str) -> str:
    """AES-256-GCM: nonce(12) + ciphertext, en base64."""
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_totp_key()).encrypt(nonce, secret.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_totp_secret(blob: str) -> str:
    raw = base64.b64decode(blob)
    return AESGCM(_totp_key()).decrypt(raw[:12], raw[12:], None).decode()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="Factuchat")


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)
