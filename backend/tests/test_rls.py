"""Checklist F1: un usuario del tenant A no puede leer datos del tenant B
ni manipulando IDs. Se prueba en las DOS barreras: API y PostgreSQL."""

import random

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from tests.conftest import TENANT_A, TENANT_B, auth_headers

CLIENTE_A = {
    "tipo_identificacion": "CEDULA",
    "identificacion": "1712345678",
    "razon_social": "Cliente Privado De A",
    "email": "cliente@a.ec",
}


@pytest.fixture()
def cliente_de_a(client, ana_tokens):
    body = {**CLIENTE_A, "identificacion": f"17{random.randint(10_000_000, 99_999_999)}"}
    r = client.post("/api/v1/clientes", json=body, headers=auth_headers(ana_tokens["access_token"]))
    assert r.status_code == 201, r.text
    return r.json()


class TestAislamientoAPI:
    def test_b_no_ve_el_listado_de_a(self, client, cliente_de_a, bob_tokens):
        r = client.get("/api/v1/clientes", headers=auth_headers(bob_tokens["access_token"]))
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()]
        assert cliente_de_a["id"] not in ids

    def test_b_no_accede_por_id_manipulado(self, client, cliente_de_a, bob_tokens):
        r = client.get(
            f"/api/v1/clientes/{cliente_de_a['id']}",
            headers=auth_headers(bob_tokens["access_token"]),
        )
        assert r.status_code == 404  # ni siquiera revela que existe

    def test_b_no_edita_por_id_manipulado(self, client, cliente_de_a, bob_tokens):
        r = client.put(
            f"/api/v1/clientes/{cliente_de_a['id']}",
            json={**CLIENTE_A, "razon_social": "Hackeado"},
            headers=auth_headers(bob_tokens["access_token"]),
        )
        assert r.status_code == 404

    def test_a_si_ve_su_cliente(self, client, cliente_de_a, ana_tokens):
        r = client.get(
            f"/api/v1/clientes/{cliente_de_a['id']}",
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 200
        assert r.json()["razon_social"] == "Cliente Privado De A"

    def test_sin_rol_no_hay_acceso(self, client, admin_auth):
        # Deny by default: /clientes exige rol CLIENTE; un SUPERADMIN recibe 403
        r = client.get("/api/v1/clientes", headers=auth_headers(admin_auth["access"]))
        assert r.status_code == 403


class TestAislamientoPostgres:
    """La segunda barrera: RLS aplica aunque el código de la app tenga un bug."""

    def _set_ctx(self, conn, tenant: str, internal: bool = False):
        conn.execute(
            text(
                "SELECT set_config('app.tenant_id', :t, true),"
                " set_config('app.is_internal', :i, true)"
            ),
            {"t": tenant, "i": "true" if internal else "false"},
        )

    def test_sin_contexto_no_hay_filas(self, app_engine, cliente_de_a):
        with app_engine.connect() as conn:
            n = conn.execute(text("SELECT count(*) FROM clientes_finales")).scalar()
            assert n == 0

    def test_con_tenant_b_no_se_ven_filas_de_a(self, app_engine, cliente_de_a):
        with app_engine.connect() as conn:
            self._set_ctx(conn, str(TENANT_B))
            rows = conn.execute(text("SELECT id::text FROM clientes_finales")).scalars().all()
            assert cliente_de_a["id"] not in rows

    def test_no_se_puede_insertar_para_otro_tenant(self, app_engine, database):
        with app_engine.connect() as conn:
            self._set_ctx(conn, str(TENANT_A))
            with pytest.raises(ProgrammingError):
                conn.execute(
                    text(
                        "INSERT INTO clientes_finales (id, tenant_id, tipo_identificacion,"
                        " identificacion, razon_social, created_at, updated_at)"
                        " VALUES (gen_random_uuid(), :otro, 'CEDULA', '0912345678',"
                        " 'Intruso', now(), now())"
                    ),
                    {"otro": str(TENANT_B)},
                )

    def test_rol_app_no_puede_apagar_rls(self, app_engine, database):
        with app_engine.connect() as conn:
            conn.execute(text("SET row_security = off"))
            with pytest.raises(ProgrammingError):
                conn.execute(text("SELECT count(*) FROM clientes_finales")).scalar()

    def test_tenant_no_lee_audit_log(self, app_engine, cliente_de_a):
        with app_engine.connect() as conn:
            self._set_ctx(conn, str(TENANT_A))
            n = conn.execute(text("SELECT count(*) FROM audit_log")).scalar()
            assert n == 0  # la política solo permite lectura interna

    def test_audit_log_es_inmutable(self, app_engine, admin_engine, cliente_de_a):
        # El rol de la app no tiene GRANT de UPDATE/DELETE
        with app_engine.connect() as conn:
            with pytest.raises(ProgrammingError):
                conn.execute(text("DELETE FROM audit_log"))
        # E incluso el dueño choca con el trigger de inmutabilidad
        with admin_engine.connect() as conn:
            with pytest.raises(Exception, match="inmutable"):
                conn.execute(text("UPDATE audit_log SET accion = 'X'"))

    def test_funcion_sa_rechaza_a_un_tenant(self, app_engine, cliente_de_a, database):
        with app_engine.connect() as conn:
            self._set_ctx(conn, str(TENANT_A), internal=False)
            with pytest.raises(ProgrammingError, match="acceso denegado"):
                conn.execute(text("SELECT * FROM sa_list_tenants('intento indebido')"))
