"""Panel interno (fase 4): impersonación auditada, promos con retenido,
precios con vigencia y funciones seguras sa_* para las 11 secciones.

Revision ID: 0005
Revises: 0004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------- impersonaciones
    # Tabla propia: una impersonación es una SESIÓN, no un evento suelto. Saber
    # cuándo empezó, cuándo terminó y con qué motivo es lo que la hace auditable.
    op.create_table(
        "impersonaciones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("motivo", sa.String(length=300), nullable=False),
        sa.Column("iniciada_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("terminada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_impersonaciones_actor_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_impersonaciones_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impersonaciones")),
    )
    op.create_index(
        op.f("ix_impersonaciones_actor_user_id"), "impersonaciones", ["actor_user_id"]
    )
    op.create_index(op.f("ix_impersonaciones_tenant_id"), "impersonaciones", ["tenant_id"])

    op.execute("ALTER TABLE impersonaciones ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE impersonaciones FORCE ROW LEVEL SECURITY;")
    # Solo el personal interno la ve; el inquilino jamás consulta esta tabla
    op.execute(
        """
        CREATE POLICY impersonaciones_interno ON impersonaciones
          FOR ALL USING (app_is_internal()) WITH CHECK (app_is_internal());
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON impersonaciones TO factuchat_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON impersonaciones TO factuchat_security;")

    # ------------------------------------------------------------- promo_uses
    # El descuento se congela al aplicarse: si el precio del plan cambia después,
    # lo retenido de ese uso NO se recalcula.
    op.add_column(
        "promo_uses",
        sa.Column("precio_lista", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "promo_uses",
        sa.Column("precio_cobrado", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column("promo_uses", sa.Column("meses_aplicados", sa.Integer(), nullable=True))

    # --------------------------------------------------------------- promos
    op.add_column("promo_codes", sa.Column("planes", sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column("promo_codes", sa.Column("meses", sa.Integer(), nullable=False, server_default="1"))

    # ------------------------------------------------- funciones seguras sa_*
    # Patrón de la fase 1: verifican el rol REAL en la base y dejan rastro.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_verificar_rol(p_motivo text, p_minimo text DEFAULT 'LECTURA')
        RETURNS TABLE (actor uuid, rol text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
          v_actor uuid := app_user();
          v_rol text;
          v_orden int;
          v_min int;
        BEGIN
          IF NOT app_is_internal() OR v_actor IS NULL THEN
            RAISE EXCEPTION 'acceso denegado';
          END IF;
          SELECT u.rol::text INTO v_rol FROM users u
           WHERE u.id = v_actor AND u.is_active AND u.tenant_id IS NULL;
          IF v_rol IS NULL THEN
            RAISE EXCEPTION 'acceso denegado';
          END IF;
          -- LECTURA < SOPORTE < SUPERADMIN
          v_orden := CASE v_rol WHEN 'LECTURA' THEN 1 WHEN 'SOPORTE' THEN 2
                                WHEN 'SUPERADMIN' THEN 3 ELSE 0 END;
          v_min := CASE p_minimo WHEN 'LECTURA' THEN 1 WHEN 'SOPORTE' THEN 2
                                 WHEN 'SUPERADMIN' THEN 3 ELSE 3 END;
          IF v_orden < v_min THEN
            RAISE EXCEPTION 'acceso denegado';
          END IF;
          RETURN QUERY SELECT v_actor, v_rol;
        END $$;
        """
    )

    op.execute(
        """
        -- Ficha completa de un inquilino. Toda consulta queda registrada con su
        -- motivo: mirar la ficha de un cliente ES un acceso a datos personales.
        CREATE OR REPLACE FUNCTION sa_ficha_cliente(p_tenant uuid, p_motivo text)
        RETURNS TABLE (
          id uuid, ruc text, razon_social text, nombre_comercial text, email text,
          telefono text, estado text, ambiente_sri text, created_at timestamptz,
          plan_nombre text, plan_precio numeric, suscripcion_estado text,
          comprobantes_mes bigint, clientes bigint, productos bigint,
          cert_subject text, cert_vence timestamptz
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_actor uuid; v_rol text;
        BEGIN
          SELECT a.actor, a.rol INTO v_actor, v_rol FROM sa_verificar_rol(p_motivo) a;
          INSERT INTO audit_log (id, actor_user_id, actor_rol, tenant_id, accion, tabla,
                                 registro_id, despues)
          VALUES (gen_random_uuid(), v_actor, v_rol, p_tenant, 'SA_FICHA', 'tenants',
                  p_tenant::text, jsonb_build_object('motivo', p_motivo));

          RETURN QUERY
          SELECT t.id, t.ruc::text, t.razon_social::text, t.nombre_comercial::text,
                 t.email::text, t.telefono::text, t.estado::text, t.ambiente_sri::text,
                 t.created_at,
                 p.nombre::text, p.precio_mensual, s.estado::text,
                 (SELECT count(*) FROM comprobantes c
                   WHERE c.tenant_id = t.id
                     AND c.estado IN ('ENVIADO_SRI','AUTORIZADO')
                     AND date_trunc('month', c.fecha_emision) = date_trunc('month', current_date)),
                 (SELECT count(*) FROM clientes_finales cf WHERE cf.tenant_id = t.id),
                 (SELECT count(*) FROM productos pr WHERE pr.tenant_id = t.id AND pr.activo),
                 ce.subject_cn::text, ce.valido_hasta
          FROM tenants t
          LEFT JOIN suscripciones s ON s.tenant_id = t.id
               AND s.estado IN ('ACTIVA','MOROSA')
          LEFT JOIN planes p ON p.id = s.plan_id
          LEFT JOIN certificados ce ON ce.tenant_id = t.id AND ce.activo
          WHERE t.id = p_tenant;
        END $$;
        """
    )

    op.execute(
        """
        -- Cola global de comprobantes: la vista en vivo del panel interno.
        CREATE OR REPLACE FUNCTION sa_cola_comprobantes(p_limite int DEFAULT 100)
        RETURNS TABLE (
          id uuid, tenant_id uuid, razon_social text, ruc text, tipo text, estado text,
          clave_acceso text, numero text, total numeric, mensajes jsonb,
          intentos int, actualizado timestamptz
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('cola de comprobantes');
          RETURN QUERY
          SELECT c.id, c.tenant_id, t.razon_social::text, t.ruc::text,
                 c.tipo::text, c.estado::text, c.clave_acceso::text,
                 CASE WHEN c.secuencial IS NULL THEN NULL
                      ELSE c.establecimiento || '-' || c.punto_emision || '-' ||
                           lpad(c.secuencial::text, 9, '0') END,
                 c.total, c.sri_mensajes, c.intentos, c.updated_at
          FROM comprobantes c JOIN tenants t ON t.id = c.tenant_id
          ORDER BY c.updated_at DESC
          LIMIT p_limite;
        END $$;
        """
    )

    op.execute(
        """
        -- Métricas del dashboard general, en una sola consulta.
        CREATE OR REPLACE FUNCTION sa_metricas()
        RETURNS TABLE (
          tenants_total bigint, tenants_activos bigint, tenants_morosos bigint,
          comprobantes_mes bigint, autorizados_mes bigint, rechazados_mes bigint,
          ingresos_mes numeric, pagos_pendientes bigint
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('dashboard');
          RETURN QUERY SELECT
            (SELECT count(*) FROM tenants),
            (SELECT count(*) FROM tenants WHERE estado = 'ACTIVO'),
            (SELECT count(*) FROM suscripciones WHERE estado = 'MOROSA'),
            (SELECT count(*) FROM comprobantes
              WHERE date_trunc('month', fecha_emision) = date_trunc('month', current_date)),
            (SELECT count(*) FROM comprobantes
              WHERE estado = 'AUTORIZADO'
                AND date_trunc('month', fecha_emision) = date_trunc('month', current_date)),
            (SELECT count(*) FROM comprobantes
              WHERE estado IN ('RECHAZADO','DEVUELTO')
                AND date_trunc('month', fecha_emision) = date_trunc('month', current_date)),
            (SELECT coalesce(sum(monto), 0) FROM pagos
              WHERE estado = 'CONFIRMADO'
                AND date_trunc('month', pagado_at) = date_trunc('month', current_date)),
            (SELECT count(*) FROM pagos WHERE estado = 'PENDIENTE');
        END $$;
        """
    )

    op.execute(
        """
        -- Listado de inquilinos con su plan y consumo, para la sección Clientes.
        CREATE OR REPLACE FUNCTION sa_clientes()
        RETURNS TABLE (
          id uuid, ruc text, razon_social text, email text, estado text,
          plan_nombre text, cupo int, usados bigint, suscripcion_estado text,
          created_at timestamptz
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('listado de clientes');
          RETURN QUERY
          SELECT t.id, t.ruc::text, t.razon_social::text, t.email::text, t.estado::text,
                 p.nombre::text,
                 coalesce((p.limites->>'cupo')::int, 0),
                 (SELECT count(*) FROM comprobantes c
                   WHERE c.tenant_id = t.id
                     AND c.estado IN ('ENVIADO_SRI','AUTORIZADO')
                     AND date_trunc('month', c.fecha_emision) = date_trunc('month', current_date)),
                 s.estado::text, t.created_at
          FROM tenants t
          LEFT JOIN suscripciones s ON s.tenant_id = t.id AND s.estado IN ('ACTIVA','MOROSA')
          LEFT JOIN planes p ON p.id = s.plan_id
          ORDER BY t.created_at DESC;
        END $$;
        """
    )

    op.execute(
        """
        -- Auditoría: SOLO LECTURA por diseño. No existe función que escriba aquí.
        CREATE OR REPLACE FUNCTION sa_auditoria(
          p_limite int DEFAULT 200, p_tenant uuid DEFAULT NULL, p_accion text DEFAULT NULL
        )
        RETURNS TABLE (
          id uuid, created_at timestamptz, actor_user_id uuid, actor_nombre text,
          actor_rol text, tenant_id uuid, tenant_nombre text, accion text, tabla text,
          registro_id text, antes jsonb, despues jsonb, ip text
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('consulta de auditoría');
          RETURN QUERY
          SELECT a.id, a.created_at, a.actor_user_id, u.nombre::text, a.actor_rol::text,
                 a.tenant_id, t.razon_social::text, a.accion::text, a.tabla::text,
                 a.registro_id::text, a.antes, a.despues, a.ip::text
          FROM audit_log a
          LEFT JOIN users u ON u.id = a.actor_user_id
          LEFT JOIN tenants t ON t.id = a.tenant_id
          WHERE (p_tenant IS NULL OR a.tenant_id = p_tenant)
            AND (p_accion IS NULL OR a.accion = p_accion)
          ORDER BY a.created_at DESC
          LIMIT p_limite;
        END $$;
        """
    )

    op.execute(
        """
        -- Acción auditada sobre un inquilino (suspender, reactivar, dar de baja).
        CREATE OR REPLACE FUNCTION sa_cambiar_estado_tenant(
          p_tenant uuid, p_estado text, p_motivo text, p_ip text, p_ua text
        ) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_actor uuid; v_rol text; v_antes text;
        BEGIN
          SELECT a.actor, a.rol INTO v_actor, v_rol FROM sa_verificar_rol(p_motivo, 'SOPORTE') a;
          SELECT estado::text INTO v_antes FROM tenants WHERE id = p_tenant FOR UPDATE;
          IF v_antes IS NULL THEN RAISE EXCEPTION 'inquilino no existe'; END IF;
          UPDATE tenants SET estado = p_estado::estado_tenant, updated_at = now()
           WHERE id = p_tenant;
          INSERT INTO audit_log (id, actor_user_id, actor_rol, tenant_id, accion, tabla,
                                 registro_id, antes, despues, ip, user_agent)
          VALUES (gen_random_uuid(), v_actor, v_rol, p_tenant, 'SA_ESTADO_TENANT', 'tenants',
                  p_tenant::text, jsonb_build_object('estado', v_antes),
                  jsonb_build_object('estado', p_estado, 'motivo', p_motivo), p_ip, p_ua);
        END $$;
        """
    )

    # El personal interno gestiona las suscripciones de cualquier inquilino.
    # Su contexto no tiene tenant, así que necesita su propia política.
    op.execute(
        """
        CREATE POLICY suscripciones_interno ON suscripciones
          FOR ALL USING (app_is_internal()) WITH CHECK (app_is_internal());
        """
    )

    op.execute(
        """
        -- Alta de inquilino desde el wizard (fase 4.2). Va por función segura
        -- porque el rol de la app NO tiene INSERT sobre tenants: crear un
        -- contribuyente es una operación interna y auditada, nunca una escritura
        -- suelta desde una petición.
        CREATE OR REPLACE FUNCTION sa_crear_tenant(
          p_ruc text, p_razon_social text, p_nombre_comercial text, p_email text,
          p_telefono text, p_direccion text, p_ip text, p_ua text
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_actor uuid; v_rol text; v_id uuid := gen_random_uuid();
        BEGIN
          SELECT a.actor, a.rol INTO v_actor, v_rol
            FROM sa_verificar_rol('alta de cliente', 'SOPORTE') a;
          IF EXISTS (SELECT 1 FROM tenants WHERE ruc = p_ruc) THEN
            RAISE EXCEPTION 'ruc duplicado';
          END IF;
          INSERT INTO tenants (id, ruc, razon_social, nombre_comercial, email, telefono,
                               direccion_matriz, estado, ambiente_sri, obligado_contabilidad,
                               created_at, updated_at)
          VALUES (v_id, p_ruc, p_razon_social, p_nombre_comercial, p_email, p_telefono,
                  p_direccion, 'ACTIVO', 'PRUEBAS', false, now(), now());
          INSERT INTO audit_log (id, actor_user_id, actor_rol, tenant_id, accion, tabla,
                                 registro_id, despues, ip, user_agent)
          VALUES (gen_random_uuid(), v_actor, v_rol, v_id, 'SA_ALTA_CLIENTE', 'tenants',
                  v_id::text,
                  jsonb_build_object('ruc', p_ruc, 'razon_social', p_razon_social),
                  p_ip, p_ua);
          RETURN v_id;
        END $$;
        """
    )

    op.execute("GRANT INSERT ON tenants TO factuchat_security;")

    op.execute(
        """
        -- Consulta mínima de un inquilino para operaciones internas que YA se
        -- auditan por su cuenta (p. ej. iniciar una impersonación). Sin esto el
        -- personal interno no puede ni leer la razón social: RLS solo deja ver
        -- el propio tenant, y el personal interno no tiene ninguno.
        CREATE OR REPLACE FUNCTION sa_tenant_basico(p_tenant uuid)
        RETURNS TABLE (id uuid, ruc text, razon_social text, estado text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('consulta interna');
          RETURN QUERY
          SELECT t.id, t.ruc::text, t.razon_social::text, t.estado::text
          FROM tenants t WHERE t.id = p_tenant;
        END $$;
        """
    )

    op.execute(
        """
        -- Usos de un código promo, con la columna Retenido de la maqueta.
        CREATE OR REPLACE FUNCTION sa_promo_usos(p_promo uuid)
        RETURNS TABLE (
          id uuid, usado_at timestamptz, cliente text, ruc text,
          precio_lista numeric, precio_cobrado numeric, descuento numeric,
          retenido numeric, meses int
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('usos de código promocional');
          RETURN QUERY
          SELECT pu.id, pu.usado_at, t.razon_social::text, t.ruc::text,
                 pu.precio_lista, pu.precio_cobrado, pu.monto_descuento,
                 pu.retenido, pu.meses_aplicados
          FROM promo_uses pu JOIN tenants t ON t.id = pu.tenant_id
          WHERE pu.promo_code_id = p_promo
          ORDER BY pu.usado_at DESC;
        END $$;
        """
    )

    op.execute(
        """
        -- De dónde vienen las altas: qué código usó cada inquilino.
        CREATE OR REPLACE FUNCTION sa_marketing_origenes()
        RETURNS TABLE (origen text, altas bigint, retenido numeric)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('origen de las altas');
          RETURN QUERY
          SELECT pc.codigo::text, count(pu.id), coalesce(sum(pu.retenido), 0)
          FROM promo_codes pc JOIN promo_uses pu ON pu.promo_code_id = pc.id
          GROUP BY pc.codigo
          UNION ALL
          SELECT 'Sin código', count(*), 0::numeric
          FROM tenants t
          WHERE NOT EXISTS (SELECT 1 FROM promo_uses pu WHERE pu.tenant_id = t.id)
          ORDER BY 2 DESC;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        DECLARE f text;
        BEGIN
          FOREACH f IN ARRAY ARRAY[
            'sa_verificar_rol(text,text)',
            'sa_crear_tenant(text,text,text,text,text,text,text,text)',
            'sa_tenant_basico(uuid)',
            'sa_promo_usos(uuid)',
            'sa_marketing_origenes()',
            'sa_ficha_cliente(uuid,text)',
            'sa_cola_comprobantes(int)',
            'sa_metricas()',
            'sa_clientes()',
            'sa_auditoria(int,uuid,text)',
            'sa_cambiar_estado_tenant(uuid,text,text,text,text)'
          ] LOOP
            EXECUTE format('ALTER FUNCTION %s OWNER TO factuchat_security', f);
            EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', f);
            EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO factuchat_app', f);
          END LOOP;
        END $$;
        """
    )

    # Permisos que las funciones necesitan sobre las tablas que tocan
    op.execute(
        """
        GRANT SELECT, UPDATE ON tenants TO factuchat_security;
        GRANT SELECT ON comprobantes, clientes_finales, productos, suscripciones,
                        planes, certificados, pagos TO factuchat_security;
        GRANT SELECT ON audit_log TO factuchat_security;
        GRANT SELECT ON promo_codes, promo_uses TO factuchat_security;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS sa_marketing_origenes();
        DROP FUNCTION IF EXISTS sa_promo_usos(uuid);
        DROP FUNCTION IF EXISTS sa_tenant_basico(uuid);
        DROP FUNCTION IF EXISTS sa_crear_tenant(text,text,text,text,text,text,text,text);
        DROP POLICY IF EXISTS suscripciones_interno ON suscripciones;
        DROP FUNCTION IF EXISTS sa_cambiar_estado_tenant(uuid,text,text,text,text);
        DROP FUNCTION IF EXISTS sa_auditoria(int,uuid,text);
        DROP FUNCTION IF EXISTS sa_clientes();
        DROP FUNCTION IF EXISTS sa_metricas();
        DROP FUNCTION IF EXISTS sa_cola_comprobantes(int);
        DROP FUNCTION IF EXISTS sa_ficha_cliente(uuid,text);
        DROP FUNCTION IF EXISTS sa_verificar_rol(text,text);
        """
    )
    op.drop_column("promo_codes", "meses")
    op.drop_column("promo_codes", "planes")
    op.drop_column("promo_uses", "meses_aplicados")
    op.drop_column("promo_uses", "precio_cobrado")
    op.drop_column("promo_uses", "precio_lista")
    op.drop_index(op.f("ix_impersonaciones_tenant_id"), table_name="impersonaciones")
    op.drop_index(op.f("ix_impersonaciones_actor_user_id"), table_name="impersonaciones")
    op.drop_table("impersonaciones")
