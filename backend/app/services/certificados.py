"""Gestión del certificado .p12 del tenant (fase 2.2)."""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import aesgcm_encrypt
from app.db.models import Certificado, Tenant
from app.sri.firma import AAD_P12, AAD_P12_PASSWORD, FirmaError, metadata_certificado

MAX_P12_BYTES = 100 * 1024  # un .p12 real pesa unos pocos KB


def _identificacion_del_certificado(meta: dict) -> str:
    """Cédula/RUC incrustado en el subject del certificado (los emisores
    ecuatorianos lo publican en serialNumber, y algunos en el CN u OID 2.5.4.5)."""
    texto = f"{meta['subject_cn']} {meta.get('serial_number_subject', '')}"
    digitos = re.findall(r"\d{10,13}", texto)
    return digitos[0] if digitos else ""


def revisar_certificado(p12_bytes: bytes, password: str, ruc: str | None = None) -> dict:
    """Abre el .p12 y aplica TODAS las reglas de aceptación, sin guardar nada.

    Existe como función aparte para que la vista previa del panel interno
    («Validar firma», antes de crear al cliente) y el guardado definitivo usen
    las mismas comprobaciones. Si se duplicaran, la vista previa podría dar por
    bueno un certificado que el guardado rechaza después.

    Lanza FirmaError con un mensaje para leer si algo no cuadra.
    """
    if len(p12_bytes) > MAX_P12_BYTES:
        raise FirmaError("El archivo supera el tamaño máximo permitido")

    meta = metadata_certificado(p12_bytes, password)  # lanza FirmaError si no abre

    ahora = datetime.now(UTC)
    if meta["valido_hasta"] < ahora:
        raise FirmaError(
            f"El certificado caducó el {meta['valido_hasta'].strftime('%d/%m/%Y')}. "
            "Renuévelo con su entidad certificadora."
        )
    if meta["valido_desde"] > ahora:
        raise FirmaError("El certificado aún no está vigente")

    # El certificado debe pertenecer al titular del RUC: firmar con el
    # certificado de otro contribuyente es un rechazo seguro del SRI (y un
    # problema legal). La cédula del RUC son sus primeros 10 dígitos.
    if ruc:
        ident_cert = _identificacion_del_certificado(meta)
        if ident_cert and not (ident_cert == ruc or ruc.startswith(ident_cert[:10])):
            raise FirmaError(
                "El certificado no corresponde al RUC del negocio "
                f"({ruc}). Suba el certificado del titular."
            )
    return meta


def guardar_certificado(
    db: Session, tenant_id: uuid.UUID, p12_bytes: bytes, password: str
) -> Certificado:
    """Valida el .p12 (que abra, tenga clave privada, esté vigente y pertenezca
    al RUC del tenant) y lo guarda cifrado.

    El archivo y la contraseña se cifran POR SEPARADO (AAD distinto) con la
    clave maestra CERT_ENC_KEY del entorno. Reemplaza el certificado anterior.
    """
    tenant = db.get(Tenant, tenant_id)
    meta = revisar_certificado(p12_bytes, password, tenant.ruc if tenant else None)

    s = get_settings()
    data_enc = aesgcm_encrypt(s.cert_enc_key, p12_bytes, AAD_P12, "CERT_ENC_KEY")
    password_enc = aesgcm_encrypt(
        s.cert_enc_key, password.encode(), AAD_P12_PASSWORD, "CERT_ENC_KEY"
    )

    cert = db.scalars(select(Certificado).where(Certificado.tenant_id == tenant_id)).first()
    if cert is None:
        cert = Certificado(
            tenant_id=tenant_id, p12_data_enc=data_enc, p12_password_enc=password_enc
        )
        db.add(cert)
    else:
        cert.p12_data_enc = data_enc
        cert.p12_password_enc = password_enc
    cert.subject_cn = meta["subject_cn"]
    cert.issuer_cn = meta["issuer_cn"]
    cert.serial = meta["serial"]
    cert.valido_desde = meta["valido_desde"]
    cert.valido_hasta = meta["valido_hasta"]
    cert.activo = True
    db.flush()
    return cert
