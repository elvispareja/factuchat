"""Emisión y consulta de comprobantes (fase 2).

El endpoint de emisión solo ENCOLA (devuelve el id); el estado se consulta por
polling. La emisión exige confirmación explícita: crear borrador ≠ emitir (A06).
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models import Comprobante
from app.db.models.enums import Rol
from app.db.session import get_db
from app.schemas.comprobantes import ComprobanteOut, EmitirIn, FacturaIn
from app.services import emision
from app.services.emision import EmisionError
from app.services.planes import LimitePlanError

router = APIRouter(prefix="/comprobantes", tags=["comprobantes"])


def _a_out(c: Comprobante) -> ComprobanteOut:
    mensajes: list[str] = []
    for grupo in (c.sri_mensajes or {}).values():
        for m in grupo:
            if m.get("legible"):
                mensajes.append(m["legible"])
    numero = None
    if c.secuencial is not None:
        numero = f"{c.establecimiento}-{c.punto_emision}-{c.secuencial:09d}"
    return ComprobanteOut(
        id=c.id,
        tipo=c.tipo.value,
        estado=c.estado.value,
        ambiente=c.ambiente.value,
        numero=numero,
        clave_acceso=c.clave_acceso,
        numero_autorizacion=c.numero_autorizacion,
        fecha_emision=c.fecha_emision.isoformat(),
        subtotal=str(c.subtotal),
        iva=str(c.iva),
        total=str(c.total),
        mensajes=mensajes,
        intentos=c.intentos,
    )


@router.post("/facturas", response_model=ComprobanteOut, status_code=status.HTTP_201_CREATED)
def crear_factura(
    body: FacturaIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    try:
        comp = emision.crear_factura(
            db,
            tenant_id=tenant_de(user),
            cliente_final_id=body.cliente_final_id,
            items_in=[i.model_dump() for i in body.items],
            forma_pago=body.forma_pago,
            info_adicional=body.info_adicional,
        )
    except LimitePlanError as e:
        # Todos los topes de plan responden 402, para que el panel muestre el
        # bloqueo con su invitación a subir de plan (fase 3.2)
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={"mensaje": e.mensaje, "funcion": e.funcion, "plan_sugerido": e.plan_sugerido},
        ) from e
    except EmisionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return _a_out(comp)


@router.post("/{comprobante_id}/emitir", response_model=ComprobanteOut, status_code=202)
def emitir(
    comprobante_id: uuid.UUID,
    body: EmitirIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    try:
        comp = emision.emitir(
            db, tenant_de(user), comprobante_id, body.establecimiento, body.punto_emision
        )
    except EmisionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return _a_out(comp)


@router.post("/{comprobante_id}/reintentar", response_model=ComprobanteOut, status_code=202)
def reintentar(
    comprobante_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    try:
        comp = emision.reintentar(db, tenant_de(user), comprobante_id)
    except EmisionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return _a_out(comp)


@router.get("", response_model=list[ComprobanteOut])
def listar(
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Comprobante).order_by(Comprobante.created_at.desc()).limit(100)).all()
    return [_a_out(c) for c in rows]


@router.get("/{comprobante_id}", response_model=ComprobanteOut)
def obtener(
    comprobante_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    comp = db.get(Comprobante, comprobante_id)  # RLS: solo del propio tenant
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comprobante no encontrado")
    return _a_out(comp)


def _descargar(comp: Comprobante | None, atributo: str, media_type: str) -> Response:
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comprobante no encontrado")
    ruta = getattr(comp, atributo)
    if not ruta or not Path(ruta).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archivo aún no disponible")
    return Response(
        content=Path(ruta).read_bytes(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{Path(ruta).name}"'},
    )


@router.get("/{comprobante_id}/xml")
def descargar_xml(
    comprobante_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    return _descargar(db.get(Comprobante, comprobante_id), "xml_path", "application/xml")


@router.get("/{comprobante_id}/ride")
def descargar_ride(
    comprobante_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    return _descargar(db.get(Comprobante, comprobante_id), "ride_path", "application/pdf")
