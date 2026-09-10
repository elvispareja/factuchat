"""Los teléfonos que pueden facturar por chat, gestionados desde el panel.

Lo que se comprueba aquí, por orden de lo que más dolería que se rompiera:

1. La NORMALIZACIÓN. El cero de la marcación nacional (`+593 0 99…`) ha costado
   dos depuraciones largas en producción: el número queda guardado, la pantalla
   lo enseña bien, y los mensajes del cliente no casan con nadie.
2. Que un mismo teléfono NO pueda facturar para dos empresas. Si pudiera, el
   bot elegiría por orden de llegada a nombre de quién emite.
3. Que el bot resuelva por esta tabla, que es el motivo de que exista.
"""

import pytest

from app.db.models import WhatsappNumero
from app.schemas.whatsapp_numeros import normalizar, para_mostrar
from app.services.planes import plan_vigente
from app.whatsapp.asistente import NumeroNoAutorizado, tenant_por_telefono
from tests.conftest import TENANT_A, auth_headers

RUTA = "/api/v1/numeros-whatsapp"


class TestNormalizacion:
    @pytest.mark.parametrize(
        "escrito",
        [
            "0993053670",  # como lo marca cualquiera en Ecuador
            "+593 99 305 3670",  # como lo enseña el panel
            "593993053670",  # como lo manda Meta
            "+5930993053670",  # el cero de más: el error que nos costó la tarde
            "  099 305 3670  ",  # con espacios y sin código
            "099-305-3670",  # con guiones
        ],
    )
    def test_todas_las_formas_dan_el_mismo_numero(self, escrito):
        assert normalizar(escrito) == "593993053670"

    def test_numero_de_otro_pais_se_respeta(self):
        """Con «+» delante no se toca: el contador puede estar en Venezuela."""
        assert normalizar("+58 412 1234567") == "584121234567"

    @pytest.mark.parametrize("basura", ["", "   ", "abc", "12", "+", "1234567890123456789"])
    def test_lo_que_no_es_un_telefono_se_rechaza(self, basura):
        with pytest.raises(ValueError):
            normalizar(basura)

    def test_se_muestra_legible(self):
        assert para_mostrar("593993053670") == "+593 99 305 3670"
        # Uno extranjero no se parte en grupos ecuatorianos
        assert para_mostrar("584121234567") == "+584121234567"


@pytest.fixture()
def sin_numeros(admin_db):
    """Deja la cuenta de Ana vacía, y la devuelve como estaba.

    La migración 0028 copia el teléfono de la ficha a esta tabla, así que un
    inquilino recién migrado puede llegar aquí con uno ya puesto."""
    previos = [
        (n.numero, n.etiqueta)
        for n in admin_db.query(WhatsappNumero).filter_by(tenant_id=TENANT_A).all()
    ]
    admin_db.query(WhatsappNumero).filter_by(tenant_id=TENANT_A).delete()
    admin_db.commit()
    yield
    admin_db.query(WhatsappNumero).filter_by(tenant_id=TENANT_A).delete()
    for numero, etiqueta in previos:
        admin_db.add(WhatsappNumero(tenant_id=TENANT_A, numero=numero, etiqueta=etiqueta))
    admin_db.commit()


def _alta(client, tokens, numero: str, etiqueta: str = "Pruebas"):
    return client.post(
        RUTA,
        json={"numero": numero, "etiqueta": etiqueta},
        headers=auth_headers(tokens["access_token"]),
    )


class TestAlta:
    def test_se_guarda_normalizado_y_el_primero_es_principal(self, client, ana_tokens, sin_numeros):
        r = _alta(client, ana_tokens, "0993053670", "Libio, dueño")
        assert r.status_code == 201, r.text
        lista = r.json()
        assert len(lista) == 1
        assert lista[0]["numero"] == "593993053670"
        assert lista[0]["mostrar"] == "+593 99 305 3670"
        assert lista[0]["etiqueta"] == "Libio, dueño"
        assert lista[0]["principal"] is True

    def test_el_listado_lo_devuelve(self, client, ana_tokens, sin_numeros):
        _alta(client, ana_tokens, "0993053670")
        r = client.get(RUTA, headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 200
        assert [n["numero"] for n in r.json()] == ["593993053670"]

    def test_repetido_en_la_propia_cuenta(self, client, ana_tokens, sin_numeros):
        assert _alta(client, ana_tokens, "0993053670").status_code == 201
        # El mismo teléfono escrito de otra forma sigue siendo el mismo
        r = _alta(client, ana_tokens, "+593 99 305 3670")
        assert r.status_code == 409
        assert "ya está en tu lista" in r.json()["detail"]

    def test_sin_etiqueta_no_se_guarda(self, client, ana_tokens, sin_numeros):
        r = _alta(client, ana_tokens, "0993053670", "   ")
        assert r.status_code == 422

    def test_numero_invalido(self, client, ana_tokens, sin_numeros):
        assert _alta(client, ana_tokens, "12").status_code == 422

    def test_el_plan_manda_cuantos_caben(self, client, ana_tokens, sin_numeros, admin_db):
        """Llenado el cupo del plan, el siguiente pide subir.

        El tope se lee del plan en vigor y no se fija aquí: otras pruebas de la
        suite le cambian el plan a Ana, y un número escrito a mano haría que
        este test pasara o fallara según el orden de ejecución."""
        tope = plan_vigente(admin_db, TENANT_A).tope("nums")
        assert tope >= 1

        for i in range(tope):
            r = _alta(client, ana_tokens, f"09930536{70 + i}", f"Autorizado {i}")
            assert r.status_code == 201, r.text

        r = _alta(client, ana_tokens, "0983317726", "Karina, mostrador")
        assert r.status_code == 402, r.text
        detalle = r.json()["detail"]
        assert detalle["funcion"] == "nums"
        assert "sube de plan" in detalle["mensaje"].lower()


class TestAislamiento:
    def test_una_cuenta_no_ve_los_de_otra(self, client, ana_tokens, bob_tokens, sin_numeros):
        _alta(client, ana_tokens, "0993053670")
        r = client.get(RUTA, headers=auth_headers(bob_tokens["access_token"]))
        assert r.status_code == 200
        assert all(n["numero"] != "593993053670" for n in r.json())

    def test_un_telefono_no_puede_facturar_para_dos_empresas(
        self, client, ana_tokens, bob_tokens, sin_numeros, admin_db
    ):
        """Si se pudiera, el bot no sabría a nombre de quién emitir."""
        assert _alta(client, ana_tokens, "0993053670").status_code == 201
        r = _alta(client, bob_tokens, "0993053670")
        assert r.status_code == 409
        assert "otra cuenta" in r.json()["detail"]
        # Y no queda ninguna fila colgando de Bob
        admin_db.expire_all()
        filas = admin_db.query(WhatsappNumero).filter_by(numero="593993053670").all()
        assert len(filas) == 1
        assert filas[0].tenant_id == TENANT_A


class TestQuitar:
    def test_quitar_lo_saca_de_la_lista(self, client, ana_tokens, sin_numeros):
        creado = _alta(client, ana_tokens, "0993053670").json()[0]
        cab = auth_headers(ana_tokens["access_token"])
        r = client.delete(f"{RUTA}/{creado['id']}", headers=cab)
        assert r.status_code == 200
        assert r.json() == []

    def test_quitar_dos_veces_no_es_error(self, client, ana_tokens, sin_numeros):
        creado = _alta(client, ana_tokens, "0993053670").json()[0]
        cab = auth_headers(ana_tokens["access_token"])
        assert client.delete(f"{RUTA}/{creado['id']}", headers=cab).status_code == 200
        assert client.delete(f"{RUTA}/{creado['id']}", headers=cab).status_code == 200

    def test_no_se_puede_quitar_el_de_otra_cuenta(
        self, client, ana_tokens, bob_tokens, sin_numeros, admin_db
    ):
        creado = _alta(client, ana_tokens, "0993053670").json()[0]
        cab = auth_headers(bob_tokens["access_token"])
        r = client.delete(f"{RUTA}/{creado['id']}", headers=cab)
        # Para Bob ese id no existe, así que le responde con SU lista intacta
        assert r.status_code == 200
        admin_db.expire_all()
        assert admin_db.query(WhatsappNumero).filter_by(numero="593993053670").count() == 1


class TestElBotResuelvePorAqui:
    """El motivo de que exista la tabla: que el bot sepa de quién es un mensaje."""

    def test_un_numero_autorizado_resuelve_su_empresa(
        self, client, ana_tokens, sin_numeros, admin_db
    ):
        _alta(client, ana_tokens, "0993053670")
        assert tenant_por_telefono(admin_db, "593993053670").id == TENANT_A

    def test_quitado_deja_de_resolver(self, client, ana_tokens, sin_numeros, admin_db):
        creado = _alta(client, ana_tokens, "0993053670").json()[0]
        client.delete(f"{RUTA}/{creado['id']}", headers=auth_headers(ana_tokens["access_token"]))
        with pytest.raises(NumeroNoAutorizado):
            tenant_por_telefono(admin_db, "593993053670")

    def test_uno_que_no_esta_no_resuelve(self, admin_db, sin_numeros):
        with pytest.raises(NumeroNoAutorizado):
            tenant_por_telefono(admin_db, "593000000000")
