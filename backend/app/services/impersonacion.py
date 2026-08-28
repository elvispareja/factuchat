"""Impersonación: entrar como un inquilino desde el panel interno (fase 4.1).

DOBLE RASTRO, que es lo que la hace aceptable:
 1. La sesión queda en `impersonaciones` (quién, a quién, motivo, inicio y fin).
 2. Cada acción hecha durante la impersonación se audita con el actor REAL, no
    con el del inquilino: el token lleva `imp` y el contexto marca `actor_real`.

El token de impersonación es corto y NO permite renovarse: se acaba cuando se
acaba. Y nunca da rol de personal interno sobre otro tenant: da rol CLIENTE
sobre el tenant impersonado, ni más ni menos.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.models import AuditLog, Impersonacion, User
from app.db.models.enums import Rol

# Ventana corta: soporte entra, mira lo que necesita y sale.
MINUTOS_IMPERSONACION = 30

# Quién puede impersonar. LECTURA nunca: mira, no actúa.
ROLES_PERMITIDOS = {Rol.SUPERADMIN, Rol.SOPORTE}


class ImpersonacionError(Exception):
    """Motivo legible para el operador."""


@dataclass
class SesionImpersonada:
    token: str
    expira_en: int
    tenant_id: uuid.UUID
    tenant_nombre: str
    impersonacion_id: uuid.UUID


def iniciar(
    db: Session,
    actor: User,
    tenant_id: uuid.UUID,
    motivo: str,
    ip: str | None,
    user_agent: str | None,
) -> SesionImpersonada:
    if actor.rol not in ROLES_PERMITIDOS:
        raise ImpersonacionError("Tu rol no permite entrar como un cliente")
    if not motivo or len(motivo.strip()) < 10:
        # Un motivo vacío convierte la auditoría en ruido
        raise ImpersonacionError("Escribe el motivo (mínimo 10 caracteres): queda en la auditoría")

    # El personal interno no lee `tenants` directamente (RLS de la fase 1):
    # pasa por la función segura, que verifica su rol en la base.
    fila = db.execute(
        text("SELECT razon_social FROM sa_tenant_basico(:t)"), {"t": str(tenant_id)}
    ).first()
    if fila is None:
        raise ImpersonacionError("El inquilino no existe")
    tenant_nombre = fila[0]

    # Una impersonación abierta por operador y tenant: si quedó una sin cerrar,
    # se cierra antes de abrir otra para que ninguna quede eterna.
    abiertas = db.scalars(
        select(Impersonacion).where(
            Impersonacion.actor_user_id == actor.id,
            Impersonacion.terminada_at.is_(None),
        )
    ).all()
    for vieja in abiertas:
        vieja.terminada_at = datetime.now(UTC)

    sesion = Impersonacion(
        actor_user_id=actor.id,
        tenant_id=tenant_id,
        motivo=motivo.strip()[:300],
        ip=ip,
        user_agent=user_agent,
    )
    db.add(sesion)
    db.flush()

    # Rastro 1: el evento de inicio, con el actor real
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            actor_rol=actor.rol.value,
            tenant_id=tenant_id,
            accion="IMPERSONACION_INICIO",
            tabla="impersonaciones",
            registro_id=str(sesion.id),
            despues={
                "motivo": sesion.motivo,
                "tenant": tenant_nombre,
                "expira_en_minutos": MINUTOS_IMPERSONACION,
            },
            ip=ip,
            user_agent=user_agent,
        )
    )

    token = create_access_token(
        user_id=actor.id,
        tenant_id=tenant_id,
        rol=Rol.CLIENTE.value,  # dentro del panel del cliente, actúa como cliente
        token_type="impersonacion",  # noqa: S106 — tipo de token, no una contraseña
        minutes=MINUTOS_IMPERSONACION,
        extra={"imp": str(sesion.id), "actor_rol": actor.rol.value},
    )
    return SesionImpersonada(
        token=token,
        expira_en=MINUTOS_IMPERSONACION * 60,
        tenant_id=tenant_id,
        tenant_nombre=tenant_nombre,
        impersonacion_id=sesion.id,
    )


def terminar(
    db: Session,
    actor: User,
    impersonacion_id: uuid.UUID,
    ip: str | None,
    user_agent: str | None,
) -> None:
    sesion = db.get(Impersonacion, impersonacion_id)
    if sesion is None or sesion.actor_user_id != actor.id:
        raise ImpersonacionError("Esa sesión de impersonación no es tuya")
    if sesion.terminada_at is not None:
        return  # idempotente: salir dos veces no es un error

    sesion.terminada_at = datetime.now(UTC)
    duracion = int((sesion.terminada_at - sesion.iniciada_at).total_seconds())
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            actor_rol=actor.rol.value,
            tenant_id=sesion.tenant_id,
            accion="IMPERSONACION_FIN",
            tabla="impersonaciones",
            registro_id=str(sesion.id),
            despues={"duracion_segundos": duracion},
            ip=ip,
            user_agent=user_agent,
        )
    )


def activas(db: Session) -> list[Impersonacion]:
    return list(
        db.scalars(
            select(Impersonacion)
            .where(Impersonacion.terminada_at.is_(None))
            .order_by(Impersonacion.iniciada_at.desc())
        ).all()
    )


def caducadas_sin_cerrar(db: Session) -> list[Impersonacion]:
    """Sesiones cuyo token ya expiró pero nadie cerró: el panel las muestra
    para que quede claro que no siguen abiertas de verdad."""
    corte = datetime.now(UTC) - timedelta(minutes=MINUTOS_IMPERSONACION)
    return list(
        db.scalars(
            select(Impersonacion).where(
                Impersonacion.terminada_at.is_(None),
                Impersonacion.iniciada_at < corte,
            )
        ).all()
    )


def settings_ok() -> bool:
    return bool(get_settings().secret_key)
