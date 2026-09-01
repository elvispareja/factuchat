"""Esquemas de emisión de facturas. Validación estricta en la frontera (A05)."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.sri.xml_builder import FORMAS_PAGO, TARIFAS_IVA


class ItemFacturaIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=25)
    descripcion: str = Field(min_length=1, max_length=300)
    cantidad: Decimal = Field(gt=0, le=Decimal("999999"))
    precio_unitario: Decimal = Field(ge=0, le=Decimal("999999999"))
    descuento: Decimal = Field(default=Decimal("0"), ge=0)
    codigo_iva: str = Field(default="4")  # 15% vigente

    @field_validator("codigo_iva")
    @classmethod
    def iva_valido(cls, v: str) -> str:
        if v not in TARIFAS_IVA:
            raise ValueError(f"Código de IVA inválido: {v}")
        return v


class FacturaIn(BaseModel):
    cliente_final_id: uuid.UUID | None = None  # None → consumidor final (hasta $200)
    items: list[ItemFacturaIn] = Field(min_length=1, max_length=200)
    forma_pago: str = Field(default="01")
    # Venta a crédito: el SRI no tiene «código de crédito» en la tabla 24, lo
    # expresa como <plazo>/<unidadTiempo> DENTRO del pago (ficha técnica 2.31).
    plazo_dias: int | None = Field(default=None, ge=1, le=3650)
    info_adicional: dict[str, str] | None = None

    @field_validator("forma_pago")
    @classmethod
    def forma_pago_valida(cls, v: str) -> str:
        if v not in FORMAS_PAGO:
            raise ValueError(f"Forma de pago inválida: {v}")
        return v

    @field_validator("info_adicional")
    @classmethod
    def info_acotada(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is not None and len(v) > 15:
            raise ValueError("Máximo 15 campos adicionales")
        return v


class EmitirIn(BaseModel):
    establecimiento: str = Field(default="001", pattern=r"^\d{3}$")
    punto_emision: str = Field(default="001", pattern=r"^\d{3}$")


class ComprobanteOut(BaseModel):
    id: uuid.UUID
    tipo: str
    estado: str
    ambiente: str
    numero: str | None  # 001-001-000000123
    clave_acceso: str | None
    numero_autorizacion: str | None
    fecha_emision: str
    subtotal: str
    iva: str
    total: str
    mensajes: list[str]  # motivos legibles (rechazo/devolución)
    intentos: int
    # Columnas CLIENTE y DETALLE del historial. Salen del snapshot del payload
    # (lo que se le mandó al SRI), no de un JOIN: ver _a_out en las rutas.
    cliente: str | None  # razón social; None = consumidor final
    cliente_identificacion: str | None
    cliente_tipo_id: str | None  # RUC | CEDULA | PASAPORTE | ID_EXTERIOR
    detalle: str | None  # «Laptop 14" y 2 más»


class SiguienteNumeroOut(BaseModel):
    """Vista PREVIA del número: no reserva nada (ver emision.siguiente_numero)."""

    numero: str  # 001-001-000001235
    establecimiento: str
    punto_emision: str
    secuencial: int


class OpcionPagoOut(BaseModel):
    codigo: str  # tabla 24 del SRI
    etiqueta: str
    plazo_dias: int | None


# Las tres formas de pago del panel, todas al contado. El soporte de plazo sigue
# en pie (FacturaIn.plazo_dias y el <plazo>/<unidadTiempo> del XML), solo que de
# momento ninguna opción lo usa: cuando haga falta ofrecer venta a crédito, se
# añade aquí una opción con plazo_dias y funciona sin tocar nada más.
OPCIONES_PAGO = [
    OpcionPagoOut(codigo="01", etiqueta="Efectivo", plazo_dias=None),
    OpcionPagoOut(codigo="20", etiqueta="Transferencia", plazo_dias=None),
    OpcionPagoOut(codigo="19", etiqueta="Tarjeta", plazo_dias=None),
]
