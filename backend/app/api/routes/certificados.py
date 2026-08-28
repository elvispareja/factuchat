"""Carga del certificado de firma .p12 del tenant (fase 2.2).

El archivo viaja por multipart y se cifra ANTES de tocar la base de datos.
Nunca se devuelve ni el archivo ni la contraseña; solo metadatos."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models import Certificado
from app.db.models.enums import Rol
from app.db.session import get_db
from app.services.certificados import MAX_P12_BYTES, guardar_certificado
from app.sri.firma import FirmaError

router = APIRouter(prefix="/certificados", tags=["certificados"])


@router.post("", status_code=status.HTTP_201_CREATED)
def subir_certificado(
    archivo: UploadFile = File(...),
    password: str = Form(min_length=1, max_length=200),
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    contenido = archivo.file.read(MAX_P12_BYTES + 1)
    try:
        cert = guardar_certificado(db, tenant_de(user), contenido, password)
    except FirmaError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return {
        "subject": cert.subject_cn,
        "emisor": cert.issuer_cn,
        "valido_desde": cert.valido_desde.isoformat() if cert.valido_desde else None,
        "valido_hasta": cert.valido_hasta.isoformat() if cert.valido_hasta else None,
        "activo": cert.activo,
    }


@router.get("")
def ver_certificado(
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    cert = db.scalars(select(Certificado)).first()  # RLS: solo el del tenant
    if cert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sin certificado cargado")
    return {
        "subject": cert.subject_cn,
        "emisor": cert.issuer_cn,
        "valido_desde": cert.valido_desde.isoformat() if cert.valido_desde else None,
        "valido_hasta": cert.valido_hasta.isoformat() if cert.valido_hasta else None,
        "activo": cert.activo,
    }
