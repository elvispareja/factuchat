"""Certificados de firma electrónica (.p12) por tenant (fase 2.2).

El archivo y su contraseña se guardan cifrados AES-256-GCM con la clave maestra
CERT_ENC_KEY (solo en el entorno, jamás en la BD ni el repo). El descifrado
ocurre únicamente en memoria del worker en el momento de firmar.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class Certificado(UUIDPk, Timestamps, Base):
    __tablename__ = "certificados"

    # Un certificado activo por tenant
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True
    )
    # Blobs AES-256-GCM (nonce+ct en base64); cifrados POR SEPARADO (AAD distinto)
    p12_data_enc: Mapped[str] = mapped_column(Text)
    p12_password_enc: Mapped[str] = mapped_column(Text)

    subject_cn: Mapped[str | None] = mapped_column(String(300))
    issuer_cn: Mapped[str | None] = mapped_column(String(300))
    serial: Mapped[str | None] = mapped_column(String(100))
    valido_desde: Mapped[datetime | None]
    valido_hasta: Mapped[datetime | None]
    activo: Mapped[bool] = mapped_column(default=True)
