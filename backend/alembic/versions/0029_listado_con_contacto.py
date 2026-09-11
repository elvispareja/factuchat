"""El listado de clientes trae también nombre comercial y teléfono.

«Editar» desde el listado abría el formulario sin esos dos campos: el listado
no los traía, y como el PUT sustituye los cuatro, abrirlos en blanco era
borrarlos al guardar. Se pedían a la ficha, que exige motivo, así que el
operador veía primero un modal con solo el motivo y los datos después.

Ahora el listado los trae y el formulario abre completo, con la misma
estructura que el alta (datos y confirmación). El motivo sigue siendo
obligatorio para guardar y queda en auditoría con el antes y el después, como
hasta ahora. La exportación a CSV comparte el cuerpo del listado, así que se
redefine con él: no saca las columnas nuevas, solo las ignora.

Revision ID: 0029
Revises: 0028
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _definir(columnas_extra: str, select_extra: str) -> None:
    """sa_clientes y sa_exportar_clientes con el cuerpo de 0011 más lo que se pida.
    CREATE OR REPLACE no puede cambiar el tipo de retorno: se borran y se crean."""
    columnas = f"""
          id uuid, ruc text, razon_social text, email text, estado text,
          estado_cartera text, plan_nombre text, cupo int, usados bigint,
          suscripcion_estado text, ultimo_comp timestamptz, created_at timestamptz
          {columnas_extra}
    """
    cuerpo = f"""
          RETURN QUERY
          SELECT t.id, t.ruc::text, t.razon_social::text, t.email::text, t.estado::text,
          CASE
            WHEN t.estado = 'BAJA'       THEN 'CANCELADO'
            WHEN t.estado = 'SUSPENDIDO' THEN 'SUSPENDIDO'
            WHEN s.estado = 'MOROSA'     THEN 'MOROSO'
            WHEN s.estado = 'SUSPENDIDA' THEN 'SUSPENDIDO'
            WHEN s.estado = 'CANCELADA'  THEN 'CANCELADO'
            WHEN s.estado = 'ACTIVA'     THEN 'ACTIVO'
            ELSE 'EN_PRUEBA'
          END::text,
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
                 {select_extra}
          FROM tenants t
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
    op.execute("DROP FUNCTION IF EXISTS sa_clientes();")
    op.execute("DROP FUNCTION IF EXISTS sa_exportar_clientes(text, text);")
    op.execute(
        f"""
        CREATE FUNCTION sa_clientes()
        RETURNS TABLE ({columnas})
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('listado de clientes');
          {cuerpo}
        END $$;
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION sa_exportar_clientes(p_ip text, p_ua text)
        RETURNS TABLE ({columnas})
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_actor uuid; v_rol text;
        BEGIN
          SELECT a.actor, a.rol INTO v_actor, v_rol
            FROM sa_verificar_rol('exportar listado de clientes') a;
          INSERT INTO audit_log (id, actor_user_id, actor_rol, accion, tabla, despues, ip)
          VALUES (gen_random_uuid(), v_actor, v_rol, 'SA_EXPORTAR_CLIENTES', 'tenants',
                  jsonb_build_object('user_agent', p_ua), p_ip);
          {cuerpo}
        END $$;
        """
    )
    for firma in ("sa_clientes()", "sa_exportar_clientes(text, text)"):
        op.execute(f"ALTER FUNCTION {firma} OWNER TO factuchat_security;")
        op.execute(f"REVOKE ALL ON FUNCTION {firma} FROM PUBLIC;")
        op.execute(f"GRANT EXECUTE ON FUNCTION {firma} TO factuchat_app;")


def upgrade() -> None:
    _definir(
        ", nombre_comercial text, telefono text", ", t.nombre_comercial::text, t.telefono::text"
    )


def downgrade() -> None:
    _definir("", "")
