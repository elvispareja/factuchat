"""Categorías y sus atributos derivados (cada atributo pertenece a UNA categoría)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models import Atributo, AtributoValor, Categoria, Producto, ProductoAtributo
from app.db.models.enums import Rol
from app.db.session import get_db
from app.schemas.categorias import (
    AtributoIn,
    AtributoOut,
    AtributoValorIn,
    AtributoValorOut,
    CategoriaIn,
    CategoriaOut,
)

router = APIRouter(prefix="/categorias", tags=["categorias"])
router_atributos = APIRouter(prefix="/atributos", tags=["atributos"])
router_valores = APIRouter(prefix="/atributo-valores", tags=["atributo-valores"])

# Las bajas son lógicas (activo = False) pero los UNIQUE son de tabla: la fila
# dada de baja sigue ocupando su hueco aunque los listados, que filtran por
# activo, ya no la enseñen. Sin esto, borrar la talla «35» y volver a
# escribirla revienta con un error de integridad que el usuario ve como un 500
# sin explicación, y esa talla queda inutilizable para siempre. Revivir la fila
# es además lo que el usuario espera: vuelve con su historial intacto.
def _revivir(fila, **campos):
    fila.activo = True
    for nombre, valor in campos.items():
        setattr(fila, nombre, valor)
    return fila


@router.get("", response_model=list[CategoriaOut])
def listar(
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    consulta = select(Categoria).where(Categoria.activo.is_(True))
    return db.scalars(consulta.order_by(Categoria.nombre)).all()


@router.post("", response_model=CategoriaOut, status_code=status.HTTP_201_CREATED)
def crear(
    body: CategoriaIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    # RLS: la consulta ya va acotada al tenant, y el UNIQUE es (tenant_id, nombre)
    dada_de_baja = db.scalars(
        select(Categoria).where(Categoria.nombre == body.nombre, Categoria.activo.is_(False))
    ).first()
    if dada_de_baja is not None:
        _revivir(dada_de_baja, descripcion=body.descripcion)
        db.flush()
        return dada_de_baja
    categoria = Categoria(tenant_id=tenant_de(user), nombre=body.nombre, descripcion=body.descripcion)
    db.add(categoria)
    db.flush()
    return categoria


@router.put("/{categoria_id}", response_model=CategoriaOut)
def actualizar(
    categoria_id: uuid.UUID,
    body: CategoriaIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    categoria = db.get(Categoria, categoria_id)  # RLS: solo del propio tenant
    if categoria is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Categoría no encontrada")
    categoria.nombre = body.nombre
    categoria.descripcion = body.descripcion
    db.flush()
    return categoria


@router.delete("/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar(
    categoria_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    categoria = db.get(Categoria, categoria_id)
    if categoria is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Categoría no encontrada")
    # No se borra si sigue en uso: dejaría atributos o productos activos sin
    # categoría de golpe, o "invisibles" (las listas filtran por activo=True).
    tiene_atributos = db.scalar(
        select(Atributo.id).where(Atributo.categoria_id == categoria_id, Atributo.activo.is_(True)).limit(1)
    )
    tiene_productos = db.scalar(
        select(Producto.id).where(Producto.categoria_id == categoria_id, Producto.activo.is_(True)).limit(1)
    )
    if tiene_atributos or tiene_productos:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No puedes eliminar esta categoría: tiene atributos o productos activos",
        )
    categoria.activo = False
    db.flush()
    return None


@router_atributos.get("", response_model=list[AtributoOut])
def listar_atributos(
    categoria_id: uuid.UUID | None = Query(default=None),
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    consulta = select(Atributo).where(Atributo.activo.is_(True))
    if categoria_id is not None:
        consulta = consulta.where(Atributo.categoria_id == categoria_id)
    return db.scalars(consulta.order_by(Atributo.nombre)).all()


@router_atributos.post("", response_model=AtributoOut, status_code=status.HTTP_201_CREATED)
def crear_atributo(
    body: AtributoIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    if db.get(Categoria, body.categoria_id) is None:  # RLS: solo del propio tenant
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Categoría no encontrada")
    dado_de_baja = db.scalars(
        select(Atributo).where(
            Atributo.categoria_id == body.categoria_id,
            Atributo.nombre == body.nombre,
            Atributo.activo.is_(False),
        )
    ).first()
    if dado_de_baja is not None:
        _revivir(dado_de_baja)
        db.flush()
        return dado_de_baja
    atributo = Atributo(tenant_id=tenant_de(user), categoria_id=body.categoria_id, nombre=body.nombre)
    db.add(atributo)
    db.flush()
    return atributo


@router_atributos.put("/{atributo_id}", response_model=AtributoOut)
def actualizar_atributo(
    atributo_id: uuid.UUID,
    body: AtributoIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    atributo = db.get(Atributo, atributo_id)
    if atributo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Atributo no encontrado")
    # categoria_id NO se edita: un atributo no cambia de categoría (simplicidad
    # a propósito); si hiciera falta, se borra y se crea en la nueva.
    atributo.nombre = body.nombre
    db.flush()
    return atributo


@router_atributos.delete("/{atributo_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_atributo(
    atributo_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    atributo = db.get(Atributo, atributo_id)
    if atributo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Atributo no encontrado")
    tiene_valores = db.scalar(
        select(AtributoValor.id)
        .where(AtributoValor.atributo_id == atributo_id, AtributoValor.activo.is_(True))
        .limit(1)
    )
    tiene_productos = db.scalar(
        select(ProductoAtributo.id)
        .join(Producto, Producto.id == ProductoAtributo.producto_id)
        .where(ProductoAtributo.atributo_id == atributo_id, Producto.activo.is_(True))
        .limit(1)
    )
    if tiene_valores or tiene_productos:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No puedes eliminar este atributo: tiene valores o productos activos usándolo",
        )
    atributo.activo = False
    db.flush()
    return None


@router_valores.get("", response_model=list[AtributoValorOut])
def listar_valores(
    atributo_id: uuid.UUID | None = Query(default=None),
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    consulta = select(AtributoValor).where(AtributoValor.activo.is_(True))
    if atributo_id is not None:
        consulta = consulta.where(AtributoValor.atributo_id == atributo_id)
    return db.scalars(consulta.order_by(AtributoValor.valor)).all()


@router_valores.post("", response_model=AtributoValorOut, status_code=status.HTTP_201_CREATED)
def crear_valor(
    body: AtributoValorIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    if db.get(Atributo, body.atributo_id) is None:  # RLS: solo del propio tenant
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Atributo no encontrado")
    dado_de_baja = db.scalars(
        select(AtributoValor).where(
            AtributoValor.atributo_id == body.atributo_id,
            AtributoValor.valor == body.valor,
            AtributoValor.activo.is_(False),
        )
    ).first()
    if dado_de_baja is not None:
        _revivir(dado_de_baja)
        db.flush()
        return dado_de_baja
    valor = AtributoValor(tenant_id=tenant_de(user), atributo_id=body.atributo_id, valor=body.valor)
    db.add(valor)
    db.flush()
    return valor


@router_valores.put("/{valor_id}", response_model=AtributoValorOut)
def actualizar_valor(
    valor_id: uuid.UUID,
    body: AtributoValorIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    valor = db.get(AtributoValor, valor_id)
    if valor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Valor no encontrado")
    valor.valor = body.valor
    db.flush()
    return valor


@router_valores.delete("/{valor_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_valor(
    valor_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    valor = db.get(AtributoValor, valor_id)
    if valor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Valor no encontrado")
    tiene_productos = db.scalar(
        select(ProductoAtributo.id)
        .join(Producto, Producto.id == ProductoAtributo.producto_id)
        .where(ProductoAtributo.atributo_valor_id == valor_id, Producto.activo.is_(True))
        .limit(1)
    )
    if tiene_productos:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "No puedes eliminar este valor: hay productos activos usándolo"
        )
    valor.activo = False
    db.flush()
    return None
