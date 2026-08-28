"""Inicio y Reportes (fase 3.1). Las cifras salen de comprobantes AUTORIZADOS."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models.enums import Rol
from app.db.session import get_db
from app.services import reportes

router = APIRouter(tags=["reportes"])

TZ_ECUADOR = ZoneInfo("America/Guayaquil")


def _hoy() -> date:
    return datetime.now(TZ_ECUADOR).date()


@router.get("/inicio")
def inicio(
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    return reportes.datos_inicio(db, tenant_de(user), _hoy())


@router.get("/reportes/resumen")
def resumen(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    r = reportes.resumen_fiscal(db, tenant_de(user), desde, hasta, _hoy())
    return {
        "desde": r.desde.isoformat(),
        "hasta": r.hasta.isoformat(),
        "ventas_sin_iva": str(r.ventas_sin_iva),
        "iva_cobrado": str(r.iva_cobrado),
        "notas_credito": str(r.notas_credito),
        "total_facturado": str(r.total_facturado),
        # De IVA: la única que baja el IVA a pagar
        "retenciones_recibidas": str(r.retenciones_recibidas),
        # De renta: crédito de la declaración anual, se informa aparte
        "retenciones_renta": str(r.retenciones_renta),
        "a_pagar": str(r.a_pagar),
        "comprobantes_emitidos": r.comprobantes_emitidos,
    }
