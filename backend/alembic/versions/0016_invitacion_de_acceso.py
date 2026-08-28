"""Invitación de acceso: el cliente estrena su cuenta poniendo su contraseña.

Hasta ahora el alta creaba el inquilino y su suscripción… y nadie con quien
entrar. El cliente quedaba sin usuario, así que el panel que se le acababa de
montar era inaccesible para él.

Ahora el alta crea también su usuario y le manda un correo con un enlace de un
solo uso donde define su contraseña. Después entra, y ahí se topa con la firma
electrónica, que es lo único que le falta para operar.

POR QUÉ UNA TABLA Y NO UN TOKEN FIRMADO. Un JWT no se puede revocar ni gastar:
quien reabriera el correo dentro de un mes podría volver a cambiar la
contraseña. La invitación tiene que ser de UN SOLO USO y con caducidad, y eso
pide estado en la base.

DEL TOKEN SOLO SE GUARDA EL HASH, igual que con los refresh tokens: si alguien
se lleva una copia de la tabla, no se lleva enlaces utilizables.

Revision ID: 0016
Revises: 0015
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invitaciones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        # sha256 del token en claro. El token viaja solo en el correo.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expira_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creada_por", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_invitaciones_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["creada_por"],
            ["users.id"],
            name=op.f("fk_invitaciones_creada_por_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitaciones")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitaciones_token_hash")),
    )
    op.create_index(op.f("ix_invitaciones_user_id"), "invitaciones", ["user_id"])

    # Nadie llega a esta tabla por SQL normal: se usa desde endpoints SIN sesión
    # (quien abre el enlace todavía no puede autenticarse), así que va por
    # funciones SECURITY DEFINER como el resto del login.
    op.execute("ALTER TABLE invitaciones ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE invitaciones FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY invitaciones_interno ON invitaciones
          FOR ALL USING (app_is_internal()) WITH CHECK (app_is_internal());
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON invitaciones TO factuchat_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON invitaciones TO factuchat_security;")
    op.execute("GRANT SELECT, UPDATE ON users TO factuchat_security;")

    # --- Validar un enlace -------------------------------------------------
    # Devuelve a quién pertenece y si sigue sirviendo. No devuelve el hash ni
    # nada que ayude a fabricar otro enlace.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_invitacion_ver(p_token_hash text)
        RETURNS TABLE (
          id uuid, user_id uuid, email text, nombre text, negocio text,
          expira_at timestamptz, usada boolean, vencida boolean
        )
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT i.id, u.id, u.email::text, u.nombre::text,
                 coalesce(t.razon_social, '')::text,
                 i.expira_at,
                 i.usada_at IS NOT NULL,
                 i.expira_at <= now()
          FROM invitaciones i
          JOIN users u ON u.id = i.user_id
          LEFT JOIN tenants t ON t.id = u.tenant_id
          WHERE i.token_hash = p_token_hash
        $$;
        """
    )

    # --- Gastar el enlace y fijar la contraseña ----------------------------
    # Todo en una sola sentencia y bajo condición: si dos peticiones llegan a la
    # vez, solo una encuentra `usada_at IS NULL` y la otra no cambia nada. Sin
    # eso, dos pestañas abiertas podrían fijar contraseñas distintas.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_invitacion_usar(
          p_token_hash text, p_password_hash text, p_ip text, p_ua text
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_user uuid;
        BEGIN
          UPDATE invitaciones
             SET usada_at = now()
           WHERE token_hash = p_token_hash
             AND usada_at IS NULL
             AND expira_at > now()
          RETURNING user_id INTO v_user;

          IF v_user IS NULL THEN
            RETURN NULL;
          END IF;

          UPDATE users
             SET password_hash = p_password_hash,
                 failed_attempts = 0,
                 locked_until = NULL,
                 updated_at = now()
           WHERE id = v_user;

          -- Cualquier otra invitación viva del mismo usuario se quema: si se
          -- reenvió el correo dos veces, el enlace viejo deja de valer.
          UPDATE invitaciones
             SET usada_at = now()
           WHERE user_id = v_user AND usada_at IS NULL;

          INSERT INTO audit_log (id, actor_user_id, accion, tabla, registro_id, ip, user_agent)
          VALUES (gen_random_uuid(), v_user, 'CLAVE_DEFINIDA', 'users', v_user::text,
                  p_ip, left(p_ua, 400));
          RETURN v_user;
        END $$;
        """
    )

    for firma in ("auth_invitacion_ver(text)", "auth_invitacion_usar(text, text, text, text)"):
        op.execute(f"ALTER FUNCTION {firma} OWNER TO factuchat_security;")
        op.execute(f"REVOKE ALL ON FUNCTION {firma} FROM PUBLIC;")
        op.execute(f"GRANT EXECUTE ON FUNCTION {firma} TO factuchat_app;")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_invitacion_usar(text, text, text, text);")
    op.execute("DROP FUNCTION IF EXISTS auth_invitacion_ver(text);")
    op.execute("DROP POLICY IF EXISTS invitaciones_interno ON invitaciones;")
    op.drop_index(op.f("ix_invitaciones_user_id"), table_name="invitaciones")
    op.drop_table("invitaciones")
