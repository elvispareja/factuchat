"""Rutas de autenticación (fase 1.3)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, client_ip, get_current_user
from app.core.ratelimit import RateLimitExceeded, check_login_rate, reset_account_rate
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    SolicitarCodigoIn,
    TokenResponse,
    TotpActivateRequest,
    TotpSetupBeginRequest,
    TotpSetupBeginResponse,
)
from app.services import acceso
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

# Mismo mensaje para código erróneo y para cuenta inexistente: la
# diferencia solo le serviría a quien esté probando direcciones.
CODIGO_INVALIDO = "Código incorrecto o caducado. Pide uno nuevo."


def _ua(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:400]


@router.post("/codigo", status_code=status.HTTP_202_ACCEPTED)
def pedir_codigo(body: SolicitarCodigoIn, request: Request, db: Session = Depends(get_db)):
    """Primer paso: manda un código de seis dígitos al correo.

    RESPONDE LO MISMO SIEMPRE, exista la cuenta o no, esté activa o no, y sea de
    cliente o de personal interno. Contestar distinto convertiría esta ruta en
    un buscador de direcciones registradas y, peor, en una forma de averiguar
    quién trabaja aquí.
    """
    ip = client_ip(request)
    try:
        check_login_rate(ip, body.email)
    except RateLimitExceeded as e:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Demasiados intentos. Espere unos minutos."},
            headers={"Retry-After": str(e.retry_after)},
        )

    datos = auth_service.solicitar_codigo(db, body.email, ip)
    if datos is not None:
        correo, nombre, codigo = datos
        # Después del commit: un correo con un código que no llegó a guardarse
        # es un código que no funciona.
        db.info.setdefault("post_commit", []).append(lambda: acceso.enviar(correo, nombre, codigo))
    return {"detail": "Si esa dirección tiene cuenta, ya va en camino un código de 6 dígitos."}


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    try:
        check_login_rate(ip, body.email)
    except RateLimitExceeded as e:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Demasiados intentos. Espere unos minutos."},
            headers={"Retry-After": str(e.retry_after)},
        )

    try:
        tokens = auth_service.login(db, body.email, body.codigo, ip, _ua(request))
    except auth_service.AccountLocked as e:
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Cuenta bloqueada temporalmente hasta {e.until.strftime('%H:%M UTC')}",
        ) from e
    except auth_service.TotpSetupRequired as e:
        # SUPERADMIN sin 2FA: no entra hasta configurarlo (obligatorio, fase 1.3)
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": "Debe configurar la verificación en dos pasos",
                "code": "TOTP_SETUP_REQUIRED",
                "setup_token": e.setup_token,
            },
        )
    except (
        auth_service.CodigoCaducado,
        auth_service.CodigoAgotado,
        auth_service.CodigoInvalido,
        auth_service.TotpRequired,
        auth_service.AuthError,
    ) as e:
        # UN SOLO MENSAJE para todo. Distinguir «ese código caducó» de «código
        # incorrecto» parecía más amable, pero el primero solo puede darse si la
        # dirección tiene cuenta: convertía esta ruta en un comprobador de
        # clientes. El servicio sí distingue los casos, para la bitácora.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, CODIGO_INVALIDO) from e

    reset_account_rate(body.email)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    try:
        tokens = auth_service.refresh(db, body.refresh_token, client_ip(request), _ua(request))
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada") from e
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    auth_service.logout(db, body.refresh_token, client_ip(request), _ua(request))
    return None


@router.post("/2fa/setup", response_model=TotpSetupBeginResponse)
def totp_setup(body: TotpSetupBeginRequest, request: Request, db: Session = Depends(get_db)):
    try:
        secret, uri = auth_service.totp_setup_begin(
            db, body.setup_token, client_ip(request), _ua(request)
        )
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de configuración inválido") from e
    return TotpSetupBeginResponse(secret=secret, otpauth_uri=uri)


@router.post("/2fa/activate", status_code=status.HTTP_204_NO_CONTENT)
def totp_activate(body: TotpActivateRequest, request: Request, db: Session = Depends(get_db)):
    try:
        auth_service.totp_setup_activate(
            db, body.setup_token, body.code, client_ip(request), _ua(request)
        )
    except auth_service.TotpRequired as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Código incorrecto") from e
    except auth_service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de configuración inválido") from e
    return None


@router.get("/me", response_model=MeResponse)
def me(user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(User, user.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    return MeResponse(
        id=row.id, email=row.email, nombre=row.nombre, rol=row.rol.value, tenant_id=row.tenant_id
    )
