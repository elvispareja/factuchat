"""Esquemas del panel interno (fase 4)."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.db.models.enums import EstadoTenant, TipoPromo


class ImpersonarIn(BaseModel):
    # El motivo queda en la auditoría: sin él, el rastro no dice nada
    motivo: str = Field(min_length=10, max_length=300)


class EstadoTenantIn(BaseModel):
    estado: EstadoTenant
    motivo: str = Field(min_length=5, max_length=300)


class PromoCodeIn(BaseModel):
    codigo: str = Field(min_length=3, max_length=50, pattern=r"^[A-Z0-9_-]+$")
    descripcion: str | None = Field(default=None, max_length=500)
    tipo: TipoPromo
    valor: Decimal = Field(ge=0, le=Decimal("9999"))
    meses: int = Field(default=1, ge=1, le=24)
    planes: list[str] | None = None
    max_usos: int | None = Field(default=None, ge=1, le=100000)
    vigente_desde: date
    vigente_hasta: date | None = None

    @field_validator("codigo")
    @classmethod
    def mayusculas(cls, v: str) -> str:
        return v.strip().upper()


class CambioPrecioIn(BaseModel):
    precio: Decimal = Field(ge=0, le=Decimal("99999"))
    # Obligatoriamente futura: el servicio lo revalida contra la fecha del servidor
    vigente_desde: date
    limites: dict | None = None


class AvisosIn(BaseModel):
    """Los textos que se guardan, por clave de aviso. Se admite guardar solo
    algunos: la pantalla manda únicamente los que cambiaron."""

    textos: dict[str, str] = Field(min_length=1)


class TarifaIn(BaseModel):
    proveedor: str = Field(min_length=2, max_length=50)
    concepto: str = Field(min_length=2, max_length=120)
    costo_unitario: Decimal = Field(ge=0)
    unidad: str = Field(min_length=1, max_length=50)
    vigente_desde: date
    notas: str | None = Field(default=None, max_length=1000)


class AltaClienteIn(BaseModel):
    ruc: str = Field(min_length=13, max_length=13)
    razon_social: str = Field(min_length=2, max_length=300)
    nombre_comercial: str | None = Field(default=None, max_length=300)
    email: EmailStr
    telefono: str | None = Field(default=None, max_length=20)
    direccion_matriz: str | None = Field(default=None, max_length=1000)
    plan: str = Field(min_length=2, max_length=50)
    codigo_promo: str | None = Field(default=None, max_length=50)
    # Canal que trajo el alta. Marketing agrupa por él, así que se guarda en el
    # inquilino en vez de deducirse después (que ya no se podría).
    origen: str = Field(default="Orgánico", max_length=40)

    @field_validator("ruc")
    @classmethod
    def ruc_valido(cls, v: str) -> str:
        v = v.strip()
        if not (v.isdigit() and v.endswith("001")):
            raise ValueError("RUC inválido: deben ser 13 dígitos terminados en 001")
        return v
