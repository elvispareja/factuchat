"""WhatsApp (fase 5): el panel interno necesita ver el consumo GLOBAL.

`whatsapp_msgs` tenía solo la política por tenant, y el personal interno no
tiene ninguno: sin esta política el tablero de consumo salía en cero. Es la
misma corrección que se hizo con `suscripciones` en la fase 4.

Revision ID: 0006
Revises: 0005
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE POLICY whatsapp_msgs_interno ON whatsapp_msgs
          FOR ALL USING (app_is_internal()) WITH CHECK (app_is_internal());
        """
    )
    # Índice para el tablero: se consulta por mes y se agrupa por inquilino
    op.create_index(
        "ix_whatsapp_msgs_tenant_fecha",
        "whatsapp_msgs",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_whatsapp_msgs_tenant_fecha", table_name="whatsapp_msgs")
    op.execute("DROP POLICY IF EXISTS whatsapp_msgs_interno ON whatsapp_msgs;")
