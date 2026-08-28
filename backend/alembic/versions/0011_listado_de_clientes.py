"""El listado de Clientes, tal como lo define la maqueta.

`Superadmin.dc.html` (bloque `esClientes`) pide dos cosas que `sa_clientes()`
no devolvía:

  · **Estado de cartera**. La maqueta filtra por ACTIVO, EN_PRUEBA, SUSPENDIDO,
    MOROSO y CANCELADO. En la base esos cinco valores no viven en un sitio:
    salen de cruzar el estado del inquilino (ACTIVO / SUSPENDIDO / BAJA) con el
    de su suscripción (ACTIVA / MOROSA / SUSPENDIDA / CANCELADA). La regla se
    escribe aquí, una sola vez, para que la columna, los filtros y cualquier
    informe futuro cuenten lo mismo. Si se derivara en el navegador, cada
    pantalla acabaría con su propia versión de «quién está moroso».

  · **Último comprobante**. La última columna de la tabla.

De paso se corrige un defecto del listado anterior: el LEFT JOIN solo miraba
suscripciones ACTIVA o MOROSA, así que a un cliente cancelado se le perdía el
plan y aparecía con un guion. Ahora se toma su última suscripción sea cual sea
su estado, que es lo que hay que ver para saber de qué plan se fue.

Se añade también `sa_exportar_clientes()`: bajarse la cartera entera en un CSV
es un acceso masivo a datos de contribuyentes, así que deja rastro en
audit_log igual que abrir una ficha.

Revision ID: 0011
Revises: 0010
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# El estado del inquilino manda sobre el de su suscripción: es el que de verdad
# le impide emitir. Un inquilino dado de baja está CANCELADO aunque su última
# suscripción figure como activa por un cierre a medias.
ESTADO_CARTERA = """
          CASE
            WHEN t.estado = 'BAJA'       THEN 'CANCELADO'
            WHEN t.estado = 'SUSPENDIDO' THEN 'SUSPENDIDO'
            WHEN s.estado = 'MOROSA'     THEN 'MOROSO'
            WHEN s.estado = 'SUSPENDIDA' THEN 'SUSPENDIDO'
            WHEN s.estado = 'CANCELADA'  THEN 'CANCELADO'
            WHEN s.estado = 'ACTIVA'     THEN 'ACTIVO'
            ELSE 'EN_PRUEBA'
          END::text
"""

CUERPO_LISTADO = f"""
          RETURN QUERY
          SELECT t.id, t.ruc::text, t.razon_social::text, t.email::text, t.estado::text,
                 {ESTADO_CARTERA},
                 p.nombre::text,
                 coalesce((p.limites->>'cupo')::int, 0),
                 (SELECT count(*) FROM comprobantes c
                   WHERE c.tenant_id = t.id
                     AND c.estado IN ('ENVIADO_SRI','AUTORIZADO')
                     AND date_trunc('month', c.fecha_emision) = date_trunc('month', current_date)),
                 s.estado::text,
                 (SELECT max(c.created_at) FROM comprobantes c
                   WHERE c.tenant_id = t.id
                     AND c.estado IN ('ENVIADO_SRI','AUTORIZADO')),
                 t.created_at
          FROM tenants t
          -- La última suscripción, esté como esté: a un cancelado hay que
          -- poder verle el plan del que se fue.
          LEFT JOIN LATERAL (
            SELECT su.estado, su.plan_id
              FROM suscripciones su
             WHERE su.tenant_id = t.id
             ORDER BY su.inicia DESC, su.created_at DESC
             LIMIT 1
          ) s ON true
          LEFT JOIN planes p ON p.id = s.plan_id
          ORDER BY t.created_at DESC;
"""

COLUMNAS = """
          id uuid, ruc text, razon_social text, email text, estado text,
          estado_cartera text, plan_nombre text, cupo int, usados bigint,
          suscripcion_estado text, ultimo_comp timestamptz, created_at timestamptz
"""


def upgrade() -> None:
    # CREATE OR REPLACE no puede cambiar el tipo de retorno de una función
    op.execute("DROP FUNCTION IF EXISTS sa_clientes();")
    op.execute(
        f"""
        CREATE FUNCTION sa_clientes()
        RETURNS TABLE ({COLUMNAS})
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('listado de clientes');
          {CUERPO_LISTADO}
        END $$;
        """
    )

    op.execute(
        f"""
        -- Mismo listado, pero dejando constancia: exportar la cartera entera es
        -- un acceso masivo a datos personales (LOPDP art. 5).
        CREATE FUNCTION sa_exportar_clientes(p_ip text, p_ua text)
        RETURNS TABLE ({COLUMNAS})
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_actor uuid; v_rol text;
        BEGIN
          SELECT a.actor, a.rol INTO v_actor, v_rol
            FROM sa_verificar_rol('exportar listado de clientes') a;
          INSERT INTO audit_log (id, actor_user_id, actor_rol, accion, tabla, despues, ip)
          VALUES (gen_random_uuid(), v_actor, v_rol, 'SA_EXPORTAR_CLIENTES', 'tenants',
                  jsonb_build_object('user_agent', p_ua), p_ip);
          {CUERPO_LISTADO}
        END $$;
        """
    )

    for firma in ("sa_clientes()", "sa_exportar_clientes(text, text)"):
        op.execute(f"ALTER FUNCTION {firma} OWNER TO factuchat_security;")
        op.execute(f"REVOKE ALL ON FUNCTION {firma} FROM PUBLIC;")
        op.execute(f"GRANT EXECUTE ON FUNCTION {firma} TO factuchat_app;")

    op.execute("GRANT INSERT ON audit_log TO factuchat_security;")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS sa_exportar_clientes(text, text);")
    op.execute("DROP FUNCTION IF EXISTS sa_clientes();")
    op.execute(
        """
        CREATE FUNCTION sa_clientes()
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
    op.execute("ALTER FUNCTION sa_clientes() OWNER TO factuchat_security;")
    op.execute("REVOKE ALL ON FUNCTION sa_clientes() FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION sa_clientes() TO factuchat_app;")
