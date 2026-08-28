"""Flujos de autenticación (fase 1.3).

Toda lectura/escritura pre-autenticación pasa por funciones SECURITY DEFINER
(auth_*) creadas en la migración de RLS: el rol de la app no puede leer users
ni user_sessions fuera de su tenant, y cada evento queda en audit_log.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_token,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_totp_secret,
    hash_refresh_token,
    new_refresh_token,
    totp_uri,
    verify_totp,
)
from app.db.models.enums import Rol
from app.services import acceso

# Quienes entran con app de autenticación en vez de con código por correo
INTERNOS = {Rol.SUPERADMIN.value, Rol.SOPORTE.value, Rol.LECTURA.value}


class AuthError(Exception):
    """Error genérico de credenciales: el usuario siempre ve el mismo mensaje
    (sin enumeración de cuentas, OWASP A07)."""


class AccountLocked(Exception):
    def __init__(self, until: datetime) -> None:
        self.until = until


class CodigoInvalido(Exception):
    """El código no coincide. Mismo mensaje para todos: no se dice si el correo
    existe ni si el código era de otra cuenta."""


class CodigoCaducado(Exception):
    """No hay ningún código vivo: caducó o ya se usó. Merece un mensaje propio
    porque la salida es distinta —pedir otro— y no ayuda a nadie que ataque."""


class CodigoAgotado(Exception):
    """Demasiados intentos con el mismo código; hay que pedir uno nuevo."""


class TotpRequired(Exception):
    """La cuenta tiene 2FA activo y falta (o falló) el código."""


class TotpSetupRequired(Exception):
    """SUPERADMIN sin 2FA configurado: debe configurarlo antes de entrar."""

    def __init__(self, setup_token: str) -> None:
        self.setup_token = setup_token


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def _issue_tokens(
    db: Session,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    rol: str,
    ip: str | None,
    ua: str | None,
) -> TokenPair:
    s = get_settings()
    refresh, refresh_hash = new_refresh_token()
    db.execute(
        text("SELECT auth_create_session(:uid, :tid, :hash, :exp, :ip, :ua)"),
        {
            "uid": str(user_id),
            "tid": str(tenant_id) if tenant_id else None,
            "hash": refresh_hash,
            "exp": datetime.now(UTC) + timedelta(days=s.refresh_token_days),
            "ip": ip,
            "ua": ua,
        },
    )
    access = create_access_token(user_id, tenant_id, rol)
    return TokenPair(access, refresh, s.access_token_minutes * 60)


def solicitar_codigo(db: Session, email: str, ip: str | None) -> tuple[str, str, str] | None:
    """Emite un código de acceso para ese correo, si procede.

    Devuelve (destinatario, nombre, codigo) para que la ruta lo envíe DESPUÉS
    del commit, o None si no hay a quién enviárselo. La ruta responde lo mismo
    en los dos casos: si contestara distinto, cualquiera podría averiguar qué
    direcciones tienen cuenta probándolas una a una.
    """
    row = (
        db.execute(text("SELECT * FROM auth_get_user_for_login(:email)"), {"email": email})
        .mappings()
        .first()
    )
    if row is None or not row["is_active"] or row["tenant_estado"] == "BAJA":
        return None
    # Quien ya tiene app de autenticación saca de ahí su código: no se le manda
    # correo. Quien todavía NO la tiene —incluido el personal interno recién
    # creado— sí lo recibe, porque es lo único que puede probar que es él antes
    # de darse de alta en la app.
    if row["totp_enabled"]:
        return None

    codigo = acceso.emitir(db, row["id"], ip)
    return row["email"], row["nombre"], codigo


def login(db: Session, email: str, codigo: str, ip: str | None, ua: str | None) -> TokenPair:
    s = get_settings()
    row = (
        db.execute(text("SELECT * FROM auth_get_user_for_login(:email)"), {"email": email})
        .mappings()
        .first()
    )

    if row is None:
        raise AuthError()
    if not row["is_active"]:
        raise AuthError()
    if row["tenant_estado"] == "BAJA":
        raise AuthError()

    now = datetime.now(UTC)
    if row["locked_until"] is not None and row["locked_until"] > now:
        raise AccountLocked(row["locked_until"])

    rol = row["rol"]

    def fallo() -> None:
        db.execute(
            text("SELECT auth_login_failed(:uid, :ip, :ua, :max)"),
            {"uid": str(row["id"]), "ip": ip, "ua": ua, "max": s.login_max_attempts},
        )
        db.commit()

    if row["totp_enabled"]:
        # Personal interno: el código viene de su app de autenticación
        totp_row = (
            db.execute(text("SELECT * FROM auth_get_totp(:uid)"), {"uid": str(row["id"])})
            .mappings()
            .first()
        )
        if totp_row is None or totp_row["totp_secret_enc"] is None:
            raise AuthError()
        secret = decrypt_totp_secret(totp_row["totp_secret_enc"])
        if not verify_totp(secret, codigo):
            fallo()
            raise CodigoInvalido()
    else:
        # Cliente: el código de seis dígitos que le llegó por correo
        veredicto = acceso.comprobar(db, row["id"], codigo)
        if veredicto != "ok":
            fallo()
            if veredicto == "nada":
                raise CodigoCaducado()
            if veredicto == "agotado":
                raise CodigoAgotado()
            raise CodigoInvalido()

        # Solo AQUÍ, con el código del correo ya comprobado, se abre el alta de
        # la app de autenticación. Ponerlo antes —como estaba al quitar la
        # contraseña— dejaba que cualquiera que supiese el correo del superadmin
        # pidiera un token de alta, se registrara en 2FA y entrara. La única
        # credencial que queda es el buzón, así que es el buzón el que autoriza.
        if rol in INTERNOS:
            setup_token = create_access_token(
                row["id"],
                row["tenant_id"],
                rol,
                token_type="totp_setup",  # noqa: S106 — tipo de token, no una contraseña
                minutes=10,
            )
            db.commit()  # el código queda gastado aunque el alta no se termine
            raise TotpSetupRequired(setup_token)

    db.execute(
        text("SELECT auth_login_success(:uid, :ip, :ua)"),
        {"uid": str(row["id"]), "ip": ip, "ua": ua},
    )
    return _issue_tokens(db, row["id"], row["tenant_id"], rol, ip, ua)


def refresh(db: Session, refresh_token: str, ip: str | None, ua: str | None) -> TokenPair:
    token_hash = hash_refresh_token(refresh_token)
    row = (
        db.execute(text("SELECT * FROM auth_get_session(:hash)"), {"hash": token_hash})
        .mappings()
        .first()
    )

    if row is None:
        raise AuthError()

    # Reutilización de un refresh ya rotado = robo probable → se revoca TODO (A07)
    if row["revoked_at"] is not None:
        db.execute(
            text("SELECT auth_revoke_all_sessions(:uid, :motivo, :ip, :ua)"),
            {"uid": str(row["user_id"]), "motivo": "REUSO_DE_REFRESH", "ip": ip, "ua": ua},
        )
        db.commit()
        raise AuthError()

    now = datetime.now(UTC)
    if row["expires_at"] <= now or not row["is_active"]:
        raise AuthError()

    s = get_settings()
    new_token, new_hash = new_refresh_token()
    db.execute(
        text("SELECT auth_rotate_session(:old, :hash, :exp, :ip, :ua)"),
        {
            "old": str(row["session_id"]),
            "hash": new_hash,
            "exp": now + timedelta(days=s.refresh_token_days),
            "ip": ip,
            "ua": ua,
        },
    )
    access = create_access_token(row["user_id"], row["tenant_id"], row["rol"])
    return TokenPair(access, new_token, s.access_token_minutes * 60)


def logout(db: Session, refresh_token: str, ip: str | None, ua: str | None) -> None:
    row = (
        db.execute(
            text("SELECT * FROM auth_get_session(:hash)"),
            {"hash": hash_refresh_token(refresh_token)},
        )
        .mappings()
        .first()
    )
    if row is not None and row["revoked_at"] is None:
        db.execute(
            text("SELECT auth_revoke_session(:sid, :ip, :ua)"),
            {"sid": str(row["session_id"]), "ip": ip, "ua": ua},
        )


def totp_setup_begin(
    db: Session, setup_token: str, ip: str | None, ua: str | None
) -> tuple[str, str]:
    """Genera y guarda (cifrado) un secreto TOTP aún inactivo. Devuelve (secreto, uri)."""
    payload = decode_token(setup_token, expected_type="totp_setup")
    if payload is None:
        payload = decode_token(setup_token, expected_type="access")  # activación voluntaria
    if payload is None:
        raise AuthError()
    user_id = payload["sub"]
    secret = generate_totp_secret()
    db.execute(
        text("SELECT auth_set_totp(:uid, :secret, false, :ip, :ua)"),
        {"uid": user_id, "secret": encrypt_totp_secret(secret), "ip": ip, "ua": ua},
    )
    totp_row = (
        db.execute(text("SELECT * FROM auth_get_totp(:uid)"), {"uid": user_id}).mappings().first()
    )
    if totp_row is None:
        raise AuthError()
    return secret, totp_uri(secret, totp_row["email"])


def totp_setup_activate(
    db: Session, setup_token: str, code: str, ip: str | None, ua: str | None
) -> None:
    payload = decode_token(setup_token, expected_type="totp_setup")
    if payload is None:
        payload = decode_token(setup_token, expected_type="access")
    if payload is None:
        raise AuthError()
    user_id = payload["sub"]
    totp_row = (
        db.execute(text("SELECT * FROM auth_get_totp(:uid)"), {"uid": user_id}).mappings().first()
    )
    if totp_row is None or totp_row["totp_secret_enc"] is None:
        raise AuthError()
    secret = decrypt_totp_secret(totp_row["totp_secret_enc"])
    if not verify_totp(secret, code):
        raise TotpRequired()
    db.execute(
        text("SELECT auth_set_totp(:uid, :secret, true, :ip, :ua)"),
        {"uid": user_id, "secret": totp_row["totp_secret_enc"], "ip": ip, "ua": ua},
    )
