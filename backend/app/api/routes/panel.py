"""Estado del panel de clientes (fase 3).

Un solo endpoint entrega lo que el armazón necesita para pintarse: plan, cupos y
qué está bloqueado. El frontend NO decide permisos, solo refleja esta respuesta.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models import Certificado
from app.db.models.enums import Rol
from app.db.session import get_db
from app.services.planes import resumen_para_frontend

router = APIRouter(prefix="/panel", tags=["panel"])

TZ_ECUADOR = ZoneInfo("America/Guayaquil")


@router.get("/estado")
def estado(
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    hoy = datetime.now(TZ_ECUADOR).date()
    tenant = tenant_de(user)
    cert = db.scalars(select(Certificado).where(Certificado.activo)).first()
    return {
        "plan": resumen_para_frontend(db, tenant, hoy),
        # Con qué se encuentra el cliente al entrar. Sin firma no puede operar
        # (lo impone `exigir_firma` en el servidor), así que la pantalla tiene
        # que saberlo para llevarlo directo a subirla.
        "firma": {
            "cargada": cert is not None,
            "vence": cert.valido_hasta.isoformat() if cert and cert.valido_hasta else None,
        },
    }
