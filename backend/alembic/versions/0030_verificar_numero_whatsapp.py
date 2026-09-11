"""Un número solo factura cuando se prueba que es de quien dice.

Hasta ahora autorizar un teléfono era teclearlo: el panel lo guardaba y el bot
empezaba a facturar desde él en el acto. Nadie comprobaba que ese número fuera
del cliente. Bastaba equivocarse en un dígito para dar de alta el teléfono de un
desconocido, y bastaba querer para dar de alta el de cualquiera.

Ahora el alta deja el número PENDIENTE y emite un código de seis dígitos. El
número factura solo cuando el código vuelve, y vuelve por dos caminos: la
plantilla que Factuchat envía a ese WhatsApp, o un mensaje que esa persona
escribe al bot desde ese teléfono. El segundo no depende de que Meta apruebe
nada y no cuesta nada, así que es el que sostiene el flujo mientras tanto.

TRES DECISIONES QUE VIVEN AQUÍ Y NO EN PYTHON
---------------------------------------------
1. LOS NÚMEROS QUE YA ESTABAN QUEDAN VERIFICADOS. `sys_tenant_por_telefono`
   pasa a exigir `verificado_at`, así que sin este injerto TODOS los clientes
   actuales dejarían de facturar por chat el día del despliegue —incluidos los
   que 0028 dio de alta migrando `tenants.telefono`, que nunca pasaron por el
   panel—. Se dan por buenos: ya venían facturando.

2. EL ÍNDICE ÚNICO GLOBAL PASA A SER PARCIAL, SOLO SOBRE LOS VERIFICADOS. Si
   una fila pendiente ocupara el hueco mundial del teléfono, cualquier cliente
   registrado podría dejar una verificación a medias sobre el número de otra
   empresa y bloqueárselo para siempre, sin llegar a probar nada. Pendiente no
   reserva; verificado sí. Dos empresas pueden tener pendiente el mismo número
   y gana quien demuestre tenerlo.

3. LA VERIFICACIÓN SE RESUELVE EN UNA SOLA SENTENCIA BAJO BLOQUEO, igual que
   los códigos de acceso de 0017. Dos intentos simultáneos no pueden gastar el
   mismo intento dos veces ni verificar dos veces.

Revision ID: 0030
Revises: 0029
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("whatsapp_numeros", sa.Column("verificado_at", sa.DateTime(timezone=True)))
    # Del código solo se guarda su sha256. En claro existe nada más el rato que
    # viaja al WhatsApp de su dueño.
    op.add_column("whatsapp_numeros", sa.Column("codigo_hash", sa.String(64)))
    op.add_column("whatsapp_numeros", sa.Column("codigo_expira", sa.DateTime(timezone=True)))
    op.add_column(
        "whatsapp_numeros",
        sa.Column("codigo_intentos", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("whatsapp_numeros", sa.Column("codigo_enviado_at", sa.DateTime(timezone=True)))

    # Decisión 1: lo que ya facturaba sigue facturando.
    op.execute("UPDATE whatsapp_numeros SET verificado_at = now() WHERE verificado_at IS NULL;")

    # Decisión 2: el hueco mundial lo reserva la posesión probada, no la
    # intención. El índice normal se queda para que la búsqueda del bot siga
    # yendo por índice.
    op.drop_index(op.f("uq_whatsapp_numeros_numero"), table_name="whatsapp_numeros")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_whatsapp_numeros_verificado
          ON whatsapp_numeros (numero) WHERE verificado_at IS NOT NULL;
        """
    )
    op.create_index("ix_whatsapp_numeros_numero", "whatsapp_numeros", ["numero"])

    # La puerta del bot. Es LA línea que hace que la verificación signifique
    # algo: sin el filtro, el número factura desde el mismo INSERT y todo lo
    # demás sería decorado del panel.
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
             AND n.verificado_at IS NOT NULL
             AND t.estado = 'ACTIVO'
           LIMIT 1;
        $$;

        ALTER FUNCTION sys_tenant_por_telefono(text) OWNER TO factuchat_security;
        REVOKE ALL ON FUNCTION sys_tenant_por_telefono(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION sys_tenant_por_telefono(text) TO factuchat_app;
        """
    )

    # Decisión 3. Una sola función para los dos caminos —el panel y el mensaje
    # al bot—, porque las reglas de un código de un solo uso no deben existir
    # en dos sitios. Devuelve:
    #   'ok'        verificado en esta llamada
    #   'no'        el código no coincide; gasta un intento DE QUIEN PREGUNTA
    #   'agotado'   se acabaron los intentos
    #   'expirado'  el código caducó
    #   'ocupado'   otra empresa ya verificó ese mismo teléfono
    #   'nada'      no hay ninguna verificación pendiente para ese número
    op.execute(
        """
        CREATE FUNCTION sys_verificar_numero(
          p_telefono text, p_hash text, p_max_intentos int, p_id uuid DEFAULT NULL
        ) RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_fila whatsapp_numeros%ROWTYPE;
        BEGIN
          -- Si alguien ya lo probó, se acabó para todos los demás.
          IF EXISTS (
            SELECT 1 FROM whatsapp_numeros
             WHERE numero = p_telefono AND verificado_at IS NOT NULL
          ) THEN
            RETURN 'ocupado';
          END IF;

          -- LA FILA LA ELIGE EL CÓDIGO, NO LA ANTIGÜEDAD. Esta función ve las
          -- filas de todos los inquilinos (corre como factuchat_security, que
          -- salta RLS), y dos empresas pueden tener pendiente el mismo teléfono
          -- a propósito. Si eligiera «la más antigua», la fila de un extraño
          -- secuestraría la comprobación del dueño real: sus intentos y su
          -- caducidad mandarían sobre los de él, dejándole el teléfono
          -- inverificable para siempre. Cada fila tiene su propio código, así
          -- que el código dice inequívocamente de quién es el intento.
          SELECT * INTO v_fila
            FROM whatsapp_numeros
           WHERE numero = p_telefono
             AND verificado_at IS NULL
             AND codigo_hash = p_hash
             AND codigo_expira > now()
           FOR UPDATE
           LIMIT 1;

          IF FOUND THEN
            IF v_fila.codigo_intentos >= p_max_intentos THEN
              RETURN 'agotado';
            END IF;
            UPDATE whatsapp_numeros
               SET verificado_at = now(),
                   codigo_hash = NULL,
                   codigo_expira = NULL,
                   codigo_intentos = 0
             WHERE id = v_fila.id;
            RETURN 'ok';
          END IF;

          -- No coincidió con ninguno. El intento se le cobra a QUIEN PREGUNTA,
          -- nunca a un tercero. Desde el panel se sabe quién es (p_id ya viene
          -- filtrado por RLS); desde el chat no hay a quién cobrárselo sin
          -- castigar a otro, y quien escribe es el dueño del teléfono: acertar
          -- solo le daría el número a la empresa que ya lo había pedido.
          IF p_id IS NULL THEN
            RETURN 'nada';
          END IF;

          SELECT * INTO v_fila
            FROM whatsapp_numeros
           WHERE id = p_id AND verificado_at IS NULL
           FOR UPDATE;

          IF NOT FOUND OR v_fila.codigo_hash IS NULL THEN
            RETURN 'nada';
          END IF;

          IF v_fila.codigo_expira IS NULL OR v_fila.codigo_expira <= now() THEN
            RETURN 'expirado';
          END IF;

          IF v_fila.codigo_intentos >= p_max_intentos THEN
            RETURN 'agotado';
          END IF;

          UPDATE whatsapp_numeros
             SET codigo_intentos = codigo_intentos + 1
           WHERE id = v_fila.id;
          RETURN 'no';
        END $$;

        ALTER FUNCTION sys_verificar_numero(text, text, int, uuid)
          OWNER TO factuchat_security;
        REVOKE ALL ON FUNCTION sys_verificar_numero(text, text, int, uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION sys_verificar_numero(text, text, int, uuid) TO factuchat_app;

        -- La función corre como `factuchat_security`, que hasta ahora solo
        -- leía esta tabla: `sys_tenant_por_telefono` no escribe. Esta sí, y
        -- `SELECT ... FOR UPDATE` ya exige el permiso de escritura.
        GRANT UPDATE ON whatsapp_numeros TO factuchat_security;
        """
    )

    # El índice parcial ya no puede decir «no» al dar de alta un teléfono que
    # otra empresa tiene VERIFICADO, porque la fila nueva nace pendiente y no
    # entra en el índice. Sin esto el alta pasaría y el choque saltaría diez
    # minutos después, al teclear el código: tarde y sin explicación.
    #
    # Responde sí o no, nada más. Es la misma información que el 409 de la ruta
    # ya daba antes de 0030, así que no destapa nada nuevo.
    op.execute(
        """
        CREATE FUNCTION sys_numero_ocupado(p_telefono text) RETURNS boolean
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT EXISTS (
            SELECT 1 FROM whatsapp_numeros
             WHERE numero = p_telefono AND verificado_at IS NOT NULL
          );
        $$;

        ALTER FUNCTION sys_numero_ocupado(text) OWNER TO factuchat_security;
        REVOKE ALL ON FUNCTION sys_numero_ocupado(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION sys_numero_ocupado(text) TO factuchat_app;
        """
    )


def downgrade() -> None:
    op.execute("REVOKE UPDATE ON whatsapp_numeros FROM factuchat_security;")
    op.execute("DROP FUNCTION IF EXISTS sys_numero_ocupado(text);")
    op.execute("DROP FUNCTION IF EXISTS sys_verificar_numero(text, text, int, uuid);")
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
    op.drop_index("ix_whatsapp_numeros_numero", table_name="whatsapp_numeros")
    op.execute("DROP INDEX IF EXISTS uq_whatsapp_numeros_verificado;")
    # Volver al único global puede fallar si quedaron duplicados pendientes:
    # se quitan primero, que es justo lo que el índice viejo no permitía. El
    # desempate va por (created_at, id) y no solo por la fecha: dos altas en el
    # mismo milisegundo no se ordenarían entre sí, no se borraría ninguna de las
    # dos y el índice único volvería a no poder crearse.
    op.execute(
        """
        DELETE FROM whatsapp_numeros a
         USING whatsapp_numeros b
         WHERE a.numero = b.numero
           AND (a.created_at, a.id) > (b.created_at, b.id);
        """
    )
    op.create_index(op.f("uq_whatsapp_numeros_numero"), "whatsapp_numeros", ["numero"], unique=True)
    for col in (
        "codigo_enviado_at",
        "codigo_intentos",
        "codigo_expira",
        "codigo_hash",
        "verificado_at",
    ):
        op.drop_column("whatsapp_numeros", col)
