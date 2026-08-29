"""Edición de los datos de un cliente desde el panel interno.

La ficha del cliente (0005) solo permitía mirar y cambiar de estado o
impersonar. No había forma de corregir un dato mal cargado en el alta —razón
social, nombre comercial, correo o teléfono— sin tocar la base directamente.
`sa_editar_cliente` sigue el mismo patrón que `sa_cambiar_estado_tenant`:
exige rol SOPORTE o superior, motivo, y deja antes/después en `audit_log`.

Revision ID: 0019
Revises: 0018
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_editar_cliente(
          p_tenant uuid, p_razon_social text, p_nombre_comercial text,
          p_email text, p_telefono text, p_motivo text, p_ip text, p_ua text
        ) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_actor uuid; v_rol text; v_antes jsonb;
        BEGIN
          SELECT a.actor, a.rol INTO v_actor, v_rol
            FROM sa_verificar_rol(p_motivo, 'SOPORTE') a;

          SELECT jsonb_build_object(
                   'razon_social', razon_social, 'nombre_comercial', nombre_comercial,
                   'email', email, 'telefono', telefono)
            INTO v_antes
            FROM tenants WHERE id = p_tenant FOR UPDATE;
          IF v_antes IS NULL THEN RAISE EXCEPTION 'inquilino no existe'; END IF;

          UPDATE tenants
             SET razon_social = p_razon_social,
                 nombre_comercial = p_nombre_comercial,
                 email = p_email,
                 telefono = p_telefono,
                 updated_at = now()
           WHERE id = p_tenant;

          INSERT INTO audit_log (id, actor_user_id, actor_rol, tenant_id, accion, tabla,
                                 registro_id, antes, despues, ip, user_agent)
          VALUES (gen_random_uuid(), v_actor, v_rol, p_tenant, 'SA_EDITAR_CLIENTE', 'tenants',
                  p_tenant::text, v_antes,
                  jsonb_build_object('razon_social', p_razon_social,
                                      'nombre_comercial', p_nombre_comercial,
                                      'email', p_email, 'telefono', p_telefono,
                                      'motivo', p_motivo),
                  p_ip, p_ua);
        END $$;
        """
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "sa_editar_cliente(uuid,text,text,text,text,text,text,text) TO factuchat_app;"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "sa_editar_cliente(uuid,text,text,text,text,text,text,text);"
    )
