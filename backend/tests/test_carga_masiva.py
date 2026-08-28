"""Carga masiva de clientes con vista previa (fase 3.1).

La vista previa NO guarda nada: eso es lo que hace confiable el paso siguiente.
"""

from sqlalchemy import select

from app.db.models import ClienteFinal, Plan, Suscripcion
from tests.conftest import TENANT_A, auth_headers

CSV_OK = (
    "Identificación,Razón social,Email\n"
    "1712345001,Panadería La Espiga,espiga@mail.ec\n"
    "1790012399001,Comercial Andrade,andrade@mail.ec\n"
)

CSV_CON_ERRORES = (
    "Identificación,Razón social\n"
    "1712345002,Cliente correcto\n"
    "123,Identificación corta\n"
    "1790012399002,\n"
    "1712345002,Repetido en el archivo\n"
    "17123AB003,Con letras\n"
)


def _empresario(admin_db):
    """La carga masiva exige el plan que trae la función."""
    from datetime import date
    from decimal import Decimal

    from app.db.models.enums import EstadoSuscripcion
    from app.services.planes import LIMITES_POR_PLAN

    plan = admin_db.scalars(select(Plan).where(Plan.codigo == "EMPRESARIO")).one()
    plan.limites = {
        k: (str(v) if isinstance(v, Decimal) else v)
        for k, v in LIMITES_POR_PLAN["Empresario"].items()
    }
    for vieja in admin_db.scalars(
        select(Suscripcion).where(Suscripcion.tenant_id == TENANT_A)
    ).all():
        admin_db.delete(vieja)
    admin_db.flush()
    sus = Suscripcion(
        tenant_id=TENANT_A,
        plan_id=plan.id,
        estado=EstadoSuscripcion.ACTIVA,
        precio=plan.precio_mensual,
        inicia=date(2026, 1, 1),
    )
    admin_db.add(sus)
    admin_db.commit()
    return sus


def _analizar(client, tokens, csv: str, nombre: str = "clientes.csv"):
    return client.post(
        "/api/v1/clientes/carga-masiva/analizar",
        files={"archivo": (nombre, csv.encode(), "text/csv")},
        headers=auth_headers(tokens["access_token"]),
    )


class TestVistaPrevia:
    def test_archivo_valido(self, client, ana_tokens, admin_db):
        _empresario(admin_db)
        r = _analizar(client, ana_tokens, CSV_OK)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total"] == 2
        assert d["validas"] == 2
        assert d["con_error"] == 0
        tipos = {f["tipo_identificacion"] for f in d["filas"]}
        assert tipos == {"CEDULA", "RUC"}

    def test_no_guarda_nada(self, client, ana_tokens, admin_db):
        """El paso de vista previa es de solo lectura."""
        _empresario(admin_db)
        antes = admin_db.scalars(
            select(ClienteFinal).where(ClienteFinal.identificacion == "1712345001")
        ).first()
        assert antes is None
        assert _analizar(client, ana_tokens, CSV_OK).status_code == 200
        despues = admin_db.scalars(
            select(ClienteFinal).where(ClienteFinal.identificacion == "1712345001")
        ).first()
        assert despues is None

    def test_reporta_los_errores_fila_por_fila(self, client, ana_tokens, admin_db):
        _empresario(admin_db)
        r = _analizar(client, ana_tokens, CSV_CON_ERRORES)
        assert r.status_code == 200, r.text
        d = r.json()
        por_fila = {f["numero"]: f for f in d["filas"]}
        assert por_fila[2]["errores"] == []  # el correcto
        assert any("10 dígitos" in e for e in por_fila[3]["errores"])
        assert any("razón social" in e.lower() for e in por_fila[4]["errores"])
        assert any("Repetido" in e for e in por_fila[5]["errores"])
        assert any("números" in e for e in por_fila[6]["errores"])
        assert d["validas"] == 1

    def test_excel_pide_csv(self, client, ana_tokens, admin_db):
        _empresario(admin_db)
        r = _analizar(client, ana_tokens, "loquesea", nombre="clientes.xlsx")
        assert r.status_code == 422
        assert "CSV" in r.json()["detail"]

    def test_faltan_columnas(self, client, ana_tokens, admin_db):
        _empresario(admin_db)
        r = _analizar(client, ana_tokens, "nombre,telefono\nJuan,099\n")
        assert r.status_code == 422
        assert "Identificación" in r.json()["detail"]

    def test_archivo_vacio(self, client, ana_tokens, admin_db):
        _empresario(admin_db)
        r = _analizar(client, ana_tokens, "")
        assert r.status_code == 422

    def test_formula_no_se_interpreta(self, client, ana_tokens, admin_db):
        """Un valor que empieza por '=' se guarda como texto, jamás se evalúa."""
        _empresario(admin_db)
        csv = "Identificación,Razón social\n1712345004,=1+1\n"
        r = _analizar(client, ana_tokens, csv)
        assert r.status_code == 200
        assert r.json()["filas"][0]["razon_social"] == "=1+1"


class TestConfirmar:
    def test_guarda_solo_las_validas(self, client, ana_tokens, admin_db):
        _empresario(admin_db)
        r = client.post(
            "/api/v1/clientes/carga-masiva/confirmar",
            files={"archivo": ("clientes.csv", CSV_CON_ERRORES.encode(), "text/csv")},
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["guardados"] == 1
        assert d["omitidos_por_error"] == 4

        guardado = admin_db.scalars(
            select(ClienteFinal).where(ClienteFinal.identificacion == "1712345002")
        ).first()
        assert guardado is not None
        assert guardado.razon_social == "Cliente correcto"

    def test_no_duplica_los_ya_guardados(self, client, ana_tokens, admin_db):
        _empresario(admin_db)
        primera = client.post(
            "/api/v1/clientes/carga-masiva/confirmar",
            files={"archivo": ("clientes.csv", CSV_OK.encode(), "text/csv")},
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert primera.json()["guardados"] == 2

        segunda = client.post(
            "/api/v1/clientes/carga-masiva/confirmar",
            files={"archivo": ("clientes.csv", CSV_OK.encode(), "text/csv")},
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert segunda.json()["guardados"] == 0
        assert segunda.json()["omitidos_por_duplicado"] == 2

        cuantos = admin_db.scalars(
            select(ClienteFinal).where(ClienteFinal.identificacion == "1712345001")
        ).all()
        assert len(cuantos) == 1
