"""RLS por tenant, funciones seguras de auth/superadmin y bitácora inmutable.

Fase 1.4/1.5:
- RLS con FORCE en toda tabla de negocio: sin contexto de tenant no hay filas.
- El rol de la app (factuchat_app) NO tiene BYPASSRLS: no puede saltarse RLS.
- Auth y superadmin operan vía funciones SECURITY DEFINER (dueño factuchat_security)
  que registran en audit_log.
- audit_log inmutable: sin políticas ni permisos de UPDATE/DELETE + trigger de bloqueo.

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tablas de negocio con aislamiento estricto por tenant
STRICT_TENANT_TABLES = [
    "suscripciones",
    "establecimientos",
    "secuenciales",
    "clientes_finales",
    "productos",
    "comprobantes",
    "pagos",
    "recargas",
    "whatsapp_msgs",
    "buzon_correos",
]

# Tablas solo para personal interno (GUC app.is_internal tras verificación de rol)
INTERNAL_ONLY_TABLES = ["promo_codes", "cost_rates", "notas_internas"]

ALL_RLS_TABLES = STRICT_TENANT_TABLES + INTERNAL_ONLY_TABLES + [
    "tenants",
    "users",
    "user_sessions",
    "planes",
    "promo_uses",
    "audit_log",
]


def upgrade() -> None:
    # ---------------------------------------------------------------- roles
    # Los roles se crean en el init del cluster; esto es defensa por si faltan.
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'factuchat_app') THEN
            CREATE ROLE factuchat_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
          END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'factuchat_security') THEN
            CREATE ROLE factuchat_security NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
          END IF;
        END $$;
        GRANT USAGE ON SCHEMA public TO factuchat_app;
        GRANT USAGE ON SCHEMA public TO factuchat_security;
        """
    )

    # ------------------------------------------------- helpers de contexto
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_tenant() RETURNS uuid
        LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

        CREATE OR REPLACE FUNCTION app_user() RETURNS uuid
        LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;

        CREATE OR REPLACE FUNCTION app_is_internal() RETURNS boolean
        LANGUAGE sql STABLE AS
        $$ SELECT current_setting('app.is_internal', true) = 'true' $$;
        """
    )

    # ------------------------------------------------------ RLS + políticas
    for table in ALL_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

    for table in STRICT_TENANT_TABLES:
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
              FOR ALL
              USING (tenant_id = app_tenant())
              WITH CHECK (tenant_id = app_tenant());
            """
        )

    for table in INTERNAL_ONLY_TABLES:
        op.execute(
            f"""
            CREATE POLICY {table}_interno ON {table}
              FOR ALL
              USING (app_is_internal())
              WITH CHECK (app_is_internal());
            """
        )

    op.execute(
        """
        -- El tenant solo se ve/edita a sí mismo; el panel interno usa funciones sa_*
        CREATE POLICY tenants_propio_select ON tenants
          FOR SELECT USING (id = app_tenant());
        CREATE POLICY tenants_propio_update ON tenants
          FOR UPDATE USING (id = app_tenant()) WITH CHECK (id = app_tenant());

        -- users/user_sessions: filas del propio tenant, o internas (tenant NULL)
        -- para personal verificado. El login pasa por funciones auth_* (SECURITY DEFINER).
        CREATE POLICY users_acceso ON users
          FOR ALL
          USING (tenant_id = app_tenant() OR (tenant_id IS NULL AND app_is_internal()))
          WITH CHECK (tenant_id = app_tenant() OR (tenant_id IS NULL AND app_is_internal()));

        CREATE POLICY user_sessions_acceso ON user_sessions
          FOR ALL
          USING (tenant_id = app_tenant() OR (tenant_id IS NULL AND app_is_internal()))
          WITH CHECK (tenant_id = app_tenant() OR (tenant_id IS NULL AND app_is_internal()));

        -- Catálogo de planes: visible para cualquier sesión autenticada; escribe solo interno
        CREATE POLICY planes_lectura ON planes FOR SELECT USING (true);
        CREATE POLICY planes_escritura_ins ON planes FOR INSERT WITH CHECK (app_is_internal());
        CREATE POLICY planes_escritura_upd ON planes FOR UPDATE
          USING (app_is_internal()) WITH CHECK (app_is_internal());
        CREATE POLICY planes_escritura_del ON planes FOR DELETE USING (app_is_internal());

        -- promo_uses: el tenant ve sus usos; escribe solo interno
        CREATE POLICY promo_uses_select ON promo_uses
          FOR SELECT USING (tenant_id = app_tenant() OR app_is_internal());
        CREATE POLICY promo_uses_ins ON promo_uses FOR INSERT WITH CHECK (app_is_internal());
        CREATE POLICY promo_uses_upd ON promo_uses FOR UPDATE
          USING (app_is_internal()) WITH CHECK (app_is_internal());

        -- audit_log: cualquiera inserta (misma transacción de la escritura),
        -- solo interno lee, NADIE actualiza ni borra (sin política = denegado)
        CREATE POLICY audit_log_insert ON audit_log FOR INSERT WITH CHECK (true);
        CREATE POLICY audit_log_select ON audit_log FOR SELECT USING (app_is_internal());
        """
    )

    # --------------------------------- inmutabilidad extra de audit_log (A09)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_inmutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit_log es inmutable';
        END $$;

        CREATE TRIGGER trg_audit_log_inmutable
          BEFORE UPDATE OR DELETE ON audit_log
          FOR EACH ROW EXECUTE FUNCTION audit_log_inmutable();
        """
    )

    # ----------------------------------------------------------- permisos
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE ON
          suscripciones, establecimientos, secuenciales, clientes_finales, productos,
          comprobantes, pagos, recargas, whatsapp_msgs, buzon_correos,
          promo_codes, cost_rates, notas_internas, planes, promo_uses,
          users, user_sessions
        TO factuchat_app;
        GRANT SELECT, UPDATE ON tenants TO factuchat_app;
        GRANT SELECT, INSERT ON audit_log TO factuchat_app;

        -- El dueño de las funciones seguras: permisos mínimos necesarios
        GRANT SELECT, UPDATE ON users TO factuchat_security;
        GRANT SELECT, INSERT, UPDATE ON user_sessions TO factuchat_security;
        GRANT SELECT ON tenants TO factuchat_security;
        GRANT INSERT ON audit_log TO factuchat_security;
        """
    )

    # ------------------------------------- funciones seguras de autenticación
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_get_user_for_login(p_email text)
        RETURNS TABLE (
          id uuid, tenant_id uuid, email text, nombre text, rol text, password_hash text,
          is_active boolean, totp_enabled boolean, failed_attempts int,
          locked_until timestamptz, tenant_estado text
        )
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT u.id, u.tenant_id, u.email::text, u.nombre::text, u.rol::text,
                 u.password_hash::text, u.is_active, u.totp_enabled, u.failed_attempts,
                 u.locked_until, t.estado::text
          FROM users u LEFT JOIN tenants t ON t.id = u.tenant_id
          WHERE lower(u.email) = lower(p_email)
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_login_failed(
          p_user_id uuid, p_ip text, p_ua text, p_max int
        ) RETURNS timestamptz
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
          v_user users%ROWTYPE;
          v_locked timestamptz;
        BEGIN
          SELECT * INTO v_user FROM users WHERE id = p_user_id FOR UPDATE;
          IF NOT FOUND THEN RETURN NULL; END IF;

          IF v_user.failed_attempts + 1 >= p_max THEN
            -- Bloqueo progresivo: 15 min, 30, 60... hasta 24 h
            v_locked := now() + least(
              interval '24 hours',
              interval '15 minutes' * power(2, v_user.lockout_count)
            );
            UPDATE users SET failed_attempts = 0, lockout_count = lockout_count + 1,
                   locked_until = v_locked, updated_at = now()
             WHERE id = p_user_id;
          ELSE
            UPDATE users SET failed_attempts = failed_attempts + 1, updated_at = now()
             WHERE id = p_user_id;
            v_locked := NULL;
          END IF;

          INSERT INTO audit_log (id, actor_user_id, actor_rol, tenant_id, accion, tabla,
                                 registro_id, despues, ip, user_agent)
          VALUES (gen_random_uuid(), p_user_id, v_user.rol::text, v_user.tenant_id,
                  'LOGIN_FALLIDO', 'users', p_user_id::text,
                  jsonb_build_object('locked_until', v_locked), p_ip, p_ua);
          RETURN v_locked;
        END $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_login_success(p_user_id uuid, p_ip text, p_ua text)
        RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_user users%ROWTYPE;
        BEGIN
          SELECT * INTO v_user FROM users WHERE id = p_user_id FOR UPDATE;
          IF NOT FOUND THEN RETURN; END IF;
          UPDATE users SET failed_attempts = 0, lockout_count = 0, locked_until = NULL,
                 last_login_at = now(), updated_at = now()
           WHERE id = p_user_id;
          INSERT INTO audit_log (id, actor_user_id, actor_rol, tenant_id, accion, tabla,
                                 registro_id, ip, user_agent)
          VALUES (gen_random_uuid(), p_user_id, v_user.rol::text, v_user.tenant_id,
                  'LOGIN_OK', 'users', p_user_id::text, p_ip, p_ua);
        END $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_create_session(
          p_user_id uuid, p_tenant_id uuid, p_token_hash text,
          p_expires timestamptz, p_ip text, p_ua text
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_id uuid := gen_random_uuid();
        BEGIN
          INSERT INTO user_sessions (id, user_id, tenant_id, token_hash, expires_at,
                                     ip, user_agent, created_at)
          VALUES (v_id, p_user_id, p_tenant_id, p_token_hash, p_expires, p_ip, p_ua, now());
          RETURN v_id;
        END $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_get_session(p_token_hash text)
        RETURNS TABLE (
          session_id uuid, user_id uuid, tenant_id uuid, expires_at timestamptz,
          revoked_at timestamptz, rol text, is_active boolean, email text,
          totp_enabled boolean
        )
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT s.id, s.user_id, s.tenant_id, s.expires_at, s.revoked_at,
                 u.rol::text, u.is_active, u.email::text, u.totp_enabled
          FROM user_sessions s JOIN users u ON u.id = s.user_id
          WHERE s.token_hash = p_token_hash
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_rotate_session(
          p_old_id uuid, p_new_hash text, p_expires timestamptz, p_ip text, p_ua text
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
          v_old user_sessions%ROWTYPE;
          v_new uuid := gen_random_uuid();
        BEGIN
          SELECT * INTO v_old FROM user_sessions WHERE id = p_old_id FOR UPDATE;
          IF NOT FOUND OR v_old.revoked_at IS NOT NULL THEN
            RAISE EXCEPTION 'sesion invalida';
          END IF;
          INSERT INTO user_sessions (id, user_id, tenant_id, token_hash, expires_at,
                                     ip, user_agent, created_at)
          VALUES (v_new, v_old.user_id, v_old.tenant_id, p_new_hash, p_expires,
                  p_ip, p_ua, now());
          UPDATE user_sessions SET revoked_at = now(), rotated_to = v_new
           WHERE id = p_old_id;
          RETURN v_new;
        END $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_revoke_all_sessions(
          p_user_id uuid, p_motivo text, p_ip text, p_ua text
        ) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          UPDATE user_sessions SET revoked_at = now()
           WHERE user_id = p_user_id AND revoked_at IS NULL;
          INSERT INTO audit_log (id, actor_user_id, accion, tabla, registro_id,
                                 despues, ip, user_agent)
          VALUES (gen_random_uuid(), p_user_id, 'SESIONES_REVOCADAS', 'user_sessions',
                  p_user_id::text, jsonb_build_object('motivo', p_motivo), p_ip, p_ua);
        END $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_revoke_session(p_session_id uuid, p_ip text, p_ua text)
        RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_session user_sessions%ROWTYPE;
        BEGIN
          SELECT * INTO v_session FROM user_sessions WHERE id = p_session_id FOR UPDATE;
          IF NOT FOUND THEN RETURN; END IF;
          UPDATE user_sessions SET revoked_at = now() WHERE id = p_session_id;
          INSERT INTO audit_log (id, actor_user_id, tenant_id, accion, tabla, registro_id,
                                 ip, user_agent)
          VALUES (gen_random_uuid(), v_session.user_id, v_session.tenant_id, 'LOGOUT',
                  'user_sessions', p_session_id::text, p_ip, p_ua);
        END $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_get_totp(p_user_id uuid)
        RETURNS TABLE (totp_secret_enc text, totp_enabled boolean, email text,
                       rol text, tenant_id uuid, is_active boolean)
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT u.totp_secret_enc::text, u.totp_enabled, u.email::text, u.rol::text,
                 u.tenant_id, u.is_active
          FROM users u WHERE u.id = p_user_id
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_set_totp(
          p_user_id uuid, p_secret_enc text, p_enabled boolean, p_ip text, p_ua text
        ) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_user users%ROWTYPE;
        BEGIN
          SELECT * INTO v_user FROM users WHERE id = p_user_id FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'usuario no existe'; END IF;
          UPDATE users SET totp_secret_enc = p_secret_enc, totp_enabled = p_enabled,
                 updated_at = now()
           WHERE id = p_user_id;
          -- El secreto JAMÁS queda en la bitácora (A04)
          INSERT INTO audit_log (id, actor_user_id, actor_rol, tenant_id, accion, tabla,
                                 registro_id, despues, ip, user_agent)
          VALUES (gen_random_uuid(), p_user_id, v_user.rol::text, v_user.tenant_id,
                  'TOTP_CONFIG', 'users', p_user_id::text,
                  jsonb_build_object('totp_enabled', p_enabled, 'totp_secret_enc', '***'),
                  p_ip, p_ua);
        END $$;
        """
    )

    # -------------------------------- patrón superadmin: consulta auditada
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_list_tenants(p_motivo text)
        RETURNS SETOF tenants
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
          v_actor uuid := app_user();
          v_rol text;
        BEGIN
          -- Doble verificación: GUC interno + rol REAL del actor en la BD
          IF NOT app_is_internal() OR v_actor IS NULL THEN
            RAISE EXCEPTION 'acceso denegado';
          END IF;
          SELECT rol::text INTO v_rol FROM users
           WHERE id = v_actor AND is_active AND tenant_id IS NULL;
          IF v_rol IS NULL OR v_rol NOT IN ('SUPERADMIN', 'SOPORTE', 'LECTURA') THEN
            RAISE EXCEPTION 'acceso denegado';
          END IF;

          INSERT INTO audit_log (id, actor_user_id, actor_rol, accion, tabla, despues)
          VALUES (gen_random_uuid(), v_actor, v_rol, 'SA_SELECT', 'tenants',
                  jsonb_build_object('motivo', p_motivo));

          RETURN QUERY SELECT * FROM tenants ORDER BY created_at DESC;
        END $$;
        """
    )

    # Propiedad y permisos de ejecución de las funciones seguras
    op.execute(
        """
        DO $$
        DECLARE f text;
        BEGIN
          FOREACH f IN ARRAY ARRAY[
            'auth_get_user_for_login(text)',
            'auth_login_failed(uuid,text,text,int)',
            'auth_login_success(uuid,text,text)',
            'auth_create_session(uuid,uuid,text,timestamptz,text,text)',
            'auth_get_session(text)',
            'auth_rotate_session(uuid,text,timestamptz,text,text)',
            'auth_revoke_all_sessions(uuid,text,text,text)',
            'auth_revoke_session(uuid,text,text)',
            'auth_get_totp(uuid)',
            'auth_set_totp(uuid,text,boolean,text,text)',
            'sa_list_tenants(text)'
          ] LOOP
            EXECUTE format('ALTER FUNCTION %s OWNER TO factuchat_security', f);
            EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', f);
            EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO factuchat_app', f);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS sa_list_tenants(text);
        DROP FUNCTION IF EXISTS auth_set_totp(uuid,text,boolean,text,text);
        DROP FUNCTION IF EXISTS auth_get_totp(uuid);
        DROP FUNCTION IF EXISTS auth_revoke_session(uuid,text,text);
        DROP FUNCTION IF EXISTS auth_revoke_all_sessions(uuid,text,text,text);
        DROP FUNCTION IF EXISTS auth_rotate_session(uuid,text,timestamptz,text,text);
        DROP FUNCTION IF EXISTS auth_get_session(text);
        DROP FUNCTION IF EXISTS auth_create_session(uuid,uuid,text,timestamptz,text,text);
        DROP FUNCTION IF EXISTS auth_login_success(uuid,text,text);
        DROP FUNCTION IF EXISTS auth_login_failed(uuid,text,text,int);
        DROP FUNCTION IF EXISTS auth_get_user_for_login(text);
        DROP TRIGGER IF EXISTS trg_audit_log_inmutable ON audit_log;
        DROP FUNCTION IF EXISTS audit_log_inmutable();
        """
    )
    for table in ALL_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            DO $$
            DECLARE p record;
            BEGIN
              FOR p IN SELECT policyname FROM pg_policies
                       WHERE schemaname = 'public' AND tablename = '{table}' LOOP
                EXECUTE format('DROP POLICY %I ON {table}', p.policyname);
              END LOOP;
            END $$;
            """
        )
    op.execute(
        """
        DROP FUNCTION IF EXISTS app_is_internal();
        DROP FUNCTION IF EXISTS app_user();
        DROP FUNCTION IF EXISTS app_tenant();
        """
    )
