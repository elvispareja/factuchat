"""Tablas de negocio del tenant: clientes finales, productos y comprobantes (fase 1.2)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.db.models.enums import (
    AmbienteSRI,
    EstadoComprobante,
    TipoComprobante,
    TipoIdentificacion,
    TipoProducto,
)


def _enum(e: type, name: str) -> Enum:
    return Enum(e, name=name, native_enum=True, validate_strings=True)


class ClienteFinal(UUIDPk, Timestamps, Base):
    """Clientes del tenant (a quienes se les factura)."""

    __tablename__ = "clientes_finales"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    tipo_identificacion: Mapped[TipoIdentificacion] = mapped_column(
        _enum(TipoIdentificacion, "tipo_identificacion")
    )
    identificacion: Mapped[str] = mapped_column(String(20))
    razon_social: Mapped[str] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    telefono: Mapped[str | None] = mapped_column(String(20))
    direccion: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("tenant_id", "tipo_identificacion", "identificacion"),)


class Producto(UUIDPk, Timestamps, Base):
    """Artículos y servicios, con inventario según plan (fase 3)."""

    __tablename__ = "productos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    codigo: Mapped[str] = mapped_column(String(50))
    nombre: Mapped[str] = mapped_column(String(300))
    descripcion: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[TipoProducto] = mapped_column(_enum(TipoProducto, "tipo_producto"))
    precio_sin_iva: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    codigo_iva: Mapped[str] = mapped_column(String(2), default="4")  # tabla 17 SRI (4 = 15%)
    porcentaje_iva: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("15.00"))
    maneja_inventario: Mapped[bool] = mapped_column(default=False)
    stock: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    stock_minimo: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    mostrar_en_tienda: Mapped[bool] = mapped_column(default=False)
    imagen_url: Mapped[str | None] = mapped_column(String(500))
    activo: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "codigo"),)


class Comprobante(UUIDPk, Timestamps, Base):
    """Comprobantes electrónicos SRI: los 6 tipos, con máquina de estados
    PENDIENTE→FIRMADO→ENVIADO_SRI→AUTORIZADO/RECHAZADO/DEVUELTO."""

    __tablename__ = "comprobantes"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    tipo: Mapped[TipoComprobante] = mapped_column(_enum(TipoComprobante, "tipo_comprobante"))
    estado: Mapped[EstadoComprobante] = mapped_column(
        _enum(EstadoComprobante, "estado_comprobante"),
        default=EstadoComprobante.PENDIENTE,
        index=True,
    )
    ambiente: Mapped[AmbienteSRI] = mapped_column(_enum(AmbienteSRI, "ambiente_sri"))

    # Se asignan al EMITIR (confirmación explícita), no al crear el borrador,
    # para no dejar huecos de secuencial por borradores abandonados.
    establecimiento: Mapped[str | None] = mapped_column(String(3))
    punto_emision: Mapped[str | None] = mapped_column(String(3))
    secuencial: Mapped[int | None] = mapped_column(Integer)
    clave_acceso: Mapped[str | None] = mapped_column(String(49), unique=True)

    cliente_final_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clientes_finales.id", ondelete="SET NULL")
    )
    fecha_emision: Mapped[date]
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    iva: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))

    # Detalle (items, pagos, info adicional) como JSON; el XML se genera en fase 2
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    origen: Mapped[str] = mapped_column(String(20), default="PANEL")  # PANEL|WHATSAPP|TIENDA

    # Integridad (OWASP A08): el XML autorizado es inmutable, con hash SHA-256
    xml_path: Mapped[str | None] = mapped_column(String(500))
    ride_path: Mapped[str | None] = mapped_column(String(500))
    sha256_xml: Mapped[str | None] = mapped_column(String(64))
    sri_mensajes: Mapped[dict | None] = mapped_column(JSONB)  # motivo legible de rechazo
    numero_autorizacion: Mapped[str | None] = mapped_column(String(49))
    autorizado_at: Mapped[datetime | None]
    intentos: Mapped[int] = mapped_column(Integer, default=0)

    # Marcas de reanudación (A10): se escriben ANTES del efecto externo para que
    # un reintento sepa qué ya ocurrió y no lo repita ni lo dé por perdido.
    enviado_recepcion_at: Mapped[datetime | None]
    correo_enviado_at: Mapped[datetime | None]

    cliente_final: Mapped[ClienteFinal | None] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "tipo", "establecimiento", "punto_emision", "secuencial"),
    )
