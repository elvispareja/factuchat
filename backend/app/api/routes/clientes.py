"""Clientes finales del tenant. Doble barrera A01: rol explícito + RLS por tenant.

La sección completa del panel llega en fase 3; estas rutas establecen el patrón
y sirven de prueba viva del aislamiento multi-tenant (checklist F1).
"""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models import ClienteFinal, Comprobante
from app.db.models.enums import EstadoComprobante, Rol, TipoComprobante
from app.db.session import get_db
from app.schemas.clientes import ClienteFinalIn, ClienteFinalListado, ClienteFinalOut
from app.services import carga_masiva
from app.services.planes import (
    LimitePlanError,
    clientes_guardados,
    exigir_cupo_clientes,
    exigir_funcion,
    plan_vigente,
)

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.get("", response_model=list[ClienteFinalListado])
def listar(
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    # Dos filtros, y los dos hacen falta:
    #   · AUTORIZADO — es lo que el SRI aceptó; un borrador, un rechazado o un
    #     devuelto no son dinero emitido.
    #   · tipo FACTURA — sin esto se suman los 6 tipos del SRI, y entonces una
    #     nota de crédito que ANULA una venta la SUMA otra vez (dobla el importe
    #     en vez de dejarlo en cero), y retenciones y guías de remisión, que no
    #     son ventas, cuentan como comprobantes facturados.
    # Es el mismo criterio que ranking_clientes() en services/reportes.py, que
    # también mide por cliente: la libreta y el ranking de Inicio no pueden dar
    # cifras distintas del mismo negocio.
    facturado = (
        select(
            Comprobante.cliente_final_id.label("cliente_id"),
            func.sum(Comprobante.total).label("facturado"),
            func.count().label("comprobantes"),
        )
        .where(
            Comprobante.estado == EstadoComprobante.AUTORIZADO,
            Comprobante.tipo == TipoComprobante.FACTURA,
        )
        .group_by(Comprobante.cliente_final_id)
        .subquery()
    )
    # Sin filtro manual por tenant: RLS ya limita a las filas del tenant
    # autenticado, en la tabla y en el agregado. Un solo viaje a la base: con un
    # SELECT por cliente serían 500 consultas en una libreta de 500.
    rows = db.execute(
        select(ClienteFinal, facturado.c.facturado, facturado.c.comprobantes)
        .outerjoin(facturado, facturado.c.cliente_id == ClienteFinal.id)
        .order_by(ClienteFinal.razon_social)
    ).all()
    return [
        ClienteFinalListado(
            **ClienteFinalOut.model_validate(cliente).model_dump(),
            facturado=total or Decimal("0"),
            comprobantes=cuantos or 0,
        )
        for cliente, total, cuantos in rows
    ]


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
