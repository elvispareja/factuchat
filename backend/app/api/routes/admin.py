"""Rutas del panel interno (fase 4 trae las 11 secciones).

Patrón obligatorio (fase 1.4): el personal interno NUNCA consulta tablas de
tenants directamente; usa funciones seguras sa_* que verifican el rol real en BD
y dejan constancia en audit_log.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles
from app.db.models.enums import Rol
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/tenants")
def listar_tenants(
    motivo: str = Query(default="listado panel", max_length=200),
    user: AuthUser = Depends(require_roles(Rol.SUPERADMIN, Rol.SOPORTE, Rol.LECTURA)),
    db: Session = Depends(get_db),
):
    rows = (
        db.execute(text("SELECT * FROM sa_list_tenants(:motivo)"), {"motivo": motivo})
        .mappings()
        .all()
    )
    return [
        {
            "id": str(r["id"]),
            "ruc": r["ruc"],
            "razon_social": r["razon_social"],
            "email": r["email"],
            "estado": r["estado"],
            "ambiente_sri": r["ambiente_sri"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
