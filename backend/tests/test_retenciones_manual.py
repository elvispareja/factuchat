"""Registrar A MANO una retención recibida (POST /api/v1/retenciones).

El buzón por correo está apagado y sin clave de cifrado —así corre esta suite,
igual que producción hoy—, pero al contribuyente le retienen de todas formas: su
cliente le manda el XML por WhatsApp o se lo entrega impreso. Aquí se prueba que
esa puerta existe y que NO se salta ninguna de las garantías del buzón:

  · el comprobante tiene que retener a ESTE inquilino,
  · la misma retención no cuenta dos veces, entre por donde entre,
  · nace sin verificar: se ve en la bandeja, pero no suma al saldo,
  · un XML ilegible, o que no es una retención, da un motivo escrito para el
    cliente y no un 500.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.models import RetencionRecibida
from app.services import retenciones
from tests.buzon_utils import clave_de_prueba, correo, xml_retencion
from tests.conftest import TENANT_A, auth_headers
from tests.test_buzon import _con_plan

RUC_A = "1790012345001"
RUC_B = "1790099999001"

# Una factura recibida: XML válido, comprobante real, pero no es crédito
FACTURA = f"""<?xml version="1.0" encoding="UTF-8"?>
<factura id="comprobante" version="1.1.0">
  <infoTributaria>
    <ruc>0992745103001</ruc>
    <razonSocial>Comercial Andrade Cía. Ltda.</razonSocial>
    <claveAcceso>{clave_de_prueba(7100001)}</claveAcceso>
    <codDoc>01</codDoc>
    <estab>001</estab><ptoEmi>001</ptoEmi><secuencial>000009999</secuencial>
  </infoTributaria>
  <infoFactura>
    <fechaEmision>12/08/2026</fechaEmision>
    <identificacionComprador>{RUC_A}</identificacionComprador>
  </infoFactura>
</factura>""".encode()


@pytest.fixture(autouse=True)
def sin_restos(admin_db):
    """Cada test se lleva sus retenciones: son crédito tributario y el saldo de
    un test no puede sumarse al del siguiente."""
    yield
    admin_db.execute(text("DELETE FROM retenciones_recibidas"))
    admin_db.execute(text("DELETE FROM buzon_correos"))
    admin_db.execute(text("DELETE FROM analisis_ia"))
    admin_db.commit()


@pytest.fixture()
def con_archivos(admin_db):
    """La subida a mano lleva la MISMA puerta de plan que la bandeja."""
    yield from _con_plan(admin_db, TENANT_A, "INDEPENDIENTE")


@pytest.fixture()
def encolados(monkeypatch):
    """La verificación contra el SRI es un task: aquí solo se anota que se
    encoló, para no despertar al worker de verdad."""
    from app.api.routes import buzon as rutas

    vistos: list[tuple[str, str]] = []
    monkeypatch.setattr(
        rutas.verificar_retencion, "delay", lambda t, r: vistos.append((t, r)) or None
    )
    return vistos


@pytest.fixture()
def ana(ana_tokens):
    return auth_headers(ana_tokens["access_token"])


def _subir(client, ana, xml: bytes, nombre: str = "retencion.xml", tipo: str = "application/xml"):
    return client.post("/api/v1/retenciones", headers=ana, files={"archivo": (nombre, xml, tipo)})


class TestCaminoFeliz:
    def test_la_retencion_subida_a_mano_queda_registrada(
        self, client, ana, con_archivos, encolados, admin_db
    ):
        clave = clave_de_prueba(7100010)
        r = _subir(client, ana, xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave))
        assert r.status_code == 201, r.text

        cuerpo = r.json()
        assert cuerpo["origen"] == "MANUAL"
        assert cuerpo["verificada"] is False
        assert cuerpo["renta"] == "41.40"
        assert cuerpo["iva"] == "54.32"

        fila = admin_db.scalars(
            select(RetencionRecibida).where(RetencionRecibida.clave_acceso == clave)
        ).one()
        assert fila.tenant_id == TENANT_A
        assert fila.origen == "MANUAL"
        assert fila.buzon_correo_id is None, "no vino de ningún correo"
        assert fila.verificada is False
        assert fila.concepto == "Retención renta 8% e IVA 70%"

        # Y se le preguntó al SRI: es el ÚNICO camino que la convierte en crédito
        assert encolados == [(str(TENANT_A), str(fila.id))]

    def test_se_ve_en_la_bandeja_con_el_buzon_apagado(
        self, client, ana, con_archivos, encolados, admin_db
    ):
        """Si el módulo apagado escondiera la bandeja, lo subido a mano se
        perdería de vista y esta función no serviría de nada."""
        assert retenciones.activo(admin_db) is False
        _subir(
            client, ana, xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7100011))
        )

        datos = client.get("/api/v1/retenciones", headers=ana).json()
        assert datos["activo"] is False, "el buzón sigue apagado, como debe"
        assert len(datos["retenciones"]) == 1
        assert datos["retenciones"][0]["origen"] == "MANUAL"

    def test_no_suma_al_saldo_hasta_que_el_sri_la_verifica(
        self, client, ana, con_archivos, encolados, admin_db
    ):
        """Un XML lo escribe cualquiera: hasta que el SRI conteste, se ve pero
        no baja el impuesto que el cliente declara."""
        clave = clave_de_prueba(7100012)
        _subir(client, ana, xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave))

        datos = client.get("/api/v1/retenciones", headers=ana).json()
        assert len(datos["retenciones"]) == 1
        assert datos["saldo"] == "0", "una retención sin verificar entró al saldo"

        # Lo que hace `verificar_retencion` cuando el SRI dice que sí
        admin_db.execute(
            text("UPDATE retenciones_recibidas SET verificada = true WHERE clave_acceso = :c"),
            {"c": clave},
        )
        admin_db.commit()

        datos = client.get("/api/v1/retenciones", headers=ana).json()
        assert Decimal(datos["saldo"]) == Decimal("95.72")
        assert datos["saldo_iva"] == "54.32"
        assert datos["saldo_renta"] == "41.40"

    def test_sin_clave_de_cifrado_se_registra_igual_pero_sin_guardar_el_xml(
        self, client, ana, con_archivos, encolados, admin_db
    ):
        """BUZON_ENC_KEY no está puesta. En claro no se guarda NUNCA, así que la
        fila entra sin fichero: el crédito lo sostienen los datos y la clave de
        acceso, no el adjunto."""
        assert not get_settings().buzon_enc_key
        clave = clave_de_prueba(7100013)
        r = _subir(client, ana, xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave))
        assert r.status_code == 201, r.text
        assert r.json()["tiene_xml"] is False

        fila = admin_db.scalars(
            select(RetencionRecibida).where(RetencionRecibida.clave_acceso == clave)
        ).one()
        assert fila.xml_path is None


class TestDefensas:
    def test_el_comprobante_que_retiene_a_otro_ruc_se_rechaza(
        self, client, ana, con_archivos, encolados, admin_db
    ):
        """Sin este control, subir el comprobante de OTRO se vuelve crédito
        propio: basta con conocer un RUC, que está en cada factura emitida."""
        r = _subir(
            client, ana, xml_retencion(ruc_retenido=RUC_B, clave_acceso=clave_de_prueba(7100020))
        )
        assert r.status_code == 422, r.text
        assert RUC_B in r.json()["detail"]
        assert "no es el RUC de este buzón" in r.json()["detail"]

        assert admin_db.execute(text("SELECT count(*) FROM retenciones_recibidas")).scalar() == 0
        assert encolados == []

    def test_sin_identificacion_del_retenido_tampoco_entra(
        self, client, ana, con_archivos, encolados
    ):
        """La ausencia del dato saltaba el control en vez de fallarlo."""
        xml = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7100021)).replace(
            b"<identificacionSujetoRetenido>" + RUC_A.encode() + b"</identificacionSujetoRetenido>",
            b"",
        )
        r = _subir(client, ana, xml)
        assert r.status_code == 422, r.text
        assert "no dice a quién retiene" in r.json()["detail"]

    def test_el_duplicado_no_crea_una_segunda_fila(
        self, client, ana, con_archivos, encolados, admin_db
    ):
        """La misma retención dos veces sería crédito inventado."""
        xml = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7100030))
        assert _subir(client, ana, xml).status_code == 201

        r = _subir(client, ana, xml)
        assert r.status_code == 409, r.text
        assert "ya estaba registrada" in r.json()["detail"]

        assert admin_db.execute(text("SELECT count(*) FROM retenciones_recibidas")).scalar() == 1
        assert len(encolados) == 1, "se volvió a encolar la verificación de una duplicada"

    def test_lo_subido_a_mano_bloquea_al_mismo_comprobante_por_correo(
        self, client, ana, con_archivos, encolados, admin_db, monkeypatch
    ):
        """El otro cruce: primero a mano y después por el buzón. La clave de
        acceso es la misma, así que el correo tiene que quedar en DUPLICADO."""
        from app.tasks import buzon as tareas

        s = get_settings()
        previa_key, previo_dominio = s.buzon_enc_key, s.buzon_dominio
        s.buzon_enc_key = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
        s.buzon_dominio = "buzon.factuchat.test"
        monkeypatch.setattr(tareas.verificar_retencion, "delay", lambda t, r: None)
        try:
            clave = clave_de_prueba(7100031)
            xml = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave)
            assert _subir(client, ana, xml).status_code == 201

            mensaje = correo(
                para=f"{RUC_A}@{s.dominio_buzon}",
                adjunto=xml,
                message_id="<manual-y-correo@proveedor.ec>",
            )
            assert tareas.ingerir(mensaje) == "duplicado"
        finally:
            s.buzon_enc_key, s.buzon_dominio = previa_key, previo_dominio

        assert admin_db.execute(text("SELECT count(*) FROM retenciones_recibidas")).scalar() == 1

    def test_una_factura_no_es_una_retencion(self, client, ana, con_archivos, encolados, admin_db):
        """Se lee perfectamente, pero una factura recibida no es crédito."""
        r = _subir(client, ana, FACTURA, nombre="factura.xml")
        assert r.status_code == 422, r.text
        assert "Factura recibida" in r.json()["detail"]
        assert "no una retención" in r.json()["detail"]
        assert admin_db.execute(text("SELECT count(*) FROM retenciones_recibidas")).scalar() == 0

    def test_un_fichero_que_no_es_xml_da_error_explicado(
        self, client, ana, con_archivos, encolados
    ):
        """Con la extensión y el tipo cambiados: los pone quien sube el fichero,
        así que no deciden nada. Y el fallo se explica, no es un 500."""
        r = _subir(client, ana, b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n")
        assert r.status_code == 422, r.text
        assert "XML mal formado" in r.json()["detail"]

    def test_un_xml_con_doctype_no_lee_ficheros_del_contenedor(
        self, client, ana, con_archivos, encolados
    ):
        """Las defensas del parser valen igual en esta puerta: aquí el XML lo
        escribe un desconocido tanto como en el correo."""
        r = _subir(
            client,
            ana,
            b'<?xml version="1.0"?>\n'
            b'<!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
            b"<comprobanteRetencion><razonSocial>&xxe;</razonSocial></comprobanteRetencion>",
        )
        assert r.status_code == 422, r.text
        assert "DOCTYPE" in r.json()["detail"]

    def test_un_fichero_vacio_no_revienta(self, client, ana, con_archivos, encolados):
        r = _subir(client, ana, b"")
        assert r.status_code == 422, r.text
        assert "vacío" in r.json()["detail"]


class TestPlan:
    def test_sin_la_funcion_archivos_no_se_registran_retenciones(
        self, client, ana, admin_db, encolados
    ):
        """Decisión de producto tomada a la vista: la subida a mano lleva la
        MISMA puerta que la bandeja. Registrar algo que después no se puede ver
        no le sirve a nadie."""
        gen = _con_plan(admin_db, TENANT_A, "INICIAL")
        next(gen)
        try:
            r = _subir(
                client,
                ana,
                xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7100040)),
            )
            assert r.status_code == 402, r.text
            assert "bandeja de retenciones" in r.json()["detail"]["mensaje"]
        finally:
            next(gen, None)
