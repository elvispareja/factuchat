"""Contexto de la petición actual (contextvars) usado por RLS y auditoría.

Se llena en el middleware/dependencias tras validar el JWT y se limpia al final
de cada petición. La auditoría (fase 1.5) y el GUC de RLS (fase 1.4) leen de aquí.
"""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class RequestContext:
    user_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    rol: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # Impersonación (fase 4.1): durante una sesión impersonada, `rol` es CLIENTE
    # pero el actor REAL es personal interno. La auditoría guarda ambos, o el
    # rastro diría que el propio inquilino hizo lo que hizo soporte.
    impersonacion_id: uuid.UUID | None = None
    actor_rol_real: str | None = None


_current: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def set_context(ctx: RequestContext) -> None:
    _current.set(ctx)


def get_context() -> RequestContext:
    ctx = _current.get()
    if ctx is None:
        ctx = RequestContext()
        _current.set(ctx)
    return ctx


def clear_context() -> None:
    _current.set(None)
