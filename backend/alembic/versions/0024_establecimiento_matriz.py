"""Todo cliente nace con su establecimiento matriz (001).

El SRI numera los comprobantes por establecimiento y punto de emisión, así que
sin una fila en `establecimientos` no se puede emitir NADA: `asignar_secuencial`
no encuentra dónde numerar y la factura muere antes de empezar. Hasta ahora
nada creaba esa fila —ni el alta desde el panel interno ni ningún otro sitio—,
o sea que cada cliente nuevo quedaba sin poder facturar hasta que alguien se
diera cuenta y la insertara a mano.

Todo contribuyente tiene al menos el establecimiento matriz, y su código es el
001 por norma, así que crearlo en el alta no supone ninguna decisión de negocio
que el operador deba tomar.

Revision ID: 0024
Revises: 0023
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Mismo cuerpo que la 0012, con el INSERT del establecimiento añadido antes
    # de la auditoría. Se reescribe entera porque PL/pgSQL no admite parches.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_crear_tenant(
          p_ruc text, p_razon_social text, p_nombre_comercial text, p_email text,
          p_telefono text, p_direccion text, p_ip text, p_ua text,
          p_origen text DEFAULT 'Orgánico'
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
          v_id uuid := gen_random_uuid();
          v_actor uuid;
          v_rol text;
        BEGIN
          SELECT actor_user_id, actor_rol INTO v_actor, v_rol
          FROM sa_verificar_rol('alta de cliente');
          IF EXISTS (SELECT 1 FROM tenants WHERE ruc = p_ruc) THEN
            RAISE EXCEPTION 'ruc duplicado';
          END IF;
          INSERT INTO tenants (id, ruc, razon_social, nombre_comercial, email, telefono,
                               direccion_matriz, estado, ambiente_sri, obligado_contabilidad,
                               origen_alta, created_at, updated_at)
          VALUES (v_id, p_ruc, p_razon_social, p_nombre_comercial, p_email, p_telefono,
                  p_direccion, 'ACTIVO', 'PRUEBAS', false,
                  coalesce(nullif(p_origen, ''), 'Orgánico'), now(), now());
          -- Sin esto el cliente no puede emitir ni su primera factura.
          INSERT INTO establecimientos (id, tenant_id, codigo, nombre, direccion,
                                        activo, created_at, updated_at)
          VALUES (gen_random_uuid(), v_id, '001', 'Matriz', p_direccion,
                  true, now(), now());
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

    # Los que se dieron de alta antes de esto siguen sin poder facturar, así que
    # se les crea la matriz aquí. ON CONFLICT por si alguno ya la tenía a mano.
    op.execute(
        """
        INSERT INTO establecimientos (id, tenant_id, codigo, nombre, direccion,
                                      activo, created_at, updated_at)
        SELECT gen_random_uuid(), t.id, '001', 'Matriz', t.direccion_matriz,
               true, now(), now()
        FROM tenants t
        ON CONFLICT (tenant_id, codigo) DO NOTHING;
        """
    )


def downgrade() -> None:
    # Vuelve a la versión de la 0012, sin el establecimiento. Las filas ya
    # creadas NO se borran: quitarlas dejaría sin numerar comprobantes que
    # quizá ya se emitieron, y una fila de más no rompe nada.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_crear_tenant(
          p_ruc text, p_razon_social text, p_nombre_comercial text, p_email text,
          p_telefono text, p_direccion text, p_ip text, p_ua text,
          p_origen text DEFAULT 'Orgánico'
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
          v_id uuid := gen_random_uuid();
          v_actor uuid;
          v_rol text;
        BEGIN
          SELECT actor_user_id, actor_rol INTO v_actor, v_rol
          FROM sa_verificar_rol('alta de cliente');
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
