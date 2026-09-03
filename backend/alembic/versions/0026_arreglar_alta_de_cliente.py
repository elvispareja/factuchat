"""Dar de alta un cliente vuelve a funcionar.

La 0024 reescribió `sa_crear_tenant` para que además creara el establecimiento
matriz, y al copiarla se equivocó en DOS cosas que la dejaron inservible:

1. `SELECT actor_user_id, actor_rol INTO ...` — `sa_verificar_rol` devuelve
   `TABLE(actor uuid, rol text)`, así que esos nombres no existen y la función
   revienta con «no existe la columna actor_user_id» ANTES de crear nada. Toda
   alta de cliente desde el panel de superadmin falla, y con ella 20 tests.
   Las demás funciones lo llaman bien: `SELECT a.actor, a.rol FROM ... a`.

2. Se perdió el `'SOPORTE'` que la 0012 pasaba como rol mínimo, así que al
   arreglar lo anterior el alta quedaría abierta al mínimo por omisión
   ('LECTURA'): quien solo puede mirar podría crear clientes. Se restituye.

Va en una migración nueva y no como parche de la 0024 porque esa ya está
aplicada: una migración corregida a posteriori no se vuelve a ejecutar y las
bases que ya pasaron por ella se quedarían rotas.

El establecimiento matriz, que era el motivo de la 0024, se conserva: sin él el
cliente no puede emitir ni su primera factura.

Revision ID: 0026
Revises: 0025
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


# Idéntica a la de la 0024 salvo las dos líneas de la verificación de rol.
_CREAR_TENANT = """
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

# La de la 0024, con su fallo, para poder volver atrás sin cambiar de conducta.
_CREAR_TENANT_0024 = _CREAR_TENANT.replace(
    "SELECT a.actor, a.rol INTO v_actor, v_rol\n"
    "    FROM sa_verificar_rol('alta de cliente', 'SOPORTE') a;",
    "SELECT actor_user_id, actor_rol INTO v_actor, v_rol\n  FROM sa_verificar_rol('alta de cliente');",
)


def upgrade() -> None:
    # Y el permiso que la 0024 tampoco puso. `sa_crear_tenant` es SECURITY
    # DEFINER y corre como `factuchat_security`, que tenía INSERT en `tenants` y
    # en `audit_log` pero no en `establecimientos`: la fila nueva que introdujo
    # la 0024 moría con «permiso denegado a la tabla establecimientos». RLS no
    # estorba aquí —ese rol tiene BYPASSRLS—, era solo el GRANT.
    op.execute("GRANT INSERT ON establecimientos TO factuchat_security;")
    op.execute(_CREAR_TENANT)


def downgrade() -> None:
    op.execute(_CREAR_TENANT_0024)
    op.execute("REVOKE INSERT ON establecimientos FROM factuchat_security;")
