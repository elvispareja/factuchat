"""Auditoría automática (fase 1.5, OWASP A09).

Listeners de SQLAlchemy: toda escritura ORM (INSERT/UPDATE/DELETE) genera una fila
en audit_log dentro de la MISMA transacción, con quién, qué, tenant, antes/después
en JSON, IP, user agent y timestamp. Los campos sensibles se enmascaran (OWASP A04).

Las escrituras que ocurren dentro de las funciones SQL auth_* / sa_* insertan su
propia fila de auditoría desde SQL (ver migración de RLS).
"""

import datetime as dt
import decimal
import enum
import uuid
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.core.context import get_context
from app.db.models import AuditLog

# Nunca persistir estos valores en la bitácora
SENSITIVE_FIELDS = {
    "password_hash",
    "totp_secret_enc",
    "token_hash",
    "p12_password_enc",
    "p12_data_enc",
    # Buzón SRI (fase 7): lo escribe un tercero desconocido y el contenido del
    # correo se custodia CIFRADO. El mensaje de error del parser llega a citar
    # un trozo del XML ajeno, y el asunto puede traer datos personales; copiarlos
    # aquí los dejaría en claro dentro de una tabla inmutable que además lee el
    # personal interno, anulando el cifrado en reposo. La fila conserva el valor
    # real para el panel; lo que se enmascara es su copia en la bitácora.
    "motivo_error",
    "asunto",
}

MASK = "***"


def _serialize(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, bytes):
        return MASK
    return value


def _snapshot(obj: Any) -> dict[str, Any]:
    mapper = inspect(obj).mapper
    out: dict[str, Any] = {}
    for col in mapper.column_attrs:
        key = col.key
        value = getattr(obj, key)
        out[key] = MASK if key in SENSITIVE_FIELDS else _serialize(value)
    return out


def _changes(obj: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """(antes, despues) solo con los campos modificados."""
    state = inspect(obj)
    antes: dict[str, Any] = {}
    despues: dict[str, Any] = {}
    for attr in state.mapper.column_attrs:
        hist = state.get_history(attr.key, True)
        if not hist.has_changes():
            continue
        old = hist.deleted[0] if hist.deleted else None
        new = hist.added[0] if hist.added else None
        if attr.key in SENSITIVE_FIELDS:
            antes[attr.key] = MASK if old is not None else None
            despues[attr.key] = MASK if new is not None else None
        else:
            antes[attr.key] = _serialize(old)
            despues[attr.key] = _serialize(new)
    return antes, despues


def _make_entry(
    ctx: Any, accion: str, obj: Any, antes: dict | None, despues: dict | None
) -> AuditLog:
    despues = dict(despues) if despues else None
    # Segundo rastro de la impersonación (fase 4.1): sin esto, lo que hizo
    # soporte quedaría registrado como si lo hubiera hecho el propio inquilino.
    impersonacion_id = getattr(ctx, "impersonacion_id", None)
    if impersonacion_id is not None:
        despues = despues or {}
        despues["_impersonacion"] = {
            "id": str(impersonacion_id),
            "actor_rol_real": getattr(ctx, "actor_rol_real", None),
        }
    return AuditLog(
        actor_user_id=ctx.user_id,
        # El rol que se guarda es el REAL del actor, no el que le presta la sesión
        actor_rol=getattr(ctx, "actor_rol_real", None) or ctx.rol,
        tenant_id=getattr(obj, "tenant_id", None) or ctx.tenant_id,
        accion=accion,
        tabla=obj.__tablename__,
        registro_id=str(getattr(obj, "id", None)),
        antes=antes or None,
        despues=despues or None,
        ip=ctx.ip,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
    )


def _before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    # El contexto autenticado viaja en session.info (las dependencias síncronas
    # de FastAPI corren en threadpool y los contextvars no cruzan de vuelta);
    # como respaldo se usa el contextvar del middleware.
    ctx = session.info.get("audit_ctx") or get_context()
    entries: list[AuditLog] = []

    for obj in session.new:
        if isinstance(obj, AuditLog):
            continue
        # El default python-side (uuid4) aún no se aplicó en before_flush
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        entries.append(_make_entry(ctx, "INSERT", obj, None, _snapshot(obj)))

    for obj in session.dirty:
        if isinstance(obj, AuditLog) or not session.is_modified(obj):
            continue
        antes, despues = _changes(obj)
        if despues:
            entries.append(_make_entry(ctx, "UPDATE", obj, antes, despues))

    for obj in session.deleted:
        if isinstance(obj, AuditLog):
            continue
        entries.append(_make_entry(ctx, "DELETE", obj, _snapshot(obj), None))

    # Se insertan en el mismo flush y la misma transacción: si la escritura
    # se revierte, la auditoría también (consistencia, OWASP A10).
    if entries:
        session.add_all(entries)


def register_audit_listeners() -> None:
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)
