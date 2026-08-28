"""Buzón SRI, retenciones recibidas y registro de análisis con IA (fase 7).

Revision ID: 0009
Revises: 0008
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------- buzon_correos: columnas
    op.add_column("buzon_correos", sa.Column("clave_acceso", sa.String(length=49), nullable=True))
    op.add_column("buzon_correos", sa.Column("motivo_error", sa.String(length=500), nullable=True))
    op.create_index(op.f("ix_buzon_correos_recibido_at"), "buzon_correos", ["recibido_at"])

    # DEDUPLICACIÓN — la corrección importante de esta migración.
    #
    # 0001 dejó message_id con UNIQUE GLOBAL. Eso permite que un remitente
    # hostil "queme" un Message-ID antes de que llegue el correo legítimo de
    # OTRO inquilino: el legítimo chocaría contra la restricción y su retención
    # nunca se sumaría. Una denegación de servicio silenciosa y cruzada. El
    # identificador lo escribe quien envía, así que solo puede ser único DENTRO
    # de cada inquilino.
    op.drop_constraint("uq_buzon_correos_message_id", "buzon_correos", type_="unique")
    op.create_unique_constraint(
        "uq_buzon_correos_tenant_message", "buzon_correos", ["tenant_id", "message_id"]
    )
    # La clave de acceso NO lleva índice único aquí a propósito: el mismo
    # comprobante puede llegar en dos correos distintos (un reenvío), y ese
    # segundo correo debe QUEDAR REGISTRADO con estado DUPLICADO, no reventar.
    # Quien no admite repetición es la retención en sí (ver más abajo), que es
    # donde importa no contar dos veces el mismo crédito.
    op.create_index(
        "ix_buzon_correos_tenant_clave", "buzon_correos", ["tenant_id", "clave_acceso"]
    )

    # El panel interno lista los correos de TODOS los inquilinos
    op.execute(
        """
        CREATE POLICY buzon_correos_interno ON buzon_correos
          FOR ALL USING (app_is_internal()) WITH CHECK (app_is_internal());
        """
    )

    # -------------------------------------------------- retenciones_recibidas
    op.create_table(
        "retenciones_recibidas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("buzon_correo_id", sa.UUID(), nullable=True),
        sa.Column("origen", sa.String(length=20), nullable=False),
        sa.Column("clave_acceso", sa.String(length=49), nullable=True),
        sa.Column("numero", sa.String(length=30), nullable=False),
        sa.Column("ruc_agente", sa.String(length=13), nullable=True),
        sa.Column("razon_social_agente", sa.String(length=300), nullable=False),
        sa.Column("fecha_emision", sa.Date(), nullable=True),
        sa.Column("periodo_fiscal", sa.String(length=7), nullable=True),
        sa.Column("concepto", sa.String(length=300), nullable=True),
        sa.Column("base_imponible", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_renta", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_iva", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("detalle", postgresql.JSONB(), nullable=True),
        # Solo cuenta como crédito lo que el SRI confirma: un XML —y su sobre de
        # autorización— los escribe cualquiera.
        sa.Column("verificada", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verificada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verificacion", postgresql.JSONB(), nullable=True),
        sa.Column("xml_path", sa.String(length=500), nullable=True),
        sa.Column("pdf_path", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_retenciones_recibidas_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["buzon_correo_id"],
            ["buzon_correos.id"],
            name=op.f("fk_retenciones_recibidas_buzon_correo_id_buzon_correos"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retenciones_recibidas")),
    )
    op.create_index(
        op.f("ix_retenciones_recibidas_tenant_id"), "retenciones_recibidas", ["tenant_id"]
    )
    op.create_index(
        op.f("ix_retenciones_recibidas_fecha_emision"),
        "retenciones_recibidas",
        ["fecha_emision"],
    )
    op.create_index(
        op.f("ix_retenciones_recibidas_created_at"), "retenciones_recibidas", ["created_at"]
    )
    op.create_index(
        op.f("ix_retenciones_recibidas_verificada"), "retenciones_recibidas", ["verificada"]
    )
    # La misma retención no se cuenta dos veces por más veces que llegue
    op.execute(
        "CREATE UNIQUE INDEX uq_retenciones_tenant_clave ON retenciones_recibidas "
        "(tenant_id, clave_acceso) WHERE clave_acceso IS NOT NULL"
    )
    # Las tecleadas a mano no traen clave: se deduplican por número y agente
    op.execute(
        "CREATE UNIQUE INDEX uq_retenciones_tenant_numero ON retenciones_recibidas "
        "(tenant_id, numero, coalesce(ruc_agente, '')) WHERE clave_acceso IS NULL"
    )

    # -------------------------------------------------------------- analisis_ia
    op.create_table(
        "analisis_ia",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("origen", sa.String(length=20), nullable=False),
        sa.Column("consume", sa.Boolean(), nullable=False),
        sa.Column("referencia", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_analisis_ia_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analisis_ia")),
    )
    op.create_index(op.f("ix_analisis_ia_tenant_id"), "analisis_ia", ["tenant_id"])
    op.create_index(op.f("ix_analisis_ia_created_at"), "analisis_ia", ["created_at"])

    # --------------------------------------------------------------------- RLS
    for tabla in ("retenciones_recibidas", "analisis_ia"):
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {tabla}_tenant ON {tabla}
              FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
            CREATE POLICY {tabla}_interno ON {tabla}
              FOR ALL USING (app_is_internal()) WITH CHECK (app_is_internal());
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tabla} TO factuchat_app;")

    # ------------------------------------------- resolver dirección → inquilino
    #
    # `tenants` no se lee directamente ni con contexto interno (política
    # tenants_propio_select de 0002): esa es la barrera que impide que un fallo
    # del código exponga la cartera de clientes. Pero el ingestor SÍ necesita
    # saber de quién es una dirección de buzón, así que se hace por función
    # segura y acotada: recibe una dirección y devuelve, como mucho, el id y el
    # RUC de UN inquilino activo. No enumera, no lista y no devuelve nada más.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sys_tenant_por_buzon(p_local text)
        RETURNS TABLE (id uuid, ruc text)
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT t.id, t.ruc::text
            FROM tenants t
           WHERE t.ruc = p_local
             AND t.estado = 'ACTIVO'
           LIMIT 1;
        $$;

        ALTER FUNCTION sys_tenant_por_buzon(text) OWNER TO factuchat_security;
        REVOKE ALL ON FUNCTION sys_tenant_por_buzon(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION sys_tenant_por_buzon(text) TO factuchat_app;
        GRANT SELECT ON tenants TO factuchat_security;
        """
    )

    # Y la misma pieza para WhatsApp, que arrastraba el mismo problema desde la
    # fase 5: `tenant_por_telefono` consultaba `tenants` directamente desde una
    # sesión de sistema y NUNCA encontraba nada, así que en producción todo
    # mensaje de un cliente legítimo habría sido rechazado como número no
    # autorizado. Los tests no lo detectaron porque inyectan el inquilino ya
    # resuelto. Se corrige aquí, con la misma función segura y acotada.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sys_tenant_por_telefono(p_telefono text)
        RETURNS TABLE (id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT t.id
            FROM tenants t
           WHERE regexp_replace(coalesce(t.telefono, ''), '\\D', '', 'g') = p_telefono
             AND p_telefono <> ''
             AND t.estado = 'ACTIVO'
           LIMIT 1;
        $$;

        ALTER FUNCTION sys_tenant_por_telefono(text) OWNER TO factuchat_security;
        REVOKE ALL ON FUNCTION sys_tenant_por_telefono(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION sys_tenant_por_telefono(text) TO factuchat_app;
        """
    )

    # La banda ámbar del panel: quién lleva demasiado sin recibir nada. Necesita
    # cruzar `tenants` con `buzon_correos`, y `tenants` está cerrada, así que
    # sin función segura la consulta devolvía SIEMPRE cero filas y la banda
    # estaba vacía en producción desde el primer día.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_buzones_callados(p_limite int DEFAULT 5)
        RETURNS TABLE (razon_social text, dias int)
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT t.razon_social::text,
                 GREATEST(0, DATE_PART('day', now() - GREATEST(
                     t.created_at, COALESCE(MAX(b.recibido_at), t.created_at)))::int)
            FROM tenants t
            LEFT JOIN buzon_correos b ON b.tenant_id = t.id
           WHERE t.estado = 'ACTIVO'
             AND app_is_internal()
           GROUP BY t.id, t.razon_social, t.created_at
          HAVING MAX(b.recibido_at) IS NULL
           ORDER BY 2 DESC
           LIMIT p_limite;
        $$;

        ALTER FUNCTION sa_buzones_callados(int) OWNER TO factuchat_security;
        REVOKE ALL ON FUNCTION sa_buzones_callados(int) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION sa_buzones_callados(int) TO factuchat_app;
        GRANT SELECT ON buzon_correos TO factuchat_security;
        """
    )

    # ------------------------------------------------------------- parametros
    # Interruptores que el superadmin cambia en caliente. La maqueta exige poder
    # encender y apagar el módulo desde el panel y que quede auditado, así que
    # el flag no puede vivir solo en una variable de entorno.
    op.create_table(
        "parametros",
        sa.Column("clave", sa.String(length=60), nullable=False),
        sa.Column("valor", sa.String(length=300), nullable=False),
        sa.Column("actualizado_por", sa.UUID(), nullable=True),
        sa.Column(
            "actualizado_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actualizado_por"], ["users.id"], name=op.f("fk_parametros_actualizado_por_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("clave", name=op.f("pk_parametros")),
    )
    op.execute("ALTER TABLE parametros ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE parametros FORCE ROW LEVEL SECURITY;")
    # Cualquiera autenticado puede LEER un interruptor (el panel del cliente
    # necesita saber si su bandeja está encendida); solo el personal interno
    # escribe, y la comprobación de que es SUPERADMIN la hace el endpoint.
    op.execute(
        """
        CREATE POLICY parametros_lectura ON parametros FOR SELECT USING (true);
        CREATE POLICY parametros_escritura ON parametros
          FOR ALL USING (app_is_internal()) WITH CHECK (app_is_internal());
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON parametros TO factuchat_app;")

    # ------------------------------------------- marca de aviso por inquilino
    # Para no repetir el recordatorio de "configura el reenvío desde el SRI"
    # cada vez que corre el barrido.
    op.add_column(
        "tenants", sa.Column("buzon_alertado_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tenants", "buzon_alertado_at")

    op.execute("DROP FUNCTION IF EXISTS sa_buzones_callados(int)")
    op.execute("DROP FUNCTION IF EXISTS sys_tenant_por_telefono(text)")
    op.execute("DROP FUNCTION IF EXISTS sys_tenant_por_buzon(text)")
    op.execute("DROP POLICY IF EXISTS parametros_escritura ON parametros")
    op.execute("DROP POLICY IF EXISTS parametros_lectura ON parametros")
    op.drop_table("parametros")

    op.execute("DROP POLICY IF EXISTS analisis_ia_interno ON analisis_ia")
    op.execute("DROP POLICY IF EXISTS analisis_ia_tenant ON analisis_ia")
    op.drop_table("analisis_ia")

    op.execute("DROP POLICY IF EXISTS retenciones_recibidas_interno ON retenciones_recibidas")
    op.execute("DROP POLICY IF EXISTS retenciones_recibidas_tenant ON retenciones_recibidas")
    op.execute("DROP INDEX IF EXISTS uq_retenciones_tenant_numero")
    op.execute("DROP INDEX IF EXISTS uq_retenciones_tenant_clave")
    op.drop_table("retenciones_recibidas")

    op.execute("DROP POLICY IF EXISTS buzon_correos_interno ON buzon_correos")
    op.execute("DROP INDEX IF EXISTS ix_buzon_correos_tenant_clave")
    op.drop_constraint("uq_buzon_correos_tenant_message", "buzon_correos", type_="unique")
    op.create_unique_constraint("uq_buzon_correos_message_id", "buzon_correos", ["message_id"])
    op.drop_index(op.f("ix_buzon_correos_recibido_at"), table_name="buzon_correos")
    op.drop_column("buzon_correos", "motivo_error")
    op.drop_column("buzon_correos", "clave_acceso")
