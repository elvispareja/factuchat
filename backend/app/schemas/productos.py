"""Esquemas de artículos y servicios (fase 3.1)."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.db.models.enums import TipoProducto
from app.sri.xml_builder import TARIFAS_IVA


class ProductoAtributoIn(BaseModel):
    atributo_id: uuid.UUID
    atributo_valor_id: uuid.UUID


class ProductoAtributoOut(BaseModel):
    model_config = {"from_attributes": True}

    atributo_id: uuid.UUID
    atributo_valor_id: uuid.UUID


class VarianteIn(BaseModel):
    """Una combinación concreta a la venta: talla 38 roja, con su SKU y su stock."""

    # Identidad de la fila que ya existe. Sin esto habría que emparejar por
    # código, y renombrar un SKU dejaría de ser un cambio de nombre: borraría la
    # variante con su stock y crearía otra, dejando además a los pedidos
    # pendientes apuntando a una fila que ya no está.
    id: uuid.UUID | None = None
    codigo: str = Field(min_length=1, max_length=25)
    # NULL = hereda el precio del producto: así la talla 45 puede costar más sin
    # obligar a rellenar precios uno por uno.
    precio_sin_iva: Decimal | None = Field(default=None, ge=0)
    stock: Decimal = Field(default=Decimal("0"), ge=0)
    valores: list[ProductoAtributoIn] = Field(min_length=1)


class VarianteOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    codigo: str
    precio_sin_iva: Decimal | None
    stock: Decimal
    activo: bool
    valores: list[ProductoAtributoOut]


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
    categoria_id: uuid.UUID | None = None
    atributos: list[ProductoAtributoIn] = Field(default_factory=list)
    variantes: list[VarianteIn] = Field(default_factory=list)

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

    @model_validator(mode="after")
    def servicio_sin_categoria(self) -> "ProductoIn":
        # Solo los productos tangibles (BIEN) se organizan por categoría y
        # atributos derivados (Marca, Color, Talla...); un servicio no, y por lo
        # mismo tampoco tiene variantes (una consultoría no viene en talla 38).
        if self.tipo == TipoProducto.SERVICIO and (
            self.categoria_id is not None or self.atributos or self.variantes
        ):
            raise ValueError("Un servicio no tiene categoría, atributos ni variantes")
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
    # Booleano derivado, NO la ruta: el frontend pide el archivo por
    # GET /productos/{id}/imagen.
    tiene_imagen: bool
    activo: bool
    categoria_id: uuid.UUID | None
    atributos: list[ProductoAtributoOut]
    variantes: list[VarianteOut]
