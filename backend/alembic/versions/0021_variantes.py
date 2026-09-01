"""Variantes de producto: "tengo 2 de la talla 38 y 3 de la 39".

Hasta ahora un producto tenía UN stock y, por el UNIQUE (producto_id,
atributo_id) de "producto_atributos", UN solo valor por atributo: no había
forma de decir cuántos pares quedan de cada talla. El modelo es el de
Shopify/Woo: en el formulario se eligen uno o varios valores por atributo; los
atributos con un solo valor son fijos para todo el producto y los que tienen
dos o más generan combinaciones (Talla=[38,39,40] × Color=[Rojo,Negro] → 6
variantes, todas Nike).

Por eso "producto_atributos" pasa a significar "qué valores tiene disponibles
este producto" (UNIQUE de tres columnas, para poder repetir el atributo con
distinto valor) y las combinaciones concretas viven en "producto_variantes",
cada una con su código (el SKU que va a la factura), su stock y, opcional, su
propio precio: NULL hereda el del producto, que cubre "la talla 45 cuesta más"
sin obligar a rellenar precios uno por uno.

Revision ID: 0021
Revises: 0020
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------- producto_atributos: varios valores
    op.drop_constraint(
        op.f("uq_producto_atributos_producto_id_atributo_id"),
        "producto_atributos",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_producto_atributos_producto_id_atributo_id_atributo_valor_id"),
        "producto_atributos",
        ["producto_id", "atributo_id", "atributo_valor_id"],
    )

    # -------------------------------------------------------- producto_variantes
    op.create_table(
        "producto_variantes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("producto_id", sa.UUID(), nullable=False),
        sa.Column("codigo", sa.String(length=25), nullable=False),
        sa.Column("precio_sin_iva", sa.Numeric(14, 6), nullable=True),
        sa.Column("stock", sa.Numeric(14, 6), server_default=sa.text("0"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_producto_variantes_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"], ["productos.id"],
            name=op.f("fk_producto_variantes_producto_id_productos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_producto_variantes")),
        # El código va impreso en el comprobante: único dentro del negocio.
        sa.UniqueConstraint(
            "tenant_id", "codigo", name=op.f("uq_producto_variantes_tenant_id_codigo")
        ),
    )
    op.create_index(op.f("ix_producto_variantes_tenant_id"), "producto_variantes", ["tenant_id"])
    op.create_index(op.f("ix_producto_variantes_producto_id"), "producto_variantes", ["producto_id"])

    # -------------------------------------------------------- variante_atributos
    op.create_table(
        "variante_atributos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("variante_id", sa.UUID(), nullable=False),
        sa.Column("atributo_id", sa.UUID(), nullable=False),
        sa.Column("atributo_valor_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_variante_atributos_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variante_id"], ["producto_variantes.id"],
            name=op.f("fk_variante_atributos_variante_id_producto_variantes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["atributo_id"], ["atributos.id"],
            name=op.f("fk_variante_atributos_atributo_id_atributos"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["atributo_valor_id"], ["atributo_valores.id"],
            name=op.f("fk_variante_atributos_atributo_valor_id_atributo_valores"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_variante_atributos")),
        # Una talla por variante: la combinación es lo que la identifica.
        sa.UniqueConstraint(
            "variante_id", "atributo_id",
            name=op.f("uq_variante_atributos_variante_id_atributo_id"),
        ),
    )
    op.create_index(op.f("ix_variante_atributos_tenant_id"), "variante_atributos", ["tenant_id"])
    op.create_index(op.f("ix_variante_atributos_variante_id"), "variante_atributos", ["variante_id"])
    op.create_index(op.f("ix_variante_atributos_atributo_id"), "variante_atributos", ["atributo_id"])
    op.create_index(
        op.f("ix_variante_atributos_atributo_valor_id"), "variante_atributos", ["atributo_valor_id"]
    )

    # ------------------------------------------------------------------ RLS
    for tabla in ("producto_variantes", "variante_atributos"):
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY;")

    # Solo del propio inquilino, igual que categorías/atributos: el panel
    # superadmin no mira el catálogo, así que no llevan política "_interno".
    op.execute(
        """
        CREATE POLICY producto_variantes_tenant ON producto_variantes
          FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
        CREATE POLICY variante_atributos_tenant ON variante_atributos
          FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
        """
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON "
        "producto_variantes, variante_atributos TO factuchat_app;"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS variante_atributos_tenant ON variante_atributos;")
    op.execute("DROP POLICY IF EXISTS producto_variantes_tenant ON producto_variantes;")
    op.drop_table("variante_atributos")
    op.drop_table("producto_variantes")

    # Volver al UNIQUE de dos columnas falla si algún producto ya guardó varios
    # valores del mismo atributo: se borran esos sobrantes primero (es
    # exactamente el dato que el modelo viejo no sabía representar).
    op.execute(
        """
        DELETE FROM producto_atributos pa
         WHERE pa.id NOT IN (
               SELECT MIN(id::text)::uuid FROM producto_atributos
                GROUP BY producto_id, atributo_id
         );
        """
    )
    op.drop_constraint(
        op.f("uq_producto_atributos_producto_id_atributo_id_atributo_valor_id"),
        "producto_atributos",
        type_="unique",
    )
    op.create_unique_constraint(
        op.f("uq_producto_atributos_producto_id_atributo_id"),
        "producto_atributos",
        ["producto_id", "atributo_id"],
    )
