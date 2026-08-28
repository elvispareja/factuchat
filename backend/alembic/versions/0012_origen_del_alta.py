"""El «Origen del alta» del asistente de nuevo cliente.

La maqueta pide el origen —Campaña Meta, Referido, Orgánico, TikTok— y la
sección Marketing agrupa las altas por él. En el código, el chip se pintaba, se
podía pulsar y se enseñaba en el resumen… y luego no viajaba a ninguna parte:
ni el cuerpo del alta lo mandaba ni `tenants` tenía dónde guardarlo. Un control
que no hace nada es peor que no tenerlo, porque quien lo pulsa cree que ha
elegido algo.

Esta migración le da columna, y `sa_crear_tenant` pasa a recibirlo.
`sa_marketing_origenes` deja de contar «Sin código» a bulto y reparte esas altas
por su origen real, que es lo que la maqueta enseña.

Revision ID: 0012
Revises: 0011
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Los cuatro de la maqueta. Se guarda el texto y no un enum de base de datos
# porque marketing añade y quita canales a menudo, y cada cambio de enum es una
# migración con bloqueo de tabla.
ORIGENES = ("Campaña Meta", "Referido", "Orgánico", "TikTok")


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("origen_alta", sa.String(40), nullable=False, server_default="Orgánico"),
    )

    # sa_crear_tenant gana un parámetro. Es el MISMO cuerpo de la 0005 —rol,
    # RUC duplicado, ambiente de pruebas, auditoría— con el origen añadido; no
    # se reescribe nada más, para no cambiar por descuido lo que ya funciona.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_crear_tenant(
          p_ruc text, p_razon_social text, p_nombre_comercial text, p_email text,
          p_telefono text, p_direccion text, p_ip text, p_ua text,
          p_origen text DEFAULT 'Orgánico'
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
                               origen_alta, created_at, updated_at)
          VALUES (v_id, p_ruc, p_razon_social, p_nombre_comercial, p_email, p_telefono,
                  p_direccion, 'ACTIVO', 'PRUEBAS', false,
                  coalesce(nullif(p_origen, ''), 'Orgánico'), now(), now());
          INSERT INTO audit_log (id, actor_user_id, actor_rol, tenant_id, accion, tabla,
                                 registro_id, despues, ip, user_agent)
          VALUES (gen_random_uuid(), v_actor, v_rol, v_id, 'SA_ALTA_CLIENTE', 'tenants',
                  v_id::text,
                  jsonb_build_object('ruc', p_ruc, 'razon_social', p_razon_social,
                                     'origen', coalesce(nullif(p_origen, ''), 'Orgánico')),
                  p_ip, p_ua);
          RETURN v_id;
        END $$;
        """
    )

    # Marketing: las altas sin código promocional ya no caen todas en un cajón
    # llamado «Sin código»; se reparten por el canal que las trajo.
    op.execute(
        """
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
          SELECT t.origen_alta::text, count(*), 0::numeric
          FROM tenants t
          WHERE NOT EXISTS (SELECT 1 FROM promo_uses pu WHERE pu.tenant_id = t.id)
          GROUP BY t.origen_alta
          ORDER BY 2 DESC;
        END $$;
        """
    )

    # La versión de ocho argumentos se retira: dejarla haría ambigua cualquier
    # llamada con ocho parámetros (Postgres no sabría cuál elegir).
    op.execute(
        "DROP FUNCTION IF EXISTS sa_crear_tenant(text, text, text, text, text, text, text, text);"
    )

    for firma in (
        "sa_crear_tenant(text, text, text, text, text, text, text, text, text)",
        "sa_marketing_origenes()",
    ):
        op.execute(f"ALTER FUNCTION {firma} OWNER TO factuchat_security;")
        op.execute(f"REVOKE ALL ON FUNCTION {firma} FROM PUBLIC;")
        op.execute(f"GRANT EXECUTE ON FUNCTION {firma} TO factuchat_app;")


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "sa_crear_tenant(text, text, text, text, text, text, text, text, text);"
    )
    op.execute(
        """
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
    op.execute("ALTER FUNCTION sa_marketing_origenes() OWNER TO factuchat_security;")
    op.drop_column("tenants", "origen_alta")
