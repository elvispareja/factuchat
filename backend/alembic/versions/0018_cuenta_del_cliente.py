"""La cuenta de acceso del cliente se crea por función segura.

El alta intentaba insertar el usuario del cliente con el rol de la aplicación y
chocaba —correctamente— contra la política RLS de `users`: el personal interno
no tiene contexto de inquilino, así que su INSERT no cumple
`tenant_id = app_tenant()`. Que la política lo frene es buena señal; lo que
faltaba era la puerta legítima, igual que existe `sa_crear_tenant` para la tabla
de inquilinos.

`sa_crear_usuario_cliente` la abre: comprueba el rol de verdad en la base, deja
constancia en `audit_log` y devuelve el id. No recibe contraseña porque ya no
existen: el cliente entra con su correo y un código de seis dígitos.

Revision ID: 0018
Revises: 0017
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_crear_usuario_cliente(
          p_tenant uuid, p_email text, p_nombre text, p_ip text, p_ua text
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_actor uuid; v_rol text; v_id uuid := gen_random_uuid();
        BEGIN
          SELECT a.actor, a.rol INTO v_actor, v_rol
            FROM sa_verificar_rol('alta de cuenta de cliente', 'SOPORTE') a;

          IF EXISTS (SELECT 1 FROM users WHERE lower(email) = lower(p_email)) THEN
            RAISE EXCEPTION 'correo duplicado';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM tenants WHERE id = p_tenant) THEN
            RAISE EXCEPTION 'inquilino inexistente';
          END IF;

          INSERT INTO users (id, tenant_id, email, nombre, rol, is_active,
                             totp_enabled, failed_attempts, lockout_count,
                             created_at, updated_at)
          VALUES (v_id, p_tenant, p_email, p_nombre, 'CLIENTE', true,
                  false, 0, 0, now(), now());

          INSERT INTO audit_log (id, actor_user_id, actor_rol, tenant_id, accion, tabla,
                                 registro_id, despues, ip, user_agent)
          VALUES (gen_random_uuid(), v_actor, v_rol, p_tenant, 'SA_ALTA_CUENTA', 'users',
                  v_id::text, jsonb_build_object('email', p_email, 'rol', 'CLIENTE'),
                  p_ip, left(p_ua, 400));
          RETURN v_id;
        END $$;
        """
    )
    op.execute("ALTER FUNCTION sa_crear_usuario_cliente(uuid, text, text, text, text) "
               "OWNER TO factuchat_security;")
    op.execute("REVOKE ALL ON FUNCTION sa_crear_usuario_cliente(uuid, text, text, text, text) "
               "FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION sa_crear_usuario_cliente(uuid, text, text, text, text) "
               "TO factuchat_app;")
    op.execute("GRANT INSERT ON users TO factuchat_security;")


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS sa_crear_usuario_cliente(uuid, text, text, text, text);"
    )
