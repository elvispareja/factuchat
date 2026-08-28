"""Consumo y costos: el costo real de cada cliente contra lo que paga.

La sección existía a medias: enseñaba la tabla de tarifas y, donde la maqueta
pone lo importante —cuánto cuesta cada cliente y cuánto margen deja—, había un
párrafo diciendo que llegaría «con la fase 5». La fase 5 ya está: el consumo se
registra desde entonces y el cálculo se puede hacer.

TRES DECISIONES QUE CONVIENE ENTENDER ANTES DE TOCAR ESTO:

1. El costo de WhatsApp NO se recalcula: se suma lo que se apuntó. Cada
   conversación guardó en `whatsapp_msgs.costo` la tarifa que regía ESE día
   (`app/whatsapp/consumo.py`). Volver a calcularlo con la tarifa de hoy
   reescribiría el pasado: si Meta sube en octubre, septiembre no se encarece.

2. IA e infraestructura no guardan su costo por fila, así que aquí se aplica la
   tarifa vigente EN LA FECHA de cada análisis y de cada comprobante, no la de
   hoy. Es el mismo criterio, por la misma razón.

3. Se listan los inquilinos ACTIVOS. Uno en prueba aparece pagando $0 y con
   costo real, o sea con margen negativo — que es exactamente lo que hay que
   ver: cuánto cuesta la prueba gratuita.

Revision ID: 0013
Revises: 0012
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Faltaban dos de las tres tarifas que la maqueta deja editar. Sin ellas el
    # costo por cliente salía cojo (solo WhatsApp) y el editor no tendría qué
    # editar. Los valores son los de la maqueta.
    op.execute(
        """
        INSERT INTO cost_rates (id, proveedor, concepto, costo_unitario, unidad, moneda,
                                vigente_desde, vigente_hasta, notas, created_at, updated_at)
        SELECT gen_random_uuid(), v.proveedor, v.concepto, v.costo, v.unidad, 'USD',
               DATE '2026-01-01', NULL, v.notas, now(), now()
          FROM (VALUES
            ('IA', 'Análisis de comprobante', 0.020000, 'análisis',
             'Costo medio por análisis del asistente'),
            ('INFRA', 'Emisión de comprobante', 0.003000, 'comprobante',
             'Servidor, almacenamiento y envío al SRI, prorrateado por comprobante')
          ) AS v(proveedor, concepto, costo, unidad, notas)
         WHERE NOT EXISTS (
           SELECT 1 FROM cost_rates c
            WHERE c.proveedor = v.proveedor AND c.concepto = v.concepto
         );
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_consumo_por_cliente()
        RETURNS TABLE (
          tenant_id uuid, cliente text, plan text,
          cupo int, usados bigint, comp_whatsapp bigint,
          ia_usados bigint, ia_cupo int,
          costo_wa numeric, costo_ia numeric, costo_infra numeric,
          paga numeric
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE ini date := date_trunc('month', current_date)::date;
        BEGIN
          PERFORM sa_verificar_rol('consumo y costos');
          RETURN QUERY
          SELECT
            t.id,
            t.razon_social::text,
            coalesce(p.nombre, 'sin plan')::text,
            coalesce((p.limites->>'cupo')::int, 0),
            coalesce(c.total, 0),
            coalesce(c.por_whatsapp, 0),
            coalesce(a.n, 0),
            coalesce((p.limites->>'ia')::int, 0),
            coalesce(w.costo, 0),
            coalesce(a.costo, 0),
            coalesce(c.costo_infra, 0),
            coalesce(s.precio, 0)
          FROM tenants t
          -- Lo que paga: el precio congelado en su suscripción, no el de lista
          LEFT JOIN LATERAL (
            SELECT su.plan_id, su.precio
              FROM suscripciones su
             WHERE su.tenant_id = t.id AND su.estado = 'ACTIVA'
             ORDER BY su.inicia DESC
             LIMIT 1
          ) s ON true
          LEFT JOIN planes p ON p.id = s.plan_id
          -- Comprobantes del mes: cuántos, cuántos por WhatsApp y su costo de
          -- infraestructura a la tarifa que regía el día de cada uno
          LEFT JOIN LATERAL (
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE co.origen = 'WHATSAPP') AS por_whatsapp,
                   coalesce(sum(coalesce((
                     SELECT cr.costo_unitario FROM cost_rates cr
                      WHERE cr.proveedor = 'INFRA'
                        AND cr.vigente_desde <= co.fecha_emision
                        AND (cr.vigente_hasta IS NULL OR cr.vigente_hasta > co.fecha_emision)
                      ORDER BY cr.vigente_desde DESC LIMIT 1), 0)), 0) AS costo_infra
              FROM comprobantes co
             WHERE co.tenant_id = t.id
               AND co.estado IN ('ENVIADO_SRI','AUTORIZADO')
               AND co.fecha_emision >= ini
          ) c ON true
          -- Análisis de IA del mes, con su tarifa por fecha
          LEFT JOIN LATERAL (
            SELECT count(*) AS n,
                   coalesce(sum(coalesce((
                     SELECT cr.costo_unitario FROM cost_rates cr
                      WHERE cr.proveedor = 'IA'
                        AND cr.vigente_desde <= ai.created_at::date
                        AND (cr.vigente_hasta IS NULL OR cr.vigente_hasta > ai.created_at::date)
                      ORDER BY cr.vigente_desde DESC LIMIT 1), 0)), 0) AS costo
              FROM analisis_ia ai
             WHERE ai.tenant_id = t.id
               AND ai.consume
               AND ai.created_at >= ini
          ) a ON true
          -- WhatsApp: lo APUNTADO, no lo recalculado
          LEFT JOIN LATERAL (
            SELECT coalesce(sum(wm.costo), 0) AS costo
              FROM whatsapp_msgs wm
             WHERE wm.tenant_id = t.id
               AND wm.created_at >= ini
          ) w ON true
          WHERE t.estado = 'ACTIVO'
          ORDER BY t.razon_social;
        END $$;
        """
    )

    op.execute("ALTER FUNCTION sa_consumo_por_cliente() OWNER TO factuchat_security;")
    op.execute("REVOKE ALL ON FUNCTION sa_consumo_por_cliente() FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION sa_consumo_por_cliente() TO factuchat_app;")
    op.execute("GRANT SELECT ON whatsapp_msgs, analisis_ia, cost_rates TO factuchat_security;")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS sa_consumo_por_cliente();")
    op.execute(
        "DELETE FROM cost_rates WHERE proveedor IN ('IA','INFRA') "
        "AND concepto IN ('Análisis de comprobante','Emisión de comprobante');"
    )
