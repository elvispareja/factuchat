"""Motor de emisión SRI (fase 2): certificados cifrados, columnas de
autorización y garantía de inmutabilidad del comprobante AUTORIZADO (OWASP A08).

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------ certificados
    op.create_table(
        "certificados",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("p12_data_enc", sa.Text(), nullable=False),
        sa.Column("p12_password_enc", sa.Text(), nullable=False),
        sa.Column("subject_cn", sa.String(length=300), nullable=True),
        sa.Column("issuer_cn", sa.String(length=300), nullable=True),
        sa.Column("serial", sa.String(length=100), nullable=True),
        sa.Column("valido_desde", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valido_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_certificados_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_certificados")),
    )
    op.create_index(op.f("ix_certificados_tenant_id"), "certificados", ["tenant_id"], unique=True)

    op.execute("ALTER TABLE certificados ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE certificados FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY certificados_tenant ON certificados
          FOR ALL
          USING (tenant_id = app_tenant())
          WITH CHECK (tenant_id = app_tenant());
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON certificados TO factuchat_app;")

    # ------------------------------------------------------------ comprobantes
    # Secuencial/serie se asignan al EMITIR (confirmación explícita), no en el borrador
    op.alter_column("comprobantes", "establecimiento", nullable=True)
    op.alter_column("comprobantes", "punto_emision", nullable=True)
    op.alter_column("comprobantes", "secuencial", nullable=True)
    op.add_column(
        "comprobantes", sa.Column("numero_autorizacion", sa.String(length=49), nullable=True)
    )
    op.add_column(
        "comprobantes",
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="0"),
    )

    # Un comprobante AUTORIZADO es inmutable: solo se permiten campos post-proceso
    # (RIDE generado, contadores). Cualquier reintento crea documento nuevo (A08).
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
          ) THEN
            RAISE EXCEPTION 'comprobante autorizado es inmutable';
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_comprobante_autorizado_inmutable
          BEFORE UPDATE ON comprobantes
          FOR EACH ROW EXECUTE FUNCTION comprobante_autorizado_inmutable();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_comprobante_autorizado_inmutable ON comprobantes;"
        "DROP FUNCTION IF EXISTS comprobante_autorizado_inmutable();"
    )
    op.drop_column("comprobantes", "intentos")
    op.drop_column("comprobantes", "numero_autorizacion")
    # Los borradores creados bajo este esquema no tienen serie asignada todavía:
    # sin descartarlos, restaurar el NOT NULL falla.
    op.execute(
        "DELETE FROM comprobantes"
        " WHERE secuencial IS NULL OR establecimiento IS NULL OR punto_emision IS NULL"
    )
    op.alter_column("comprobantes", "secuencial", nullable=False)
    op.alter_column("comprobantes", "punto_emision", nullable=False)
    op.alter_column("comprobantes", "establecimiento", nullable=False)
    op.drop_index(op.f("ix_certificados_tenant_id"), table_name="certificados")
    op.drop_table("certificados")
