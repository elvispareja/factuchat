"""Cifrado simétrico AES-256-GCM para secretos en reposo (OWASP A04).

Formato del blob: base64( nonce(12) + ciphertext+tag ). El AAD separa dominios
de uso: un blob cifrado como contraseña no puede reutilizarse como archivo.
"""

import base64
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _load_key(key_b64: str, nombre: str) -> bytes:
    if not key_b64:
        raise RuntimeError(f"{nombre} no configurada")
    key = base64.b64decode(key_b64)
    if len(key) != 32:
        raise RuntimeError(f"{nombre} debe ser 32 bytes en base64")
    return key


def aesgcm_encrypt(key_b64: str, plaintext: bytes, aad: bytes, key_name: str = "clave") -> str:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_load_key(key_b64, key_name)).encrypt(nonce, plaintext, aad)
    return base64.b64encode(nonce + ct).decode()


def aesgcm_decrypt(key_b64: str, blob_b64: str, aad: bytes, key_name: str = "clave") -> bytes:
    raw = base64.b64decode(blob_b64)
    return AESGCM(_load_key(key_b64, key_name)).decrypt(raw[:12], raw[12:], aad)
