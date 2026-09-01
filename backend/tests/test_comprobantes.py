"""Lo que el panel pide al backend para pintar el historial y el modal
«Nueva factura»: la columna CLIENTE, la columna DETALLE y el número que le
tocará al comprobante SIN quemar el secuencial.

Aquí no se emite nada: `emitir` encola el pipeline (que en este Windows
arrastra WeasyPrint) y lo que se prueba es justo lo de ANTES de emitir.
"""

import random

from sqlalchemy import event, select

from app.db.models import Comprobante, Secuencial
from app.db.session import get_engine
from app.sri.xml_builder import FORMAS_PAGO
from tests.conftest import TENANT_A, auth_headers

LAPTOP = {
    "codigo": "LAP14",
    "descripcion": 'Laptop 14"',
    "cantidad": "1",
    "precio_unitario": "50.00",
    "codigo_iva": "4",
}


def _item(codigo: str, descripcion: str) -> dict:
    return {**LAPTOP, "codigo": codigo, "descripcion": descripcion, "precio_unitario": "10.00"}


def _cab(tokens: dict) -> dict:
    return auth_headers(tokens["access_token"])


def _crear_cliente(client, tokens, tipo: str = "RUC") -> dict:
    sufijo = random.randint(10_000_000, 99_999_999)
    r = client.post(
        "/api/v1/clientes",
        json={
            "tipo_identificacion": tipo,
            "identificacion": f"09{sufijo}001" if tipo == "RUC" else f"09{sufijo}",
            "razon_social": "Comercial del Pacífico S.A.",
        },
        headers=_cab(tokens),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _crear_factura(client, tokens, cliente_id=None, items=None, **extra) -> dict:
    r = client.post(
        "/api/v1/comprobantes/facturas",
        json={
            "cliente_final_id": cliente_id,
            "items": items or [LAPTOP],
            "forma_pago": "01",
            **extra,
        },
        headers=_cab(tokens),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _fila_del_listado(client, tokens, comprobante_id: str) -> dict:
    r = client.get("/api/v1/comprobantes", headers=_cab(tokens))
    assert r.status_code == 200, r.text
    fila = next((c for c in r.json() if c["id"] == comprobante_id), None)
    assert fila is not None, "el comprobante no apareció en el listado"
    return fila


class TestHistorial:
    def test_listado_trae_cliente_y_detalle(self, client, ana_tokens):
        cliente = _crear_cliente(client, ana_tokens)
        borrador = _crear_factura(
            client,
            ana_tokens,
            cliente_id=cliente["id"],
            items=[LAPTOP, _item("MOU1", "Mouse"), _item("TEC1", "Teclado")],
        )

        fila = _fila_del_listado(client, ana_tokens, borrador["id"])
        assert fila["cliente"] == "Comercial del Pacífico S.A."
        assert fila["cliente_identificacion"] == cliente["identificacion"]
        assert fila["cliente_tipo_id"] == "RUC"  # el front pinta «RUC 09…001»
        assert fila["detalle"] == 'Laptop 14" y 2 más'

    def test_un_solo_item_no_dice_y_0_mas(self, client, ana_tokens):
        cliente = _crear_cliente(client, ana_tokens, tipo="CEDULA")
        borrador = _crear_factura(client, ana_tokens, cliente_id=cliente["id"])

        fila = _fila_del_listado(client, ana_tokens, borrador["id"])
        assert fila["detalle"] == 'Laptop 14"'
        assert fila["cliente_tipo_id"] == "CEDULA"

    def test_consumidor_final_sale_con_cliente_none(self, client, ana_tokens):
        """Sin cliente el historial no puede reventar: cliente en blanco y el
        detalle igual de legible."""
        borrador = _crear_factura(client, ana_tokens)  # sin cliente_final_id

        fila = _fila_del_listado(client, ana_tokens, borrador["id"])
        assert fila["cliente"] is None
        assert fila["cliente_identificacion"] is None
        assert fila["cliente_tipo_id"] is None
        assert fila["detalle"] == 'Laptop 14"'

    def test_una_sola_consulta_para_todo_el_listado(self, client, ana_tokens):
        """El cliente sale del payload de cada fila, así que el listado es UN
        SELECT: con una consulta por comprobante, 100 filas serían 100 viajes."""
        _crear_factura(client, ana_tokens, cliente_id=_crear_cliente(client, ana_tokens)["id"])
        sentencias: list[str] = []

        def _apuntar(conn, cursor, sentencia, *_resto):
            sentencias.append(sentencia)

        motor = get_engine()
        event.listen(motor, "before_cursor_execute", _apuntar)
        try:
            r = client.get("/api/v1/comprobantes", headers=_cab(ana_tokens))
        finally:
            event.remove(motor, "before_cursor_execute", _apuntar)

        assert len(r.json()) > 0
        assert len([s for s in sentencias if "FROM comprobantes" in s]) == 1
        assert not [s for s in sentencias if "FROM clientes_finales" in s]


class TestSiguienteNumero:
    def _secuenciales(self, admin_db) -> list[int]:
        admin_db.rollback()  # transacción nueva: hay que ver lo recién confirmado
        return list(
            admin_db.scalars(
                select(Secuencial.secuencial_actual)
                .where(
                    Secuencial.tenant_id == TENANT_A,
                    Secuencial.tipo_comprobante == "FACTURA",
                )
                .order_by(Secuencial.punto_emision)
            ).all()
        )

    def test_consultarlo_dos_veces_no_consume_secuencial(self, client, ana_tokens, admin_db):
        """Es una VISTA PREVIA. Si reservara, abrir y cerrar el modal dejaría un
        hueco en la numeración, y los huecos son un problema con el SRI."""
        antes = self._secuenciales(admin_db)

        primera = client.get("/api/v1/comprobantes/siguiente-numero", headers=_cab(ana_tokens))
        segunda = client.get("/api/v1/comprobantes/siguiente-numero", headers=_cab(ana_tokens))
        assert primera.status_code == 200, primera.text
        assert primera.json() == segunda.json()

        numero = primera.json()["numero"]
        assert numero.startswith("001-001-") and len(numero.split("-")[2]) == 9
        assert self._secuenciales(admin_db) == antes  # ni se creó la fila ni subió

    def test_el_numero_previsto_es_el_siguiente_real(self, client, ana_tokens, admin_db):
        actuales = self._secuenciales(admin_db)
        r = client.get("/api/v1/comprobantes/siguiente-numero", headers=_cab(ana_tokens))
        assert r.json()["secuencial"] == (actuales[0] if actuales else 0) + 1

    def test_crear_un_borrador_tampoco_lo_mueve(self, client, ana_tokens):
        """El secuencial se asigna al EMITIR, no al guardar el borrador."""
        antes = client.get("/api/v1/comprobantes/siguiente-numero", headers=_cab(ana_tokens))
        _crear_factura(client, ana_tokens)
        despues = client.get("/api/v1/comprobantes/siguiente-numero", headers=_cab(ana_tokens))
        assert antes.json() == despues.json()

    def test_establecimiento_inexistente_es_404(self, client, ana_tokens):
        r = client.get(
            "/api/v1/comprobantes/siguiente-numero?establecimiento=777",
            headers=_cab(ana_tokens),
        )
        assert r.status_code == 404

    def test_no_lo_ve_otro_tenant(self, client, bob_tokens):
        """Empresa B no tiene establecimiento sembrado: no puede leer el
        contador de Empresa A (RLS)."""
        r = client.get("/api/v1/comprobantes/siguiente-numero", headers=_cab(bob_tokens))
        assert r.status_code == 404


class TestFormasDePago:
    def _opciones(self, client, tokens) -> list[dict]:
        r = client.get("/api/v1/comprobantes/formas-pago", headers=_cab(tokens))
        assert r.status_code == 200, r.text
        return r.json()

    def test_catalogo_con_codigos_validos(self, client, ana_tokens):
        opciones = self._opciones(client, ana_tokens)
        assert [o["etiqueta"] for o in opciones] == ["Efectivo", "Transferencia", "Tarjeta"]
        assert all(o["codigo"] in FORMAS_PAGO for o in opciones)  # tabla 24 del SRI
        # Todas al contado: la venta a crédito no se ofrece por ahora.
        assert all(o["plazo_dias"] is None for o in opciones)

    def test_el_plazo_sigue_soportado_aunque_no_se_ofrezca(self, client, ana_tokens, admin_db):
        """El crédito salió del panel, pero la maquinaria sigue en pie.

        Un plazo NO es una forma de pago de la tabla 24: viaja como el código de
        pago que sea más un <plazo>/<unidadTiempo> en el XML. Se comprueba por la
        API para que, cuando se vuelva a ofrecer venta a crédito, sea añadir una
        opción y nada más.
        """
        borrador = _crear_factura(
            client,
            ana_tokens,
            forma_pago="01",
            plazo_dias=30,
        )
        admin_db.rollback()
        payload = admin_db.scalars(
            select(Comprobante.payload).where(Comprobante.id == borrador["id"])
        ).one()
        assert payload["forma_pago"] == "01"
        assert payload["plazo_dias"] == 30  # llega al XML como <plazo>30</plazo>
