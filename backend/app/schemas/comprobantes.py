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
