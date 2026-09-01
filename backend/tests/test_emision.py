"""Checklist F2 (en sandbox local con SRI simulado):
- factura autorizada de punta a punta (borrador → emitir → firmar → recepción →
  autorización → RIDE → correo);
- el certificado y su clave JAMÁS aparecen en logs;
- un rechazo muestra motivo legible y permite reintento con documento nuevo.

La llamada real al ambiente PRUEBAS del SRI queda documentada en
deploy/scripts/emision-prueba-sri.md (requiere el .p12 real del cliente).
"""

import logging
import random
import re
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AuditLog, Comprobante, Tenant
from app.sri.client import SRITransientError
from app.sri.firma import huella_sha256
from app.tasks.emision import ejecutar_pipeline
from tests.conftest import TENANT_A, auth_headers
from tests.sri_utils import (
    HTML_MANTENIMIENTO,
    RECEPCION_CLAVE_YA_REGISTRADA,
    RECEPCION_DEVUELTA,
    RECEPCION_RECIBIDA,
    SOAP_TRUNCADO,
    autorizacion_autorizado,
    autorizacion_de_otra_clave,
    autorizacion_rechazado,
    autorizacion_vacia,
    generar_p12_prueba,
)


def _autorizar_con_clave_real(sri) -> None:
    """El SRI responde la autorización de la clave que se le consultó.

    Un mock que devuelve siempre una clave fija ocultaría que aceptamos
    autorizaciones ajenas, así que se extrae la clave del propio request.
    """

    def _responder(request):
        cuerpo = request.content.decode()
        clave = re.search(r"<claveAccesoComprobante>(\d{49})</claveAccesoComprobante>", cuerpo)
        return httpx.Response(200, content=autorizacion_autorizado(clave.group(1)))

    sri.autorizacion.mock(side_effect=_responder)


@pytest.fixture()
def cert_subido(client, ana_tokens):
    p12_bytes, password, cert_pem = generar_p12_prueba()
    r = client.post(
        "/api/v1/certificados",
        files={"archivo": ("firma.p12", p12_bytes, "application/x-pkcs12")},
        data={"password": password},
        headers=auth_headers(ana_tokens["access_token"]),
    )
    assert r.status_code == 201, r.text
    return {"p12": p12_bytes, "password": password, "pem": cert_pem}


def _crear_cliente_con_email(client, tokens) -> dict:
    r = client.post(
        "/api/v1/clientes",
        json={
            "tipo_identificacion": "CEDULA",
            "identificacion": f"17{random.randint(10_000_000, 99_999_999)}",
            "razon_social": "Compradora Final",
            "email": "compradora@mail.ec",
        },
        headers=auth_headers(tokens["access_token"]),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _crear_factura(client, tokens, cliente_id=None, precio="10.00", cantidad="2"):
    r = client.post(
        "/api/v1/comprobantes/facturas",
        json={
            "cliente_final_id": cliente_id,
            "items": [
                {
                    "codigo": "SRV1",
                    "descripcion": "Servicio de prueba",
                    "cantidad": cantidad,
                    "precio_unitario": precio,
                    "codigo_iva": "4",
                }
            ],
            "forma_pago": "01",
        },
        headers=auth_headers(tokens["access_token"]),
    )
    return r


def _emitir(client, tokens, comp_id):
    return client.post(
        f"/api/v1/comprobantes/{comp_id}/emitir",
        json={},
        headers=auth_headers(tokens["access_token"]),
    )


def _pipeline(comp_id: str, max_iter: int = 6) -> None:
    for _ in range(max_iter):
        try:
            ejecutar_pipeline(str(TENANT_A), comp_id)
            return
        except SRITransientError:
            continue
    raise AssertionError("El pipeline no convergió")


@pytest.fixture()
def sri():
    s = get_settings()
    with respx.mock(assert_all_called=False) as mock:
        mock.recepcion = mock.post(s.sri_recepcion_url_pruebas)
        mock.autorizacion = mock.post(s.sri_autorizacion_url_pruebas)
        yield mock


class TestFacturaAutorizada:
    def test_punta_a_punta(self, client, ana_tokens, admin_db, cert_subido, sri, caplog):
        cliente = _crear_cliente_con_email(client, ana_tokens)

        # 1. Borrador: totales calculados en servidor, sin clave todavía (A06)
        r = _crear_factura(client, ana_tokens, cliente_id=cliente["id"])
        assert r.status_code == 201, r.text
        draft = r.json()
        assert draft["estado"] == "PENDIENTE"
        assert draft["clave_acceso"] is None
        assert draft["subtotal"] == "20.00"
        assert draft["iva"] == "3.00"
        assert draft["total"] == "23.00"

        # 2. Confirmación explícita: asigna secuencial y clave, y encola
        r = _emitir(client, ana_tokens, draft["id"])
        assert r.status_code == 202, r.text
        emitido = r.json()
        assert emitido["clave_acceso"] and len(emitido["clave_acceso"]) == 49
        assert emitido["numero"].startswith("001-001-")

        # 3. SRI simulado: primera consulta sin registro (reintento), luego autorizado
        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_RECIBIDA))
        sri.autorizacion.side_effect = [
            httpx.Response(200, content=autorizacion_vacia(emitido["clave_acceso"])),
            httpx.Response(200, content=autorizacion_autorizado(emitido["clave_acceso"])),
        ]

        with caplog.at_level(logging.DEBUG):
            _pipeline(draft["id"])

        # 4. Estado final por polling (como hará el frontend)
        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 200
        final = r.json()
        assert final["estado"] == "AUTORIZADO"
        assert final["numero_autorizacion"] == emitido["clave_acceso"]
        assert final["mensajes"] == []

        # 5. XML firmado en disco, con hash de integridad (A08)
        comp = admin_db.scalars(select(Comprobante).where(Comprobante.id == draft["id"])).one()
        xml = Path(comp.xml_path).read_bytes()
        assert b"<factura" in xml and b"Signature" in xml
        assert comp.sha256_xml == huella_sha256(xml)

        # 6. RIDE descargable en PDF. Sin GTK (Windows) WeasyPrint no carga y
        #    render_ride_factura cae al respaldo de xhtml2pdf, así que el PDF
        #    sale en cualquier equipo y este paso ya no se salta.
        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}/ride",
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")

        # 6b. El PDF sale, pero el que valga como RIDE depende de lo que lleve
        #     dentro. Se comprueba sobre el HTML —misma plantilla y mismo
        #     contexto que el PDF— porque extraer texto del PDF depende del
        #     motor y aquí solo interesa que el contenido obligatorio esté.
        from app.services.emision import datos_para_xml
        from app.sri.ride import _env
        from app.tasks.emision import _contexto_ride

        tenant_obj = admin_db.get(Tenant, comp.tenant_id)
        contexto = _contexto_ride(tenant_obj, comp, datos_para_xml(tenant_obj, comp)[0])
        html = _env.get_template("ride_factura.html").render(**contexto, barcode_svg="")
        for obligatorio in (
            tenant_obj.ruc,
            comp.clave_acceso,
            comp.numero_autorizacion,
            "001-001-000000001",
            "PRUEBAS",
            "NORMAL",  # tipo de emisión, ya no escrito a mano en la plantilla
            "SUBTOTAL SIN IMPUESTOS",
            "FORMA DE PAGO",
            "VALOR TOTAL",
            contexto["totales"]["importe_total"],
        ):
            assert obligatorio in html, f"El RIDE se quedó sin {obligatorio!r}"
        # Subtotal y valor POR TARIFA, no solo el global (lo pide la normativa)
        for imp in contexto["totales"]["impuestos"]:
            assert f"SUBTOTAL {imp['tarifa']}%" in html
            assert f"IVA {imp['tarifa']}%" in html
            assert imp["base"] in html

        # 7. Correo al cliente final con RIDE + XML adjuntos (modo outbox)
        outbox = Path(get_settings().email_outbox_dir)
        correos = [
            p
            for p in outbox.glob("*.eml")
            if emitido["clave_acceso"] in p.read_text(errors="ignore")
        ]
        assert correos, "No se generó el correo con el RIDE"

        # 8. El certificado y su clave JAMÁS aparecen en logs (checklist F2)
        import base64

        assert cert_subido["password"] not in caplog.text
        assert base64.b64encode(cert_subido["p12"]).decode()[:40] not in caplog.text

        # 9. La recepción se llamó UNA sola vez pese a los reintentos de
        #    autorización (idempotencia por estado)
        assert sri.recepcion.call_count == 1

        # 10. Re-ejecutar el pipeline no duplica nada (idempotencia total)
        _pipeline(draft["id"])
        assert sri.recepcion.call_count == 1
        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.json()["estado"] == "AUTORIZADO"

        # 11. Los cambios de estado del worker quedaron auditados
        acciones = admin_db.scalars(
            select(AuditLog).where(
                AuditLog.tabla == "comprobantes",
                AuditLog.registro_id == draft["id"],
                AuditLog.accion == "UPDATE",
            )
        ).all()
        assert any(a.actor_rol == "SYSTEM" for a in acciones)


class TestRechazosYReintentos:
    def test_devuelta_con_motivo_y_reintento(self, client, ana_tokens, cert_subido, sri):
        r = _crear_factura(client, ana_tokens)  # consumidor final
        draft = r.json()
        r = _emitir(client, ana_tokens, draft["id"])
        clave_original = r.json()["clave_acceso"]

        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_DEVUELTA))
        _pipeline(draft["id"])

        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        estado = r.json()
        assert estado["estado"] == "DEVUELTO"
        # Motivo legible para el usuario (cola de rechazados, fase 2.3)
        assert any("NO CUMPLE ESTRUCTURA XML" in m for m in estado["mensajes"])

        # Reintento: clave NUEVA (documento nuevo, A08), mismo secuencial
        r = client.post(
            f"/api/v1/comprobantes/{draft['id']}/reintentar",
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 202, r.text
        reintento = r.json()
        assert reintento["estado"] == "PENDIENTE"
        assert reintento["clave_acceso"] != clave_original
        assert reintento["numero"] == estado["numero"]

        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_RECIBIDA))
        _autorizar_con_clave_real(sri)
        _pipeline(draft["id"])
        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.json()["estado"] == "AUTORIZADO"

    def test_no_autorizado_motivo_claro(self, client, ana_tokens, cert_subido, sri):
        draft = _crear_factura(client, ana_tokens).json()
        r = _emitir(client, ana_tokens, draft["id"])
        clave = r.json()["clave_acceso"]

        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_RECIBIDA))
        sri.autorizacion.mock(
            return_value=httpx.Response(200, content=autorizacion_rechazado(clave))
        )
        _pipeline(draft["id"])

        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        estado = r.json()
        assert estado["estado"] == "RECHAZADO"
        assert any("Firma inválida" in m for m in estado["mensajes"])


class TestNoDuplicarFacturas:
    """Lo más grave que puede hacer un emisor: mandar la misma venta dos veces
    al SRI, o emitir un segundo documento con un secuencial ya registrado."""

    def test_caida_tras_enviar_no_reenvia(self, client, ana_tokens, admin_db, cert_subido, sri):
        """El worker muere DESPUÉS del POST y antes de confirmar el estado.
        Si el SRI ya lo tiene, el reintento NO debe reenviarlo."""
        draft = _crear_factura(client, ana_tokens).json()
        _emitir(client, ana_tokens, draft["id"])

        # El envío llega al SRI pero se pierde la respuesta
        sri.recepcion.mock(side_effect=httpx.ReadTimeout("respuesta perdida"))
        with pytest.raises(SRITransientError):
            ejecutar_pipeline(str(TENANT_A), draft["id"])

        comp = admin_db.scalars(select(Comprobante).where(Comprobante.id == draft["id"])).one()
        admin_db.refresh(comp)
        assert comp.enviado_recepcion_at is not None  # marca persistente de "en vuelo"
        assert comp.estado.value == "FIRMADO"

        # El SRI confirma que SÍ lo tiene → no debe reenviarse
        llamadas_previas = sri.recepcion.call_count
        _autorizar_con_clave_real(sri)
        _pipeline(draft["id"])
        assert sri.recepcion.call_count == llamadas_previas  # ni un envío más

        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.json()["estado"] == "AUTORIZADO"

    def test_caida_sin_llegar_al_sri_si_reenvia(
        self, client, ana_tokens, admin_db, cert_subido, sri
    ):
        """Contrapartida: si el envío NUNCA llegó, el comprobante no puede
        quedar colgado. El SRI responde SIN REGISTRO y se reenvía."""
        draft = _crear_factura(client, ana_tokens).json()
        _emitir(client, ana_tokens, draft["id"])

        sri.recepcion.mock(side_effect=httpx.ConnectError("no salió"))
        with pytest.raises(SRITransientError):
            ejecutar_pipeline(str(TENANT_A), draft["id"])

        comp = admin_db.scalars(select(Comprobante).where(Comprobante.id == draft["id"])).one()
        admin_db.refresh(comp)
        assert comp.enviado_recepcion_at is not None

        # El SRI no conoce la clave (SIN REGISTRO) → hay que reenviar
        respuestas = {"n": 0}

        def _autorizacion(request):
            clave = re.search(
                r"<claveAccesoComprobante>(\d{49})</claveAccesoComprobante>",
                request.content.decode(),
            ).group(1)
            respuestas["n"] += 1
            if respuestas["n"] == 1:  # consulta previa al reenvío
                return httpx.Response(200, content=autorizacion_vacia(clave))
            return httpx.Response(200, content=autorizacion_autorizado(clave))

        sri.autorizacion.mock(side_effect=_autorizacion)
        llamadas_previas = sri.recepcion.call_count
        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_RECIBIDA))
        _pipeline(draft["id"])

        assert sri.recepcion.call_count > llamadas_previas  # sí se reenvió
        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.json()["estado"] == "AUTORIZADO"

    def test_clave_ya_registrada_no_es_rechazo(self, client, ana_tokens, cert_subido, sri):
        """Si el SRI responde «clave ya registrada», el comprobante YA está allá:
        tratarlo como rechazo llevaría a reemitir y duplicar la factura."""
        draft = _crear_factura(client, ana_tokens).json()
        _emitir(client, ana_tokens, draft["id"])

        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_CLAVE_YA_REGISTRADA))
        _autorizar_con_clave_real(sri)
        _pipeline(draft["id"])

        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.json()["estado"] == "AUTORIZADO"


class TestFallosDeCanal:
    """Un WAF, un 404 o una página de mantenimiento NO son un veredicto sobre
    el comprobante: deben reintentarse, nunca marcarlo rechazado."""

    @pytest.mark.parametrize(
        "respuesta",
        [
            httpx.Response(503, content=HTML_MANTENIMIENTO),
            httpx.Response(403, content="<html>Forbidden</html>"),
            httpx.Response(404, content="<html>Not Found</html>"),
            httpx.Response(429, content="slow down"),
            httpx.Response(200, content=HTML_MANTENIMIENTO),
            httpx.Response(200, content=SOAP_TRUNCADO),
        ],
    )
    def test_respuesta_no_soap_es_transitoria(
        self, client, ana_tokens, cert_subido, sri, respuesta
    ):
        draft = _crear_factura(client, ana_tokens).json()
        _emitir(client, ana_tokens, draft["id"])
        sri.recepcion.mock(return_value=respuesta)

        with pytest.raises(SRITransientError):
            ejecutar_pipeline(str(TENANT_A), draft["id"])

        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        # Sigue vivo y reintentable, NO rechazado
        assert r.json()["estado"] == "FIRMADO"

    def test_autorizacion_de_otra_clave_se_rechaza(self, client, ana_tokens, cert_subido, sri):
        draft = _crear_factura(client, ana_tokens).json()
        r = _emitir(client, ana_tokens, draft["id"])
        clave = r.json()["clave_acceso"]

        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_RECIBIDA))
        # El SRI responde con la clave de OTRO comprobante
        otra = clave[:-2] + "99"
        sri.autorizacion.mock(
            return_value=httpx.Response(200, content=autorizacion_de_otra_clave(otra))
        )
        ejecutar_pipeline(str(TENANT_A), draft["id"])

        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        # Jamás AUTORIZADO con una respuesta que no le corresponde
        assert r.json()["estado"] != "AUTORIZADO"


class TestBarridoAtascados:
    def test_reencola_comprobante_detenido(self, client, ana_tokens, admin_db, cert_subido, sri):
        from app.tasks.emision import MINUTOS_ATASCADO, barrer_atascados

        draft = _crear_factura(client, ana_tokens).json()
        _emitir(client, ana_tokens, draft["id"])
        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_RECIBIDA))

        def _sin_registro(request):
            clave = re.search(
                r"<claveAccesoComprobante>(\d{49})</claveAccesoComprobante>",
                request.content.decode(),
            ).group(1)
            return httpx.Response(200, content=autorizacion_vacia(clave))

        sri.autorizacion.mock(side_effect=_sin_registro)
        with pytest.raises(SRITransientError):
            ejecutar_pipeline(str(TENANT_A), draft["id"])

        # Envejecer el comprobante más allá del umbral de atasco
        from sqlalchemy import text as _text

        admin_db.execute(
            _text(
                "UPDATE comprobantes SET updated_at = now() - :d * interval '1 minute'"
                " WHERE id = :id"
            ),
            {"d": MINUTOS_ATASCADO + 10, "id": draft["id"]},
        )
        admin_db.commit()

        encolados = []
        from app.tasks.emision import procesar_emision

        original = procesar_emision.delay
        try:
            procesar_emision.delay = lambda t, c: encolados.append(c)
            assert barrer_atascados() >= 1
        finally:
            procesar_emision.delay = original
        assert draft["id"] in encolados


class TestConcurrencia:
    def test_dos_ejecuciones_simultaneas_no_duplican_envio(
        self, client, ana_tokens, cert_subido, sri
    ):
        """Con el candado tomado, una segunda ejecución del task no toca el SRI."""
        from app.core.ratelimit import get_redis
        from app.tasks.emision import _LOCK_TTL_S, ejecutar_pipeline

        draft = _crear_factura(client, ana_tokens).json()
        _emitir(client, ana_tokens, draft["id"])

        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_RECIBIDA))
        _autorizar_con_clave_real(sri)

        # Simula que otro worker ya está procesando este comprobante
        get_redis().set(f"emision:lock:{draft['id']}", "otro-worker", ex=_LOCK_TTL_S)
        assert ejecutar_pipeline(str(TENANT_A), draft["id"]) == "en-proceso"
        assert sri.recepcion.call_count == 0  # no se envió nada al SRI

        # Liberado el candado, el pipeline avanza con normalidad
        get_redis().delete(f"emision:lock:{draft['id']}")
        _pipeline(draft["id"])
        assert sri.recepcion.call_count == 1
        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.json()["estado"] == "AUTORIZADO"

    def test_candado_se_libera_al_terminar(self, client, ana_tokens, cert_subido, sri):
        from app.core.ratelimit import get_redis

        draft = _crear_factura(client, ana_tokens).json()
        _emitir(client, ana_tokens, draft["id"])
        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_RECIBIDA))
        _autorizar_con_clave_real(sri)
        _pipeline(draft["id"])
        assert get_redis().get(f"emision:lock:{draft['id']}") is None


class TestEncoladoTrasCommit:
    def test_task_ve_el_comprobante_ya_confirmado(
        self, client, ana_tokens, admin_engine, cert_subido, monkeypatch
    ):
        """El task se encola DESPUÉS del commit: si se encolara dentro de la
        transacción, el worker podría leer el comprobante sin clave y abortar."""
        from sqlalchemy.orm import Session as _Session

        from app.tasks.emision import procesar_emision

        visto: dict = {}

        def _fake_delay(tenant_id: str, comprobante_id: str):
            # Sesión NUEVA e independiente: solo ve lo ya confirmado en la BD
            with _Session(admin_engine) as fresh:
                row = fresh.scalars(
                    select(Comprobante).where(Comprobante.id == comprobante_id)
                ).one_or_none()
                visto["clave"] = row.clave_acceso if row else None
                visto["secuencial"] = row.secuencial if row else None

        monkeypatch.setattr(procesar_emision, "delay", _fake_delay)

        draft = _crear_factura(client, ana_tokens).json()
        r = _emitir(client, ana_tokens, draft["id"])
        assert r.status_code == 202

        assert visto.get("clave") == r.json()["clave_acceso"]
        assert visto.get("secuencial") is not None


class TestReglasDeNegocio:
    def test_consumidor_final_maximo_200(self, client, ana_tokens):
        r = _crear_factura(client, ana_tokens, precio="150.00", cantidad="2")  # 300+IVA
        assert r.status_code == 422
        assert "200" in r.json()["detail"]

    def test_no_se_emite_dos_veces(self, client, ana_tokens, cert_subido):
        draft = _crear_factura(client, ana_tokens).json()
        assert _emitir(client, ana_tokens, draft["id"]).status_code == 202
        r = _emitir(client, ana_tokens, draft["id"])
        assert r.status_code == 422

    def test_secuencial_incrementa(self, client, ana_tokens, cert_subido):
        d1 = _crear_factura(client, ana_tokens).json()
        d2 = _crear_factura(client, ana_tokens).json()
        n1 = int(_emitir(client, ana_tokens, d1["id"]).json()["numero"].split("-")[2])
        n2 = int(_emitir(client, ana_tokens, d2["id"]).json()["numero"].split("-")[2])
        assert n2 == n1 + 1

    def test_reintentar_exige_estado_final(self, client, ana_tokens):
        draft = _crear_factura(client, ana_tokens).json()
        r = client.post(
            f"/api/v1/comprobantes/{draft['id']}/reintentar",
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 422

    def test_comprobante_invisible_para_otro_tenant(self, client, ana_tokens, bob_tokens):
        draft = _crear_factura(client, ana_tokens).json()
        r = client.get(
            f"/api/v1/comprobantes/{draft['id']}", headers=auth_headers(bob_tokens["access_token"])
        )
        assert r.status_code == 404

    def test_autorizado_inmutable_en_bd(self, client, ana_tokens, admin_db, cert_subido, sri):
        draft = _crear_factura(client, ana_tokens).json()
        _emitir(client, ana_tokens, draft["id"])
        sri.recepcion.mock(return_value=httpx.Response(200, content=RECEPCION_RECIBIDA))
        _autorizar_con_clave_real(sri)
        _pipeline(draft["id"])

        import pytest as _pytest
        from sqlalchemy import text as _text

        with _pytest.raises(Exception, match="inmutable"):
            admin_db.execute(
                _text("UPDATE comprobantes SET total = 999 WHERE id = :id"),
                {"id": draft["id"]},
            )
            admin_db.commit()
        admin_db.rollback()
