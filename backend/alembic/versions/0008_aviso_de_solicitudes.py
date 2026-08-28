"""Marca de aviso al equipo sobre una solicitud de la landing (fase 6.2).

El checklist F6 exige que el pedido por transferencia «cree registro y
notifique». La marca vive en la propia solicitud para que el reintento del task
sepa si el correo ya salió y no mande un segundo aviso.

Revision ID: 0008
Revises: 0007
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "solicitudes_contacto",
        sa.Column("avisado_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Índice parcial: la consulta que importa es "las que faltan por avisar"
    op.execute(
        "CREATE INDEX ix_solicitudes_sin_avisar ON solicitudes_contacto (creada_at) "
        "WHERE avisado_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_solicitudes_sin_avisar")
    op.drop_column("solicitudes_contacto", "avisado_at")
