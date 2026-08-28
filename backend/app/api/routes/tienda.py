"""Tienda interna del panel (fase 6.1).

Vitrina para el EQUIPO del negocio: no hay endpoints públicos aquí. Requiere el
plan que trae la tienda, y esa decisión la toma el servidor.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models import Pedido
from app.db.models.enums import EstadoPedido, MetodoPago, Rol
from app.db.session import get_db
from app.schemas.tienda import PedidoIn
from app.services import tienda
from app.services.planes import LimitePlanError, exigir_funcion, plan_vigente
from app.services.tienda import TiendaError

router = APIRouter(prefix="/tienda", tags=["tienda"])

SOLO_CLIENTE = require_roles(Rol.CLIENTE)


def _exigir_tienda(db: Session, tenant_id: uuid.UUID) -> None:
    try:
        exigir_funcion(plan_vigente(db, tenant_id), "tienda")
    except LimitePlanError as e:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={"mensaje": e.mensaje, "funcion": e.funcion, "plan_sugerido": e.plan_sugerido},
        ) from e


def _a_out(p: Pedido) -> dict:
    return {
        "id": str(p.id),
        "numero": f"PD-{p.numero:04d}",
        "estado": p.estado.value,
        "metodo_pago": p.metodo_pago.value,
        "comprador": p.comprador_nombre or "Sin datos",
        "comprador_telefono": p.comprador_telefono,
        "identificado": p.cliente_final_id is not None,
        "items": p.items,
        "subtotal": str(p.subtotal),
        "iva": str(p.iva),
        "total": str(p.total),
        "tiene_comprobante_pago": bool(p.comprobante_pago_url),
        "comprobante_id": str(p.comprobante_id) if p.comprobante_id else None,
        "nota": p.nota,
        "creado": p.created_at.isoformat(),
    }


@router.get("/vitrina")
def vitrina(user: AuthUser = Depends(SOLO_CLIENTE), db: Session = Depends(get_db)):
    """Lo que el equipo ve para armar una venta: precio SIN IVA y su tarifa
    aparte, tal como se guarda. El impuesto se calcula al facturar."""
    tenant_id = tenant_de(user)
    _exigir_tienda(db, tenant_id)
    return [
        {
            "id": str(p.id),
            "codigo": p.codigo,
            "nombre": p.nombre,
            "precio_sin_iva": str(p.precio_sin_iva),
            "porcentaje_iva": str(p.porcentaje_iva),
            "tipo": p.tipo.value,
            "maneja_inventario": p.maneja_inventario,
            "stock": str(p.stock),
            "agotado": p.maneja_inventario and p.stock <= 0,
        }
        for p in tienda.vitrina(db)
    ]


@router.get("/pedidos")
def listar_pedidos(
    estado: EstadoPedido | None = Query(default=None),
    user: AuthUser = Depends(SOLO_CLIENTE),
    db: Session = Depends(get_db),
):
    tenant_id = tenant_de(user)
    _exigir_tienda(db, tenant_id)
    consulta = select(Pedido).order_by(Pedido.created_at.desc()).limit(200)
    if estado is not None:
        consulta = consulta.where(Pedido.estado == estado)
    return {
        "resumen": tienda.resumen_por_estado(db, tenant_id),
        "pedidos": [_a_out(p) for p in db.scalars(consulta).all()],
    }


@router.post("/pedidos", status_code=status.HTTP_201_CREATED)
def crear_pedido(
    body: PedidoIn,
    user: AuthUser = Depends(SOLO_CLIENTE),
    db: Session = Depends(get_db),
):
    tenant_id = tenant_de(user)
    _exigir_tienda(db, tenant_id)
    try:
        pedido = tienda.crear_pedido(
            db,
            tenant_id=tenant_id,
            lineas=[i.model_dump() for i in body.items],
            metodo_pago=body.metodo_pago,
            cliente_final_id=body.cliente_final_id,
            comprador_nombre=body.comprador_nombre,
            comprador_telefono=body.comprador_telefono,
            nota=body.nota,
        )
    except TiendaError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return _a_out(pedido)


def _pedido_o_404(db: Session, pedido_id: uuid.UUID) -> Pedido:
    pedido = db.get(Pedido, pedido_id)  # RLS: solo del propio tenant
    if pedido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    return pedido


@router.post("/pedidos/{pedido_id}/confirmar-pago")
def confirmar_pago(
    pedido_id: uuid.UUID,
    user: AuthUser = Depends(SOLO_CLIENTE),
    db: Session = Depends(get_db),
):
    """El equipo verificó que el dinero llegó."""
    tenant_id = tenant_de(user)
    _exigir_tienda(db, tenant_id)
    try:
        pedido = tienda.confirmar_pago(db, _pedido_o_404(db, pedido_id))
    except TiendaError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return _a_out(pedido)


@router.post("/pedidos/{pedido_id}/facturar", status_code=status.HTTP_201_CREATED)
def facturar(
    pedido_id: uuid.UUID,
    user: AuthUser = Depends(SOLO_CLIENTE),
    db: Session = Depends(get_db),
):
    """Emite el comprobante del pedido y descuenta el inventario."""
    tenant_id = tenant_de(user)
    _exigir_tienda(db, tenant_id)
    pedido = _pedido_o_404(db, pedido_id)
    try:
        comprobante = tienda.facturar(db, tenant_id, pedido)
    except TiendaError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    except LimitePlanError as e:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={"mensaje": e.mensaje, "funcion": e.funcion, "plan_sugerido": e.plan_sugerido},
        ) from e
    return {"pedido": _a_out(pedido), "comprobante_id": str(comprobante.id)}


@router.post("/pedidos/{pedido_id}/anular")
def anular(
    pedido_id: uuid.UUID,
    motivo: str = Query(min_length=3, max_length=300),
    user: AuthUser = Depends(SOLO_CLIENTE),
    db: Session = Depends(get_db),
):
    tenant_id = tenant_de(user)
    _exigir_tienda(db, tenant_id)
    try:
        pedido = tienda.anular(db, _pedido_o_404(db, pedido_id), motivo)
    except TiendaError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return _a_out(pedido)


@router.get("/metodos")
def metodos_de_cobro(user: AuthUser = Depends(SOLO_CLIENTE), db: Session = Depends(get_db)):
    """Cómo cobras: transferencia y WhatsApp siempre; tarjeta si conectas
    Payphone. El dinero de Payphone entra directo a la cuenta del negocio."""
    tenant_id = tenant_de(user)
    _exigir_tienda(db, tenant_id)
    payphone_conectado = False  # la conexión con Payphone llega con su integración
    return [
        {
            "id": MetodoPago.PAYPHONE.value,
            "label": "Tarjeta de crédito",
            "nota": "Payphone, opcional",
            "activo": payphone_conectado,
        },
        {
            "id": MetodoPago.TRANSFERENCIA.value,
            "label": "Transferencia bancaria",
            "nota": "Tu comprador sube el comprobante",
            "activo": True,
        },
        {
            "id": MetodoPago.OTRO.value,
            "label": "Coordinar por WhatsApp",
            "nota": "El pedido llega a tu chat",
            "activo": True,
        },
    ]
