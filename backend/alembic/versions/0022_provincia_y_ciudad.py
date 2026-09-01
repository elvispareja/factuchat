"""Provincia y ciudad en la libreta de clientes.

La ficha guardaba una `direccion` de texto libre, que no sirve para filtrar ni
para agrupar por zona. Se añaden dos columnas sueltas en vez de normalizar el
catálogo de provincias/cantones: el listado vive en el frontend y duplicarlo
aquí obligaría a mantener el mismo dataset en dos sitios.

NULLABLE a propósito: los clientes ya cargados no tienen esos datos y no se les
puede exigir de forma retroactiva.

RLS no se toca: `clientes_finales` ya tiene su política; esto solo añade
columnas.

Revision ID: 0022
Revises: 0021
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clientes_finales", sa.Column("provincia", sa.String(length=100), nullable=True))
    op.add_column("clientes_finales", sa.Column("ciudad", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("clientes_finales", "ciudad")
    op.drop_column("clientes_finales", "provincia")
