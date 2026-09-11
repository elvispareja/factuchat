"""Los teléfonos que pueden facturar por chat, gestionados desde el panel.

Lo que se comprueba aquí, por orden de lo que más dolería que se rompiera:

1. La NORMALIZACIÓN. El cero de la marcación nacional (`+593 0 99…`) ha costado
   dos depuraciones largas en producción: el número queda guardado, la pantalla
   lo enseña bien, y los mensajes del cliente no casan con nadie.
2. Que un mismo teléfono NO pueda facturar para dos empresas. Si pudiera, el
   bot elegiría por orden de llegada a nombre de quién emite.
3. Que el bot resuelva por esta tabla, que es el motivo de que exista.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.ratelimit import get_redis
from app.db.models import WhatsappNumero
from app.schemas.whatsapp_numeros import normalizar, para_mostrar
from app.services import verificacion_numero
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


CODIGO = "123456"

# Los que usan las pruebas. Desde 0030 un alta pendiente NO choca con otra
# cuenta, así que hay que barrerlos de todas o una prueba ensucia a la
# siguiente.
DE_PRUEBA = ("593993053670", "593998887766")


@pytest.fixture()
def sin_numeros(admin_db):
    """Deja la cuenta de Ana vacía, y la devuelve como estaba.

    La migración 0028 copia el teléfono de la ficha a esta tabla, así que un
    inquilino recién migrado puede llegar aquí con uno ya puesto. Se restauran
    VERIFICADOS, que es como los dejó el injerto de 0030."""
    previos = [
        (n.numero, n.etiqueta)
        for n in admin_db.query(WhatsappNumero).filter_by(tenant_id=TENANT_A).all()
    ]

    def barrer():
        admin_db.query(WhatsappNumero).filter_by(tenant_id=TENANT_A).delete()
        admin_db.query(WhatsappNumero).filter(WhatsappNumero.numero.in_(DE_PRUEBA)).delete(
            synchronize_session=False
        )
        admin_db.commit()
        # El freno de envíos vive en Redis y no lo limpia la base: sin esto, a
        # la cuarta alta del mismo número la prueba recibe un 429.
        for numero in DE_PRUEBA:
            get_redis().delete(f"rl:wa_verif:{numero}")

    barrer()
    yield
    barrer()
    for numero, etiqueta in previos:
        admin_db.add(
            WhatsappNumero(
                tenant_id=TENANT_A,
                numero=numero,
                etiqueta=etiqueta,
                verificado_at=datetime.now(UTC),
            )
        )
    admin_db.commit()


@pytest.fixture()
def codigo_fijo(monkeypatch):
    """El código es un secreto que solo viaja al WhatsApp de su dueño: la
    prueba no puede leerlo de la base, que guarda el sha256. Se fija."""
    monkeypatch.setattr(verificacion_numero, "generar", lambda: CODIGO)
    return CODIGO


def _alta(client, tokens, numero: str, etiqueta: str = "Pruebas"):
    return client.post(
        RUTA,
        json={"numero": numero, "etiqueta": etiqueta},
        headers=auth_headers(tokens["access_token"]),
    )


def _verificar(client, tokens, numero_id, codigo=CODIGO):
    return client.post(
        f"{RUTA}/{numero_id}/verificar",
        json={"codigo": codigo},
        headers=auth_headers(tokens["access_token"]),
    )


def _alta_verificada(client, tokens, numero: str, etiqueta: str = "Pruebas"):
    """Alta + código, que es lo que antes hacía el alta a secas."""
    r = _alta(client, tokens, numero, etiqueta)
    assert r.status_code == 201, r.text
    # Ojo: la lista trae el número YA normalizado, no como se tecleó.
    fila = next(n for n in r.json() if n["numero"] == normalizar(numero))
    assert _verificar(client, tokens, fila["id"]).status_code == 200
    return fila


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

    def test_un_telefono_verificado_no_lo_puede_dar_de_alta_otra_empresa(
        self, client, ana_tokens, bob_tokens, sin_numeros, codigo_fijo, admin_db
    ):
        """Si se pudiera, el bot no sabría a nombre de quién emitir."""
        _alta_verificada(client, ana_tokens, "0993053670")
        r = _alta(client, bob_tokens, "0993053670")
        assert r.status_code == 409
        assert "otra cuenta" in r.json()["detail"]
        # Y no queda ninguna fila colgando de Bob
        admin_db.expire_all()
        filas = admin_db.query(WhatsappNumero).filter_by(numero="593993053670").all()
        assert len(filas) == 1
        assert filas[0].tenant_id == TENANT_A

    def test_dos_pendientes_conviven_y_gana_quien_lo_demuestra(
        self, client, ana_tokens, bob_tokens, sin_numeros, codigo_fijo, admin_db
    ):
        """PENDIENTE no reserva el número.

        Si lo reservara, bastaría con teclear el teléfono de otra empresa y no
        verificarlo nunca para dejárselo bloqueado. Así que las dos altas pasan
        y el hueco se lo lleva quien pruebe tenerlo; al otro se le dice por qué.
        """
        de_ana = _alta(client, ana_tokens, "0993053670").json()[0]
        r_bob = _alta(client, bob_tokens, "0993053670")
        assert r_bob.status_code == 201, r_bob.text
        de_bob = next(n for n in r_bob.json() if n["numero"] == "593993053670")
        assert _verificar(client, ana_tokens, de_ana["id"]).status_code == 200
        r = _verificar(client, bob_tokens, de_bob["id"])
        assert r.status_code == 409
        assert "otra cuenta" in r.json()["detail"]
        assert tenant_por_telefono(admin_db, "593993053670").id == TENANT_A


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

    def test_un_numero_verificado_resuelve_su_empresa(
        self, client, ana_tokens, sin_numeros, codigo_fijo, admin_db
    ):
        _alta_verificada(client, ana_tokens, "0993053670")
        assert tenant_por_telefono(admin_db, "593993053670").id == TENANT_A

    def test_uno_pendiente_todavia_no_factura(self, client, ana_tokens, sin_numeros, admin_db):
        """LA razón de ser de la verificación: dar de alta no es autorizar."""
        _alta(client, ana_tokens, "0993053670")
        with pytest.raises(NumeroNoAutorizado):
            tenant_por_telefono(admin_db, "593993053670")

    def test_quitado_deja_de_resolver(self, client, ana_tokens, sin_numeros, codigo_fijo, admin_db):
        creado = _alta_verificada(client, ana_tokens, "0993053670")
        client.delete(f"{RUTA}/{creado['id']}", headers=auth_headers(ana_tokens["access_token"]))
        with pytest.raises(NumeroNoAutorizado):
            tenant_por_telefono(admin_db, "593993053670")

    def test_uno_que_no_esta_no_resuelve(self, admin_db, sin_numeros):
        with pytest.raises(NumeroNoAutorizado):
            tenant_por_telefono(admin_db, "593000000000")


class TestVerificacion:
    """Dar de alta no es autorizar: hace falta probar que el teléfono es tuyo."""

    def test_el_alta_deja_el_numero_pendiente(self, client, ana_tokens, sin_numeros):
        fila = _alta(client, ana_tokens, "0993053670").json()[0]
        assert fila["verificado"] is False

    def test_el_codigo_bueno_lo_deja_facturando(
        self, client, ana_tokens, sin_numeros, codigo_fijo, admin_db
    ):
        fila = _alta(client, ana_tokens, "0993053670").json()[0]
        r = _verificar(client, ana_tokens, fila["id"])
        assert r.status_code == 200
        assert r.json()[0]["verificado"] is True
        assert tenant_por_telefono(admin_db, "593993053670").id == TENANT_A

    def test_el_codigo_malo_no_verifica_y_gasta_un_intento(
        self, client, ana_tokens, sin_numeros, codigo_fijo, admin_db
    ):
        fila = _alta(client, ana_tokens, "0993053670").json()[0]
        r = _verificar(client, ana_tokens, fila["id"], "000000")
        assert r.status_code == 409
        assert "no es" in r.json()["detail"]
        admin_db.expire_all()
        assert admin_db.get(WhatsappNumero, uuid.UUID(fila["id"])).codigo_intentos == 1

    def test_a_los_cinco_fallos_se_quema(self, client, ana_tokens, sin_numeros, codigo_fijo):
        """Sin esto, seis dígitos se adivinan a fuerza de intentos."""
        fila = _alta(client, ana_tokens, "0993053670").json()[0]
        for _ in range(verificacion_numero.MAX_INTENTOS):
            assert _verificar(client, ana_tokens, fila["id"], "000000").status_code == 409
        # Y ya ni el bueno vale: hay que pedir uno nuevo
        r = _verificar(client, ana_tokens, fila["id"])
        assert r.status_code == 409
        assert "Demasiados intentos" in r.json()["detail"]

    def test_un_codigo_caducado_no_vale(
        self, client, ana_tokens, sin_numeros, codigo_fijo, admin_db
    ):
        fila = _alta(client, ana_tokens, "0993053670").json()[0]
        guardado = admin_db.get(WhatsappNumero, uuid.UUID(fila["id"]))
        guardado.codigo_expira = datetime.now(UTC) - timedelta(minutes=1)
        admin_db.commit()
        r = _verificar(client, ana_tokens, fila["id"])
        assert r.status_code == 409
        assert "caducó" in r.json()["detail"]

    def test_pedir_uno_nuevo_invalida_el_anterior(
        self, client, ana_tokens, sin_numeros, monkeypatch, admin_db
    ):
        """Si el viejo siguiera valiendo, pedir diez códigos daría cincuenta
        intentos en vez de cinco."""
        monkeypatch.setattr(verificacion_numero, "generar", lambda: "111111")
        fila = _alta(client, ana_tokens, "0993053670").json()[0]
        monkeypatch.setattr(verificacion_numero, "generar", lambda: "222222")
        cab = auth_headers(ana_tokens["access_token"])
        assert client.post(f"{RUTA}/{fila['id']}/codigo", headers=cab).status_code == 200

        assert _verificar(client, ana_tokens, fila["id"], "111111").status_code == 409
        assert _verificar(client, ana_tokens, fila["id"], "222222").status_code == 200

    def test_verificar_dos_veces_no_es_error(self, client, ana_tokens, sin_numeros, codigo_fijo):
        fila = _alta(client, ana_tokens, "0993053670").json()[0]
        assert _verificar(client, ana_tokens, fila["id"]).status_code == 200
        assert _verificar(client, ana_tokens, fila["id"]).status_code == 200

    def test_no_se_manda_un_codigo_a_cualquiera_sin_freno(
        self, client, ana_tokens, sin_numeros, codigo_fijo
    ):
        """Cada envío es una plantilla que Meta cobra, y del otro lado hay una
        persona que no pidió nada."""
        fila = _alta(client, ana_tokens, "0993053670").json()[0]
        cab = auth_headers(ana_tokens["access_token"])
        codigos = [
            client.post(f"{RUTA}/{fila['id']}/codigo", headers=cab).status_code
            for _ in range(verificacion_numero.MAX_ENVIOS + 1)
        ]
        assert 429 in codigos

    def test_un_pendiente_ajeno_no_secuestra_la_verificacion(
        self, client, ana_tokens, bob_tokens, sin_numeros, monkeypatch, admin_db
    ):
        """EL ATAQUE QUE DESTAPÓ LA REVISIÓN, con códigos DISTINTOS.

        Bob da de alta el teléfono de Ana y no lo verifica nunca. Si la
        comprobación eligiera «la fila pendiente más antigua», la de Bob se
        comería los intentos de Ana y su caducidad, dejándole el número
        inverificable para siempre. La fila la elige el CÓDIGO, no la edad.
        """
        monkeypatch.setattr(verificacion_numero, "generar", lambda: "111111")
        de_bob = next(
            n
            for n in _alta(client, bob_tokens, "0993053670").json()
            if n["numero"] == "593993053670"
        )
        monkeypatch.setattr(verificacion_numero, "generar", lambda: "222222")
        de_ana = _alta(client, ana_tokens, "0993053670").json()[0]

        # Ana teclea SU código y se verifica, con el okupa delante
        assert _verificar(client, ana_tokens, de_ana["id"], "222222").status_code == 200
        assert tenant_por_telefono(admin_db, "593993053670").id == TENANT_A

        # Y a Bob no se le regaló nada: su fila sigue pendiente y ya no puede
        admin_db.expire_all()
        assert admin_db.get(WhatsappNumero, uuid.UUID(de_bob["id"])).verificado_at is None
        r = _verificar(client, bob_tokens, de_bob["id"], "111111")
        assert r.status_code == 409
        assert "otra cuenta" in r.json()["detail"]

    def test_un_fallo_se_le_cobra_a_quien_pregunta_no_al_vecino(
        self, client, ana_tokens, bob_tokens, sin_numeros, monkeypatch, admin_db
    ):
        """Bob no puede quemarle a Ana los intentos de su código vivo."""
        monkeypatch.setattr(verificacion_numero, "generar", lambda: "222222")
        de_ana = _alta(client, ana_tokens, "0993053670").json()[0]
        monkeypatch.setattr(verificacion_numero, "generar", lambda: "111111")
        de_bob = next(
            n
            for n in _alta(client, bob_tokens, "0993053670").json()
            if n["numero"] == "593993053670"
        )

        for _ in range(verificacion_numero.MAX_INTENTOS):
            assert _verificar(client, bob_tokens, de_bob["id"], "000000").status_code == 409

        admin_db.expire_all()
        assert admin_db.get(WhatsappNumero, uuid.UUID(de_bob["id"])).codigo_intentos == 5
        assert admin_db.get(WhatsappNumero, uuid.UUID(de_ana["id"])).codigo_intentos == 0
        # Y Ana sigue pudiendo verificar el suyo
        assert _verificar(client, ana_tokens, de_ana["id"], "222222").status_code == 200

    def test_el_codigo_escrito_al_bot_tambien_verifica(
        self, client, ana_tokens, sin_numeros, codigo_fijo, admin_db
    ):
        """EL CAMINO QUE NO DEPENDE DE META. La persona escribe el código desde
        ese mismo teléfono: lo abre ella, así que no hace falta plantilla."""
        from app.tasks.whatsapp import procesar_mensaje

        _alta(client, ana_tokens, "0993053670")
        with pytest.raises(NumeroNoAutorizado):
            tenant_por_telefono(admin_db, "593993053670")

        procesar_mensaje(_webhook_desde("593993053670", f"VERIFICAR {CODIGO}"), enviar=False)

        admin_db.expire_all()
        assert tenant_por_telefono(admin_db, "593993053670").id == TENANT_A

    def test_a_un_desconocido_que_prueba_codigos_no_se_le_contesta(
        self, client, ana_tokens, sin_numeros, admin_db
    ):
        """Contestar confirmaría que el número existe."""
        from app.tasks.whatsapp import procesar_mensaje

        respuestas = procesar_mensaje(_webhook_desde("593000000000", "482913"), enviar=False)
        assert respuestas == []


def _webhook_desde(telefono: str, texto: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": telefono,
                                    "id": f"wamid.{uuid.uuid4().hex}",
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }
