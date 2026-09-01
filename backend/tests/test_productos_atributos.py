"""Categorías/atributos configurables y su cableado con productos.

Cubre el camino feliz (crear categoría → atributo → valor → producto con
atributos) y el motivo real por el que _validar_categoria/_validar_atributos
existen: las FK de Postgres saltan RLS, así que sin el chequeo explícito con
db.get() un producto de un tenant podría terminar apuntando a una categoría,
atributo o valor de OTRO tenant.
"""

import random

import pytest

from tests.conftest import auth_headers

PRODUCTO_BASE = {
    "codigo": "SKU",
    "nombre": "Camiseta",
    "tipo": "BIEN",
    "precio_sin_iva": "10.00",
}


def _codigo() -> str:
    return f"SKU{random.randint(100000, 999999)}"


@pytest.fixture()
def categoria_de_a(client, ana_tokens):
    r = client.post(
        "/api/v1/categorias",
        json={"nombre": f"Ropa {random.randint(1, 999999)}"},
        headers=auth_headers(ana_tokens["access_token"]),
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def atributo_de_a(client, ana_tokens, categoria_de_a):
    r = client.post(
        "/api/v1/atributos",
        json={"categoria_id": categoria_de_a["id"], "nombre": "Color"},
        headers=auth_headers(ana_tokens["access_token"]),
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def valor_de_a(client, ana_tokens, atributo_de_a):
    r = client.post(
        "/api/v1/atributo-valores",
        json={"atributo_id": atributo_de_a["id"], "valor": "Rojo"},
        headers=auth_headers(ana_tokens["access_token"]),
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestCaminoFeliz:
    def test_crea_producto_con_atributos(self, client, ana_tokens, categoria_de_a, atributo_de_a, valor_de_a):
        body = {
            **PRODUCTO_BASE,
            "codigo": _codigo(),
            "categoria_id": categoria_de_a["id"],
            "atributos": [{"atributo_id": atributo_de_a["id"], "atributo_valor_id": valor_de_a["id"]}],
        }
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["categoria_id"] == categoria_de_a["id"]
        assert data["atributos"] == [
            {"atributo_id": atributo_de_a["id"], "atributo_valor_id": valor_de_a["id"]}
        ]

        # El listado también arma el campo atributos (relationship, no columna)
        r = client.get("/api/v1/productos", headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 200
        listado = {p["id"]: p for p in r.json()}
        assert listado[data["id"]]["atributos"] == data["atributos"]

    def test_actualizar_resincroniza_atributos(
        self, client, ana_tokens, categoria_de_a, atributo_de_a, valor_de_a
    ):
        headers = auth_headers(ana_tokens["access_token"])
        body = {**PRODUCTO_BASE, "codigo": _codigo(), "categoria_id": categoria_de_a["id"], "atributos": []}
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 201, r.text
        producto = r.json()

        body["atributos"] = [
            {"atributo_id": atributo_de_a["id"], "atributo_valor_id": valor_de_a["id"]}
        ]
        r = client.put(f"/api/v1/productos/{producto['id']}", json=body, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["atributos"] == body["atributos"]

        # Quitar el atributo también debe reflejarse (no queda huérfano)
        body["atributos"] = []
        r = client.put(f"/api/v1/productos/{producto['id']}", json=body, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["atributos"] == []


class TestAislamientoEntreTenants:
    def test_categoria_de_otro_tenant_rechazada(self, client, bob_tokens, categoria_de_a):
        body = {**PRODUCTO_BASE, "codigo": _codigo(), "categoria_id": categoria_de_a["id"]}
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(bob_tokens["access_token"])
        )
        assert r.status_code == 400
        assert "categor" in r.json()["detail"].lower()

    def test_atributo_de_otro_tenant_rechazado(self, client, bob_tokens, atributo_de_a, valor_de_a):
        # Bob crea su propia categoría, pero usa el atributo (y valor) de Ana
        r = client.post(
            "/api/v1/categorias",
            json={"nombre": f"CategoriaB {random.randint(1, 999999)}"},
            headers=auth_headers(bob_tokens["access_token"]),
        )
        assert r.status_code == 201, r.text
        categoria_b = r.json()

        body = {
            **PRODUCTO_BASE,
            "codigo": _codigo(),
            "categoria_id": categoria_b["id"],
            "atributos": [{"atributo_id": atributo_de_a["id"], "atributo_valor_id": valor_de_a["id"]}],
        }
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(bob_tokens["access_token"])
        )
        assert r.status_code == 400
        assert "atributo" in r.json()["detail"].lower()


class TestValidacionesDeIntegridad:
    def test_atributo_de_otra_categoria_rechazado(self, client, ana_tokens, categoria_de_a, valor_de_a):
        headers = auth_headers(ana_tokens["access_token"])
        r = client.post(
            "/api/v1/categorias",
            json={"nombre": f"Otra {random.randint(1, 999999)}"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        otra_categoria = r.json()

        body = {
            **PRODUCTO_BASE,
            "codigo": _codigo(),
            "categoria_id": otra_categoria["id"],
            "atributos": [
                {"atributo_id": valor_de_a["atributo_id"], "atributo_valor_id": valor_de_a["id"]}
            ],
        }
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 400
        assert "no pertenece a la categoría" in r.json()["detail"]

    def test_valor_de_otro_atributo_rechazado(self, client, ana_tokens, categoria_de_a, atributo_de_a):
        headers = auth_headers(ana_tokens["access_token"])
        r = client.post(
            "/api/v1/atributos",
            json={"categoria_id": categoria_de_a["id"], "nombre": "Talla"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        otro_atributo = r.json()
        r = client.post(
            "/api/v1/atributo-valores",
            json={"atributo_id": otro_atributo["id"], "valor": "M"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        valor_de_talla = r.json()

        body = {
            **PRODUCTO_BASE,
            "codigo": _codigo(),
            "categoria_id": categoria_de_a["id"],
            "atributos": [
                {"atributo_id": atributo_de_a["id"], "atributo_valor_id": valor_de_talla["id"]}
            ],
        }
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 400
        assert "no pertenece al atributo" in r.json()["detail"]

    def test_atributos_sin_categoria_rechazado(self, client, ana_tokens, atributo_de_a, valor_de_a):
        body = {
            **PRODUCTO_BASE,
            "codigo": _codigo(),
            "categoria_id": None,
            "atributos": [{"atributo_id": atributo_de_a["id"], "atributo_valor_id": valor_de_a["id"]}],
        }
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 400
        assert "selecciona una categoría" in r.json()["detail"].lower()


class TestServiciosSinCategoria:
    """Solo los productos tangibles (BIEN) tienen categoría/atributos."""

    def test_servicio_con_categoria_rechazado(self, client, ana_tokens, categoria_de_a):
        body = {
            "codigo": _codigo(),
            "nombre": "Consultoría",
            "tipo": "SERVICIO",
            "precio_sin_iva": "10.00",
            "categoria_id": categoria_de_a["id"],
        }
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 422

    def test_servicio_con_atributos_rechazado(self, client, ana_tokens, atributo_de_a, valor_de_a):
        body = {
            "codigo": _codigo(),
            "nombre": "Consultoría",
            "tipo": "SERVICIO",
            "precio_sin_iva": "10.00",
            "atributos": [{"atributo_id": atributo_de_a["id"], "atributo_valor_id": valor_de_a["id"]}],
        }
        r = client.post(
            "/api/v1/productos", json=body, headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 422


class TestRecrearLoBorrado:
    """Las bajas son lógicas pero los UNIQUE son de tabla: sin revivir la fila,
    volver a crear algo borrado chocaba contra el índice y devolvía un 500 que
    dejaba ese nombre inutilizable para siempre."""

    def test_valor_borrado_se_puede_volver_a_crear(self, client, ana_tokens, atributo_de_a, valor_de_a):
        headers = auth_headers(ana_tokens["access_token"])
        r = client.delete(f"/api/v1/atributo-valores/{valor_de_a['id']}", headers=headers)
        assert r.status_code == 204, r.text

        r = client.post(
            "/api/v1/atributo-valores",
            json={"atributo_id": atributo_de_a["id"], "valor": valor_de_a["valor"]},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        assert r.json()["activo"] is True

        # Vuelve a aparecer en el listado, que filtra por activo
        r = client.get(
            f"/api/v1/atributo-valores?atributo_id={atributo_de_a['id']}", headers=headers
        )
        assert valor_de_a["valor"] in [v["valor"] for v in r.json()]

    def test_atributo_borrado_se_puede_volver_a_crear(self, client, ana_tokens, categoria_de_a, atributo_de_a):
        headers = auth_headers(ana_tokens["access_token"])
        r = client.delete(f"/api/v1/atributos/{atributo_de_a['id']}", headers=headers)
        assert r.status_code == 204, r.text

        r = client.post(
            "/api/v1/atributos",
            json={"categoria_id": categoria_de_a["id"], "nombre": atributo_de_a["nombre"]},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        assert r.json()["activo"] is True

    def test_categoria_borrada_se_puede_volver_a_crear(self, client, ana_tokens, categoria_de_a):
        headers = auth_headers(ana_tokens["access_token"])
        r = client.delete(f"/api/v1/categorias/{categoria_de_a['id']}", headers=headers)
        assert r.status_code == 204, r.text

        r = client.post(
            "/api/v1/categorias", json={"nombre": categoria_de_a["nombre"]}, headers=headers
        )
        assert r.status_code == 201, r.text
        assert r.json()["activo"] is True


class TestNoEliminarSiEstaEnUso:
    """No se borra (baja lógica) una categoría/atributo/valor mientras algo
    activo siga apoyado en él: dejaría datos activos huérfanos o invisibles."""

    def test_categoria_con_producto_activo_no_se_elimina(
        self, client, ana_tokens, categoria_de_a
    ):
        headers = auth_headers(ana_tokens["access_token"])
        body = {**PRODUCTO_BASE, "codigo": _codigo(), "categoria_id": categoria_de_a["id"]}
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 201, r.text

        r = client.delete(f"/api/v1/categorias/{categoria_de_a['id']}", headers=headers)
        assert r.status_code == 400

    def test_categoria_con_atributo_activo_no_se_elimina(
        self, client, ana_tokens, categoria_de_a, atributo_de_a
    ):
        headers = auth_headers(ana_tokens["access_token"])
        r = client.delete(f"/api/v1/categorias/{categoria_de_a['id']}", headers=headers)
        assert r.status_code == 400

    def test_atributo_con_valor_activo_no_se_elimina(
        self, client, ana_tokens, atributo_de_a, valor_de_a
    ):
        headers = auth_headers(ana_tokens["access_token"])
        r = client.delete(f"/api/v1/atributos/{atributo_de_a['id']}", headers=headers)
        assert r.status_code == 400

    def test_atributo_con_producto_activo_no_se_elimina(
        self, client, ana_tokens, categoria_de_a, atributo_de_a, valor_de_a
    ):
        headers = auth_headers(ana_tokens["access_token"])
        body = {
            **PRODUCTO_BASE,
            "codigo": _codigo(),
            "categoria_id": categoria_de_a["id"],
            "atributos": [{"atributo_id": atributo_de_a["id"], "atributo_valor_id": valor_de_a["id"]}],
        }
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 201, r.text

        r = client.delete(f"/api/v1/atributos/{atributo_de_a['id']}", headers=headers)
        assert r.status_code == 400

    def test_valor_con_producto_activo_no_se_elimina(
        self, client, ana_tokens, categoria_de_a, atributo_de_a, valor_de_a
    ):
        headers = auth_headers(ana_tokens["access_token"])
        body = {
            **PRODUCTO_BASE,
            "codigo": _codigo(),
            "categoria_id": categoria_de_a["id"],
            "atributos": [{"atributo_id": atributo_de_a["id"], "atributo_valor_id": valor_de_a["id"]}],
        }
        r = client.post("/api/v1/productos", json=body, headers=headers)
        assert r.status_code == 201, r.text

        r = client.delete(f"/api/v1/atributo-valores/{valor_de_a['id']}", headers=headers)
        assert r.status_code == 400
