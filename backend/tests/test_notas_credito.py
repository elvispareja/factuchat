"""La nota de crédito: la única forma de deshacer una factura ya autorizada.

Lo que se prueba aquí no es el formulario, es lo que hay DETRÁS: que la factura
de origen exista, sea del propio negocio, esté autorizada, vaya al mismo cliente
y —sobre todo— que no se pueda acreditar más de lo que esa factura vale. Sin ese
tope se puede anular 900 de una factura de 689, y eso el SRI lo rechaza; o peor,
lo acepta y la contabilidad queda descuadrada para siempre.

Como en test_comprobantes.py, aquí no se emite nada: se crea el borrador. La
emisión es POST /comprobantes/{id}/emitir, que ya sirve para cualquier tipo.
"""

import random
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import ClienteFinal, Comprobante, Tenant
from app.db.models.enums import (
    AmbienteSRI,
    EstadoComprobante,
    TipoComprobante,
    TipoIdentificacion,
)
from tests.conftest import TENANT_A, TENANT_B, auth_headers

# 50.00 + 15% = 57.50. Dos líneas así son la factura de 115.00 que se acredita.
LINEA = {
    "codigo": "LAP14",
    "descripcion": 'Laptop 14"',
    "cantidad": "1",
    "precio_unitario": "50.00",
    "codigo_iva": "4",
}


def _cab(tokens: dict) -> dict:
    return auth_headers(tokens["access_token"])


class Siembra:
    """Clientes y facturas puestos DIRECTAMENTE en la base, no por la API.

    Dos motivos. Uno: el pipeline de emisión no se puede recorrer aquí (habla
    con el SRI y con un worker) y lo que hace falta es el estado final, una
    factura AUTORIZADA contra la que acreditar. Dos: el plan gratuito solo deja
    guardar 20 clientes en toda la sesión, así que dar de alta uno por test
    agotaría el cupo y reventaría los tests de OTROS archivos con un 402 ajeno.
    """

    def __init__(self, db):
        self.db = db
        self.creados: list[Comprobante | ClienteFinal] = []

    def cliente(self, tenant_id=TENANT_A, razon_social="Comercial del Pacífico S.A.") -> dict:
        cli = ClienteFinal(
            tenant_id=tenant_id,
            tipo_identificacion=TipoIdentificacion.RUC,
            identificacion=f"09{random.randint(10_000_000, 99_999_999)}001",
            razon_social=razon_social,
        )
        self.db.add(cli)
        self.db.commit()
        self.creados.append(cli)
        return {
            "id": str(cli.id),
            "identificacion": cli.identificacion,
            "razon_social": cli.razon_social,
        }

    def factura(
        self,
        tenant_id=TENANT_A,
        cliente: dict | None = None,
        total: str = "115.00",
        estado: EstadoComprobante = EstadoComprobante.AUTORIZADO,
        items: list[dict] | None = None,
    ) -> Comprobante:
        bruto = Decimal(total)
        subtotal = (bruto / Decimal("1.15")).quantize(Decimal("0.01"))
        comp = Comprobante(
            tenant_id=tenant_id,
            tipo=TipoComprobante.FACTURA,
            estado=estado,
            ambiente=AmbienteSRI.PRUEBAS,
            establecimiento="001",
            punto_emision="001",
            secuencial=random.randint(500_000, 899_999),
            clave_acceso=f"nc{random.randint(10**20, 10**21 - 1)}".ljust(49, "0"),
            cliente_final_id=uuid.UUID(cliente["id"]) if cliente else None,
            fecha_emision=date(2026, 2, 10),
            subtotal=subtotal,
            iva=bruto - subtotal,
            total=bruto,
            payload={
                "comprador": {
                    "tipo_identificacion_codigo": "04" if cliente else "07",
                    "razon_social": cliente["razon_social"] if cliente else "CONSUMIDOR FINAL",
                    "identificacion": cliente["identificacion"] if cliente else "9999999999999",
                    "email": None,
                },
                "items": items or [],
                "totales": {},
            },
        )
        self.db.add(comp)
        self.db.commit()
        self.creados.append(comp)
        return comp


@pytest.fixture()
def siembra(admin_db):
    s = Siembra(admin_db)
    yield s

    admin_db.rollback()
    # En orden inverso: la factura arrastra sus notas de crédito (FK ON DELETE
    # CASCADE) y el cliente tiene que irse después de los comprobantes.
    for fila in reversed(s.creados):
        vivo = admin_db.get(type(fila), fila.id)
        if vivo is not None:
            admin_db.delete(vivo)
    admin_db.commit()


def _numero(comp: Comprobante) -> str:
    return f"{comp.establecimiento}-{comp.punto_emision}-{comp.secuencial:09d}"


def _nota(client, tokens, **cuerpo):
    return client.post(
        "/api/v1/comprobantes/notas-credito",
        json={"motivo": "Producto devuelto por el cliente", **cuerpo},
        headers=_cab(tokens),
    )


def _acreditables(client, tokens) -> dict[str, dict]:
    r = client.get("/api/v1/comprobantes/acreditables", headers=_cab(tokens))
    assert r.status_code == 200, r.text
    return {f["id"]: f for f in r.json()}


class TestCaminoFeliz:
    def test_crea_el_borrador_con_los_datos_de_la_factura(
        self, client, ana_tokens, admin_db, siembra
    ):
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)

        r = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            items=[LINEA],
        )
        assert r.status_code == 201, r.text
        nota = r.json()
        assert nota["tipo"] == "NOTA_CREDITO"
        assert nota["estado"] == "PENDIENTE"  # borrador: emitir es otro paso
        assert nota["total"] == "57.50"  # calculado en servidor, no enviado
        assert nota["numero"] is None  # el secuencial se asigna al emitir

        admin_db.rollback()
        fila = admin_db.get(Comprobante, uuid.UUID(nota["id"]))
        assert fila.comprobante_modificado_id == factura.id
        assert fila.payload["motivo"] == "Producto devuelto por el cliente"
        # El XML tiene que citar el número y la fecha que el SRI autorizó
        assert fila.payload["doc_modificado"] == {
            "cod_doc": "01",
            "numero": _numero(factura),
            "fecha": "2026-02-10",
        }

    def test_el_numero_tecleado_no_gana_al_de_la_factura(
        self, client, ana_tokens, admin_db, siembra
    ):
        """Con factura_id la factura es la fuente de la verdad: lo que venga
        escrito en doc_modificado se descarta, no se cita un número inventado."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)

        r = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            doc_modificado={"numero": "009-009-000000999", "fecha": "2020-01-01"},
            items=[LINEA],
        )
        assert r.status_code == 201, r.text
        admin_db.rollback()
        fila = admin_db.get(Comprobante, uuid.UUID(r.json()["id"]))
        assert fila.payload["doc_modificado"]["numero"] == _numero(factura)
        assert fila.payload["doc_modificado"]["fecha"] == "2026-02-10"

    def test_factura_de_otro_sistema_solo_pide_formato(
        self, client, ana_tokens, admin_db, siembra
    ):
        """Tecleada a mano no hay contra qué validar: se acepta con el número y
        la fecha que den, y sin enlace a ninguna factura del sistema."""
        cliente = siembra.cliente()
        r = _nota(
            client,
            ana_tokens,
            cliente_final_id=cliente["id"],
            doc_modificado={"numero": "001-001-000000123", "fecha": "2026-01-15"},
            items=[LINEA],
        )
        assert r.status_code == 201, r.text
        admin_db.rollback()
        fila = admin_db.get(Comprobante, uuid.UUID(r.json()["id"]))
        assert fila.comprobante_modificado_id is None
        assert fila.payload["doc_modificado"]["numero"] == "001-001-000000123"
        admin_db.delete(fila)  # no cuelga de ninguna factura sembrada
        admin_db.commit()

    def test_el_pie_del_modal_numera_aparte_de_las_facturas(self, client, ana_tokens):
        """La nota tiene su propia serie: /siguiente-numero ya acepta el tipo,
        así que el pie del modal funciona sin tocar nada."""
        r = client.get(
            "/api/v1/comprobantes/siguiente-numero?tipo=NOTA_CREDITO", headers=_cab(ana_tokens)
        )
        assert r.status_code == 200, r.text
        assert r.json()["numero"].startswith("001-001-")

    def test_sin_numero_ni_factura_no_hay_nota(self, client, ana_tokens):
        r = _nota(client, ana_tokens, items=[LINEA])
        assert r.status_code == 422, r.text

    def test_el_numero_mal_formado_se_rechaza(self, client, ana_tokens):
        r = _nota(
            client,
            ana_tokens,
            items=[LINEA],
            doc_modificado={"numero": "1-1-123", "fecha": "2026-01-15"},
        )
        assert r.status_code == 422, r.text

    def test_el_motivo_va_impreso_asi_que_tiene_que_decir_algo(self, client, ana_tokens):
        for basura in ("x", "   ", "....."):
            r = client.post(
                "/api/v1/comprobantes/notas-credito",
                json={
                    "motivo": basura,
                    "items": [LINEA],
                    "doc_modificado": {"numero": "001-001-000000123", "fecha": "2026-01-15"},
                },
                headers=_cab(ana_tokens),
            )
            assert r.status_code == 422, f"«{basura}» no debería pasar: {r.text}"


class TestContraLaFacturaDeOrigen:
    def test_no_se_puede_acreditar_mas_de_lo_que_vale(self, client, ana_tokens, siembra):
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, total="115.00")

        r = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            items=[LINEA, LINEA, LINEA],  # 172.50 sobre una factura de 115.00
        )
        assert r.status_code == 422, r.text
        assert "115.00" in r.json()["detail"] and "172.50" in r.json()["detail"]

    def test_lo_ya_emitido_reduce_el_tope(self, client, ana_tokens, siembra):
        """Segunda nota: el tope no es el total de la factura, es lo que queda."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, total="115.00")
        comun = {"factura_id": str(factura.id), "cliente_final_id": cliente["id"]}

        assert _nota(client, ana_tokens, items=[LINEA], **comun).status_code == 201
        # Quedan 57.50; pedir 115.00 más ya no cabe
        r = _nota(client, ana_tokens, items=[LINEA, LINEA], **comun)
        assert r.status_code == 422, r.text
        assert "57.50" in r.json()["detail"]
        # Pero lo que sí cabe pasa
        assert _nota(client, ana_tokens, items=[LINEA], **comun).status_code == 201

    def test_factura_ya_anulada_del_todo_es_400(self, client, ana_tokens, siembra):
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, total="57.50")
        comun = {"factura_id": str(factura.id), "cliente_final_id": cliente["id"]}

        assert _nota(client, ana_tokens, items=[LINEA], **comun).status_code == 201
        r = _nota(client, ana_tokens, items=[LINEA], **comun)
        assert r.status_code == 400, r.text
        assert "acreditada por completo" in r.json()["detail"]

    def test_no_autorizada_no_se_corrige(self, client, ana_tokens, siembra):
        """Lo que el SRI no aceptó no existe: no hay nada que deshacer."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, estado=EstadoComprobante.PENDIENTE)

        r = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            items=[LINEA],
        )
        assert r.status_code == 422, r.text
        assert "AUTORIZADA" in r.json()["detail"]

    def test_el_cliente_tiene_que_ser_el_de_la_factura(self, client, ana_tokens, siembra):
        cliente = siembra.cliente()
        otro = siembra.cliente(razon_social="Otro Comercio Cía. Ltda.")
        factura = siembra.factura(cliente=cliente)

        r = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=otro["id"],
            items=[LINEA],
        )
        assert r.status_code == 422, r.text
        assert "mismo cliente" in r.json()["detail"]

    def test_consumidor_final_tambien_tiene_que_coincidir(self, client, ana_tokens, siembra):
        """La factura fue a consumidor final: su nota no puede ir a un cliente
        con nombre y apellidos."""
        factura = siembra.factura(cliente=None)
        cliente = siembra.cliente()

        r = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            items=[LINEA],
        )
        assert r.status_code == 422, r.text

    def test_la_factura_de_otro_negocio_no_existe(self, client, ana_tokens, siembra):
        """La FK de Postgres NO respeta RLS: si la pertenencia no se comprobara
        en el servicio, Empresa A podría acreditar una factura de Empresa B."""
        ajena = siembra.factura(tenant_id=TENANT_B)

        r = _nota(client, ana_tokens, factura_id=str(ajena.id), items=[LINEA])
        assert r.status_code == 422, r.text
        assert "no existe" in r.json()["detail"]

    def test_un_id_inventado_tampoco(self, client, ana_tokens):
        r = _nota(client, ana_tokens, factura_id=str(uuid.uuid4()), items=[LINEA])
        assert r.status_code == 422, r.text


class TestAcreditables:
    def test_lista_la_factura_con_su_saldo(self, client, ana_tokens, siembra):
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, total="115.00")

        fila = _acreditables(client, ana_tokens)[str(factura.id)]
        assert fila["numero"] == _numero(factura)
        assert fila["fecha_emision"] == "2026-02-10"
        assert fila["cliente"] == "Comercial del Pacífico S.A."
        assert fila["cliente_final_id"] == cliente["id"]  # el modal precarga con él
        assert (fila["total"], fila["pendiente"]) == ("115.00", "115.00")
        assert Decimal(fila["acreditado"]) == 0

    def test_descuenta_lo_ya_emitido_y_desaparece_al_agotarse(self, client, ana_tokens, siembra):
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, total="115.00")
        comun = {"factura_id": str(factura.id), "cliente_final_id": cliente["id"]}

        assert _nota(client, ana_tokens, items=[LINEA], **comun).status_code == 201
        fila = _acreditables(client, ana_tokens)[str(factura.id)]
        assert (fila["acreditado"], fila["pendiente"]) == ("57.50", "57.50")

        assert _nota(client, ana_tokens, items=[LINEA], **comun).status_code == 201
        # Sin saldo ya no es acreditable: no se ofrece lo que no se puede hacer
        assert str(factura.id) not in _acreditables(client, ana_tokens)

    def test_un_borrador_de_nota_ya_reserva_su_importe(
        self, client, ana_tokens, siembra, admin_db
    ):
        """La nota recién creada aún no la autorizó el SRI, pero si no contara,
        dos borradores por el total pasarían los dos y se acreditaría el doble."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, total="115.00")
        nota = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            items=[LINEA],
        ).json()

        admin_db.rollback()
        assert (
            admin_db.get(Comprobante, uuid.UUID(nota["id"])).estado
            == EstadoComprobante.PENDIENTE
        )
        assert _acreditables(client, ana_tokens)[str(factura.id)]["acreditado"] == "57.50"

    def test_una_nota_rechazada_devuelve_el_saldo(self, client, ana_tokens, siembra, admin_db):
        """Lo que el SRI rechazó no existe para el fisco: bloquear el saldo por
        una nota muerta dejaría la factura sin poder corregirse nunca."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente, total="115.00")
        nota = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            items=[LINEA],
        ).json()

        admin_db.rollback()
        admin_db.get(Comprobante, uuid.UUID(nota["id"])).estado = EstadoComprobante.RECHAZADO
        admin_db.commit()

        assert _acreditables(client, ana_tokens)[str(factura.id)]["pendiente"] == "115.00"

    def test_solo_facturas_autorizadas_del_propio_negocio(self, client, ana_tokens, siembra):
        borrador = siembra.factura(estado=EstadoComprobante.PENDIENTE)
        ajena = siembra.factura(tenant_id=TENANT_B)
        autorizada = siembra.factura()

        filas = _acreditables(client, ana_tokens)
        assert str(autorizada.id) in filas
        assert str(borrador.id) not in filas
        assert str(ajena.id) not in filas

    def test_devuelve_las_lineas_para_precargar_la_nota(self, client, ana_tokens, siembra):
        """Sin las líneas, el modal no puede distinguir anular de corregir.

        Salen del snapshot del payload y con los mismos nombres que acepta
        POST /notas-credito: lo que se devuelve aquí se le puede volver a mandar
        tal cual, sin traducir nada por el camino.
        """
        cliente = siembra.cliente()
        factura = siembra.factura(
            cliente=cliente,
            items=[
                {
                    **LINEA,
                    "descuento": "0",
                    "tarifa_iva": "15.00",
                    "total_sin_impuesto": "50.00",
                    "valor_iva": "7.50",
                }
            ],
        )

        (item,) = _acreditables(client, ana_tokens)[str(factura.id)]["items"]
        assert item == {
            "codigo": "LAP14",
            "descripcion": 'Laptop 14"',
            "cantidad": "1",
            "precio_unitario": "50.00",
            # La rebaja viaja: sin ella la nota se precarga con el precio de
            # tarifa y no con lo que el cliente pagó, y una venta rebajada no se
            # puede ni anular porque la nota nace pasándose del pendiente.
            "descuento": "0",
            "codigo_iva": "4",
            "tarifa_iva": "15.00",
        }
        # Y con esas mismas líneas se crea la nota que anula la factura entera.
        assert (
            _nota(
                client,
                ana_tokens,
                factura_id=str(factura.id),
                cliente_final_id=cliente["id"],
                items=[item],
            ).status_code
            == 201
        )

    def test_una_factura_vieja_sin_lineas_no_revienta(self, client, ana_tokens, siembra):
        """El payload es un JSONB: nada garantiza que una fila antigua las tenga,
        y el listado no puede caerse entero por eso."""
        factura = siembra.factura(items=[{"codigo": "X", "descripcion": "Servicio"}])

        (item,) = _acreditables(client, ana_tokens)[str(factura.id)]["items"]
        assert (item["codigo"], item["cantidad"], item["tarifa_iva"]) == ("X", "", "")

    def test_una_nota_de_credito_no_es_acreditable(self, client, ana_tokens, siembra):
        """Solo se acreditan facturas: una nota no se corrige con otra nota."""
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)
        nota = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            items=[LINEA],
        ).json()

        assert nota["id"] not in _acreditables(client, ana_tokens)


class TestElXmlSaleDeLaNota:
    def test_el_payload_alimenta_a_construir_nota_credito(
        self, client, ana_tokens, admin_db, siembra
    ):
        """El pipeline arma el XML desde el payload: si al snapshot le faltara
        algo, el fallo saldría en el worker y no aquí. Se comprueba entero."""
        from app.services.emision import datos_para_xml
        from app.sri.xml_builder import construir_nota_credito

        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)
        nota = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            items=[LINEA],
        ).json()

        admin_db.rollback()
        comp = admin_db.get(Comprobante, uuid.UUID(nota["id"]))
        # Lo que pone `emitir` antes de firmar; aquí se simula para no arrancar
        # el pipeline (que habla con el SRI).
        comp.secuencial, comp.clave_acceso = 7, "7" * 49
        comp.establecimiento, comp.punto_emision = "001", "001"

        emisor, nc = datos_para_xml(admin_db.get(Tenant, TENANT_A), comp)
        xml = construir_nota_credito(emisor, nc).decode()
        assert "<codDoc>04</codDoc>" in xml
        assert f"<numDocModificado>{_numero(factura)}</numDocModificado>" in xml
        assert "<fechaEmisionDocSustento>10/02/2026</fechaEmisionDocSustento>" in xml
        assert "<motivo>Producto devuelto por el cliente</motivo>" in xml
        assert "<valorModificacion>57.50</valorModificacion>" in xml
        admin_db.rollback()  # los cambios de arriba no se guardan


class TestNoSePuedeAcreditarDosVeces:
    """Los dos caminos por los que se colaba el doble de lo facturado."""

    def test_teclear_el_numero_a_mano_no_saltea_el_tope(
        self, client, ana_tokens, siembra
    ):
        """«La factura es de otro sistema» no es una puerta trasera.

        Si el número tecleado corresponde a una factura NUESTRA, se le aplican
        los mismos controles que si se hubiera elegido del historial. Antes solo
        se validaba el formato, así que bastaba con teclear el número de una
        factura ya acreditada para volver a acreditarla entera.
        """
        cliente = siembra.cliente()
        factura = siembra.factura(cliente=cliente)  # 115.00

        # Se acredita por completo, del modo normal
        r = _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            items=[LINEA, LINEA],
        )
        assert r.status_code == 201, r.text

        # Y ahora por el camino manual, con el MISMO número
        r = _nota(
            client,
            ana_tokens,
            cliente_final_id=cliente["id"],
            items=[LINEA],
            doc_modificado={"numero": _numero(factura), "fecha": str(factura.fecha_emision)},
        )
        assert r.status_code == 400, r.text
        assert "acreditada" in r.json()["detail"].lower()

    def test_una_factura_ajena_de_verdad_si_pasa(self, client, ana_tokens, siembra):
        """El caso legítimo sigue abierto: un número que NO es nuestro no se
        puede validar contra nada, y eso es lo inevitable, no un agujero."""
        cliente = siembra.cliente()
        r = _nota(
            client,
            ana_tokens,
            cliente_final_id=cliente["id"],
            items=[LINEA],
            doc_modificado={"numero": "009-009-000000999", "fecha": "2026-01-15"},
        )
        assert r.status_code == 201, r.text


def test_una_venta_rebajada_se_puede_anular_entera(client, ana_tokens, siembra):
    """La rebaja de la factura viaja en la precarga, y sin ella no se puede anular.

    Una línea de 1 × $100,00 con $20,00 de descuento se cobró por $92,00. Si la
    precarga se olvida del descuento, la nota nace sumando $115,00 y se pasa del
    pendiente: el botón sale apagado nada más elegir la factura y esa venta se
    queda sin forma de anularse. Peor en una nota PARCIAL, donde el tope mira el
    total de la factura y no la línea: ahí no frena nada y devuelve de más.
    """
    cliente = siembra.cliente()
    factura = siembra.factura(
        cliente=cliente,
        total="92.00",
        items=[
            {
                **LINEA,
                "precio_unitario": "100.00",
                "descuento": "20.00",
                "tarifa_iva": "15.00",
                "total_sin_impuesto": "80.00",
                "valor_iva": "12.00",
            }
        ],
    )

    fila = _acreditables(client, ana_tokens)[str(factura.id)]
    assert fila["pendiente"] == "92.00"
    (item,) = fila["items"]
    assert item["descuento"] == "20.00"

    # Con la línea tal cual llega, la nota cuadra con lo que se cobró.
    r = _nota(
        client,
        ana_tokens,
        factura_id=str(factura.id),
        cliente_final_id=cliente["id"],
        items=[item],
    )
    assert r.status_code == 201, r.text
    assert r.json()["total"] == "92.00"

    # Y sin el descuento se habría pasado del pendiente, que es lo que pasaba.
    sin_rebaja = {k: v for k, v in item.items() if k != "descuento"}
    assert (
        _nota(
            client,
            ana_tokens,
            factura_id=str(factura.id),
            cliente_final_id=cliente["id"],
            items=[sin_rebaja],
        ).status_code
        == 400  # «no puedes acreditar más de…»: el tope, no un fallo de formato
    )
