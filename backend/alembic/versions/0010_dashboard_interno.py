"""El Dashboard general del panel interno, tal como lo define la maqueta.

La primera versión de esta pantalla se construyó con los datos que ya devolvía
`sa_metricas()` —inquilinos, morosos, comprobantes e ingresos— en vez de con los
que pide `Superadmin.dc.html`. El resultado no se parecía a la maqueta: faltaban
el MRR, las altas y bajas del mes, el desglose de clientes por plan, el gráfico
de 30 días, el semáforo de servicios y las alertas críticas.

Esta migración añade las funciones seguras que faltaban. Van por `SECURITY
DEFINER` como el resto de las `sa_*`, porque `tenants`, `suscripciones` y
`pagos` están cerradas incluso para el personal interno.

Revision ID: 0010
Revises: 0009
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --------------------------------------------------- KPI de la cabecera
    #
    # MRR = suma de lo que se cobra REALMENTE cada mes, que es el precio
    # congelado en la suscripción y no el precio de lista del plan: una promo
    # aplicada baja el MRR y ese es justamente el número que hay que mirar.
    # El plan Inicial es pago único, así que no es ingreso recurrente y queda
    # fuera; si entrara, el MRR estaría inflado por clientes que no renuevan.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_dashboard_kpis()
        RETURNS TABLE (
          mrr numeric, mrr_anterior numeric,
          altas_mes bigint, altas_con_promo bigint,
          bajas_mes bigint, cancelaciones bigint, suspensiones bigint,
          activos_total bigint
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
          ini_mes date := date_trunc('month', current_date)::date;
          ini_ant date := (date_trunc('month', current_date) - interval '1 month')::date;
        BEGIN
          PERFORM sa_verificar_rol('dashboard');
          RETURN QUERY SELECT
            (SELECT coalesce(sum(s.precio), 0) FROM suscripciones s
               JOIN planes p ON p.id = s.plan_id
              WHERE s.estado = 'ACTIVA' AND p.codigo <> 'INICIAL'),
            -- El mismo cálculo sobre las suscripciones que ya existían el mes
            -- pasado: sirve para el «+12% vs julio» de la maqueta.
            (SELECT coalesce(sum(s.precio), 0) FROM suscripciones s
               JOIN planes p ON p.id = s.plan_id
              WHERE p.codigo <> 'INICIAL'
                AND s.inicia < ini_mes
                AND (s.termina IS NULL OR s.termina >= ini_ant)),
            (SELECT count(*) FROM tenants WHERE created_at >= ini_mes),
            (SELECT count(DISTINCT pu.tenant_id) FROM promo_uses pu
              WHERE pu.usado_at >= ini_mes),
            (SELECT count(*) FROM suscripciones
              WHERE estado IN ('CANCELADA','SUSPENDIDA') AND updated_at >= ini_mes),
            (SELECT count(*) FROM suscripciones
              WHERE estado = 'CANCELADA' AND updated_at >= ini_mes),
            (SELECT count(*) FROM suscripciones
              WHERE estado = 'SUSPENDIDA' AND updated_at >= ini_mes),
            (SELECT count(*) FROM tenants WHERE estado = 'ACTIVO');
        END $$;
        """
    )

    # Desglose de clientes activos por plan: «2 Independiente · 2 Emprendedor…»
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_dashboard_planes()
        RETURNS TABLE (plan text, clientes bigint)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('dashboard');
          RETURN QUERY
            SELECT p.nombre::text, count(*)
              FROM suscripciones s
              JOIN planes p ON p.id = s.plan_id
              JOIN tenants t ON t.id = s.tenant_id
             WHERE s.estado = 'ACTIVA' AND t.estado = 'ACTIVO'
             GROUP BY p.nombre
             ORDER BY count(*) DESC, p.nombre;
        END $$;
        """
    )

    # Comprobantes emitidos: los tres contadores y las 30 barras del gráfico.
    # Se cuentan los que LLEGARON al SRI (enviados o autorizados): un borrador
    # no es actividad emitida y hincharía la gráfica.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_dashboard_emision()
        RETURNS TABLE (dia date, emitidos bigint)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          PERFORM sa_verificar_rol('dashboard');
          RETURN QUERY
            SELECT d::date,
                   (SELECT count(*) FROM comprobantes c
                     WHERE c.fecha_emision = d::date
                       AND c.estado IN ('ENVIADO_SRI','AUTORIZADO'))
              FROM generate_series(current_date - interval '29 days',
                                   current_date, interval '1 day') AS d
             ORDER BY d;
        END $$;
        """
    )

    # Alertas críticas. Cada fila trae su severidad y la sección a la que hay
    # que ir al pulsar «Ver», para que el botón lleve a algún sitio de verdad.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sa_dashboard_alertas()
        RETURNS TABLE (severidad text, texto text, seccion text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE n bigint;
        BEGIN
          PERFORM sa_verificar_rol('dashboard');

          SELECT count(*) INTO n FROM comprobantes
           WHERE estado IN ('RECHAZADO','DEVUELTO') AND updated_at >= now() - interval '24 hours';
          IF n > 0 THEN
            RETURN QUERY SELECT 'alta'::text,
              (n || ' comprobante' || CASE WHEN n = 1 THEN '' ELSE 's' END ||
               ' rechazado' || CASE WHEN n = 1 THEN '' ELSE 's' END ||
               ' por el SRI en las últimas 24 h')::text, 'comp'::text;
          END IF;

          RETURN QUERY
            SELECT 'alta'::text,
                   ('Firma de ' || t.razon_social || ' vence en ' ||
                    (c.valido_hasta::date - current_date) || ' días')::text,
                   'clientes'::text
              FROM certificados c JOIN tenants t ON t.id = c.tenant_id
             WHERE c.activo AND c.valido_hasta IS NOT NULL
               AND c.valido_hasta::date - current_date BETWEEN 0 AND 30
             ORDER BY c.valido_hasta
             LIMIT 3;

          RETURN QUERY
            SELECT 'media'::text,
                   (t.razon_social || ' con pago vencido hace ' ||
                    (current_date - p.vence_at) || ' días')::text,
                   'pagos'::text
              FROM pagos p JOIN tenants t ON t.id = p.tenant_id
             WHERE p.estado = 'PENDIENTE' AND p.vence_at IS NOT NULL
               AND p.vence_at < current_date
             ORDER BY p.vence_at
             LIMIT 3;

          SELECT count(*) INTO n FROM buzon_correos
           WHERE estado = 'ERROR' AND recibido_at >= now() - interval '24 hours';
          IF n > 0 THEN
            RETURN QUERY SELECT 'media'::text,
              (n || ' correo' || CASE WHEN n = 1 THEN '' ELSE 's' END ||
               ' del buzón sin poder leerse en las últimas 24 h')::text, 'buzon'::text;
          END IF;
        END $$;
        """
    )

    for firma in (
        "sa_dashboard_kpis()",
        "sa_dashboard_planes()",
        "sa_dashboard_emision()",
        "sa_dashboard_alertas()",
    ):
        op.execute(f"ALTER FUNCTION {firma} OWNER TO factuchat_security;")
        op.execute(f"REVOKE ALL ON FUNCTION {firma} FROM PUBLIC;")
        op.execute(f"GRANT EXECUTE ON FUNCTION {firma} TO factuchat_app;")

    # Las funciones nuevas leen tablas que factuchat_security aún no tenía
    op.execute(
        """
        GRANT SELECT ON suscripciones, planes, promo_uses, comprobantes,
                        certificados, pagos TO factuchat_security;
        """
    )


def downgrade() -> None:
    for firma in (
        "sa_dashboard_alertas()",
        "sa_dashboard_emision()",
        "sa_dashboard_planes()",
        "sa_dashboard_kpis()",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {firma}")
