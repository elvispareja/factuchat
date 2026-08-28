"""Tablas núcleo: tenants, usuarios, sesiones, planes, suscripciones,
establecimientos y secuenciales (fase 1.2)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.db.models.enums import AmbienteSRI, EstadoSuscripcion, EstadoTenant, Rol


def _enum(e: type, name: str) -> Enum:
    return Enum(e, name=name, native_enum=True, validate_strings=True)


class Tenant(UUIDPk, Timestamps, Base):
    __tablename__ = "tenants"

    ruc: Mapped[str] = mapped_column(String(13), unique=True)
    razon_social: Mapped[str] = mapped_column(String(300))
    nombre_comercial: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str] = mapped_column(String(320))
    telefono: Mapped[str | None] = mapped_column(String(20))
    direccion_matriz: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[EstadoTenant] = mapped_column(
        _enum(EstadoTenant, "estado_tenant"), default=EstadoTenant.ACTIVO
    )
    ambiente_sri: Mapped[AmbienteSRI] = mapped_column(
        _enum(AmbienteSRI, "ambiente_sri"), default=AmbienteSRI.PRUEBAS
    )
    obligado_contabilidad: Mapped[bool] = mapped_column(default=False)
    # Canal que trajo el alta (Campaña Meta, Referido, Orgánico, TikTok). Lo
    # elige quien da de alta y Marketing agrupa por él; texto libre y no enum
    # porque los canales cambian a menudo.
    origen_alta: Mapped[str] = mapped_column(String(40), default="Orgánico")
    # Última vez que se le recordó configurar el reenvío del SRI (fase 7). Se
    # limpia en cuanto llega algo al buzón: el reloj vuelve a empezar.
    buzon_alertado_at: Mapped[datetime | None]


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    # NULL = personal interno de Factuchat (SUPERADMIN / SOPORTE / LECTURA)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True)
    nombre: Mapped[str] = mapped_column(String(200))
    rol: Mapped[Rol] = mapped_column(_enum(Rol, "rol_usuario"))
    is_active: Mapped[bool] = mapped_column(default=True)

    # 2FA TOTP — obligatorio para SUPERADMIN (fase 1.3). Secreto cifrado AES-256-GCM.
    totp_enabled: Mapped[bool] = mapped_column(default=False)
    totp_secret_enc: Mapped[str | None] = mapped_column(String(500))

    # Bloqueo progresivo de cuenta
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    lockout_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    password_changed_at: Mapped[datetime | None]

    tenant: Mapped[Tenant | None] = relationship()


class UserSession(UUIDPk, Base):
    """Sesiones de refresh con rotación (fase 1.3). Solo se guarda el hash del token."""

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]
    rotated_to: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))


class Plan(UUIDPk, Timestamps, Base):
    """Planes comerciales con vigencia: un cambio de precio crea una versión nueva
    con vigente_desde futuro; las suscripciones actuales no se tocan (fase 4)."""

    __tablename__ = "planes"

    codigo: Mapped[str] = mapped_column(String(50), index=True)  # INICIAL, EMPRENDEDOR, ...
    nombre: Mapped[str] = mapped_column(String(120))
    precio_mensual: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    limites: Mapped[dict] = mapped_column(JSONB, default=dict)  # cupos, inventario, tienda...
    vigente_desde: Mapped[date]
    vigente_hasta: Mapped[date | None] = mapped_column(Date)
    activo: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("codigo", "vigente_desde"),)


class Suscripcion(UUIDPk, Timestamps, Base):
    __tablename__ = "suscripciones"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("planes.id"))
    estado: Mapped[EstadoSuscripcion] = mapped_column(
        _enum(EstadoSuscripcion, "estado_suscripcion"), default=EstadoSuscripcion.ACTIVA
    )
    # Precio congelado al contratar: cambios de plan con vigencia futura no lo alteran
    precio: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    inicia: Mapped[date]
    termina: Mapped[date | None] = mapped_column(Date)
    proximo_cobro: Mapped[date | None] = mapped_column(Date)

    plan: Mapped[Plan] = relationship()


class Establecimiento(UUIDPk, Timestamps, Base):
    __tablename__ = "establecimientos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    codigo: Mapped[str] = mapped_column(String(3))  # 001, 002...
    nombre: Mapped[str | None] = mapped_column(String(200))
    direccion: Mapped[str | None] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "codigo"),)


class Secuencial(UUIDPk, Timestamps, Base):
    """Secuencial por establecimiento + punto de emisión + tipo de comprobante."""

    __tablename__ = "secuenciales"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    establecimiento_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("establecimientos.id", ondelete="CASCADE")
    )
    punto_emision: Mapped[str] = mapped_column(String(3))  # 001, 002...
    tipo_comprobante: Mapped[str] = mapped_column(String(30))  # valores de TipoComprobante
    secuencial_actual: Mapped[int] = mapped_column(BigInteger, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_id", "establecimiento_id", "punto_emision", "tipo_comprobante"),
    )
