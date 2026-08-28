"""Los tres avisos automáticos, editables desde Configuración.

La maqueta pone en Configuración tres textos editables —pre-declaración, cupo
agotado y pago vencido— con un botón «Guardar textos». En el código vivían
fijos en `app/whatsapp/plantillas.py`, así que cambiar una coma exigía un
despliegue.

Se guardan en `parametros`, que ya es la tabla de los ajustes en caliente. Lo
único que hacía falta es que `valor` deje de ser VARCHAR(300): un aviso ronda
los 200 caracteres y basta que alguien añada una frase para que el guardado
reviente con un error de longitud justo al pulsar «Guardar textos».

Revision ID: 0014
Revises: 0013
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "parametros",
        "valor",
        existing_type=sa.String(length=300),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Los textos largos se recortan antes de estrechar la columna, o el ALTER
    # falla y deja la bajada a medias.
    op.execute("UPDATE parametros SET valor = left(valor, 300) WHERE length(valor) > 300;")
    op.alter_column(
        "parametros",
        "valor",
        existing_type=sa.Text(),
        type_=sa.String(length=300),
        existing_nullable=False,
    )
