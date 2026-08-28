"""Tienda interna, aceptación de términos y solicitudes de contacto (fase 6).

Revision ID: 0007
Revises: 0006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE estado_pedido AS ENUM "
        "('POR_REVISAR','TRANSFERENCIA_POR_CONFIRMAR','POR_ENTREGAR','PAGADO','ANULADO')"
    )

    # ------------------------------------------------------------- pedidos
    op.create_table(
        "pedidos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        # Los tipos ENUM ya existen: create_type=False evita recrearlos
        sa.Column(
            "estado",
            postgresql.ENUM(name="estado_pedido", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "metodo_pago",
            postgresql.ENUM(name="metodo_pago", create_type=False),
            nullable=False,
        ),
        sa.Column("cliente_final_id", sa.UUID(), nullable=True),
        sa.Column("comprador_nombre", sa.String(length=300), nullable=True),
        sa.Column("comprador_telefono", sa.String(length=20), nullable=True),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("iva", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("comprobante_pago_url", sa.String(length=500), nullable=True),
        sa.Column("referencia_pago", sa.String(length=200), nullable=True),
        sa.Column("comprobante_id", sa.UUID(), nullable=True),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.Column("confirmado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entregado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_pedidos_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cliente_final_id"], ["clientes_finales.id"],
            name=op.f("fk_pedidos_cliente_final_id_clientes_finales"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["comprobante_id"], ["comprobantes.id"],
            name=op.f("fk_pedidos_comprobante_id_comprobantes"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pedidos")),
        sa.UniqueConstraint("tenant_id", "numero", name=op.f("uq_pedidos_tenant_id_numero")),
    )
    op.create_index(op.f("ix_pedidos_tenant_id"), "pedidos", ["tenant_id"])
    op.create_index(op.f("ix_pedidos_estado"), "pedidos", ["estado"])

    # ------------------------------------------- aceptaciones de términos
    op.create_table(
        "aceptaciones_terminos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("nombre", sa.String(length=300), nullable=True),
        sa.Column("identificacion", sa.String(length=20), nullable=True),
        sa.Column("documento", sa.String(length=40), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("aceptado", sa.Boolean(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("origen", sa.String(length=40), nullable=False),
        sa.Column(
            "aceptado_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name=op.f("fk_aceptaciones_terminos_tenant_id_tenants"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_aceptaciones_terminos")),
    )
    op.create_index(
        op.f("ix_aceptaciones_terminos_tenant_id"), "aceptaciones_terminos", ["tenant_id"]
    )
    op.create_index(op.f("ix_aceptaciones_terminos_email"), "aceptaciones_terminos", ["email"])
    op.create_index(
        op.f("ix_aceptaciones_terminos_aceptado_at"), "aceptaciones_terminos", ["aceptado_at"]
    )

    # ----------------------------------------------- solicitudes de contacto
    op.create_table(
        "solicitudes_contacto",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=300), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("telefono", sa.String(length=20), nullable=True),
        sa.Column("identificacion", sa.String(length=20), nullable=True),
        sa.Column("ciudad", sa.String(length=120), nullable=True),
        sa.Column("provincia", sa.String(length=120), nullable=True),
        sa.Column("pais", sa.String(length=80), nullable=False),
        sa.Column("plan", sa.String(length=50), nullable=True),
        sa.Column("metodo_pago", sa.String(length=30), nullable=True),
        sa.Column("agenda_dia", sa.Date(), nullable=True),
        sa.Column("agenda_hora", sa.String(length=20), nullable=True),
        sa.Column("mensaje", sa.Text(), nullable=True),
        sa.Column("codigo_promo", sa.String(length=50), nullable=True),
        sa.Column("comprobante_url", sa.String(length=500), nullable=True),
        sa.Column("atendida", sa.Boolean(), nullable=False),
        sa.Column(
            "creada_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solicitudes_contacto")),
    )
    op.create_index(
        op.f("ix_solicitudes_contacto_creada_at"), "solicitudes_contacto", ["creada_at"]
    )

    # ------------------------------------------------------------------ RLS
    for tabla in ("pedidos", "aceptaciones_terminos", "solicitudes_contacto"):
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY;")

    # Los pedidos son del inquilino; el personal interno los ve para dar soporte
    op.execute(
        """
        CREATE POLICY pedidos_tenant ON pedidos
          FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
        CREATE POLICY pedidos_interno ON pedidos
          FOR ALL USING (app_is_internal()) WITH CHECK (app_is_internal());
        """
    )

    # Las aceptaciones se escriben desde el checkout PÚBLICO (sin tenant todavía)
    # y solo las lee el personal interno: son la prueba de cumplimiento LOPDP.
    # Nadie las edita ni las borra: sin política de UPDATE/DELETE quedan cerradas.
    op.execute(
        """
        CREATE POLICY aceptaciones_insert ON aceptaciones_terminos
          FOR INSERT WITH CHECK (true);
        CREATE POLICY aceptaciones_select ON aceptaciones_terminos
          FOR SELECT USING (app_is_internal() OR tenant_id = app_tenant());
        """
    )
    op.execute(
        """
        CREATE POLICY solicitudes_insert ON solicitudes_contacto
          FOR INSERT WITH CHECK (true);
        CREATE POLICY solicitudes_interno ON solicitudes_contacto
          FOR SELECT USING (app_is_internal());
        CREATE POLICY solicitudes_update ON solicitudes_contacto
          FOR UPDATE USING (app_is_internal()) WITH CHECK (app_is_internal());
        """
    )

    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE ON pedidos TO factuchat_app;
        GRANT SELECT, INSERT ON aceptaciones_terminos TO factuchat_app;
        GRANT SELECT, INSERT, UPDATE ON solicitudes_contacto TO factuchat_app;
        """
    )

    # Adjuntar el comprobante de una transferencia desde el checkout PÚBLICO.
    # Va por función segura y acotada: quien envió el formulario no puede leer
    # la tabla (ni enumerar solicitudes ajenas), pero sí completar LA SUYA, cuyo
    # UUID solo conoce él. La función no devuelve ningún dato, solo si pudo.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION publico_adjuntar_comprobante(
          p_solicitud uuid, p_url text
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_filas int;
        BEGIN
          UPDATE solicitudes_contacto
             SET comprobante_url = p_url
           WHERE id = p_solicitud AND comprobante_url IS NULL;
          GET DIAGNOSTICS v_filas = ROW_COUNT;
          RETURN v_filas > 0;
        END $$;

        ALTER FUNCTION publico_adjuntar_comprobante(uuid, text)
          OWNER TO factuchat_security;
        REVOKE ALL ON FUNCTION publico_adjuntar_comprobante(uuid, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION publico_adjuntar_comprobante(uuid, text) TO factuchat_app;
        GRANT SELECT, UPDATE ON solicitudes_contacto TO factuchat_security;
        """
    )

    # Igual que audit_log: la constancia de una aceptación no se reescribe
    op.execute(
        """
        CREATE OR REPLACE FUNCTION aceptacion_inmutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'la aceptación de términos es inmutable';
        END $$;

        CREATE TRIGGER trg_aceptacion_inmutable
          BEFORE UPDATE OR DELETE ON aceptaciones_terminos
          FOR EACH ROW EXECUTE FUNCTION aceptacion_inmutable();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_aceptacion_inmutable ON aceptaciones_terminos;"
        "DROP FUNCTION IF EXISTS aceptacion_inmutable();"
    )
    op.execute("DROP FUNCTION IF EXISTS publico_adjuntar_comprobante(uuid, text);")
    op.drop_table("solicitudes_contacto")
    op.drop_table("aceptaciones_terminos")
    op.drop_table("pedidos")
    op.execute("DROP TYPE IF EXISTS estado_pedido")
