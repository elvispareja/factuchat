"""Esquemas de autenticación. Validación estricta en la frontera (OWASP A05)."""

import uuid

from pydantic import BaseModel, EmailStr, Field


class SolicitarCodigoIn(BaseModel):
    """Primer paso: el correo. La respuesta es siempre la misma, exista o no."""

    email: EmailStr


class LoginRequest(BaseModel):
    """Segundo paso: el código de seis dígitos.

    Para un cliente es el que le llegó por correo; para el personal interno, el
    de su app de autenticación. El campo es el mismo a propósito: la pantalla no
    tiene por qué saber de qué tipo es la cuenta antes de tiempo.
    """

    email: EmailStr
    codigo: str = Field(min_length=6, max_length=8)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — tipo OAuth2, no una contraseña
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class TotpSetupBeginRequest(BaseModel):
    setup_token: str = Field(max_length=2000)


class TotpSetupBeginResponse(BaseModel):
    secret: str
    otpauth_uri: str


class TotpActivateRequest(BaseModel):
    setup_token: str = Field(max_length=2000)
    code: str = Field(min_length=6, max_length=8)


class MeResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    nombre: str
    rol: str
    tenant_id: uuid.UUID | None
