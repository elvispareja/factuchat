"""Esquemas de categorías y sus atributos derivados."""

import uuid

from pydantic import BaseModel, Field


class CategoriaIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=150)
    descripcion: str | None = Field(default=None, max_length=2000)


class CategoriaOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    nombre: str
    descripcion: str | None
    activo: bool


class AtributoIn(BaseModel):
    categoria_id: uuid.UUID
    nombre: str = Field(min_length=1, max_length=100)


class AtributoOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    categoria_id: uuid.UUID
    nombre: str
    activo: bool


class AtributoValorIn(BaseModel):
    atributo_id: uuid.UUID
    valor: str = Field(min_length=1, max_length=150)


class AtributoValorOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    atributo_id: uuid.UUID
    valor: str
    activo: bool
