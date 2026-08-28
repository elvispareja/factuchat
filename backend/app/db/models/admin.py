"""Tablas de cobros, promociones, costos y operación interna (fase 1.2):
pagos, recargas, promo_codes, promo_uses, cost_rates, audit_log,
notas_internas, whatsapp_msgs, buzon_correos."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.db.models.enums import (
    CategoriaMsg,
    DireccionMsg,
    EstadoCorreoBuzon,
    EstadoPago,
    MetodoPago,
    TipoPromo,
)


def _enum(e: type, name: str) -> Enum:
    return Enum(e, name=name, native_enum=True, validate_strings=True)


class Pago(UUIDPk, Timestamps, Base):
    __tablename__ = "pagos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    suscripcion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suscripciones.id"))
    concepto: Mapped[str] = mapped_column(String(300))
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    metodo: Mapped[MetodoPago] = mapped_column(_enum(MetodoPago, "metodo_pago"))
    estado: Mapped[EstadoPago] = mapped_column(
        _enum(EstadoPago, "estado_pago"), default=EstadoPago.PENDIENTE
    )
    referencia: Mapped[str | None] = mapped_column(String(200))
    comprobante_url: Mapped[str | None] = mapped_column(String(500))  # foto de transferencia
    vence_at: Mapped[date | None]
    pagado_at: Mapped[datetime | None]


class Recarga(UUIDPk, Timestamps, Base):
    """Compras de cupo extra (comprobantes, WhatsApp) fuera del plan."""

    __tablename__ = "recargas"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    tipo: Mapped[str] = mapped_column(String(30))  # COMPROBANTES | WHATSAPP
    cantidad: Mapped[int] = mapped_column(Integer)
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    pago_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pagos.id"))


class PromoCode(UUIDPk, Timestamps, Base):
    __tablename__ = "promo_codes"

    codigo: Mapped[str] = mapped_column(String(50), unique=True)  # p. ej. LANZA99
    descripcion: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[TipoPromo] = mapped_column(_enum(TipoPromo, "tipo_promo"))
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # PRECIO_FIJO 0.99 → primer mes $0.99
    max_usos: Mapped[int | None] = mapped_column(Integer)
    usos: Mapped[int] = mapped_column(Integer, default=0)
    # Planes a los que aplica (null = todos) y cuántos meses dura el beneficio
    planes: Mapped[list | None] = mapped_column(JSONB)
    meses: Mapped[int] = mapped_column(Integer, default=1)
    vigente_desde: Mapped[date]
    vigente_hasta: Mapped[date | None]
    activo: Mapped[bool] = mapped_column(default=True)


class PromoUse(UUIDPk, Base):
    __tablename__ = "promo_uses"

    promo_code_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    monto_descuento: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Columna "Retenido" de la maqueta de marketing: ingreso no percibido por la
    # promo. Se CONGELA al aplicarse — si el precio del plan cambia después, este
    # número no se recalcula, porque describe un hecho pasado.
    retenido: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    precio_lista: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    precio_cobrado: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    meses_aplicados: Mapped[int | None] = mapped_column(Integer)
    usado_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CostRate(UUIDPk, Timestamps, Base):
    """Tarifas de costo por proveedor con vigencia (p. ej. alza de Meta oct-2026)."""

    __tablename__ = "cost_rates"

    proveedor: Mapped[str] = mapped_column(String(50))  # META_WHATSAPP | IA | SMTP | PAYPHONE
    concepto: Mapped[str] = mapped_column(String(120))
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    unidad: Mapped[str] = mapped_column(String(50))  # conversacion, mensaje, token, correo...
    moneda: Mapped[str] = mapped_column(String(3), default="USD")
    vigente_desde: Mapped[date]
    vigente_hasta: Mapped[date | None]
    notas: Mapped[str | None] = mapped_column(Text)


class AuditLog(UUIDPk, Base):
    """Bitácora inmutable (fase 1.5, OWASP A09): sin UPDATE/DELETE por permisos de BD."""

    __tablename__ = "audit_log"
    # Sin RETURNING al insertar: el rol de la app puede INSERTAR pero no LEER
    # la bitácora (y RETURNING exigiría pasar la política de SELECT).
    __mapper_args__ = {"eager_defaults": False}

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    actor_rol: Mapped[str | None] = mapped_column(String(20))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    accion: Mapped[str] = mapped_column(String(40))  # INSERT|UPDATE|DELETE|LOGIN_OK|SA_SELECT...
    tabla: Mapped[str | None] = mapped_column(String(80))
    registro_id: Mapped[str | None] = mapped_column(String(64))
    antes: Mapped[dict | None] = mapped_column(JSONB)
    despues: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    request_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class NotaInterna(UUIDPk, Timestamps, Base):
    """Notas del equipo de Factuchat sobre un cliente (solo panel interno)."""

    __tablename__ = "notas_internas"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    autor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    texto: Mapped[str] = mapped_column(Text)


class WhatsappMsg(UUIDPk, Base):
    __tablename__ = "whatsapp_msgs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    wa_phone: Mapped[str] = mapped_column(String(20))
    direccion: Mapped[DireccionMsg] = mapped_column(_enum(DireccionMsg, "direccion_msg"))
    categoria: Mapped[CategoriaMsg | None] = mapped_column(_enum(CategoriaMsg, "categoria_msg"))
    tipo: Mapped[str] = mapped_column(String(30), default="TEXTO")  # TEXTO|PLANTILLA|INTERACTIVO
    wa_message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    contenido: Mapped[dict | None] = mapped_column(JSONB)
    costo: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class BuzonCorreo(UUIDPk, Base):
    """Correos del buzón SRI por tenant (fase 7, tras feature flag BUZON_ACTIVO).

    Aquí NO vive el contenido del correo, solo sus señas. El mensaje completo se
    guarda cifrado en `payload_path` y se descifra bajo demanda: una columna con
    el XML en claro acabaría replicada en `audit_log`, que es inmutable y lo lee
    el personal interno, anulando el cifrado en reposo.
    """

    __tablename__ = "buzon_correos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    # Deduplicación: el par (tenant, message_id) es único. Global NO puede ser —
    # un remitente hostil que reutilice un Message-ID dejaría marcado DUPLICADO
    # el correo legítimo de OTRO inquilino, cuya retención nunca se sumaría.
    message_id: Mapped[str] = mapped_column(String(300))
    remitente: Mapped[str | None] = mapped_column(String(320))
    asunto: Mapped[str | None] = mapped_column(String(500))
    xml_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    tipo_detectado: Mapped[str | None] = mapped_column(String(30))
    # Clave de acceso del comprobante: la deduplicación de verdad, porque el
    # mismo documento puede llegar en dos correos distintos (reenvíos).
    clave_acceso: Mapped[str | None] = mapped_column(String(49))
    estado: Mapped[EstadoCorreoBuzon] = mapped_column(
        _enum(EstadoCorreoBuzon, "estado_correo_buzon"), default=EstadoCorreoBuzon.RECIBIDO
    )
    # Lo que el panel interno muestra en las filas con ERROR
    motivo_error: Mapped[str | None] = mapped_column(String(500))
    payload_path: Mapped[str | None] = mapped_column(String(500))  # cifrado en reposo (fase 7)
    recibido_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    procesado_at: Mapped[datetime | None]


class RetencionRecibida(UUIDPk, Base):
    """Comprobante de retención que le hicieron al inquilino (fase 7).

    El inquilino nunca EMITE retenciones, solo las recibe: por eso esto no es un
    Comprobante sino su propia tabla. Cada fila es crédito tributario, y por eso
    la retención de renta y la de IVA viven en columnas SEPARADAS: son impuestos
    distintos y solo la de IVA baja el IVA a pagar. Sumarlas daría un número
    fiscalmente falso.
    """

    __tablename__ = "retenciones_recibidas"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    buzon_correo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("buzon_correos.id", ondelete="SET NULL")
    )
    # BUZON | MANUAL | WHATSAPP — de dónde entró
    origen: Mapped[str] = mapped_column(String(20), default="BUZON")

    clave_acceso: Mapped[str | None] = mapped_column(String(49))
    numero: Mapped[str] = mapped_column(String(30))  # 001-001-000001234
    ruc_agente: Mapped[str | None] = mapped_column(String(13))
    razon_social_agente: Mapped[str] = mapped_column(String(300))
    fecha_emision: Mapped[date | None] = mapped_column(index=True)
    periodo_fiscal: Mapped[str | None] = mapped_column(String(7))  # mm/aaaa
    concepto: Mapped[str | None] = mapped_column(String(300))

    base_imponible: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_renta: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_iva: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    detalle: Mapped[dict | None] = mapped_column(JSONB)

    # Un XML lo escribe cualquiera, y el sobre <autorizacion> también: decir
    # «AUTORIZADO» dentro de un fichero no prueba nada. Solo cuenta como crédito
    # lo que el SRI confirma como autorizado cuando se le pregunta por su clave
    # de acceso. Sin esto, alguien que sepa el RUC de un contribuyente podría
    # bajarle el impuesto que declara mandándole un comprobante inventado.
    verificada: Mapped[bool] = mapped_column(default=False, index=True)
    verificada_at: Mapped[datetime | None]
    verificacion: Mapped[dict | None] = mapped_column(JSONB)

    # Custodia de siete años: el XML va cifrado, el RIDE en PDF si llegó
    xml_path: Mapped[str | None] = mapped_column(String(500))
    pdf_path: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class Parametro(Base):
    """Interruptor del sistema, cambiable en caliente por el superadmin.

    La clave es la primaria: son pocos, con nombre propio, y no tiene sentido
    darles un UUID. Lo que se guarda aquí pisa al valor del entorno.
    """

    __tablename__ = "parametros"

    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str] = mapped_column(String(300))
    actualizado_por: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    actualizado_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AnalisisIA(UUIDPk, Base):
    """Registro de los análisis de documentos con IA (regla 7.2).

    Existe para que la promesa de la landing —«Los XML de tu buzón SRI no
    consumen tus análisis con IA; las fotos de documentos sí»— sea comprobable y
    no un accidente. Cada análisis deja fila con su ORIGEN y con si consumió o
    no cupo; los del buzón se registran con `consume=False`.
    """

    __tablename__ = "analisis_ia"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    # BUZON | FOTO | PDF
    origen: Mapped[str] = mapped_column(String(20))
    consume: Mapped[bool] = mapped_column(default=True)
    referencia: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class Invitacion(UUIDPk, Base):
    """Enlace de un solo uso para que un cliente estrene su contraseña.

    Solo se guarda el sha256 del token: el enlace utilizable existe únicamente
    dentro del correo que se le envió.
    """

    __tablename__ = "invitaciones"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expira_at: Mapped[datetime]
    usada_at: Mapped[datetime | None]
    creada_por: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
