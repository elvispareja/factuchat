"""Certificados .p12 (fase 2.2): validación, cifrado en reposo y metadatos."""

import pytest
from sqlalchemy import select, text

from app.db.models import AuditLog, Certificado
from tests.conftest import TENANT_A, auth_headers
from tests.sri_utils import generar_p12_prueba


def _subir(client, tokens, p12_bytes, password):
    return client.post(
        "/api/v1/certificados",
        files={"archivo": ("firma.p12", p12_bytes, "application/x-pkcs12")},
        data={"password": password},
        headers=auth_headers(tokens["access_token"]),
    )


class TestCertificados:
    def test_subida_valida_y_metadata(self, client, ana_tokens):
        p12_bytes, password, _pem = generar_p12_prueba()
        r = _subir(client, ana_tokens, p12_bytes, password)
        assert r.status_code == 201, r.text
        data = r.json()
        assert "FIRMA DE PRUEBAS FACTUCHAT" in data["subject"]
        assert data["activo"] is True

        r = client.get("/api/v1/certificados", headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 200
        assert "p12" not in r.text  # jamás se devuelve el archivo ni la clave

    def test_password_incorrecta_rechazada(self, client, ana_tokens):
        p12_bytes, _password, _pem = generar_p12_prueba()
        r = _subir(client, ana_tokens, p12_bytes, "clave-equivocada")
        assert r.status_code == 422
        assert "clave-equivocada" not in r.text

    def test_cifrado_en_reposo(self, client, ana_tokens, admin_db):
        p12_bytes, password, _pem = generar_p12_prueba()
        r = _subir(client, ana_tokens, p12_bytes, password)
        assert r.status_code == 201

        # Los dos negocios de prueba tienen el suyo: hay que mirar el de A
        cert = admin_db.scalars(select(Certificado).where(Certificado.tenant_id == TENANT_A)).one()
        # Ni el binario del .p12 ni la contraseña aparecen en claro en la BD
        import base64

        assert base64.b64encode(p12_bytes).decode()[:60] not in cert.p12_data_enc
        assert password not in cert.p12_password_enc

        # El AAD liga cada blob a su uso: descifrar la contraseña con el AAD del
        # archivo (o al revés) DEBE fallar, no devolver el otro secreto.
        from cryptography.exceptions import InvalidTag

        from app.core.config import get_settings
        from app.core.crypto import aesgcm_decrypt
        from app.sri.firma import AAD_P12, AAD_P12_PASSWORD

        clave = get_settings().cert_enc_key
        assert aesgcm_decrypt(clave, cert.p12_data_enc, AAD_P12) == p12_bytes
        assert aesgcm_decrypt(clave, cert.p12_password_enc, AAD_P12_PASSWORD) == password.encode()
        with pytest.raises(InvalidTag):
            aesgcm_decrypt(clave, cert.p12_password_enc, AAD_P12)
        with pytest.raises(InvalidTag):
            aesgcm_decrypt(clave, cert.p12_data_enc, AAD_P12_PASSWORD)

        # Nonce aleatorio por llamada: cifrar dos veces lo mismo da blobs distintos
        from app.core.crypto import aesgcm_encrypt

        assert aesgcm_encrypt(clave, b"x", AAD_P12) != aesgcm_encrypt(clave, b"x", AAD_P12)

        # La fila completa de users/certificados en audit_log va enmascarada
        entry = admin_db.scalars(
            select(AuditLog)
            .where(AuditLog.tabla == "certificados")
            .order_by(AuditLog.created_at.desc())
        ).first()
        assert entry is not None
        despues = str(entry.despues)
        assert password not in despues
        assert "***" in despues

    def test_certificado_de_otro_ruc_rechazado(self, client, ana_tokens):
        """Firmar con el certificado de otro contribuyente es rechazo seguro
        del SRI y un problema legal: se corta en la subida."""
        p12_bytes, password, _pem = generar_p12_prueba(identificacion="0912345678")
        r = _subir(client, ana_tokens, p12_bytes, password)
        assert r.status_code == 422
        assert "RUC" in r.json()["detail"]

    def test_certificado_del_titular_aceptado(self, client, ana_tokens):
        # TENANT_A tiene RUC 1790012345001 → cédula del titular 1790012345
        p12_bytes, password, _pem = generar_p12_prueba(identificacion="1790012345")
        assert _subir(client, ana_tokens, p12_bytes, password).status_code == 201

    def test_certificado_caducado_rechazado(self, client, ana_tokens):
        p12_bytes, password, _pem = generar_p12_prueba(dias_validez=-1, dias_desde=-400)
        r = _subir(client, ana_tokens, p12_bytes, password)
        assert r.status_code == 422
        assert "caduc" in r.json()["detail"].lower()

    def test_tenant_b_no_ve_certificado_de_a(self, client, ana_tokens, bob_tokens):
        """Cada negocio ve SU certificado y solo el suyo.

        Antes este test comprobaba que B recibía un 404 porque no tenía
        ninguno. Ahora los dos tienen el suyo —hace falta para operar— así que
        el aislamiento se comprueba de forma más fuerte: B recibe el suyo, y en
        su respuesta no aparece nada del de A.
        """
        p12_bytes, password, _pem = generar_p12_prueba(identificacion="1790012345")
        assert _subir(client, ana_tokens, p12_bytes, password).status_code == 201
        de_a = client.get(
            "/api/v1/certificados", headers=auth_headers(ana_tokens["access_token"])
        ).json()

        r = client.get("/api/v1/certificados", headers=auth_headers(bob_tokens["access_token"]))
        assert r.status_code == 200
        de_b = r.json()
        assert de_b["subject"] != de_a["subject"]
        assert "1790012345" not in r.text  # ni rastro de la identificación de A

    def test_rls_directo_en_bd(self, app_engine, client, ana_tokens):
        p12_bytes, password, _pem = generar_p12_prueba()
        assert _subir(client, ana_tokens, p12_bytes, password).status_code == 201
        with app_engine.connect() as conn:
            n = conn.execute(text("SELECT count(*) FROM certificados")).scalar()
            assert n == 0  # sin contexto de tenant no hay filas


class TestSinFirmaNoSeOpera:
    """El .p12 y su clave son privados del contribuyente: Factuchat no los pide
    en el alta ni los ve nunca. El cliente los sube él mismo en su primer
    ingreso, y hasta entonces no puede operar.

    El candado vive en el SERVIDOR. Esconder botones no sirve de nada: quien
    tenga un token puede llamar a la API a mano.
    """

    RUTAS_BLOQUEADAS = [
        ("GET", "/api/v1/clientes"),
        ("GET", "/api/v1/productos"),
        ("GET", "/api/v1/comprobantes"),
        ("GET", "/api/v1/inicio"),
        ("GET", "/api/v1/reportes/resumen"),
        ("GET", "/api/v1/retenciones"),
    ]

    @pytest.fixture()
    def sin_firma(self, client, admin_db):
        """Un negocio recién dado de alta: existe, tiene usuario y plan, y aún
        no ha subido su certificado."""
        from app.db.models import Tenant, User
        from app.db.models.enums import Rol

        t = Tenant(
            ruc="1790055555001",
            razon_social="Recién Llegada S.A.",
            email="nueva@empresa.ec",
            direccion_matriz="Av. Nueva 100, Quito",
        )
        admin_db.add(t)
        admin_db.flush()
        admin_db.add(
            User(
                tenant_id=t.id,
                email="nueva@empresa.ec",
                nombre="Nueva",
                rol=Rol.CLIENTE,
            )
        )
        admin_db.commit()

        from tests.conftest import codigo_de

        r = client.post(
            "/api/v1/auth/login",
            json={
                "email": "nueva@empresa.ec",
                "codigo": codigo_de(admin_db.get_bind(), "nueva@empresa.ec"),
            },
            headers={"X-Real-IP": "10.7.7.7"},
        )
        assert r.status_code == 200, r.text
        yield r.json()

        for u in admin_db.scalars(select(User).where(User.tenant_id == t.id)).all():
            admin_db.delete(u)
        for c in admin_db.scalars(select(Certificado).where(Certificado.tenant_id == t.id)).all():
            admin_db.delete(c)
        admin_db.flush()
        admin_db.delete(admin_db.get(Tenant, t.id))
        admin_db.commit()

    @pytest.mark.parametrize("metodo,ruta", RUTAS_BLOQUEADAS)
    def test_no_puede_operar(self, client, sin_firma, metodo, ruta):
        r = client.request(metodo, ruta, headers=auth_headers(sin_firma["access_token"]))
        assert r.status_code == 403, f"{ruta} deberia estar bloqueada"
        assert r.json()["detail"]["codigo"] == "FIRMA_REQUERIDA"

    def test_tampoco_puede_emitir(self, client, sin_firma):
        r = client.post(
            "/api/v1/comprobantes/facturas",
            json={"cliente": {"identificacion": "9999999999999", "tipo_id": "04"}, "lineas": []},
            headers=auth_headers(sin_firma["access_token"]),
        )
        assert r.status_code == 403
        assert r.json()["detail"]["codigo"] == "FIRMA_REQUERIDA"

    def test_si_puede_hacer_lo_necesario_para_desbloquearse(self, client, sin_firma):
        """Entrar, ver su estado y subir el certificado. Si esto quedara
        bloqueado, el cliente no tendría forma de salir del candado."""
        h = auth_headers(sin_firma["access_token"])

        r = client.get("/api/v1/panel/estado", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["firma"]["cargada"] is False

        assert client.get("/api/v1/certificados", headers=h).status_code == 404
        assert client.get("/api/v1/auth/me", headers=h).status_code == 200

    def test_al_subir_su_firma_queda_desbloqueado(self, client, sin_firma):
        h = auth_headers(sin_firma["access_token"])
        assert client.get("/api/v1/clientes", headers=h).status_code == 403

        p12_bytes, password, _pem = generar_p12_prueba(identificacion="1790055555")
        r = client.post(
            "/api/v1/certificados",
            files={"archivo": ("firma.p12", p12_bytes, "application/x-pkcs12")},
            data={"password": password},
            headers=h,
        )
        assert r.status_code == 201, r.text

        assert client.get("/api/v1/clientes", headers=h).status_code == 200
        assert client.get("/api/v1/panel/estado", headers=h).json()["firma"]["cargada"] is True

    def test_el_personal_interno_no_queda_atrapado_por_el_candado(self, client, admin_auth):
        """El candado es para negocios que emiten. El panel interno no emite."""
        h = auth_headers(admin_auth["access"])
        assert client.get("/api/v1/sa/clientes", headers=h).status_code == 200

    def test_el_webhook_del_buzon_sigue_siendo_publico(self, client):
        """Lo llama el proveedor de correo, sin sesión ni certificado. Al poner
        el candado por router se quedó exigiendo login; esto lo fija."""
        r = client.post("/api/v1/buzon/webhook", content=b"{}")
        assert r.status_code != 401, "el webhook no puede pedir sesión"
