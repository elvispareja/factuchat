"""La nota de crédito apunta a la factura que corrige.

Sin este enlace no hay forma de saber cuánto se lleva acreditado de una factura,
y sin ese saldo se puede anular 900 de una factura de 689: el SRI lo rechaza, o
peor, lo acepta y la contabilidad queda descuadrada.

Va como columna y no dentro del `payload`: el saldo pendiente se calcula con un
SUM agrupado por factura (el listado de acreditables y la validación de importe),
y eso sobre JSONB es una expresión sin índice.

OJO: la FK NO respeta RLS —Postgres comprueba las claves ajenas con permisos de
superusuario—, así que la pertenencia al tenant se valida en el servicio con
`db.get` ANTES de escribir aquí. La FK solo garantiza que la fila exista.

ON DELETE CASCADE: los comprobantes no se borran de uno en uno; el único borrado
real es el del tenant, y ahí las notas de crédito deben irse con su factura (un
RESTRICT abortaría ese CASCADE).

Revision ID: 0025
Revises: 0024
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comprobantes", sa.Column("comprobante_modificado_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "fk_comprobantes_comprobante_modificado_id_comprobantes",
        "comprobantes",
        "comprobantes",
        ["comprobante_modificado_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_comprobantes_comprobante_modificado_id",
        "comprobantes",
        ["comprobante_modificado_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_comprobantes_comprobante_modificado_id", table_name="comprobantes")
    op.drop_constraint(
        "fk_comprobantes_comprobante_modificado_id_comprobantes",
        "comprobantes",
        type_="foreignkey",
    )
    op.drop_column("comprobantes", "comprobante_modificado_id")
