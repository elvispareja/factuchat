"""Esquemas de la tienda interna y el checkout público (fase 6)."""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.db.models.enums import MetodoPago


class LineaPedidoIn(BaseModel):
    producto_id: uuid.UUID
    # Qué combinación exacta se vende (talla 38 roja). Los productos sin
    # variantes —la mayoría— siguen mandando solo producto_id.
    variante_id: uuid.UUID | None = None
    cantidad: Decimal = Field(gt=0, le=Decimal("99999"))
    # El PRECIO no se acepta desde fuera: se lee del catálogo. Aceptarlo dejaría
    # cobrar lo que quisiera quien llame a la API.


class PedidoIn(BaseModel):
    items: list[LineaPedidoIn] = Field(min_length=1, max_length=100)
    metodo_pago: MetodoPago
    cliente_final_id: uuid.UUID | None = None
    comprador_nombre: str | None = Field(default=None, max_length=300)
    comprador_telefono: str | None = Field(default=None, max_length=20)
    nota: str | None = Field(default=None, max_length=1000)


class AceptacionIn(BaseModel):
    """La casilla del checkout. Nace desmarcada y así debe llegar si el usuario
    no la marcó: la LOPDP exige un acto afirmativo, nunca un valor por defecto."""

    condiciones: bool = False
    datos: bool = False


class CheckoutIn(BaseModel):
    nombres: str = Field(min_length=2, max_length=150)
    apellidos: str = Field(min_length=2, max_length=150)
    identificacion: str = Field(min_length=5, max_length=20)
    telefono: str = Field(min_length=6, max_length=20)
    email: EmailStr
    pais: str = Field(default="Ecuador", max_length=80)
    provincia: str | None = Field(default=None, max_length=120)
    ciudad: str | None = Field(default=None, max_length=120)

    plan: str = Field(min_length=2, max_length=50)
    metodo_pago: MetodoPago
    codigo_promo: str | None = Field(default=None, max_length=50)

    # Vía "solicitar información": el usuario agenda cuándo lo llaman
    agenda_dia: date | None = None
    agenda_hora: str | None = Field(default=None, max_length=20)

    mensaje: str | None = Field(default=None, max_length=1000)
    acepta: AceptacionIn

    @field_validator("identificacion")
    @classmethod
    def solo_alfanumerico(cls, v: str) -> str:
        limpio = v.strip()
        if not limpio.replace("-", "").replace(".", "").isalnum():
            raise ValueError("Identificación con caracteres inválidos")
        return limpio


class ContactoIn(BaseModel):
    """Formulario de contacto de la landing: abre WhatsApp con el mensaje."""

    nombre: str = Field(min_length=2, max_length=300)
    email: EmailStr
    telefono: str | None = Field(default=None, max_length=20)
    asunto: str = Field(default="Quiero contratar un plan", max_length=200)
    mensaje: str = Field(min_length=1, max_length=2000)
