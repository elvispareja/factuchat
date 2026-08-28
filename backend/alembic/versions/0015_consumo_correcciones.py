"""Correcciones al cálculo de costo por cliente, tras revisarlo a fondo.

Cinco defectos reales, todos en el mismo sitio: el dinero.

1. ZONA HORARIA. Postgres arrancaba en UTC mientras la aplicación opera en
   America/Guayaquil. `current_date` y cualquier `timestamptz::date` iban cinco
   horas adelantados, así que durante las últimas cinco horas de cada mes el
   panel daba por empezado el mes siguiente: «Total de agosto» salía en cero el
   31 a las 20:00, justo cuando se mira para facturar. Se corrige en la base
   entera —no solo en esta función— porque el mismo desfase afectaba al
   Dashboard y al cupo del mes en el listado de clientes.

2. LA TARIFA SE BUSCABA SOLO POR PROVEEDOR, no por concepto. Como `POST
   /sa/tarifas` acepta conceptos libres y ya hay dos conceptos bajo
   META_WHATSAPP, bastaba registrar un segundo concepto de INFRA para que TODOS
   los comprobantes pasaran a valorarse con esa tarifa. El resto del proyecto sí
   filtra por las dos columnas (`configuracion.tarifa_vigente`).

3. EMPATE SIN DESEMPATE. `ORDER BY vigente_desde DESC LIMIT 1` con dos filas de
   la misma fecha devolvía una u otra según el plan de ejecución: dos cargas
   seguidas podían dar márgenes distintos. Se añade desempate y, sobre todo, un
   índice único que impide que ese empate llegue a existir.

4. LOS MOROSOS DESAPARECÍAN. El LATERAL solo miraba suscripciones ACTIVA, así
   que un cliente con suscripción MOROSA salía «sin plan», cupo 0 y pagando $0
   —y por tanto etiquetado como «aún no paga», que la pantalla explica como
   periodo de prueba. Un moroso no es una prueba gratuita: es cobro pendiente, y
   además su ingreso desaparecía del total.

Revision ID: 0015
Revises: 0014
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ZONA = "America/Guayaquil"


def upgrade() -> None:
    # --- 1. La base entera pasa a la hora de Ecuador ------------------------
    # Afecta a current_date, now()::date y a todo cast de timestamptz a date,
    # que es lo que usan las funciones sa_* para recortar «este mes» y «hoy».
    op.execute(
        f"""
        DO $$
        BEGIN
          EXECUTE format('ALTER DATABASE %I SET timezone = %L',
                         current_database(), '{ZONA}');
        END $$;
        """
    )

    # --- 3. Que el empate no pueda existir ----------------------------------
    # `planes` ya tenía su equivalente (uq_planes_codigo_vigente_desde); a
    # `cost_rates` se le había olvidado.
    op.execute(
        """
        DELETE FROM cost_rates a
         USING cost_rates b
         WHERE a.proveedor = b.proveedor
           AND a.concepto = b.concepto
           AND a.vigente_desde = b.vigente_desde
           AND a.ctid < b.ctid;
        """
    )
    op.create_index(
        "uq_cost_rates_proveedor_concepto_desde",
        "cost_rates",
        ["proveedor", "concepto", "vigente_desde"],
        unique=True,
    )

    # --- 2 y 4. La función, corregida ---------------------------------------
    # Gana una columna (`suscripcion`), y CREATE OR REPLACE no puede cambiar el
    # tipo de retorno de una función existente.
    op.execute("DROP FUNCTION IF EXISTS sa_consumo_por_cliente();")
    op.execute(
        f"""
        CREATE FUNCTION sa_consumo_por_cliente()
        RETURNS TABLE (
          tenant_id uuid, cliente text, plan text,
          cupo int, usados bigint, comp_whatsapp bigint,
          ia_usados bigint, ia_cupo int,
          costo_wa numeric, costo_ia numeric, costo_infra numeric,
          paga numeric, suscripcion text
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
          -- Explícito aunque la base ya esté en hora de Ecuador: esta función
          -- calcula dinero y no debe depender de cómo venga configurada la
          -- sesión que la llame.
          ini date := date_trunc('month', (now() AT TIME ZONE '{ZONA}'))::date;
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
            coalesce(s.precio, 0),
            coalesce(s.estado::text, 'sin suscripción')
          FROM tenants t
          -- ACTIVA o MOROSA: un moroso sigue teniendo plan y sigue debiendo.
          -- Igual que hace `planes.plan_vigente` en el resto del sistema.
          LEFT JOIN LATERAL (
            SELECT su.plan_id, su.precio, su.estado
              FROM suscripciones su
             WHERE su.tenant_id = t.id AND su.estado IN ('ACTIVA','MOROSA')
             ORDER BY su.inicia DESC, su.created_at DESC
             LIMIT 1
          ) s ON true
          LEFT JOIN planes p ON p.id = s.plan_id
          LEFT JOIN LATERAL (
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE co.origen = 'WHATSAPP') AS por_whatsapp,
                   coalesce(sum(coalesce((
                     SELECT cr.costo_unitario FROM cost_rates cr
                      WHERE cr.proveedor = 'INFRA'
                        AND cr.concepto = 'Emisión de comprobante'
                        AND cr.vigente_desde <= co.fecha_emision
                        AND (cr.vigente_hasta IS NULL OR cr.vigente_hasta > co.fecha_emision)
                      ORDER BY cr.vigente_desde DESC, cr.created_at DESC
                      LIMIT 1), 0)), 0) AS costo_infra
              FROM comprobantes co
             WHERE co.tenant_id = t.id
               AND co.estado IN ('ENVIADO_SRI','AUTORIZADO')
               AND co.fecha_emision >= ini
          ) c ON true
          LEFT JOIN LATERAL (
            SELECT count(*) AS n,
                   coalesce(sum(coalesce((
                     SELECT cr.costo_unitario FROM cost_rates cr
                      WHERE cr.proveedor = 'IA'
                        AND cr.concepto = 'Análisis de comprobante'
                        AND cr.vigente_desde <= (ai.created_at AT TIME ZONE '{ZONA}')::date
                        AND (cr.vigente_hasta IS NULL
                             OR cr.vigente_hasta > (ai.created_at AT TIME ZONE '{ZONA}')::date)
                      ORDER BY cr.vigente_desde DESC, cr.created_at DESC
                      LIMIT 1), 0)), 0) AS costo
              FROM analisis_ia ai
             WHERE ai.tenant_id = t.id
               AND ai.consume
               AND (ai.created_at AT TIME ZONE '{ZONA}')::date >= ini
          ) a ON true
          LEFT JOIN LATERAL (
            SELECT coalesce(sum(wm.costo), 0) AS costo
              FROM whatsapp_msgs wm
             WHERE wm.tenant_id = t.id
               AND (wm.created_at AT TIME ZONE '{ZONA}')::date >= ini
          ) w ON true
          WHERE t.estado = 'ACTIVO'
          ORDER BY t.razon_social;
        END $$;
        """
    )
    op.execute("ALTER FUNCTION sa_consumo_por_cliente() OWNER TO factuchat_security;")
    op.execute("REVOKE ALL ON FUNCTION sa_consumo_por_cliente() FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION sa_consumo_por_cliente() TO factuchat_app;")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          EXECUTE format('ALTER DATABASE %I RESET timezone', current_database());
        END $$;
        """
    )
    op.drop_index("uq_cost_rates_proveedor_concepto_desde", table_name="cost_rates")
    op.execute("DROP FUNCTION IF EXISTS sa_consumo_por_cliente();")
