"""Varias fotos por artículo, no una.

Un producto tenía UNA imagen (`productos.imagen_path`), así que subir otra
reemplazaba la anterior. Vender ropa o repuestos con una sola foto es vender a
ciegas: hace falta la prenda de frente, de espalda, la etiqueta y el detalle de
la costura.

La foto sigue viviendo en disco y solo su ruta en la base, como estaba: los
binarios en Postgres hinchan los respaldos y el WAL. Lo que cambia es que ahora
hay una fila por foto, con su `orden`.

LA PRIMERA (orden 0) ES LA PRINCIPAL: la que sale en el listado y en la tienda.
Se guarda como orden y no como un booleano «es_principal» porque un booleano
permite dos principales, o ninguna, y habría que defenderse de los dos casos en
cada consulta.

Las imágenes que ya existían se conservan: pasan a ser la primera foto de su
producto. Nadie pierde nada.

Revision ID: 0027
Revises: 0026
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "producto_imagenes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("producto_id", sa.UUID(), nullable=False),
        # Ruta en disco, no el binario.
        sa.Column("ruta", sa.String(length=500), nullable=False),
        sa.Column("orden", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_producto_imagenes_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"],
            ["productos.id"],
            name=op.f("fk_producto_imagenes_producto_id_productos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_producto_imagenes")),
    )
    op.create_index(op.f("ix_producto_imagenes_tenant_id"), "producto_imagenes", ["tenant_id"])
    op.create_index(
        op.f("ix_producto_imagenes_producto_id"), "producto_imagenes", ["producto_id", "orden"]
    )

    op.execute("ALTER TABLE producto_imagenes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE producto_imagenes FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY producto_imagenes_tenant ON producto_imagenes
          FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON producto_imagenes TO factuchat_app;")

    # Las fotos que ya había pasan a ser la primera de su producto
    op.execute(
        """
        INSERT INTO producto_imagenes (id, tenant_id, producto_id, ruta, orden, created_at)
        SELECT gen_random_uuid(), p.tenant_id, p.id, p.imagen_path, 0, now()
          FROM productos p
         WHERE p.imagen_path IS NOT NULL;
        """
    )

    # `imagen_path` desaparece: dejarla sería tener dos sitios donde vive «la
    # foto» y, tarde o temprano, dos respuestas distintas a la misma pregunta.
    op.drop_column("productos", "imagen_path")


def downgrade() -> None:
    op.add_column("productos", sa.Column("imagen_path", sa.String(length=500), nullable=True))
    # Vuelve solo la principal: es lo único que la columna sabe guardar. Las
    # demás fotos quedan huérfanas en disco, así que bajar de aquí PIERDE datos.
    op.execute(
        """
        UPDATE productos p
           SET imagen_path = i.ruta
          FROM producto_imagenes i
         WHERE i.producto_id = p.id AND i.orden = 0;
        """
    )
    op.execute("DROP POLICY IF EXISTS producto_imagenes_tenant ON producto_imagenes;")
    op.drop_table("producto_imagenes")
