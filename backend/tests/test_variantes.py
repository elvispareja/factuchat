"""Variantes: "tengo 2 de la talla 38 y 3 de la 39".

Un producto con varios valores del mismo atributo genera combinaciones, y cada
combinación tiene su propio código (el SKU que va al comprobante) y su propio
stock. Aquí se cubren el camino feliz, los rechazos que evitan inventario
ambiguo (misma combinación dos veces, código repetido), el aislamiento entre
inquilinos —las FK de Postgres saltan RLS, así que el chequeo explícito es lo
único que impide usar el valor de OTRO negocio— y lo que más caro saldría: que
editar un producto no se lleve por delante el inventario.
"""

import random
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import Producto
from tests.conftest import TENANT_A, auth_headers
from tests.test_tienda import con_tienda  # noqa: F401  (fixture: el plan con tienda)

# Todo el archivo corre con el plan que trae tienda e inventario: sin él, el
# cupo de productos del plan por defecto (10) se agota con lo que dejan los
# demás archivos de la suite y las altas devolverían 402 en vez de lo que se
# está midiendo.
pytestmark = pytest.mark.usefixtures("con_tienda")

PRODUCTO_BASE = {
    "codigo": "SKU",
    "nombre": "Air Nike TN",
    "tipo": "BIEN",
    "precio_sin_iva": "50.00",
}


def _codigo(prefijo: str = "SKU") -> str:
    return f"{prefijo}{random.randint(100000, 999999)}"


@pytest.fixture(autouse=True)
def _sin_dejar_rastro(admin_db):
    """Borra los productos que crea cada test: el cupo del plan cuenta
    productos activos, y dejarlos ahí se lo come para el resto de la suite."""
    yield
    admin_db.expire_all()
    for producto in admin_db.scalars(
        select(Producto).where(Producto.tenant_id == TENANT_A, Producto.nombre.like("Air Nike TN%"))
    ).all():
        admin_db.delete(producto)
    admin_db.commit()


@pytest.fixture()
def calzado(client, ana_tokens):
    """Categoría Calzado con Talla=[38,39]: dos valores del mismo atributo."""
    headers = auth_headers(ana_tokens["access_token"])
    r = client.post(
        "/api/v1/categorias",
        json={"nombre": f"Calzado {random.randint(1, 999999)}"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    categoria = r.json()

    r = client.post(
        "/api/v1/atributos",
        json={"categoria_id": categoria["id"], "nombre": "Talla"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    talla = r.json()

    valores = {}
    for v in ("38", "39"):
        r = client.post(
            "/api/v1/atributo-valores",
            json={"atributo_id": talla["id"], "valor": v},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        valores[v] = r.json()

    return {"categoria": categoria, "talla": talla, "valores": valores}


def _body(calzado, **extra) -> dict:
    """Producto con las dos tallas declaradas y una variante por talla."""
    talla = calzado["talla"]["id"]
    cuerpo = {
        **PRODUCTO_BASE,
        "codigo": _codigo(),
        "categoria_id": calzado["categoria"]["id"],
        "atributos": [
            {"atributo_id": talla, "atributo_valor_id": calzado["valores"]["38"]["id"]},
            {"atributo_id": talla, "atributo_valor_id": calzado["valores"]["39"]["id"]},
        ],
        "variantes": [
            {
                "codigo": _codigo("TN38-"),
                "stock": "2",
                "valores": [
                    {"atributo_id": talla, "atributo_valor_id": calzado["valores"]["38"]["id"]}
                ],
            },
            {
                "codigo": _codigo("TN39-"),
                "stock": "3",
                "precio_sin_iva": "60.00",  # la 39 cuesta más
                "valores": [
                    {"atributo_id": talla, "atributo_valor_id": calzado["valores"]["39"]["id"]}
                ],
            },
        ],
    }
    cuerpo.update(extra)
    return cuerpo


class TestCaminoFeliz:
    def test_crea_producto_con_variantes(self, client, ana_tokens, calzado):
        headers = auth_headers(ana_tokens["access_token"])
        body = _body(calzado)
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 201, r.text
        data = r.json()

        # Dos valores del MISMO atributo: lo que antes bloqueaba el UNIQUE viejo
        assert len(data["atributos"]) == 2
        variantes = {v["codigo"]: v for v in data["variantes"]}
        assert len(variantes) == 2
        de_38 = variantes[body["variantes"][0]["codigo"]]
        de_39 = variantes[body["variantes"][1]["codigo"]]
        assert Decimal(de_38["stock"]) == Decimal("2")
        assert Decimal(de_39["stock"]) == Decimal("3")
        assert de_38["precio_sin_iva"] is None  # hereda el del producto
        assert Decimal(de_39["precio_sin_iva"]) == Decimal("60.00")
        assert de_38["valores"] == body["variantes"][0]["valores"]

        # El listado también las arma (relationship, no columna)
        r = client.get("/api/v1/productos", headers=headers)
        assert r.status_code == 200
        listado = {p["id"]: p for p in r.json()}
        assert len(listado[data["id"]]["variantes"]) == 2

    def test_quitar_una_variante_la_borra(self, client, ana_tokens, calzado):
        headers = auth_headers(ana_tokens["access_token"])
        body = _body(calzado)
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 201, r.text
        producto = r.json()

        body["variantes"] = body["variantes"][:1]
        r = client.put(f"/api/v1/productos/{producto['id']}", json=body, headers=headers)
        assert r.status_code == 200, r.text
        assert [v["codigo"] for v in r.json()["variantes"]] == [body["variantes"][0]["codigo"]]


class TestRechazos:
    def test_misma_combinacion_dos_veces(self, client, ana_tokens, calzado):
        body = _body(calzado)
        # La segunda variante pasa a ser también la talla 38: dos stocks para lo
        # mismo, nadie sabría cuál baja al vender.
        body["variantes"][1]["valores"] = body["variantes"][0]["valores"]
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 400
        assert "misma combinación" in r.json()["detail"]

    def test_codigo_repetido_en_el_mismo_cuerpo(self, client, ana_tokens, calzado):
        body = _body(calzado)
        body["variantes"][1]["codigo"] = body["variantes"][0]["codigo"]
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 400
        assert "mismo código" in r.json()["detail"]

    def test_dos_valores_del_mismo_atributo_en_una_variante(self, client, ana_tokens, calzado):
        body = _body(calzado)
        body["variantes"][0]["valores"] = [
            {
                "atributo_id": calzado["talla"]["id"],
                "atributo_valor_id": calzado["valores"]["38"]["id"],
            },
            {
                "atributo_id": calzado["talla"]["id"],
                "atributo_valor_id": calzado["valores"]["39"]["id"],
            },
        ]
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 400
        assert "dos valores del mismo atributo" in r.json()["detail"]

    def test_variantes_sin_categoria(self, client, ana_tokens, calzado):
        body = _body(calzado, categoria_id=None, atributos=[])
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 400
        assert "categoría" in r.json()["detail"].lower()

    def test_servicio_no_tiene_variantes(self, client, ana_tokens, calzado):
        body = _body(calzado, tipo="SERVICIO", categoria_id=None, atributos=[])
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 422

    def test_valor_de_otro_tenant_rechazado(self, client, bob_tokens, calzado):
        """Las FK de Postgres saltan RLS: sin el db.get() explícito, Bob podría
        montar sus variantes sobre las tallas de Ana."""
        headers = auth_headers(bob_tokens["access_token"])
        r = client.post(
            "/api/v1/categorias",
            json={"nombre": f"CalzadoB {random.randint(1, 999999)}"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        categoria_b = r.json()

        body = _body(calzado, categoria_id=categoria_b["id"], atributos=[])
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 400
        assert "atributo" in r.json()["detail"].lower()


class TestElStockSobreviveALaEdicion:
    """Perder el inventario al editar el nombre de un producto sería grave."""

    def test_stock_se_conserva_si_el_cuerpo_no_lo_manda(self, client, ana_tokens, calzado):
        headers = auth_headers(ana_tokens["access_token"])
        body = _body(calzado)
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 201, r.text
        producto = r.json()

        # El formulario reenvía el producto para cambiarle el nombre, sin stock
        body["nombre"] = "Air Nike TN (2026)"
        for v in body["variantes"]:
            v.pop("stock")
        r = client.put(f"/api/v1/productos/{producto['id']}", json=body, headers=headers)
        assert r.status_code == 200, r.text
        stocks = {v["codigo"]: Decimal(v["stock"]) for v in r.json()["variantes"]}
        assert stocks[body["variantes"][0]["codigo"]] == Decimal("2")
        assert stocks[body["variantes"][1]["codigo"]] == Decimal("3")

    def test_stock_se_actualiza_si_el_cuerpo_lo_manda(self, client, ana_tokens, calzado):
        headers = auth_headers(ana_tokens["access_token"])
        body = _body(calzado)
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 201, r.text
        producto = r.json()

        body["variantes"][0]["stock"] = "7"
        r = client.put(f"/api/v1/productos/{producto['id']}", json=body, headers=headers)
        assert r.status_code == 200, r.text
        stocks = {v["codigo"]: Decimal(v["stock"]) for v in r.json()["variantes"]}
        assert stocks[body["variantes"][0]["codigo"]] == Decimal("7")

    def test_cambiar_el_valor_de_una_variante_no_la_recrea(self, client, ana_tokens, calzado):
        """Corregir la talla mantiene la fila (y su stock): se empareja por código."""
        headers = auth_headers(ana_tokens["access_token"])
        body = _body(calzado)
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 201, r.text
        producto = r.json()
        id_original = {v["codigo"]: v["id"] for v in producto["variantes"]}

        codigo_38 = body["variantes"][0]["codigo"]
        body["variantes"][0]["valores"] = body["variantes"][1]["valores"]
        body["variantes"].pop(1)  # si no, quedarían dos variantes con la 39
        for v in body["variantes"]:
            v.pop("stock", None)
        r = client.put(f"/api/v1/productos/{producto['id']}", json=body, headers=headers)
        assert r.status_code == 200, r.text
        variante = r.json()["variantes"][0]
        assert variante["id"] == id_original[codigo_38]
        assert Decimal(variante["stock"]) == Decimal("2")


class TestVentaDeUnaVariante:
    def test_se_vende_y_se_descuenta_la_variante(self, client, ana_tokens, admin_db, calzado):
        from app.db.models import Producto, ProductoVariante

        headers = auth_headers(ana_tokens["access_token"])
        body = _body(calzado, maneja_inventario=True, stock="0", mostrar_en_tienda=True)
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 201, r.text
        producto = r.json()
        de_39 = next(
            v for v in producto["variantes"] if v["codigo"] == body["variantes"][1]["codigo"]
        )

        # La vitrina las publica para poder armar la venta
        r = client.get("/api/v1/tienda/vitrina", headers=headers)
        assert r.status_code == 200, r.text
        en_vitrina = next(p for p in r.json() if p["id"] == producto["id"])
        assert {v["id"] for v in en_vitrina["variantes"]} == {
            v["id"] for v in producto["variantes"]
        }

        # El stock que manda es el de la variante, no el del producto (que es 0)
        r = client.post(
            "/api/v1/tienda/pedidos",
            json={
                "items": [
                    {"producto_id": producto["id"], "variante_id": de_39["id"], "cantidad": "9"}
                ],
                "metodo_pago": "EFECTIVO",
            },
            headers=headers,
        )
        assert r.status_code == 422
        assert "Solo quedan 3" in r.json()["detail"]

        r = client.post(
            "/api/v1/tienda/pedidos",
            json={
                "items": [
                    {"producto_id": producto["id"], "variante_id": de_39["id"], "cantidad": "2"}
                ],
                "metodo_pago": "EFECTIVO",
            },
            headers=headers,
        )
        assert r.status_code == 201, r.text
        pedido = r.json()
        # Precio propio de la variante: 2 × $60, no 2 × $50
        assert Decimal(pedido["subtotal"]) == Decimal("120.00")
        assert pedido["items"][0]["codigo"] == de_39["codigo"]  # el SKU va al comprobante

        r = client.post(f"/api/v1/tienda/pedidos/{pedido['id']}/facturar", headers=headers)
        assert r.status_code == 201, r.text

        admin_db.expire_all()
        variante = admin_db.get(ProductoVariante, uuid.UUID(de_39["id"]))
        assert variante.stock == Decimal("1")  # 3 − 2
        assert admin_db.get(Producto, uuid.UUID(producto["id"])).stock == Decimal("0")

    def test_variante_de_otro_producto_rechazada(self, client, ana_tokens, calzado):
        headers = auth_headers(ana_tokens["access_token"])
        con_variantes = client.post(
            "/api/v1/productos",
            json=_body(calzado, mostrar_en_tienda=True),
            headers=headers,
        ).json()
        otro = client.post(
            "/api/v1/productos",
            json={**PRODUCTO_BASE, "codigo": _codigo(), "mostrar_en_tienda": True},
            headers=headers,
        ).json()

        r = client.post(
            "/api/v1/tienda/pedidos",
            json={
                "items": [
                    {
                        "producto_id": otro["id"],
                        "variante_id": con_variantes["variantes"][0]["id"],
                        "cantidad": "1",
                    }
                ],
                "metodo_pago": "EFECTIVO",
            },
            headers=headers,
        )
        assert r.status_code == 422
        assert "variante" in r.json()["detail"].lower()


class TestNoPerderInventarioPorAccidente:
    """Los tres caminos por los que un PUT vaciaba el stock sin que nadie lo pidiera."""

    def test_put_sin_variantes_no_borra_las_existentes(self, client, ana_tokens, calzado):
        """Omitir «variantes» es «no hablo del inventario», no «bórralo».

        El formulario carga la matriz con dos peticiones encadenadas; si el
        usuario guardaba antes de que llegaran, el cuerpo salía sin variantes y
        se llevaba por delante el stock de todas.
        """
        headers = auth_headers(ana_tokens["access_token"])
        cuerpo = _body(calzado)
        creado = client.post("/api/v1/productos", json=cuerpo, headers=headers).json()
        assert len(creado["variantes"]) == 2

        sin_variantes = {k: v for k, v in cuerpo.items() if k != "variantes"}
        sin_variantes["nombre"] = "Air Nike TN (renombrado)"
        r = client.put(f"/api/v1/productos/{creado['id']}", json=sin_variantes, headers=headers)
        assert r.status_code == 200, r.text
        assert len(r.json()["variantes"]) == 2, "un PUT parcial no puede vaciar el inventario"
        assert {v["stock"] for v in r.json()["variantes"]} == {"2.000000", "3.000000"}

    def test_renombrar_el_codigo_conserva_stock_e_id(self, client, ana_tokens, calzado):
        """Cambiar el SKU es renombrar, no borrar y recrear.

        Emparejar por código hacía que el pedido pendiente quedara apuntando a
        una fila borrada y que el stock volviera a cero.
        """
        headers = auth_headers(ana_tokens["access_token"])
        cuerpo = _body(calzado)
        creado = client.post("/api/v1/productos", json=cuerpo, headers=headers).json()
        # Por código, no por índice: la respuesta no promete conservar el orden
        por_codigo = {v["codigo"]: v for v in creado["variantes"]}
        vieja = por_codigo[cuerpo["variantes"][0]["codigo"]]

        cuerpo["variantes"] = [
            {**v, "id": por_codigo[v["codigo"]]["id"], "codigo": f"NUEVO-{i}"}
            for i, v in enumerate(cuerpo["variantes"])
        ]
        for v in cuerpo["variantes"]:
            v.pop("stock", None)  # solo se renombra: el cuerpo no habla de stock
        r = client.put(f"/api/v1/productos/{creado['id']}", json=cuerpo, headers=headers)
        assert r.status_code == 200, r.text

        renombrada = next(v for v in r.json()["variantes"] if v["id"] == vieja["id"])
        assert renombrada["codigo"] != vieja["codigo"], "el código sí cambia"
        # Decimal y no cadena: el servidor devuelve "2.000000" donde el cuerpo
        # mandó "2", y comparar el texto haría fallar un test que está bien.
        assert Decimal(renombrada["stock"]) == Decimal(vieja["stock"]), (
            "el stock NO se pierde al renombrar"
        )

    def test_codigo_de_otro_producto_da_400_y_no_500(self, client, ana_tokens, calzado):
        """El UNIQUE es (tenant, codigo): abarca todo el negocio, no un producto."""
        headers = auth_headers(ana_tokens["access_token"])
        primero = client.post("/api/v1/productos", json=_body(calzado), headers=headers).json()
        repetido = primero["variantes"][0]["codigo"]

        otro = _body(calzado)
        otro["variantes"][0]["codigo"] = repetido
        r = client.post("/api/v1/productos", json=otro, headers=headers)
        assert r.status_code == 400, r.text
        assert "ya lo usa otro producto" in r.json()["detail"]

    def test_editar_conservando_sus_propios_codigos(self, client, ana_tokens, calzado):
        """El aviso anterior no puede dispararse con los códigos de uno mismo."""
        headers = auth_headers(ana_tokens["access_token"])
        cuerpo = _body(calzado)
        creado = client.post("/api/v1/productos", json=cuerpo, headers=headers).json()
        cuerpo["nombre"] = "Otro nombre"
        r = client.put(f"/api/v1/productos/{creado['id']}", json=cuerpo, headers=headers)
        assert r.status_code == 200, r.text
