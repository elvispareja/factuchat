"""Modelos del panel interno (fase 4)."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPk


class Impersonacion(Base, UUIDPk):
    """Sesión de impersonación: quién entró como qué inquilino, por qué y hasta
    cuándo. Es una SESIÓN, no un evento suelto: sin el cierre no se sabe cuánto
    duró el acceso a datos ajenos (fase 4.1)."""

    __tablename__ = "impersonaciones"

    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    motivo: Mapped[str] = mapped_column(String(300))
    iniciada_at: Mapped[datetime] = mapped_column(server_default=func.now())
    terminada_at: Mapped[datetime | None]
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
