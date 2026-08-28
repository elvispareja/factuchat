"""Tienda interna y aceptación de términos (fase 6).

La tienda es una VITRINA INTERNA: el equipo del negocio arma el pedido, cobra y
emite. No hay tienda pública con carrito, así que un pedido siempre lo crea
alguien de la casa, nunca un visitante anónimo.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.db.models.enums import EstadoPedido, MetodoPago


def _enum(e: type, name: str) -> Enum:
    return Enum(e, name=name, native_enum=True, validate_strings=True)


class Pedido(UUIDPk, Timestamps, Base):
    """Una venta de la vitrina interna, desde que se arma hasta que se cobra."""

    __tablename__ = "pedidos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    numero: Mapped[int] = mapped_column(Integer)  # correlativo por tenant
    estado: Mapped[EstadoPedido] = mapped_column(
        _enum(EstadoPedido, "estado_pedido"), default=EstadoPedido.POR_REVISAR, index=True
    )
    metodo_pago: Mapped[MetodoPago] = mapped_column(_enum(MetodoPago, "metodo_pago"))

    # Comprador: si no da datos, sale a consumidor final (tope $200)
    cliente_final_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clientes_finales.id", ondelete="SET NULL")
    )
    comprador_nombre: Mapped[str | None] = mapped_column(String(300))
    comprador_telefono: Mapped[str | None] = mapped_column(String(20))

    # Los ítems se congelan al crear el pedido: si el precio del producto cambia
    # después, este pedido conserva lo que se acordó.
    items: Mapped[list] = mapped_column(JSONB, default=list)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    iva: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))

    # Transferencia: la foto del comprobante que sube el comprador
    comprobante_pago_url: Mapped[str | None] = mapped_column(String(500))
    referencia_pago: Mapped[str | None] = mapped_column(String(200))

    comprobante_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comprobantes.id", ondelete="SET NULL")
    )
    nota: Mapped[str | None] = mapped_column(Text)
    confirmado_at: Mapped[datetime | None]
    entregado_at: Mapped[datetime | None]


class AceptacionTerminos(UUIDPk, Base):
    """Constancia de que alguien aceptó los términos y el tratamiento de datos.

    La LOPDP exige poder demostrar QUÉ se aceptó y CUÁNDO: por eso se guarda la
    VERSIÓN del documento y su hash, no solo un booleano. Un "sí" sin versión no
    prueba nada si el texto cambió después.
    """

    __tablename__ = "aceptaciones_terminos"
    # Sin RETURNING al insertar: el checkout PÚBLICO puede escribir la
    # constancia pero no leerla, y RETURNING exigiría pasar la política de
    # SELECT (que solo permite al personal interno y al propio tenant).
    __mapper_args__ = {"eager_defaults": False}

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), index=True
    )
    # Quién aceptó: en el checkout público todavía no hay tenant ni usuario
    email: Mapped[str] = mapped_column(String(320), index=True)
    nombre: Mapped[str | None] = mapped_column(String(300))
    identificacion: Mapped[str | None] = mapped_column(String(20))

    documento: Mapped[str] = mapped_column(String(40))  # TERMINOS | DATOS_PERSONALES
    version: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str] = mapped_column(String(64))
    aceptado: Mapped[bool] = mapped_column(default=True)

    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    origen: Mapped[str] = mapped_column(String(40), default="CHECKOUT")
    aceptado_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class SolicitudContacto(UUIDPk, Base):
    """Pedido de contacto desde la landing: agenda y datos del interesado."""

    __tablename__ = "solicitudes_contacto"
    # Igual que arriba: quien envía el formulario no puede leer la tabla.
    __mapper_args__ = {"eager_defaults": False}

    nombre: Mapped[str] = mapped_column(String(300))
    email: Mapped[str] = mapped_column(String(320))
    telefono: Mapped[str | None] = mapped_column(String(20))
    identificacion: Mapped[str | None] = mapped_column(String(20))
    ciudad: Mapped[str | None] = mapped_column(String(120))
    provincia: Mapped[str | None] = mapped_column(String(120))
    pais: Mapped[str] = mapped_column(String(80), default="Ecuador")

    plan: Mapped[str | None] = mapped_column(String(50))
    metodo_pago: Mapped[str | None] = mapped_column(String(30))
    agenda_dia: Mapped[date | None]
    agenda_hora: Mapped[str | None] = mapped_column(String(20))
    mensaje: Mapped[str | None] = mapped_column(Text)
    codigo_promo: Mapped[str | None] = mapped_column(String(50))

    # Comprobante de transferencia, si eligió esa vía
    comprobante_url: Mapped[str | None] = mapped_column(String(500))

    atendida: Mapped[bool] = mapped_column(default=False)
    creada_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    # Cuándo se avisó al equipo. Nulo = el aviso todavía no salió; el task lo
    # mira para no mandar un segundo correo cuando se reintenta.
    avisado_at: Mapped[datetime | None]
