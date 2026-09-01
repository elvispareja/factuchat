"""Categorías y atributos configurables para el catálogo de productos.

Hasta ahora un producto solo tenía código, nombre y tipo: sin forma de
agruparlo para filtrar la tienda o el catálogo del panel. Se agrega
"categorias" (propia del tenant, vía RLS igual que "productos") y
"atributos", que SIEMPRE cuelgan de una categoría (de ahí "derivados": si la
categoría se borra, sus atributos se borran con ella, CASCADE). A diferencia
de una "marca" fija, un atributo es un rótulo configurable por categoría
(Marca, Color, Talla...) con sus propios valores posibles en
"atributo_valores". Un producto puede declarar categoría y, vía la tabla
puente "producto_atributos", cualquier número de atributos —pero como mucho
un valor por atributo—. Nada de esto es obligatorio: el catálogo sigue
funcionando igual sin clasificar.

Revision ID: 0020
Revises: 0019
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --------------------------------------------------------------- categorias
    op.create_table(
        "categorias",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_categorias_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categorias")),
        sa.UniqueConstraint("tenant_id", "nombre", name=op.f("uq_categorias_tenant_id_nombre")),
    )
    op.create_index(op.f("ix_categorias_tenant_id"), "categorias", ["tenant_id"])

    # ---------------------------------------------------------------- atributos
    op.create_table(
        "atributos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("categoria_id", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_atributos_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["categoria_id"], ["categorias.id"], name=op.f("fk_atributos_categoria_id_categorias"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_atributos")),
        sa.UniqueConstraint("categoria_id", "nombre", name=op.f("uq_atributos_categoria_id_nombre")),
    )
    op.create_index(op.f("ix_atributos_tenant_id"), "atributos", ["tenant_id"])
    op.create_index(op.f("ix_atributos_categoria_id"), "atributos", ["categoria_id"])

    # ----------------------------------------------------------- atributo_valores
    op.create_table(
        "atributo_valores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("atributo_id", sa.UUID(), nullable=False),
        sa.Column("valor", sa.String(length=150), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_atributo_valores_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["atributo_id"], ["atributos.id"], name=op.f("fk_atributo_valores_atributo_id_atributos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_atributo_valores")),
        sa.UniqueConstraint(
            "atributo_id", "valor", name=op.f("uq_atributo_valores_atributo_id_valor")
        ),
    )
    op.create_index(op.f("ix_atributo_valores_tenant_id"), "atributo_valores", ["tenant_id"])
    op.create_index(op.f("ix_atributo_valores_atributo_id"), "atributo_valores", ["atributo_id"])

    # --------------------------------------------------------- producto_atributos
    op.create_table(
        "producto_atributos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("producto_id", sa.UUID(), nullable=False),
        sa.Column("atributo_id", sa.UUID(), nullable=False),
        sa.Column("atributo_valor_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_producto_atributos_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"], ["productos.id"],
            name=op.f("fk_producto_atributos_producto_id_productos"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["atributo_id"], ["atributos.id"],
            name=op.f("fk_producto_atributos_atributo_id_atributos"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["atributo_valor_id"], ["atributo_valores.id"],
            name=op.f("fk_producto_atributos_atributo_valor_id_atributo_valores"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_producto_atributos")),
        sa.UniqueConstraint(
            "producto_id", "atributo_id", name=op.f("uq_producto_atributos_producto_id_atributo_id")
        ),
    )
    op.create_index(op.f("ix_producto_atributos_tenant_id"), "producto_atributos", ["tenant_id"])
    op.create_index(op.f("ix_producto_atributos_producto_id"), "producto_atributos", ["producto_id"])
    op.create_index(op.f("ix_producto_atributos_atributo_id"), "producto_atributos", ["atributo_id"])
    op.create_index(
        op.f("ix_producto_atributos_atributo_valor_id"), "producto_atributos", ["atributo_valor_id"]
    )

    # ------------------------------------------------------------------ RLS
    tablas = ("categorias", "atributos", "atributo_valores", "producto_atributos")
    for tabla in tablas:
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY;")

    # Solo del propio inquilino: a diferencia de "pedidos", el panel superadmin
    # no necesita mirar categorías/atributos, así que no llevan política
    # "_interno" (igual que "productos" y "clientes_finales").
    op.execute(
        """
        CREATE POLICY categorias_tenant ON categorias
          FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
        CREATE POLICY atributos_tenant ON atributos
          FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
        CREATE POLICY atributo_valores_tenant ON atributo_valores
          FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
        CREATE POLICY producto_atributos_tenant ON producto_atributos
          FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
        """
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON "
        "categorias, atributos, atributo_valores, producto_atributos TO factuchat_app;"
    )

    # --------------------------------------------------- productos: clasificación
    # Opcional: un producto sigue funcionando sin categoría.
    op.add_column("productos", sa.Column("categoria_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_productos_categoria_id_categorias"), "productos", "categorias",
        ["categoria_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_productos_categoria_id_categorias"), "productos", type_="foreignkey")
    op.drop_column("productos", "categoria_id")

    op.execute("DROP POLICY IF EXISTS categorias_tenant ON categorias;")
    op.execute("DROP POLICY IF EXISTS atributos_tenant ON atributos;")
    op.execute("DROP POLICY IF EXISTS atributo_valores_tenant ON atributo_valores;")
    op.execute("DROP POLICY IF EXISTS producto_atributos_tenant ON producto_atributos;")

    op.drop_table("producto_atributos")
    op.drop_table("atributo_valores")
    op.drop_table("atributos")
    op.drop_table("categorias")
