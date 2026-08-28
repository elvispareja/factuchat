"""Artículos y servicios (fase 3.1), con inventario gated por plan (3.2)."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models import Producto
from app.db.models.enums import Rol, TipoProducto
from app.db.session import get_db
from app.schemas.productos import ProductoIn, ProductoOut
from app.services.planes import (
    LimitePlanError,
    exigir_cupo_productos,
    exigir_funcion,
    plan_vigente,
)
from app.sri.xml_builder import TARIFAS_IVA

router = APIRouter(prefix="/productos", tags=["productos"])


def _aplicar(producto: Producto, body: ProductoIn, permite_stock: bool) -> None:
    producto.codigo = body.codigo
    producto.nombre = body.nombre
    producto.descripcion = body.descripcion
    producto.tipo = body.tipo
    producto.precio_sin_iva = body.precio_sin_iva
    producto.codigo_iva = body.codigo_iva
    producto.porcentaje_iva = TARIFAS_IVA[body.codigo_iva]
    producto.mostrar_en_tienda = body.mostrar_en_tienda
    # Sin la función de inventario en el plan, el catálogo funciona igual pero
    # sin conteo: los campos de stock simplemente no se guardan.
    if permite_stock:
        producto.maneja_inventario = body.maneja_inventario
        producto.stock = body.stock
        producto.stock_minimo = body.stock_minimo
    else:
        producto.maneja_inventario = False
        producto.stock = Decimal("0")
        producto.stock_minimo = None


@router.get("", response_model=list[ProductoOut])
def listar(
    tipo: TipoProducto | None = Query(default=None),
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    consulta = select(Producto).where(Producto.activo.is_(True))
    if tipo is not None:
        consulta = consulta.where(Producto.tipo == tipo)
    return db.scalars(consulta.order_by(Producto.nombre)).all()


@router.post("", response_model=ProductoOut, status_code=status.HTTP_201_CREATED)
def crear(
    body: ProductoIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    tenant_id = tenant_de(user)
    plan = plan_vigente(db, tenant_id)
    try:
        exigir_cupo_productos(db, tenant_id, plan)
        if body.mostrar_en_tienda:
            exigir_funcion(plan, "tienda")
    except LimitePlanError as e:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "mensaje": e.mensaje,
                "funcion": e.funcion,
                "plan_sugerido": e.plan_sugerido,
            },
        ) from e

    producto = Producto(tenant_id=tenant_id)
    _aplicar(producto, body, plan.permite("stock"))
    db.add(producto)
    db.flush()
    return producto


@router.put("/{producto_id}", response_model=ProductoOut)
def actualizar(
    producto_id: uuid.UUID,
    body: ProductoIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    producto = db.get(Producto, producto_id)  # RLS: solo del propio tenant
    if producto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Producto no encontrado")
    plan = plan_vigente(db, tenant_de(user))
    try:
        if body.mostrar_en_tienda and not producto.mostrar_en_tienda:
            exigir_funcion(plan, "tienda")
    except LimitePlanError as e:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "mensaje": e.mensaje,
                "funcion": e.funcion,
                "plan_sugerido": e.plan_sugerido,
            },
        ) from e
    _aplicar(producto, body, plan.permite("stock"))
    db.flush()
    return producto


@router.delete("/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar(
    producto_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    producto = db.get(Producto, producto_id)
    if producto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Producto no encontrado")
    # Baja lógica: el histórico de comprobantes debe seguir siendo legible
    producto.activo = False
    db.flush()
    return None
