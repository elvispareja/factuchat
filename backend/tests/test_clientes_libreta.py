"""Libreta de clientes: provincia/ciudad y lo facturado por cliente.

El agregado de GET /clientes es código nuevo que habla de dinero, así que
además del camino feliz se prueba el aislamiento: un comprobante de OTRO
inquilino no puede sumar aquí, ni siquiera si apunta a un cliente de este
(las FK de Postgres saltan RLS, quien filtra es la política de la tabla).
"""

import random
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import ClienteFinal, Comprobante
from app.db.models.enums import AmbienteSRI, EstadoComprobante, TipoComprobante
from tests.conftest import TENANT_A, TENANT_B, auth_headers


class _Libreta:
    """Alta de clientes por la API + siembra de comprobantes saltándose RLS
    (que es justo lo que hay que probar), con limpieza al final.

    La limpieza NO es cosmética: los clientes cuentan contra el cupo del plan
    del inquilino y, si se quedan, otros tests del cupo empiezan a fallar.
    """

    def __init__(self, client, admin_db):
        self._client = client
        self._db = admin_db
        self.clientes: list[str] = []
        self.comprobantes: list[Comprobante] = []

    def cliente(self, tokens, **extra) -> dict:
        r = self._client.post(
            "/api/v1/clientes",
            json={
                "tipo_identificacion": "CEDULA",
                "identificacion": f"17{random.randint(10_000_000, 99_999_999)}",
                "razon_social": "Cliente de Libreta",
                **extra,
            },
            headers=auth_headers(tokens["access_token"]),
        )
        assert r.status_code == 201, r.text
        self.clientes.append(r.json()["id"])
        return r.json()

    def comprobante(self, tenant_id, cliente_id, estado, total, tipo=None) -> None:
        c = Comprobante(
            tenant_id=tenant_id,
            tipo=tipo or TipoComprobante.FACTURA,
            estado=estado,
            ambiente=AmbienteSRI.PRUEBAS,
            # Un mes viejo y ajeno: no contamina los períodos que miden otros
            # tests (reportes cierra marzo 2026, el cupo mira el mes en curso).
            fecha_emision=date(2020, 1, 15),
            cliente_final_id=cliente_id,
            subtotal=Decimal(total),
            iva=Decimal("0"),
            total=Decimal(total),
            payload={},
        )
        self._db.add(c)
        self._db.commit()
        self.comprobantes.append(c)

    def fila(self, tokens, cliente_id: str) -> dict:
        r = self._client.get("/api/v1/clientes", headers=auth_headers(tokens["access_token"]))
        assert r.status_code == 200, r.text
        filas = {f["id"]: f for f in r.json()}
        assert cliente_id in filas
        return filas[cliente_id]

    def limpiar(self) -> None:
        for c in self.comprobantes:
            self._db.delete(c)
        self._db.commit()
        for cliente_id in self.clientes:
            self._db.delete(self._db.get(ClienteFinal, cliente_id))
        self._db.commit()


@pytest.fixture()
def libreta(client, admin_db):
    l = _Libreta(client, admin_db)
    yield l
    l.limpiar()


class TestProvinciaYCiudad:
    def test_se_guardan_y_vuelven(self, libreta, client, ana_tokens):
        cliente = libreta.cliente(ana_tokens, provincia="Pichincha", ciudad="Quito")
        assert (cliente["provincia"], cliente["ciudad"]) == ("Pichincha", "Quito")

        r = client.get(
            f"/api/v1/clientes/{cliente['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 200
        assert (r.json()["provincia"], r.json()["ciudad"]) == ("Pichincha", "Quito")

        fila = libreta.fila(ana_tokens, cliente["id"])
        assert (fila["provincia"], fila["ciudad"]) == ("Pichincha", "Quito")

    def test_son_opcionales(self, libreta, ana_tokens):
        """Los clientes ya cargados no tienen esos datos: no se pueden exigir."""
        cliente = libreta.cliente(ana_tokens)
        assert cliente["provincia"] is None
        assert cliente["ciudad"] is None

    def test_editar_cambia_la_ciudad(self, libreta, client, ana_tokens):
        cliente = libreta.cliente(ana_tokens, provincia="Guayas", ciudad="Guayaquil")
        r = client.put(
            f"/api/v1/clientes/{cliente['id']}",
            json={
                "tipo_identificacion": "CEDULA",
                "identificacion": cliente["identificacion"],
                "razon_social": cliente["razon_social"],
                "provincia": "Guayas",
                "ciudad": "Durán",
            },
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 200, r.text
        assert r.json()["ciudad"] == "Durán"


class TestFacturadoPorCliente:
    def test_cliente_sin_comprobantes_sale_en_cero(self, libreta, ana_tokens):
        """En cero, no ausente ni null: la tabla del panel pinta el número."""
        cliente = libreta.cliente(ana_tokens)
        fila = libreta.fila(ana_tokens, cliente["id"])
        assert Decimal(fila["facturado"]) == Decimal("0")
        assert fila["comprobantes"] == 0

    def test_suma_solo_los_autorizados(self, libreta, ana_tokens):
        """AUTORIZADO es lo que el SRI aceptó; lo demás no es dinero facturado."""
        cliente = libreta.cliente(ana_tokens)
        libreta.comprobante(TENANT_A, cliente["id"], EstadoComprobante.AUTORIZADO, "100.00")
        libreta.comprobante(TENANT_A, cliente["id"], EstadoComprobante.AUTORIZADO, "15.00")
        for estado in (
            EstadoComprobante.PENDIENTE,
            EstadoComprobante.FIRMADO,
            EstadoComprobante.ENVIADO_SRI,
            EstadoComprobante.RECHAZADO,
            EstadoComprobante.DEVUELTO,
        ):
            libreta.comprobante(TENANT_A, cliente["id"], estado, "999.00")

        fila = libreta.fila(ana_tokens, cliente["id"])
        assert Decimal(fila["facturado"]) == Decimal("115.00")
        assert fila["comprobantes"] == 2

    def test_comprobante_de_otro_tenant_no_suma(self, libreta, client, ana_tokens, bob_tokens):
        cliente_a = libreta.cliente(ana_tokens)
        libreta.comprobante(TENANT_A, cliente_a["id"], EstadoComprobante.AUTORIZADO, "10.00")
        # Comprobante del inquilino B apuntando al cliente de A: la FK lo
        # permite (salta RLS), el listado de A NO debe contarlo.
        libreta.comprobante(TENANT_B, cliente_a["id"], EstadoComprobante.AUTORIZADO, "5000.00")

        fila = libreta.fila(ana_tokens, cliente_a["id"])
        assert Decimal(fila["facturado"]) == Decimal("10.00")
        assert fila["comprobantes"] == 1

        # Y el cliente de A ni siquiera existe para B.
        r = client.get("/api/v1/clientes", headers=auth_headers(bob_tokens["access_token"]))
        assert r.status_code == 200
        assert cliente_a["id"] not in [f["id"] for f in r.json()]


class TestSoloLasFacturasSonVentas:
    """El estado no basta: hay que filtrar también por TIPO de comprobante.

    Sin el filtro, los 6 tipos del SRI se sumaban por igual: una nota de crédito
    que ANULA una factura la sumaba otra vez (doblando el importe en vez de
    dejarlo en cero), y retenciones y guías de remisión —que no son ventas—
    contaban como comprobantes facturados.
    """

    def test_la_nota_de_credito_no_suma(self, libreta, ana_tokens):
        cliente = libreta.cliente(ana_tokens)
        libreta.comprobante(TENANT_A, cliente["id"], EstadoComprobante.AUTORIZADO, "115.00")
        libreta.comprobante(
            TENANT_A,
            cliente["id"],
            EstadoComprobante.AUTORIZADO,
            "115.00",
            tipo=TipoComprobante.NOTA_CREDITO,
        )

        fila = libreta.fila(ana_tokens, cliente["id"])
        assert Decimal(fila["facturado"]) == Decimal("115.00"), "la NC no puede sumar"
        assert fila["comprobantes"] == 1

    def test_retenciones_y_guias_no_cuentan(self, libreta, ana_tokens):
        cliente = libreta.cliente(ana_tokens)
        libreta.comprobante(TENANT_A, cliente["id"], EstadoComprobante.AUTORIZADO, "50.00")
        for tipo, total in (
            (TipoComprobante.RETENCION, "10.00"),
            (TipoComprobante.GUIA_REMISION, "0.00"),
        ):
            libreta.comprobante(
                TENANT_A, cliente["id"], EstadoComprobante.AUTORIZADO, total, tipo=tipo
            )

        fila = libreta.fila(ana_tokens, cliente["id"])
        assert Decimal(fila["facturado"]) == Decimal("50.00")
        assert fila["comprobantes"] == 1, "solo la factura es una venta"
