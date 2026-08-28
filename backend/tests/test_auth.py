"""Autenticación sin contraseña: correo + código de 6 dígitos.

El cliente pide un código y le llega al correo. El personal interno usa su app
de autenticación. Ya no hay contraseñas en ninguna parte.

Un código de seis dígitos es un millón de combinaciones, que no es nada si se
puede probar sin límite. Lo que lo sostiene son las reglas de alrededor, y esta
suite existe sobre todo para fijarlas: caducidad, un solo uso, contador de
intentos, un único código vivo por cuenta, y ninguna respuesta que revele si una
dirección tiene cuenta.
"""

import pyotp
import pytest
from sqlalchemy import text

from tests.conftest import USERS, auth_headers, codigo_de, do_login


def pedir_codigo(client, email: str, ip: str = "10.9.9.9"):
    return client.post("/api/v1/auth/codigo", json={"email": email}, headers={"X-Real-IP": ip})


def entrar(client, email: str, codigo: str, ip: str = "10.9.9.9"):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "codigo": codigo},
        headers={"X-Real-IP": ip},
    )


class TestPedirCodigo:
    def test_una_cuenta_real_recibe_su_codigo(self, client, admin_engine, clean_redis):
        r = pedir_codigo(client, USERS["ana"]["email"])
        assert r.status_code == 202, r.text
        # El código NUNCA viaja en la respuesta: solo por correo
        assert not any(c.isdigit() for c in r.json()["detail"] if c not in "6")

    def test_una_direccion_desconocida_responde_exactamente_igual(
        self, client, admin_engine, clean_redis
    ):
        """Si la respuesta cambiara, esta ruta sería un buscador de clientes."""
        buena = pedir_codigo(client, USERS["ana"]["email"], ip="10.1.1.1")
        mala = pedir_codigo(client, "no-existe-nadie@ejemplo.ec", ip="10.1.1.2")
        assert buena.status_code == mala.status_code == 202
        assert buena.json() == mala.json()

    def test_una_cuenta_interna_responde_igual_aunque_no_reciba_correo(
        self, client, admin_auth, clean_redis
    ):
        """El superadmin usa su app; decir «a esta no le mandamos correo»
        revelaría quién trabaja aquí."""
        cliente = pedir_codigo(client, USERS["ana"]["email"], ip="10.1.2.1")
        interna = pedir_codigo(client, USERS["root"]["email"], ip="10.1.2.2")
        assert cliente.json() == interna.json()

    def test_de_la_base_no_se_puede_sacar_el_codigo(self, client, admin_engine, clean_redis):
        """Solo se guarda su sha256: una copia de la tabla no sirve para entrar."""
        codigo = codigo_de(admin_engine, USERS["ana"]["email"])
        with admin_engine.connect() as c:
            guardados = [
                f[0]
                for f in c.execute(
                    text("SELECT codigo_hash FROM codigos_acceso WHERE usado_at IS NULL")
                )
            ]
        assert codigo not in guardados
        assert all(len(h) == 64 for h in guardados)


class TestEntrarConCodigo:
    def test_el_codigo_correcto_abre_sesion(self, client, admin_engine, clean_redis):
        r = do_login(client, "ana", admin_engine=admin_engine)
        assert r.status_code == 200, r.text
        assert r.json()["access_token"]

    def test_el_codigo_solo_sirve_una_vez(self, client, admin_engine, clean_redis):
        codigo = codigo_de(admin_engine, USERS["ana"]["email"])
        assert entrar(client, USERS["ana"]["email"], codigo).status_code == 200
        segunda = entrar(client, USERS["ana"]["email"], codigo)
        assert segunda.status_code == 401
        assert "nuevo" in segunda.json()["detail"].lower()

    def test_pedir_otro_codigo_invalida_el_anterior(self, client, admin_engine, clean_redis):
        """Si convivieran varios, pedir diez códigos daría cincuenta intentos
        en vez de cinco."""
        viejo = codigo_de(admin_engine, USERS["bob"]["email"])
        nuevo = codigo_de(admin_engine, USERS["bob"]["email"])
        assert entrar(client, USERS["bob"]["email"], viejo).status_code == 401
        assert entrar(client, USERS["bob"]["email"], nuevo).status_code == 200

    def test_el_codigo_de_otra_cuenta_no_vale(self, client, admin_engine, clean_redis):
        de_ana = codigo_de(admin_engine, USERS["ana"]["email"])
        r = entrar(client, USERS["bob"]["email"], de_ana)
        assert r.status_code == 401

    def test_un_codigo_caducado_no_vale(self, client, admin_engine, clean_redis):
        codigo = codigo_de(admin_engine, USERS["ana"]["email"])
        with admin_engine.begin() as c:
            c.execute(
                text(
                    "UPDATE codigos_acceso SET expira_at = now() - interval '1 minute'"
                    " WHERE usado_at IS NULL"
                )
            )
        r = entrar(client, USERS["ana"]["email"], codigo)
        assert r.status_code == 401
        assert "caducado" in r.json()["detail"].lower()

    def test_se_quema_tras_cinco_intentos(self, admin_engine, database):
        """Sin este contador, un millón de combinaciones se prueban solas.

        Se comprueba sobre el servicio y no por HTTP porque el bloqueo de la
        cuenta salta a los cinco fallos y taparía justo lo que se quiere medir.
        """
        from sqlalchemy.orm import Session

        from app.services import acceso

        with Session(admin_engine) as db:
            uid = db.execute(
                text("SELECT id FROM users WHERE email = :e"), {"e": USERS["rl1"]["email"]}
            ).scalar_one()
            bueno = acceso.emitir(db, uid, "10.0.0.1")
            db.commit()

            malo = "000000" if bueno != "000000" else "111111"
            for _ in range(acceso.MAX_INTENTOS):
                assert acceso.comprobar(db, uid, malo) == "no"
                db.commit()

            # Al siguiente está agotado, y el código BUENO tampoco sirve ya
            assert acceso.comprobar(db, uid, malo) == "agotado"
            db.commit()
            assert acceso.comprobar(db, uid, bueno) != "ok"
            db.commit()

    def test_el_mensaje_no_distingue_cuenta_inexistente_de_codigo_malo(
        self, client, admin_engine, clean_redis
    ):
        """Esta prueba encontró una fuga real: «ese código caducó» solo puede
        pasarle a una dirección que TIENE cuenta, así que distinguirlo del
        «código incorrecto» convertía el login en un comprobador de clientes."""
        sin_cuenta = entrar(client, "no-existe@ejemplo.ec", "123456", ip="10.6.1.1")
        codigo_malo = entrar(client, USERS["bob"]["email"], "999999", ip="10.6.1.2")
        codigo_de(admin_engine, USERS["rl2"]["email"])
        caducado = entrar(client, USERS["rl2"]["email"], "888888", ip="10.6.1.3")

        respuestas = [sin_cuenta, codigo_malo, caducado]
        assert {r.status_code for r in respuestas} == {401}
        assert len({r.json()["detail"] for r in respuestas}) == 1

    def test_me_requiere_token(self, client, database):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_me_con_token(self, client, ana_tokens):
        r = client.get("/api/v1/auth/me", headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 200
        assert r.json()["email"] == USERS["ana"]["email"]


class TestPersonalInterno:
    def test_el_superadmin_entra_con_su_app_de_autenticacion(self, client, admin_auth, clean_redis):
        r = entrar(
            client, USERS["root"]["email"], pyotp.TOTP(admin_auth["secret"]).now(), ip="10.8.1.1"
        )
        assert r.status_code == 200, r.text

    def test_un_codigo_de_app_equivocado_no_entra(self, client, admin_auth, clean_redis):
        r = entrar(client, USERS["root"]["email"], "000000", ip="10.8.1.2")
        assert r.status_code == 401

    def test_el_correo_no_abre_la_puerta_de_una_cuenta_con_app(
        self, client, admin_auth, admin_engine, clean_redis
    ):
        """Quien ya tiene 2FA no puede saltársela pidiendo un código por correo:
        si pudiera, el segundo factor sería decorativo."""
        codigo = codigo_de(admin_engine, USERS["root"]["email"])
        r = entrar(client, USERS["root"]["email"], codigo, ip="10.8.1.3")
        assert r.status_code == 401

    def test_darse_de_alta_en_2fa_exige_antes_el_codigo_del_correo(
        self, client, admin_engine, clean_redis
    ):
        """El agujero que abrió quitar la contraseña: sin esta condición,
        cualquiera que supiera el correo del superadmin podía pedir un token de
        alta, registrarse en 2FA y entrar."""
        r = entrar(client, USERS["root"]["email"], "123456", ip="10.8.2.1")
        assert r.status_code == 401
        assert "setup_token" not in r.text


class TestRateLimit:
    def test_429_tras_varios_intentos_desde_la_misma_ip(self, client, database, clean_redis):
        for _ in range(5):
            entrar(client, "quien-sea@ejemplo.ec", "123456", ip="10.7.7.7")
        r = entrar(client, "otro@ejemplo.ec", "123456", ip="10.7.7.7")
        assert r.status_code == 429
        assert r.headers.get("Retry-After")

    def test_429_por_cuenta_aunque_cambie_la_ip(self, client, database, clean_redis):
        for i in range(5):
            entrar(client, USERS["lock"]["email"], "123456", ip=f"10.7.8.{i}")
        r = entrar(client, USERS["lock"]["email"], "123456", ip="10.7.8.200")
        assert r.status_code == 429

    def test_pedir_codigo_tambien_esta_limitado(self, client, database, clean_redis):
        """Sin límite aquí, esta ruta sería un cañón de correos contra cualquier
        dirección."""
        for _ in range(5):
            pedir_codigo(client, USERS["ana"]["email"], ip="10.7.9.9")
        r = pedir_codigo(client, USERS["ana"]["email"], ip="10.7.9.9")
        assert r.status_code == 429


class TestBloqueoProgresivo:
    def test_cuenta_bloqueada_tras_fallos(self, client, database, clean_redis, admin_engine):
        with admin_engine.begin() as c:
            c.execute(
                text(
                    "UPDATE users SET failed_attempts = 0, locked_until = NULL,"
                    " lockout_count = 0 WHERE email = :e"
                ),
                {"e": USERS["mask"]["email"]},
            )
        codigo_de(admin_engine, USERS["mask"]["email"])
        for i in range(5):
            entrar(client, USERS["mask"]["email"], "000000", ip=f"10.3.3.{i}")
            # cada intento va desde otra IP: aquí se mide el bloqueo de CUENTA

        with admin_engine.connect() as c:
            bloqueada = c.execute(
                text("SELECT locked_until FROM users WHERE email = :e"),
                {"e": USERS["mask"]["email"]},
            ).scalar()
        assert bloqueada is not None


class TestRefreshRotacion:
    def test_refresh_rota_y_detecta_reuso(self, client, admin_engine, clean_redis):
        r = do_login(client, "ana", admin_engine=admin_engine, ip="10.20.1.1")
        assert r.status_code == 200, r.text
        entrada = r.json()
        primero = entrada["refresh_token"]

        r = client.post("/api/v1/auth/refresh", json={"refresh_token": primero})
        assert r.status_code == 200
        segundo = r.json()["refresh_token"]
        assert segundo != primero

        # Reusar el viejo revoca la familia entera
        assert (
            client.post("/api/v1/auth/refresh", json={"refresh_token": primero}).status_code == 401
        )
        assert (
            client.post("/api/v1/auth/refresh", json={"refresh_token": segundo}).status_code == 401
        )

    def test_logout_revoca_refresh(self, client, admin_engine, clean_redis):
        r = do_login(client, "bob", admin_engine=admin_engine, ip="10.20.1.2")
        assert r.status_code == 200, r.text
        entrada = r.json()
        assert (
            client.post(
                "/api/v1/auth/logout", json={"refresh_token": entrada["refresh_token"]}
            ).status_code
            == 204
        )
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": entrada["refresh_token"]})
        assert r.status_code == 401


class TestSinContrasenas:
    def test_la_columna_de_contrasenas_ya_no_existe(self, admin_engine):
        """Dejarla sin usar habría sido peor que quitarla: alguien acabaría
        comprobándola «por si acaso» y tendríamos dos puertas, una sin vigilar."""
        with admin_engine.connect() as c:
            hay = c.execute(
                text(
                    "SELECT 1 FROM information_schema.columns"
                    " WHERE table_name = 'users' AND column_name = 'password_hash'"
                )
            ).first()
        assert hay is None

    def test_el_login_ignora_una_contrasena_si_alguien_la_manda(self, client, database):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": USERS["ana"]["email"], "password": "loquesea"},
            headers={"X-Real-IP": "10.9.1.1"},
        )
        # Falta `codigo`: la petición ni siquiera es válida
        assert r.status_code == 422

    @pytest.mark.parametrize("ruta", ["/api/v1/auth/invitacion"])
    def test_las_rutas_de_la_invitacion_ya_no_existen(self, client, ruta):
        assert client.get(ruta).status_code == 404
