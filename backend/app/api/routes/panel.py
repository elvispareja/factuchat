"""Estado del panel de clientes (fase 3).

Un solo endpoint entrega lo que el armazón necesita para pintarse: plan, cupos y
qué está bloqueado. El frontend NO decide permisos, solo refleja esta respuesta.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models import Certificado, Tenant
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
    negocio = db.get(Tenant, tenant)  # RLS: solo su propia fila
    # Esta es la llamada que se hace al arrancar el panel: sin la guarda, una
    # fila que RLS no deja ver tumba la pantalla entera con un AttributeError
    # disfrazado de 500. El resto del código ya comprueba este mismo `db.get`.
    if negocio is None:
        raise HTTPException(status_code=404, detail="Negocio no disponible")
    return {
        "plan": resumen_para_frontend(db, tenant, hoy),
        # Cabecera del emisor tal y como la imprime el RIDE, para que «Revisa tu
        # factura» se lea como el documento que va a salir. Va aquí y no en una
        # ruta propia porque es la misma pantalla, el mismo rol y el mismo
        # momento (el panel ya llama a /panel/estado al montar): una ruta aparte
        # solo añadiría un viaje más para cinco campos que no cambian. NADA del
        # certificado ni rutas de disco: eso vive en /certificados.
        "emisor": {
            "razon_social": negocio.razon_social,
            "nombre_comercial": negocio.nombre_comercial,
            "ruc": negocio.ruc,
            "direccion_matriz": negocio.direccion_matriz,
            "obligado_contabilidad": negocio.obligado_contabilidad,
        },
        # Con qué se encuentra el cliente al entrar. Sin firma no puede operar
        # (lo impone `exigir_firma` en el servidor), así que la pantalla tiene
        # que saberlo para llevarlo directo a subirla.
        "firma": {
            "cargada": cert is not None,
            "vence": cert.valido_hasta.isoformat() if cert and cert.valido_hasta else None,
        },
    }
