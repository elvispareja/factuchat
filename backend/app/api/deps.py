"""Dependencias de autorización.

Deny by default (OWASP A01): TODA ruta protegida declara sus roles con
require_roles(...). No existe ruta de negocio sin rol explícito. La doble
barrera es: (1) verificación de rol aquí + (2) RLS por tenant en PostgreSQL.
"""

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.context import RequestContext, get_context, set_context
from app.core.security import decode_token
from app.db.models.enums import Rol
from app.db.session import apply_rls_context, get_db

_bearer = HTTPBearer(auto_error=False)

INTERNAL_ROLES = {Rol.SUPERADMIN, Rol.SOPORTE, Rol.LECTURA}


@dataclass
class AuthUser:
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    rol: Rol


def tenant_de(user: AuthUser) -> uuid.UUID:
    """Tenant del usuario autenticado; el personal interno no opera como tenant."""
    if user.tenant_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La cuenta no pertenece a un negocio")
    return user.tenant_id


def client_ip(request: Request) -> str:
    # nginx (único expuesto) fija X-Real-IP; en desarrollo se usa la conexión directa
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()[:64]
    return request.client.host if request.client else "desconocida"


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    payload = decode_token(credentials.credentials, expected_type="access")
    if payload is None:
        # Un token de impersonación vale para el panel del cliente, pero se
        # distingue del normal para poder auditarlo aparte (fase 4.1)
        payload = decode_token(credentials.credentials, expected_type="impersonacion")
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")

    try:
        rol = Rol(payload["rol"])
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada") from e

    user_id = uuid.UUID(payload["sub"])
    tenant_id = uuid.UUID(payload["tenant_id"]) if payload.get("tenant_id") else None

    base = get_context()
    imp_id = payload.get("imp")
    ctx = RequestContext(
        user_id=user_id,
        tenant_id=tenant_id,
        rol=rol.value,
        ip=base.ip or client_ip(request),
        user_agent=base.user_agent,
        request_id=base.request_id,
        impersonacion_id=uuid.UUID(imp_id) if imp_id else None,
        actor_rol_real=payload.get("actor_rol"),
    )
    set_context(ctx)
    # El contexto de auditoría viaja con la SESIÓN (los contextvars no cruzan
    # los hilos del threadpool de FastAPI); lo lee el listener de audit (1.5)
    db.info["audit_ctx"] = ctx
    # Fija los GUCs de RLS en la transacción de esta petición (fase 1.4)
    apply_rls_context(db, ctx, is_internal=rol in INTERNAL_ROLES)
    return AuthUser(id=user_id, tenant_id=tenant_id, rol=rol)


def firma_cargada(db: Session, tenant_id: uuid.UUID) -> bool:
    """¿El negocio tiene su certificado de firma activo?

    Va por SQL directo y no por el ORM porque se llama en CADA petición del
    cliente: es un EXISTS sobre el índice de tenant, no una carga de fila.
    """
    return bool(
        db.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM certificados"
                "                WHERE tenant_id = :t AND activo)"
            ),
            {"t": str(tenant_id)},
        ).scalar()
    )


def exigir_firma(
    user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthUser:
    """Sin firma electrónica cargada, el negocio no opera.

    El .p12 y su clave son privados del contribuyente: nadie de Factuchat los
    pide ni los ve. Por eso el alta interna NO los recoge y el certificado se
    sube desde el propio panel del cliente, en su primer ingreso.

    Esta comprobación vive en el SERVIDOR y no en la pantalla: esconder botones
    no impide llamar a la API. Se aplica a los routers de operación; quedan
    fuera, a propósito, el login, la carga del propio certificado y el estado
    del panel, porque son justamente lo que hace falta para desbloquearse.
    """
    if user.rol is not Rol.CLIENTE:
        return user  # el personal interno no emite; no le aplica
    if not firma_cargada(db, tenant_de(user)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "codigo": "FIRMA_REQUERIDA",
                "mensaje": (
                    "Sube tu firma electrónica para empezar a usar Factuchat. "
                    "Sin ella no podemos firmar tus comprobantes ante el SRI."
                ),
            },
        )
    return user


def require_roles(*roles: Rol):
    allowed = set(roles)

    def checker(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.rol not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permiso para esta acción")
        return user

    return checker
