"""Esquemas de artículos y servicios (fase 3.1)."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.db.models.enums import TipoProducto
from app.sri.xml_builder import TARIFAS_IVA


class ProductoIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=25)
    nombre: str = Field(min_length=1, max_length=300)
    descripcion: str | None = Field(default=None, max_length=2000)
    tipo: TipoProducto
    # Precio SIN impuesto: la tienda y la factura calculan el IVA al emitir,
    # tal como explica la maqueta ("así nunca hay dobles cobros ni descuadres").
    precio_sin_iva: Decimal = Field(ge=0, le=Decimal("999999999"))
    codigo_iva: str = Field(default="4")
    maneja_inventario: bool = False
    stock: Decimal = Field(default=Decimal("0"), ge=0)
    stock_minimo: Decimal | None = Field(default=None, ge=0)
    mostrar_en_tienda: bool = False

    @field_validator("codigo_iva")
    @classmethod
    def iva_valido(cls, v: str) -> str:
        if v not in TARIFAS_IVA:
            raise ValueError(f"Código de IVA inválido: {v}")
        return v

    @model_validator(mode="after")
    def servicio_sin_inventario(self) -> "ProductoIn":
        if self.tipo == TipoProducto.SERVICIO and self.maneja_inventario:
            raise ValueError("Un servicio no maneja inventario")
        return self


class ProductoOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    codigo: str
    nombre: str
    descripcion: str | None
    tipo: TipoProducto
    precio_sin_iva: Decimal
    codigo_iva: str
    porcentaje_iva: Decimal
    maneja_inventario: bool
    stock: Decimal
    stock_minimo: Decimal | None
    mostrar_en_tienda: bool
    activo: bool
