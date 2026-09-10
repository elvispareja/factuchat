"""Varios WhatsApp autorizados por empresa, y gestionados por el cliente.

Hasta ahora el bot resolvía de quién era un mensaje mirando `tenants.telefono`:
UNA columna, UN número, y escrito a mano en la base porque el panel no tenía
dónde ponerlo. La tarjeta «Números de WhatsApp» de Mi cuenta estaba pintada
pero su botón no hacía nada.

Un negocio real no factura desde un solo teléfono. Factura el dueño, la
contadora y quien esté en el mostrador. Así que el número deja de ser una
columna del inquilino y pasa a ser una tabla con una fila por teléfono.

EL NÚMERO SE GUARDA EN CRUDO, SOLO DÍGITOS Y CON CÓDIGO DE PAÍS —
`593993053670`— porque es exactamente lo que manda Meta en el webhook. Guardar
`+593 99 305 3670` obligaría a normalizar en cada consulta, y basta con que una
se olvide para que el mensaje de un cliente legítimo acabe rechazado.

UN NÚMERO NO PUEDE ESTAR EN DOS EMPRESAS. El índice único es global, no por
inquilino: si el mismo teléfono estuviera autorizado dos veces, el bot no
tendría forma de saber a nombre de quién emitir, y elegiría por orden de
llegada. Mejor que no se pueda guardar.

`tenants.telefono` se queda donde está: es el teléfono de contacto de la ficha,
que no tiene por qué ser un WhatsApp. Lo que cambia es que deja de decidir
quién puede facturar por chat. Los que ya había se copian aquí para que ningún
emparejamiento existente se rompa.

Revision ID: 0028
Revises: 0027
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_numeros",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # Solo dígitos y con código de país, tal y como llega en el webhook.
        sa.Column("numero", sa.String(length=20), nullable=False),
        # De quién es: «Libio (dueño)», «Contadora». Lo ve solo el cliente.
        sa.Column("etiqueta", sa.String(length=60), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_whatsapp_numeros_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_numeros")),
    )
    op.create_index(op.f("ix_whatsapp_numeros_tenant_id"), "whatsapp_numeros", ["tenant_id"])
    # Global a propósito: ver la cabecera. No lleva tenant_id.
    op.create_index(
        op.f("uq_whatsapp_numeros_numero"), "whatsapp_numeros", ["numero"], unique=True
    )

    op.execute("ALTER TABLE whatsapp_numeros ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE whatsapp_numeros FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY whatsapp_numeros_tenant ON whatsapp_numeros
          FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_numeros TO factuchat_app;")
    # La función de abajo la ejecuta factuchat_security, que es quien puede
    # cruzar inquilinos. Sin este GRANT la resolución devolvería cero filas.
    op.execute("GRANT SELECT ON whatsapp_numeros TO factuchat_security;")

    # Los emparejamientos que ya existían. El `^5930` es el cero de la
    # marcación nacional colado dentro del formato internacional: `+593 0 99…`
    # es el mismo teléfono que `+593 99…`, pero para Meta son distintos y el
    # mensaje nunca casaría. Ya nos ha mordido dos veces.
    op.execute(
        """
        INSERT INTO whatsapp_numeros (id, tenant_id, numero, etiqueta, created_at)
        SELECT gen_random_uuid(),
               t.id,
               regexp_replace(regexp_replace(t.telefono, '\\D', '', 'g'), '^5930', '593'),
               'Número principal',
               now()
          FROM tenants t
         WHERE coalesce(regexp_replace(t.telefono, '\\D', '', 'g'), '') <> ''
        ON CONFLICT DO NOTHING;
        """
    )

    # La resolución del bot pasa a mirar la tabla. Misma firma y mismos
    # permisos que en 0009: lo único que cambia es de dónde lee.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sys_tenant_por_telefono(p_telefono text)
        RETURNS TABLE (id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT t.id
            FROM whatsapp_numeros n
            JOIN tenants t ON t.id = n.tenant_id
           WHERE n.numero = p_telefono
             AND p_telefono <> ''
             AND t.estado = 'ACTIVO'
           LIMIT 1;
        $$;

        ALTER FUNCTION sys_tenant_por_telefono(text) OWNER TO factuchat_security;
        REVOKE ALL ON FUNCTION sys_tenant_por_telefono(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION sys_tenant_por_telefono(text) TO factuchat_app;
        """
    )


def downgrade() -> None:
    # Vuelve a mirar la columna del inquilino, como en 0009.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sys_tenant_por_telefono(p_telefono text)
        RETURNS TABLE (id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT t.id
            FROM tenants t
           WHERE regexp_replace(coalesce(t.telefono, ''), '\\D', '', 'g') = p_telefono
             AND p_telefono <> ''
             AND t.estado = 'ACTIVO'
           LIMIT 1;
        $$;

        ALTER FUNCTION sys_tenant_por_telefono(text) OWNER TO factuchat_security;
        REVOKE ALL ON FUNCTION sys_tenant_por_telefono(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION sys_tenant_por_telefono(text) TO factuchat_app;
        """
    )
    op.execute("DROP POLICY IF EXISTS whatsapp_numeros_tenant ON whatsapp_numeros;")
    # Bajar de aquí PIERDE los números adicionales: la columna del inquilino
    # solo sabe guardar uno.
    op.drop_table("whatsapp_numeros")
