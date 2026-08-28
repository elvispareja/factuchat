"""Marcas persistentes de reanudación del pipeline de emisión (OWASP A08/A10).

Sin ellas, una caída del worker JUSTO DESPUÉS de enviar a recepción (pero antes
de confirmar el estado) hacía que el reintento reenviara el mismo XML al SRI; y
un fallo de SMTP dejaba al comprador sin factura para siempre, porque ride_path
ya estaba confirmado y actuaba como guardia de idempotencia del correo.

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comprobantes",
        sa.Column("enviado_recepcion_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "comprobantes",
        sa.Column("correo_enviado_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Índice para el barrido de comprobantes atascados en ENVIADO_SRI
    op.create_index(
        "ix_comprobantes_pendientes_autorizacion",
        "comprobantes",
        ["estado", "updated_at"],
    )

    # El trigger de inmutabilidad debe seguir permitiendo estas marcas
    # post-proceso sobre un comprobante ya AUTORIZADO (correo reintentado).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION comprobante_autorizado_inmutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.estado = 'AUTORIZADO' AND (
               NEW.estado IS DISTINCT FROM OLD.estado
            OR NEW.clave_acceso IS DISTINCT FROM OLD.clave_acceso
            OR NEW.sha256_xml IS DISTINCT FROM OLD.sha256_xml
            OR NEW.xml_path IS DISTINCT FROM OLD.xml_path
            OR NEW.secuencial IS DISTINCT FROM OLD.secuencial
            OR NEW.establecimiento IS DISTINCT FROM OLD.establecimiento
            OR NEW.punto_emision IS DISTINCT FROM OLD.punto_emision
            OR NEW.numero_autorizacion IS DISTINCT FROM OLD.numero_autorizacion
            OR NEW.subtotal IS DISTINCT FROM OLD.subtotal
            OR NEW.iva IS DISTINCT FROM OLD.iva
            OR NEW.total IS DISTINCT FROM OLD.total
            OR NEW.payload IS DISTINCT FROM OLD.payload
            OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
            OR NEW.tipo IS DISTINCT FROM OLD.tipo
            OR NEW.fecha_emision IS DISTINCT FROM OLD.fecha_emision
            OR NEW.autorizado_at IS DISTINCT FROM OLD.autorizado_at
          ) THEN
            RAISE EXCEPTION 'comprobante autorizado es inmutable';
          END IF;
          RETURN NEW;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_comprobantes_pendientes_autorizacion", table_name="comprobantes")
    op.drop_column("comprobantes", "correo_enviado_at")
    op.drop_column("comprobantes", "enviado_recepcion_at")
