"""Se acabaron las contraseñas: se entra con el correo y un código de 6 dígitos.

QUÉ CAMBIA
  · El cliente escribe su correo y le llega un código de seis dígitos. Cada vez
    que entra. No hay contraseña que recordar, que reutilizar ni que robar de
    otra base de datos filtrada.
  · El personal interno (SUPERADMIN, SOPORTE, LECTURA) usa el código de su app
    de autenticación, la misma que ya tenía.
  · La columna `password_hash` desaparece. Dejarla sin usar sería peor que
    quitarla: alguien acabaría comprobándola «por si acaso» y volveríamos a
    tener dos caminos de entrada, uno de ellos sin vigilancia.

CÓMO SE PROTEGE UN CÓDIGO DE SEIS DÍGITOS
Un millón de combinaciones no es gran cosa, así que la seguridad no está en su
longitud sino en el resto:
  · caduca a los 10 minutos,
  · vale UNA sola vez,
  · lleva contador de intentos y se quema al quinto,
  · pedir uno nuevo invalida el anterior, para que no haya varios vivos a la vez,
  · se guarda su sha256, no el código: una copia de la tabla no sirve para entrar.

Esto se suma al límite de intentos por IP y por cuenta que ya existía.

DESPUÉS DE ESTO, la invitación por correo que se acababa de construir sobra: ya
no hay contraseña que estrenar. Se retira aquí en vez de dejarla muerta.

Revision ID: 0017
Revises: 0016
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Fuera la invitación: ya no hay contraseña que definir ---------------
    op.execute("DROP FUNCTION IF EXISTS auth_invitacion_usar(text, text, text, text);")
    op.execute("DROP FUNCTION IF EXISTS auth_invitacion_ver(text);")
    op.execute("DROP POLICY IF EXISTS invitaciones_interno ON invitaciones;")
    op.execute("DROP TABLE IF EXISTS invitaciones;")

    # --- Códigos de acceso ---------------------------------------------------
    op.create_table(
        "codigos_acceso",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        # sha256 del código. El de seis dígitos solo existe en el correo.
        sa.Column("codigo_hash", sa.String(length=64), nullable=False),
        sa.Column("expira_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_codigos_acceso_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_codigos_acceso")),
    )
    op.create_index(op.f("ix_codigos_acceso_user_id"), "codigos_acceso", ["user_id"])
    # Solo se busca por hash, y así el índice sirve además de guardia contra
    # colisiones entre códigos vivos.
    op.create_index(op.f("ix_codigos_acceso_codigo_hash"), "codigos_acceso", ["codigo_hash"])

    op.execute("ALTER TABLE codigos_acceso ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE codigos_acceso FORCE ROW LEVEL SECURITY;")
    # Nadie llega aquí con una sesión abierta: quien pide un código todavía no
    # ha entrado. Se opera solo por funciones auth_*, como el resto del login.
    op.execute(
        """
        CREATE POLICY codigos_acceso_interno ON codigos_acceso
          FOR ALL USING (app_is_internal()) WITH CHECK (app_is_internal());
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON codigos_acceso TO factuchat_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON codigos_acceso TO factuchat_security;")

    # --- Emitir: invalida los anteriores y deja uno vivo --------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_codigo_emitir(
          p_user uuid, p_hash text, p_expira timestamptz, p_ip text
        ) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          -- Un solo código vivo por cuenta: si hubiera varios, pedir otro sería
          -- una forma de multiplicar los intentos disponibles.
          UPDATE codigos_acceso SET usado_at = now()
           WHERE user_id = p_user AND usado_at IS NULL;

          INSERT INTO codigos_acceso (id, user_id, codigo_hash, expira_at, ip)
          VALUES (gen_random_uuid(), p_user, p_hash, p_expira, p_ip);
        END $$;
        """
    )

    # --- Consumir: una sola vez, con contador de intentos -------------------
    # Devuelve 'ok' | 'no' (no coincide, gasta un intento) | 'agotado' | 'nada'.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_codigo_usar(
          p_user uuid, p_hash text, p_max_intentos int
        ) RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v codigos_acceso%ROWTYPE;
        BEGIN
          SELECT * INTO v FROM codigos_acceso
           WHERE user_id = p_user AND usado_at IS NULL AND expira_at > now()
           ORDER BY created_at DESC
           LIMIT 1
           FOR UPDATE;

          IF v.id IS NULL THEN
            RETURN 'nada';
          END IF;

          IF v.intentos >= p_max_intentos THEN
            UPDATE codigos_acceso SET usado_at = now() WHERE id = v.id;
            RETURN 'agotado';
          END IF;

          IF v.codigo_hash = p_hash THEN
            UPDATE codigos_acceso SET usado_at = now() WHERE id = v.id;
            RETURN 'ok';
          END IF;

          UPDATE codigos_acceso SET intentos = intentos + 1 WHERE id = v.id;
          RETURN 'no';
        END $$;
        """
    )

    # --- El login deja de mirar contraseñas ---------------------------------
    op.execute("DROP FUNCTION IF EXISTS auth_get_user_for_login(text);")
    op.execute(
        """
        CREATE FUNCTION auth_get_user_for_login(p_email text)
        RETURNS TABLE (
          id uuid, tenant_id uuid, email text, nombre text, rol text,
          is_active boolean, totp_enabled boolean, failed_attempts int,
          locked_until timestamptz, tenant_estado text
        )
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT u.id, u.tenant_id, u.email::text, u.nombre::text, u.rol::text,
                 u.is_active, u.totp_enabled, u.failed_attempts,
                 u.locked_until, t.estado::text
          FROM users u LEFT JOIN tenants t ON t.id = u.tenant_id
          WHERE lower(u.email) = lower(p_email)
        $$;
        """
    )

    op.drop_column("users", "password_hash")

    for firma in (
        "auth_get_user_for_login(text)",
        "auth_codigo_emitir(uuid, text, timestamptz, text)",
        "auth_codigo_usar(uuid, text, int)",
    ):
        op.execute(f"ALTER FUNCTION {firma} OWNER TO factuchat_security;")
        op.execute(f"REVOKE ALL ON FUNCTION {firma} FROM PUBLIC;")
        op.execute(f"GRANT EXECUTE ON FUNCTION {firma} TO factuchat_app;")


def downgrade() -> None:
    # Vuelven las contraseñas, pero NADIE recupera la suya: se ponen hashes
    # imposibles y habría que restablecerlas una a una. Bajar de aquí es una
    # decisión con consecuencias, no un paso atrás inocente.
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=300), nullable=False, server_default="!"),
    )
    op.execute("DROP FUNCTION IF EXISTS auth_get_user_for_login(text);")
    op.execute(
        """
        CREATE FUNCTION auth_get_user_for_login(p_email text)
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
    op.execute("ALTER FUNCTION auth_get_user_for_login(text) OWNER TO factuchat_security;")
    op.execute("GRANT EXECUTE ON FUNCTION auth_get_user_for_login(text) TO factuchat_app;")

    op.execute("DROP FUNCTION IF EXISTS auth_codigo_usar(uuid, text, int);")
    op.execute("DROP FUNCTION IF EXISTS auth_codigo_emitir(uuid, text, timestamptz, text);")
    op.execute("DROP POLICY IF EXISTS codigos_acceso_interno ON codigos_acceso;")
    op.drop_table("codigos_acceso")
