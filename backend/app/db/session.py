"""Motores y sesiones.

- Motor de la app: rol factuchat_app, SIEMPRE sujeto a RLS (fase 1.4).
- El contexto (tenant, usuario, interno) viaja como GUCs locales a la transacción:
  las políticas RLS leen app.tenant_id; sin contexto no hay filas (deny by default).
"""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.context import RequestContext

# Ecuador entero opera en America/Guayaquil (UTC-5, sin horario de verano) y
# ahí es donde vencen las declaraciones del SRI. Postgres, en cambio, arranca en
# UTC, así que `current_date` y cualquier `timestamptz::date` se resolvían con
# cinco horas de desfase: durante las últimas cinco horas de cada mes el panel
# daba por empezado el mes siguiente y las secciones del mes salían vacías,
# justo cuando se consultan para facturar.
#
# Se fija por conexión, además de en la propia base, para que valga también si
# alguien apunta la aplicación a otra base sin ese ajuste.
ZONA_BD = "America/Guayaquil"

_engine = None
_session_local: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _session_local
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            pool_size=5,
            connect_args={"options": f"-c timezone={ZONA_BD}"},
        )
        _session_local = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _session_local is not None
    return _session_local


def apply_rls_context(db: Session, ctx: RequestContext, is_internal: bool = False) -> None:
    """Fija los GUCs que leen las políticas RLS, locales a la transacción actual."""
    db.execute(
        text(
            "SELECT set_config('app.tenant_id', :tenant, true),"
            " set_config('app.user_id', :user, true),"
            " set_config('app.is_internal', :internal, true)"
        ),
        {
            "tenant": str(ctx.tenant_id) if ctx.tenant_id else "",
            "user": str(ctx.user_id) if ctx.user_id else "",
            "internal": "true" if is_internal else "false",
        },
    )


def get_db() -> Generator[Session, None, None]:
    """Dependencia FastAPI: una sesión (y una transacción) por petición.

    Los callables en db.info["post_commit"] se ejecutan DESPUÉS del commit:
    es la vía correcta para encolar tasks de Celery (si se encolara antes,
    el worker podría leer datos aún no confirmados)."""
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
        for hook in db.info.get("post_commit", []):
            hook()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def despues_del_commit(db: Session, hook) -> None:
    db.info.setdefault("post_commit", []).append(hook)
