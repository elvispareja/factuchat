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
    # Texto libre: el catálogo de provincias/cantones vive en el frontend.
    provincia: Mapped[str | None] = mapped_column(String(100))
    ciudad: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (UniqueConstraint("tenant_id", "tipo_identificacion", "identificacion"),)


class Categoria(UUIDPk, Timestamps, Base):
    """Categorías del catálogo del tenant, para agrupar productos y atributos."""

    __tablename__ = "categorias"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    nombre: Mapped[str] = mapped_column(String(150))
    descripcion: Mapped[str | None] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "nombre"),)


class Atributo(UUIDPk, Timestamps, Base):
    """Atributos configurables por categoría (Marca, Color, Talla...), cada uno
    con sus propios valores en AtributoValor. Pertenece a UNA categoría
    (CASCADE con ella)."""

    __tablename__ = "atributos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    categoria_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categorias.id", ondelete="CASCADE"), index=True
    )
    nombre: Mapped[str] = mapped_column(String(100))
    activo: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("categoria_id", "nombre"),)


class AtributoValor(UUIDPk, Timestamps, Base):
    """Valores posibles de un atributo (ej. Nike/Adidas para Marca, Rojo/Azul
    para Color). Pertenece a UN atributo (CASCADE con él)."""

    __tablename__ = "atributo_valores"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    atributo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("atributos.id", ondelete="CASCADE"), index=True
    )
    valor: Mapped[str] = mapped_column(String(150))
    activo: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (UniqueConstraint("atributo_id", "valor"),)


class ProductoAtributo(UUIDPk, Timestamps, Base):
    """Tabla puente: QUÉ VALORES tiene disponibles este producto. Un atributo
    puede repetirse con distinto valor (Talla=38, Talla=39): los que traen dos
    o más valores son los que generan las variantes."""

    __tablename__ = "producto_atributos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    producto_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("productos.id", ondelete="CASCADE"), index=True
    )
    atributo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("atributos.id", ondelete="CASCADE"), index=True
    )
    atributo_valor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("atributo_valores.id", ondelete="CASCADE"), index=True
    )

    __table_args__ = (UniqueConstraint("producto_id", "atributo_id", "atributo_valor_id"),)


class ProductoVariante(UUIDPk, Timestamps, Base):
    """Una combinación concreta a la venta (talla 38 roja), con su propio SKU y
    su propio stock. `precio_sin_iva` NULL hereda el del producto: cubre "la
    talla 45 cuesta más" sin obligar a rellenar precios uno por uno."""

    __tablename__ = "producto_variantes"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    producto_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("productos.id", ondelete="CASCADE"), index=True
    )
    codigo: Mapped[str] = mapped_column(String(25))  # el SKU que va al comprobante
    precio_sin_iva: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    stock: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("0"))
    activo: Mapped[bool] = mapped_column(default=True)

    valores: Mapped[list["VarianteAtributo"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (UniqueConstraint("tenant_id", "codigo"),)


class VarianteAtributo(UUIDPk, Timestamps, Base):
    """Los valores que definen una variante: una talla y un color, no dos."""

    __tablename__ = "variante_atributos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    variante_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("producto_variantes.id", ondelete="CASCADE"), index=True
    )
    atributo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("atributos.id", ondelete="CASCADE"), index=True
    )
    atributo_valor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("atributo_valores.id", ondelete="CASCADE"), index=True
    )

    __table_args__ = (UniqueConstraint("variante_id", "atributo_id"),)


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
    # Ruta en disco de la imagen, no la imagen: los binarios en Postgres hinchan
    # la base y complican los backups. Nunca sale hacia el navegador (delataría
    # la estructura interna del servidor); lo que se expone es `tiene_imagen`.
    imagen_path: Mapped[str | None] = mapped_column(String(500))
    activo: Mapped[bool] = mapped_column(default=True)
    categoria_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categorias.id", ondelete="SET NULL")
    )

    @property
    def tiene_imagen(self) -> bool:
        """Lo único que el frontend necesita saber: si pedir la miniatura."""
        return bool(self.imagen_path)

    atributos: Mapped[list["ProductoAtributo"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )
    variantes: Mapped[list["ProductoVariante"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )

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
    # Nota de crédito → la factura que anula o corrige, cuando esa factura está
    # en el sistema (si se tecleó a mano, queda en None y solo hay el número del
    # payload). La FK NO respeta RLS: el tenant se valida en el servicio.
    comprobante_modificado_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comprobantes.id", ondelete="CASCADE"), index=True
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
