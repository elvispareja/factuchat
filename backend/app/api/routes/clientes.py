"""Clientes finales del tenant. Doble barrera A01: rol explícito + RLS por tenant.

La sección completa del panel llega en fase 3; estas rutas establecen el patrón
y sirven de prueba viva del aislamiento multi-tenant (checklist F1).
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models import ClienteFinal
from app.db.models.enums import Rol
from app.db.session import get_db
from app.schemas.clientes import ClienteFinalIn, ClienteFinalOut
from app.services import carga_masiva
from app.services.planes import (
    LimitePlanError,
    clientes_guardados,
    exigir_cupo_clientes,
    exigir_funcion,
    plan_vigente,
)

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.get("", response_model=list[ClienteFinalOut])
def listar(
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    # Sin filtro manual por tenant: RLS ya limita a las filas del tenant autenticado.
    rows = db.scalars(select(ClienteFinal).order_by(ClienteFinal.razon_social)).all()
    return rows


def _error_plan(e: LimitePlanError) -> HTTPException:
    return HTTPException(
        status.HTTP_402_PAYMENT_REQUIRED,
        detail={"mensaje": e.mensaje, "funcion": e.funcion, "plan_sugerido": e.plan_sugerido},
    )


@router.post("", response_model=ClienteFinalOut, status_code=status.HTTP_201_CREATED)
def crear(
    body: ClienteFinalIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    tenant_id = tenant_de(user)
    try:
        exigir_cupo_clientes(db, tenant_id, plan_vigente(db, tenant_id))
    except LimitePlanError as e:
        raise _error_plan(e) from e
    cliente = ClienteFinal(tenant_id=tenant_id, **body.model_dump())
    db.add(cliente)
    db.flush()
    return cliente


@router.post("/carga-masiva/analizar")
def analizar_carga(
    archivo: UploadFile = File(...),
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    """Vista previa: NADA se guarda todavía (la maqueta muestra los errores
    fila por fila antes de confirmar)."""
    tenant_id = tenant_de(user)
    plan = plan_vigente(db, tenant_id)
    try:
        exigir_funcion(plan, "masivo")
    except LimitePlanError as e:
        raise _error_plan(e) from e

    contenido = archivo.file.read(carga_masiva.MAX_BYTES + 1)
    try:
        filas = carga_masiva.analizar(contenido, archivo.filename or "")
    except carga_masiva.CargaMasivaError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    carga_masiva.marcar_existentes(db, tenant_id, filas)

    tope = plan.tope("cli")
    disponibles = max(0, tope - clientes_guardados(db, tenant_id)) if tope else 0
    validas = [f for f in filas if f.valida]
    return {
        "total": len(filas),
        "validas": len(validas),
        "con_error": sum(1 for f in filas if f.errores),
        "ya_guardados": sum(1 for f in filas if f.duplicado),
        "cabe_en_el_plan": (len(validas) <= disponibles) if tope else True,
        "disponibles_en_el_plan": disponibles if tope else None,
        "filas": [
            {
                "numero": f.numero,
                "identificacion": f.identificacion,
                "razon_social": f.razon_social,
                "email": f.email,
                "telefono": f.telefono,
                "tipo_identificacion": f.tipo_identificacion,
                "errores": f.errores,
                "ya_guardado": f.duplicado,
            }
            for f in filas[:200]  # la vista previa muestra las primeras 200
        ],
    }


@router.post("/carga-masiva/confirmar", status_code=status.HTTP_201_CREATED)
def confirmar_carga(
    archivo: UploadFile = File(...),
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    tenant_id = tenant_de(user)
    plan = plan_vigente(db, tenant_id)
    try:
        exigir_funcion(plan, "masivo")
    except LimitePlanError as e:
        raise _error_plan(e) from e

    contenido = archivo.file.read(carga_masiva.MAX_BYTES + 1)
    try:
        filas = carga_masiva.analizar(contenido, archivo.filename or "")
    except carga_masiva.CargaMasivaError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    carga_masiva.marcar_existentes(db, tenant_id, filas)

    tope = plan.tope("cli")
    disponibles = max(0, tope - clientes_guardados(db, tenant_id)) if tope else 0
    guardadas = carga_masiva.guardar(db, tenant_id, filas, disponibles if tope else 0)
    validas = sum(1 for f in filas if f.valida)
    return {
        "guardados": guardadas,
        "omitidos_por_error": sum(1 for f in filas if f.errores),
        "omitidos_por_duplicado": sum(1 for f in filas if f.duplicado),
        "omitidos_por_plan": max(0, validas - guardadas),
    }


@router.get("/{cliente_id}", response_model=ClienteFinalOut)
def obtener(
    cliente_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    # Si el ID pertenece a otro tenant, RLS devuelve vacío → 404 (sin fuga de existencia)
    row = db.get(ClienteFinal, cliente_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente no encontrado")
    return row


@router.put("/{cliente_id}", response_model=ClienteFinalOut)
def actualizar(
    cliente_id: uuid.UUID,
    body: ClienteFinalIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    row = db.get(ClienteFinal, cliente_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente no encontrado")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    db.flush()
    return row
