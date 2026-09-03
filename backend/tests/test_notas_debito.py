"""La nota de débito: cobrar un recargo sobre una factura ya autorizada.

La hermana de la nota de crédito al revés. Aquella resta —y por eso lo que más
se prueba allí es el TOPE, que no se acredite más de lo facturado—; esta suma, y
ahí no hay tope que valga: un interés por mora sobre una factura de $100 impagada
durante dos años puede ser cualquier cifra. Lo que sí hay que probar es contra
QUÉ se cobra: que la factura exista, sea del propio negocio, esté autorizada y
sea del mismo cliente, incluso cuando el número llega tecleado a mano.

Como en test_notas_credito.py, aquí no se emite nada: se crea el borrador.
"""

import uuid
from decimal import Decimal

import pytest

from app.db.models import Comprobante, Tenant
from app.db.models.enums import EstadoComprobante
from tests.conftest import TENANT_A, TENANT_B, auth_headers

# La siembra es la MISMA que la de la nota de crédito (clientes y facturas
# puestos directamente en la base, porque el pipeline habla con el SRI y el cupo
# de clientes del plan gratuito no da para uno por test). Se importa en vez de
# copiarla: si cambia la forma de sembrar una factura, cambia en un solo sitio.
from tests.test_notas_credito import Siembra, _numero

MOTIVO = "Interés por mora de 60 días"


def _cab(tokens: dict) -> dict:
    return auth_headers(tokens["access_token"])


@pytest.fixture()
def siembra(admin_db):
    s = Siembra(admin_db)
    yield s

    admin_db.rollback()
    # En orden inverso: la factura arrastra sus notas (FK ON DELETE CASCADE) y el
    # cliente tiene que irse después de los comprobantes.
    for fila in reversed(s.creados):
        vivo = admin_db.get(type(fila), fila.id)
        if vivo is not None:
            admin_db.delete(vivo)
    admin_db.commit()


def _nota(client, tokens, valor="20.00", **cuerpo):
    return client.post(
        "/api/v1/comprobantes/notas-debito",
        json={"motivo": MOTIVO, "valor_recargo": valor, **cuerpo},
        headers=_cab(tokens),
    )


def _elegibles(client, tokens, **params) -> dict[str, dict]:
    r = client.get("/api/v1/comprobantes/acreditables", params=params, headers=_cab(tokens))
    assert r.status_code == 200, r.text
    return {f["id"]: f for f in r.json()}


class TestCaminoFeliz:
    def test_crea_el_borrador_con_los_datos_de_la_factura(
        self, client, ana_tokens, admin_db, siembra
    ):
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)

        r = _nota(
            client, ana_tokens, factura_id=str(factura.id), cliente_final_id=cliente["id"]
        )
        assert r.status_code == 201, r.text
        nota = r.json()
        assert nota["tipo"] == "NOTA_DEBITO"
        assert nota["estado"] == "PENDIENTE"  # borrador: emitir es otro paso
        assert nota["numero"] is None  # el secuencial se asigna al emitir

        admin_db.rollback()
        fila = admin_db.get(Comprobante, uuid.UUID(nota["id"]))
        assert fila.comprobante_modificado_id == factura.id
        # El XML tiene que citar el número y la fecha que el SRI autorizó
        assert fila.payload["doc_modificado"] == {
            "cod_doc": "01",
            "numero": _numero(factura),
            "fecha": "2026-02-10",
        }
        # El XML pide los motivos en LISTA, con su valor sin impuestos
        assert fila.payload["motivos"] == [{"razon": MOTIVO, "valor": "17.39"}]

    def test_el_valor_tecleado_es_lo_que_se_cobra_con_iva_dentro(
        self, client, ana_tokens, siembra
    ):
        """Quien teclea 20.00 quiere cobrar 20.00, no 20.00 + IVA: el servidor
        desglosa 17.39 de base y 2.61 de IVA."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)

        nota = _nota(
            client, ana_tokens, valor="20.00", factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
        ).json()
        assert (nota["subtotal"], nota["iva"], nota["total"]) == ("17.39", "2.61", "20.00")

    def test_hay_importes_que_salen_a_un_centavo(self, client, ana_tokens, siembra):
        """Decidido, no accidental: el IVA se redondea al céntimo y el SRI
        recalcula base×tarifa, así que 10.00 no es expresable con IVA dentro
        (8.70 + 1.31). Se cobra el total del documento, que la pantalla de
        revisión enseña antes de emitir."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)

        nota = _nota(
            client, ana_tokens, valor="10.00", factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
        ).json()
        assert (nota["subtotal"], nota["iva"], nota["total"]) == ("8.70", "1.31", "10.01")

    def test_el_recargo_no_lleva_lineas_de_producto(self, client, ana_tokens, siembra):
        """Una nota de débito no vende nada: no se le mandan items y el motivo es
        lo que describe el cobro en el RIDE y en el historial."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)

        nota = _nota(
            client, ana_tokens, factura_id=str(factura.id), cliente_final_id=cliente["id"]
        ).json()
        assert nota["detalle"] == MOTIVO

    def test_sin_numero_ni_factura_no_hay_nota(self, client, ana_tokens):
        assert _nota(client, ana_tokens).status_code == 422

    def test_el_motivo_va_impreso_asi_que_tiene_que_decir_algo(self, client, ana_tokens):
        for basura in ("x", "   ", "....."):
            r = _nota(
                client,
                ana_tokens,
                motivo=basura,
                doc_modificado={"numero": "001-001-000000123", "fecha": "2026-01-15"},
            )
            assert r.status_code == 422, f"«{basura}» no debería pasar: {r.text}"

    def test_un_recargo_de_cero_no_es_un_recargo(self, client, ana_tokens):
        r = _nota(
            client,
            ana_tokens,
            valor="0",
            doc_modificado={"numero": "001-001-000000123", "fecha": "2026-01-15"},
        )
        assert r.status_code == 422, r.text

    def test_el_pie_del_modal_numera_aparte(self, client, ana_tokens):
        """La nota de débito tiene su propia serie: /siguiente-numero ya acepta el
        tipo, así que el pie del modal funciona sin tocar nada."""
        r = client.get(
            "/api/v1/comprobantes/siguiente-numero?tipo=NOTA_DEBITO", headers=_cab(ana_tokens)
        )
        assert r.status_code == 200, r.text
        assert r.json()["numero"].startswith("001-001-")


class TestContraLaFacturaDeOrigen:
    def test_el_recargo_no_esta_limitado_por_el_total_de_la_factura(
        self, client, ana_tokens, siembra
    ):
        """LA diferencia con la nota de crédito. Acreditar 500 de una factura de
        115 es imposible; cobrar 500 de mora sobre esa misma factura no lo es, y
        copiar el tope de la nota de crédito habría prohibido el caso normal."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, total="115.00")

        r = _nota(
            client, ana_tokens, valor="500.00", factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
        )
        assert r.status_code == 201, r.text
        assert r.json()["total"] == "500.00"

    def test_una_factura_ya_acreditada_del_todo_admite_recargo(
        self, client, ana_tokens, siembra
    ):
        """Anulada por una nota de crédito no significa intocable: el recargo por
        mora de los meses que estuvo impagada se sigue pudiendo cobrar."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, total="57.50")
        comun = {"factura_id": str(factura.id), "cliente_final_id": cliente["id"]}

        # Se acredita entera, y una segunda nota de crédito ya no cabe
        nc = client.post(
            "/api/v1/comprobantes/notas-credito",
            json={
                "motivo": "Producto devuelto por el cliente",
                "items": [
                    {
                        "codigo": "LAP14",
                        "descripcion": 'Laptop 14"',
                        "cantidad": "1",
                        "precio_unitario": "50.00",
                        "codigo_iva": "4",
                    }
                ],
                **comun,
            },
            headers=_cab(ana_tokens),
        )
        assert nc.status_code == 201, nc.text

        assert _nota(client, ana_tokens, **comun).status_code == 201

    def test_no_autorizada_no_se_recarga(self, client, ana_tokens, siembra):
        """Lo que el SRI no aceptó no existe: no hay a qué añadirle un recargo."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, estado=EstadoComprobante.PENDIENTE)

        r = _nota(
            client, ana_tokens, factura_id=str(factura.id), cliente_final_id=cliente["id"]
        )
        assert r.status_code == 422, r.text
        assert "AUTORIZADA" in r.json()["detail"]

    def test_el_cliente_tiene_que_ser_el_de_la_factura(self, client, ana_tokens, siembra):
        cliente = siembra.cliente()
        otro = siembra.cliente(razon_social="Otro Comercio Cía. Ltda.")
        factura = siembra.factura(cliente=cliente)

        r = _nota(client, ana_tokens, factura_id=str(factura.id), cliente_final_id=otro["id"])
        assert r.status_code == 422, r.text
        assert "mismo cliente" in r.json()["detail"]

    def test_consumidor_final_tambien_tiene_que_coincidir(self, client, ana_tokens, siembra):
        factura = siembra.factura(cliente=None)
        cliente = siembra.cliente()

        r = _nota(
            client, ana_tokens, factura_id=str(factura.id), cliente_final_id=cliente["id"]
        )
        assert r.status_code == 422, r.text

    def test_la_factura_de_otro_negocio_no_existe(self, client, ana_tokens, siembra):
        """La FK de Postgres NO respeta RLS: si la pertenencia no se comprobara
        en el servicio, Empresa A podría recargar una factura de Empresa B."""
        ajena = siembra.factura(tenant_id=TENANT_B)

        r = _nota(client, ana_tokens, factura_id=str(ajena.id))
        assert r.status_code == 422, r.text
        assert "no existe" in r.json()["detail"]

    def test_un_id_inventado_tampoco(self, client, ana_tokens):
        assert _nota(client, ana_tokens, factura_id=str(uuid.uuid4())).status_code == 422

    def test_una_nota_de_credito_no_se_recarga(self, client, ana_tokens, siembra):
        """Solo se recargan facturas: el recargo va sobre la venta, no sobre otra
        nota. Se prueba con el propio id de una nota ya creada."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)
        nota = _nota(
            client, ana_tokens, factura_id=str(factura.id), cliente_final_id=cliente["id"]
        ).json()

        r = _nota(
            client, ana_tokens, factura_id=nota["id"], cliente_final_id=cliente["id"]
        )
        assert r.status_code == 422, r.text
        assert "no existe" in r.json()["detail"]


class TestElNumeroTecleadoAMano:
    """«La factura es de otro sistema» no es una puerta trasera.

    Fue un hallazgo bloqueante en la nota de crédito y aquí vale igual: si el
    número corresponde a una factura NUESTRA, se le aplican los mismos controles
    y la nota queda enlazada a ella.
    """

    def test_una_factura_propia_se_valida_igual(self, client, ana_tokens, siembra):
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, estado=EstadoComprobante.PENDIENTE)

        r = _nota(
            client,
            ana_tokens,
            cliente_final_id=cliente["id"],
            doc_modificado={"numero": _numero(factura), "fecha": "2026-02-10"},
        )
        assert r.status_code == 422, r.text
        assert "AUTORIZADA" in r.json()["detail"]

    def test_y_el_cliente_tampoco_se_salta(self, client, ana_tokens, siembra):
        cliente = siembra.cliente()
        otro = siembra.cliente(razon_social="Otro Comercio Cía. Ltda.")
        factura = siembra.factura(cliente=cliente)

        r = _nota(
            client,
            ana_tokens,
            cliente_final_id=otro["id"],
            doc_modificado={"numero": _numero(factura), "fecha": "2026-02-10"},
        )
        assert r.status_code == 422, r.text
        assert "mismo cliente" in r.json()["detail"]

    def test_la_propia_queda_enlazada_y_con_su_fecha_real(
        self, client, ana_tokens, admin_db, siembra
    ):
        """Y la fecha tecleada no gana a la que el SRI autorizó."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)

        r = _nota(
            client,
            ana_tokens,
            cliente_final_id=cliente["id"],
            doc_modificado={"numero": _numero(factura), "fecha": "2020-01-01"},
        )
        assert r.status_code == 201, r.text
        admin_db.rollback()
        fila = admin_db.get(Comprobante, uuid.UUID(r.json()["id"]))
        assert fila.comprobante_modificado_id == factura.id
        assert fila.payload["doc_modificado"]["fecha"] == "2026-02-10"

    def test_una_factura_ajena_de_verdad_si_pasa(self, client, ana_tokens, admin_db, siembra):
        """El caso legítimo sigue abierto: un número que NO es nuestro no se
        puede validar contra nada, y eso es lo inevitable, no un agujero."""
        cliente = siembra.cliente()
        r = _nota(
            client,
            ana_tokens,
            cliente_final_id=cliente["id"],
            doc_modificado={"numero": "009-009-000000999", "fecha": "2026-01-15"},
        )
        assert r.status_code == 201, r.text
        admin_db.rollback()
        fila = admin_db.get(Comprobante, uuid.UUID(r.json()["id"]))
        assert fila.comprobante_modificado_id is None
        admin_db.delete(fila)  # no cuelga de ninguna factura sembrada
        admin_db.commit()


class TestFacturasElegibles:
    def test_sin_saldo_no_admite_credito_pero_si_recargo(self, client, ana_tokens, siembra):
        """El selector de la nota de crédito solo puede ofrecer lo acreditable;
        el de la nota de débito, cualquier factura autorizada. Un parámetro en la
        misma ruta, porque la fila que necesitan los dos es idéntica."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, total="57.50")
        client.post(
            "/api/v1/comprobantes/notas-credito",
            json={
                "motivo": "Producto devuelto por el cliente",
                "factura_id": str(factura.id),
                "cliente_final_id": cliente["id"],
                "items": [
                    {
                        "codigo": "LAP14",
                        "descripcion": 'Laptop 14"',
                        "cantidad": "1",
                        "precio_unitario": "50.00",
                        "codigo_iva": "4",
                    }
                ],
            },
            headers=_cab(ana_tokens),
        )

        assert str(factura.id) not in _elegibles(client, ana_tokens)  # como siempre
        fila = _elegibles(client, ana_tokens, solo_con_saldo="false")[str(factura.id)]
        assert (fila["total"], fila["pendiente"]) == ("57.50", "0.00")
        assert fila["cliente_final_id"] == cliente["id"]  # el modal precarga con él

    def test_sigue_sin_ofrecer_borradores_ni_las_de_otro_negocio(
        self, client, ana_tokens, siembra
    ):
        borrador = siembra.factura(estado=EstadoComprobante.PENDIENTE)
        ajena = siembra.factura(tenant_id=TENANT_B)
        autorizada = siembra.factura()

        filas = _elegibles(client, ana_tokens, solo_con_saldo="false")
        assert str(autorizada.id) in filas
        assert str(borrador.id) not in filas
        assert str(ajena.id) not in filas


class TestElXmlSaleDeLaNota:
    def test_el_payload_alimenta_a_construir_nota_debito(
        self, client, ana_tokens, admin_db, siembra
    ):
        """El pipeline arma el XML desde el payload: si al snapshot le faltara
        algo, el fallo saldría en el worker y no aquí. Se comprueba entero."""
        from app.services.emision import datos_para_xml
        from app.sri.xml_builder import construir_nota_debito

        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)
        nota = _nota(
            client, ana_tokens, factura_id=str(factura.id), cliente_final_id=cliente["id"]
        ).json()

        admin_db.rollback()
        comp = admin_db.get(Comprobante, uuid.UUID(nota["id"]))
        # Lo que pone `emitir` antes de firmar; aquí se simula para no arrancar
        # el pipeline (que habla con el SRI).
        comp.secuencial, comp.clave_acceso = 7, "7" * 49
        comp.establecimiento, comp.punto_emision = "001", "001"

        emisor, nd = datos_para_xml(admin_db.get(Tenant, TENANT_A), comp)
        xml = construir_nota_debito(emisor, nd).decode()
        assert "<codDoc>05</codDoc>" in xml
        assert f"<numDocModificado>{_numero(factura)}</numDocModificado>" in xml
        assert "<fechaEmisionDocSustento>10/02/2026</fechaEmisionDocSustento>" in xml
        # La nota de débito usa valorTotal, no valorModificacion
        assert "<valorTotal>20.00</valorTotal>" in xml
        assert "<totalSinImpuestos>17.39</totalSinImpuestos>" in xml
        # …y una LISTA de motivos, cada uno con su valor sin impuestos
        assert f"<motivos><motivo><razon>{MOTIVO}</razon><valor>17.39</valor>" in xml
        assert "<valor>2.61</valor>" in xml  # el IVA del recargo
        admin_db.rollback()  # los cambios de arriba no se guardan


def test_el_pipeline_ya_sabe_construir_la_nota_de_debito():
    """El despacho por tipo se arregló al hacer la nota de crédito; aquí solo
    faltaba dar de alta el tipo, y si no está el fallo aparece en el worker."""
    from app.db.models.enums import TipoComprobante
    from app.tasks.emision import _BUILDER, _NOMBRE_DOC

    assert TipoComprobante.NOTA_DEBITO in _BUILDER
    assert _NOMBRE_DOC[TipoComprobante.NOTA_DEBITO] == "NOTA DE DÉBITO"


def test_el_total_del_recargo_lo_calcula_el_servidor(client, ana_tokens, siembra):
    """Mandar subtotal o total desde el cliente no cambia nada: campos que el
    esquema no conoce se ignoran y los importes salen del valor del recargo."""
    cliente = siembra.cliente()
    factura = siembra.factura(cliente=cliente)

    nota = _nota(
        client,
        ana_tokens,
        valor="20.00",
        factura_id=str(factura.id),
        cliente_final_id=cliente["id"],
        total="9999.00",
        iva="0.00",
    ).json()
    assert Decimal(nota["total"]) == Decimal("20.00")


def test_el_recargo_entra_en_el_iva_a_pagar(admin_db, siembra):
    """El IVA de una nota de débito es IVA generado: hay que declararlo.

    Si el cuadro fiscal no la cuenta, el negocio cobra ese impuesto y el panel le
    dice que no lo debe —con el comprobante autorizado en el sistema del SRI
    demostrando lo contrario—. La nota de crédito sigue restando, que es lo suyo.
    """
    import random
    from datetime import date

    from app.db.models.enums import AmbienteSRI, TipoComprobante
    from app.services import reportes

    desde, hasta = date(2026, 2, 1), date(2026, 3, 1)
    cliente = siembra.cliente()
    siembra.factura(cliente=cliente, total="115.00")
    antes = reportes.resumen_fiscal(admin_db, TENANT_A, desde, hasta)

    nota = Comprobante(
        tenant_id=TENANT_A,
        tipo=TipoComprobante.NOTA_DEBITO,
        estado=EstadoComprobante.AUTORIZADO,
        ambiente=AmbienteSRI.PRUEBAS,
        establecimiento="001",
        punto_emision="001",
        secuencial=random.randint(900_000, 999_999),
        clave_acceso=f"nd{random.randint(10**20, 10**21 - 1)}".ljust(49, "0"),
        cliente_final_id=uuid.UUID(cliente["id"]),
        fecha_emision=date(2026, 2, 12),
        subtotal=Decimal("17.39"),
        iva=Decimal("2.61"),
        total=Decimal("20.00"),
        payload={"comprador": {"razon_social": cliente["razon_social"]}, "items": []},
    )
    admin_db.add(nota)
    admin_db.commit()
    siembra.creados.append(nota)

    despues = reportes.resumen_fiscal(admin_db, TENANT_A, desde, hasta)
    assert despues.iva_cobrado - antes.iva_cobrado == Decimal("2.61")
    assert despues.a_pagar - antes.a_pagar == Decimal("2.61")
    assert despues.total_facturado - antes.total_facturado == Decimal("20.00")
