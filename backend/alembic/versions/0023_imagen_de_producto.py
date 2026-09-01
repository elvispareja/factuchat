"""Una imagen por producto, para la miniatura del catálogo y de la tienda.

Se guarda la RUTA del archivo en disco, no el binario: meter imágenes en
Postgres hincha la base y complica los backups.

Es un RENOMBRADO, no una columna nueva. `productos.imagen_url` existe desde
0001, tiene exactamente la forma que hace falta (varchar(500) NULL) y está
muerta: ninguna consulta, esquema ni pantalla la lee o la escribe, así que
todas las filas la tienen a NULL. Añadir `imagen_path` al lado dejaría dos
columnas para lo mismo y la duda permanente de cuál manda. El nombre cambia
porque lo que se guarda es una ruta local, no una URL.

Revision ID: 0023
Revises: 0022
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("productos", "imagen_url", new_column_name="imagen_path")


def downgrade() -> None:
    op.alter_column("productos", "imagen_path", new_column_name="imagen_url")
