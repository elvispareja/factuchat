"""Esquemas de clientes finales con validación de RUC/cédula (OWASP A05)."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.db.models.enums import TipoIdentificacion


class ClienteFinalIn(BaseModel):
    tipo_identificacion: TipoIdentificacion
    identificacion: str = Field(min_length=3, max_length=20)
    razon_social: str = Field(min_length=2, max_length=300)
    email: EmailStr | None = None
    telefono: str | None = Field(default=None, max_length=20)
    direccion: str | None = Field(default=None, max_length=1000)
    # Sin validar que la ciudad pertenezca a la provincia: el catálogo está en
    # el frontend y comprobarlo aquí obligaría a mantenerlo en dos sitios.
    provincia: str | None = Field(default=None, max_length=100)
    ciudad: str | None = Field(default=None, max_length=100)

    @field_validator("identificacion")
    @classmethod
    def solo_alfanumerico(cls, v: str) -> str:
        v = v.strip()
        if not v.replace("-", "").isalnum():
            raise ValueError("Identificación con caracteres inválidos")
        return v

    @model_validator(mode="after")
    def valida_formato(self) -> "ClienteFinalIn":
        ident = self.identificacion
        if self.tipo_identificacion == TipoIdentificacion.RUC:
            if not (ident.isdigit() and len(ident) == 13 and ident.endswith("001")):
                raise ValueError("RUC inválido: deben ser 13 dígitos terminados en 001")
        elif self.tipo_identificacion == TipoIdentificacion.CEDULA:
            if not (ident.isdigit() and len(ident) == 10):
                raise ValueError("Cédula inválida: deben ser 10 dígitos")
        elif self.tipo_identificacion == TipoIdentificacion.CONSUMIDOR_FINAL:
            if ident != "9999999999999":
                raise ValueError("Consumidor final debe usar 9999999999999")
        return self


class ClienteFinalOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    tipo_identificacion: TipoIdentificacion
    identificacion: str
    razon_social: str
    email: str | None
    telefono: str | None
    direccion: str | None
    provincia: str | None = None
    ciudad: str | None = None


class ClienteFinalListado(ClienteFinalOut):
    """Fila del listado: añade lo facturado. Solo en GET /clientes; en la ficha
    devolver 0 sería mentir sobre un dato de dinero."""

    facturado: Decimal
    comprobantes: int
