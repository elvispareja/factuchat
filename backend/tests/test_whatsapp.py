"""Checklist F5:
 1. emisión completa por chat (sandbox: SRI simulado, sin llamar a Meta);
 2. el webhook RECHAZA firmas inválidas;
 3. el consumo aparece en el panel interno.

Además: la conversación nunca envía al SRI sin confirmación explícita.
"""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Comprobante, Tenant, WhatsappMsg
from app.db.models.enums import CategoriaMsg, DireccionMsg
from app.whatsapp import consumo
from app.whatsapp.asistente import Entrante, NumeroNoAutorizado, procesar, tenant_por_telefono
from app.whatsapp.conversacion import limpiar
from app.whatsapp.intents import Intent, reconocer
from tests.conftest import TENANT_A, auth_headers
from tests.sri_utils import RECEPCION_RECIBIDA, generar_p12_prueba

TELEFONO = "593995123344"
APP_SECRET = "secreto-de-prueba-de-la-app"


@pytest.fixture(autouse=True)
def wa_configurado(monkeypatch):
    """Configura WhatsApp sin tocar la red."""
    s = get_settings()
    monkeypatch.setattr(s, "wa_app_secret", APP_SECRET, raising=False)
    monkeypatch.setattr(s, "wa_verify_token", "token-de-verificacion", raising=False)
    monkeypatch.setattr(s, "wa_phone_number_id", "123456", raising=False)
    monkeypatch.setattr(s, "wa_access_token", "token-de-acceso", raising=False)
    yield


@pytest.fixture()
def tenant_con_telefono(admin_db):
    """El tenant A responde al número de WhatsApp de las pruebas."""
    t = admin_db.get(Tenant, TENANT_A)
    anterior = t.telefono
    t.telefono = f"+{TELEFONO}"
    admin_db.commit()
    yield t
    t = admin_db.get(Tenant, TENANT_A)
    t.telefono = anterior
    admin_db.commit()


@pytest.fixture()
def conversacion_limpia():
    limpiar(TENANT_A, TELEFONO)
    yield
    limpiar(TENANT_A, TELEFONO)


def _firmar(cuerpo: bytes, secreto: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def _webhook_texto(texto: str) -> dict:
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
                                    "from": TELEFONO,
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


class TestWebhookFirma:
    """2. El webhook rechaza firmas inválidas."""

    def test_firma_valida_se_acepta(self, client, monkeypatch):
        encolados = []
        from app.tasks.whatsapp import procesar_webhook

        monkeypatch.setattr(procesar_webhook, "delay", lambda c: encolados.append(c))

        cuerpo = json.dumps(_webhook_texto("hola")).encode()
        r = client.post(
            "/api/v1/whatsapp/webhook",
            content=cuerpo,
            headers={"X-Hub-Signature-256": _firmar(cuerpo), "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        assert len(encolados) == 1

    def test_firma_invalida_se_rechaza(self, client, monkeypatch):
        llamado = []
        from app.tasks.whatsapp import procesar_webhook

        monkeypatch.setattr(procesar_webhook, "delay", lambda c: llamado.append(c))

        cuerpo = json.dumps(_webhook_texto("hola")).encode()
        r = client.post(
            "/api/v1/whatsapp/webhook",
            content=cuerpo,
            headers={
                "X-Hub-Signature-256": _firmar(cuerpo, "secreto-equivocado"),
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 403
        # Y lo importante: el cuerpo ni se encoló
        assert llamado == []

    def test_sin_firma_se_rechaza(self, client):
        cuerpo = json.dumps(_webhook_texto("hola")).encode()
        r = client.post(
            "/api/v1/whatsapp/webhook",
            content=cuerpo,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 403

    def test_cuerpo_alterado_se_rechaza(self, client):
        """La firma cubre el cuerpo: cambiar un byte la invalida."""
        original = json.dumps(_webhook_texto("factura 10")).encode()
        firma = _firmar(original)
        alterado = json.dumps(_webhook_texto("factura 99999")).encode()
        r = client.post(
            "/api/v1/whatsapp/webhook",
            content=alterado,
            headers={"X-Hub-Signature-256": firma, "Content-Type": "application/json"},
        )
        assert r.status_code == 403

    def test_verificacion_de_suscripcion(self, client):
        r = client.get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "token-de-verificacion",
                "hub.challenge": "desafio123",
            },
        )
        assert r.status_code == 200
        assert r.text == "desafio123"

    def test_verificacion_con_token_malo(self, client):
        r = client.get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "token-equivocado",
                "hub.challenge": "desafio123",
            },
        )
        assert r.status_code == 403


class TestIntents:
    @pytest.mark.parametrize(
        "texto,esperado",
        [
            ("facturale 20 dolares a Juan", Intent.FACTURAR),
            ("hazme una factura", Intent.FACTURAR),
            ("quiero cobrarle a Andrade", Intent.FACTURAR),
            ("reenviame la factura 001-001-000123", Intent.REENVIAR),
            ("consultar mis comprobantes", Intent.CONSULTAR),
            ("cuanto debo declarar", Intent.REPORTE),
            ("dame el resumen del mes", Intent.REPORTE),
            ("hola", Intent.AYUDA),
            ("ayuda", Intent.AYUDA),
            ("si", Intent.CONFIRMAR),
            ("cancelar", Intent.CANCELAR),
        ],
    )
    def test_reconoce(self, texto, esperado):
        assert reconocer(texto).intent == esperado

    def test_extrae_monto_y_nombre(self):
        r = reconocer("factura a Comercial Andrade por 450.50 dolares")
        assert r.intent == Intent.FACTURAR
        assert r.monto == Decimal("450.50")
        assert "Andrade" in (r.nombre or "")

    def test_extrae_identificacion(self):
        r = reconocer("facturale al 1791234567001")
        assert r.identificacion == "1791234567001"
        # Un RUC NO se confunde con el monto
        assert r.monto is None

    def test_numero_de_comprobante(self):
        r = reconocer("reenviame la 001-001-000123")
        assert r.numero_comprobante == "001-001-000123"


def _turno(entrante: Entrante) -> list:
    """Un mensaje = una sesión, igual que en el worker real.

    El contexto de RLS es LOCAL A LA TRANSACCIÓN (set_config con is_local=true):
    tras un commit se pierde, y reusar la sesión dejaría al siguiente query sin
    tenant y sin filas. Es la elección segura —un GUC de sesión se filtraría a la
    siguiente petición que tome esa conexión del pool— y el worker la respeta
    abriendo una sesión por mensaje.
    """
    from app.core.context import RequestContext
    from app.db.session import apply_rls_context, get_sessionmaker

    db = get_sessionmaker()()
    try:
        ctx = RequestContext(tenant_id=TENANT_A, rol="SYSTEM")
        db.info["audit_ctx"] = ctx
        apply_rls_context(db, ctx)
        tenant = db.get(Tenant, TENANT_A)
        respuestas = procesar(db, tenant, entrante)
        db.commit()
        return respuestas
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _ultimo_comprobante(admin_db):
    """Solo los emitidos POR CHAT: otros tests dejan comprobantes del panel."""
    admin_db.expire_all()
    return admin_db.scalars(
        select(Comprobante)
        .where(Comprobante.origen == "WHATSAPP")
        .order_by(Comprobante.created_at.desc())
    ).first()


@pytest.fixture()
def con_cupo(admin_db):
    """Deja al tenant en un plan con cupo de sobra.

    Los tests de emisión consumen el cupo mensual y el gating —correctamente—
    corta la conversación al llegar al tope. Un cliente real que factura por
    WhatsApp tiene su plan contratado, así que esto es lo fiel.
    """
    from datetime import date as _date

    from app.db.models import Plan, Suscripcion
    from app.db.models.enums import EstadoSuscripcion

    plan = admin_db.scalars(select(Plan).where(Plan.codigo == "EMPRESARIO")).one()
    for previa in admin_db.scalars(
        select(Suscripcion).where(Suscripcion.tenant_id == TENANT_A)
    ).all():
        admin_db.delete(previa)
    admin_db.flush()
    sus = Suscripcion(
        tenant_id=TENANT_A,
        plan_id=plan.id,
        estado=EstadoSuscripcion.ACTIVA,
        precio=plan.precio_mensual,
        inicia=_date(2026, 1, 1),
    )
    admin_db.add(sus)
    admin_db.commit()
    yield
    obj = admin_db.get(Suscripcion, sus.id)
    if obj is not None:
        admin_db.delete(obj)
        admin_db.commit()


class TestConversacionCompleta:
    """1. Emisión completa por chat, con confirmación explícita."""

    @pytest.fixture()
    def preparado(
        self, client, ana_tokens, admin_db, tenant_con_telefono, conversacion_limpia, con_cupo
    ):
        # Certificado cargado (sin él la conversación avisa y no factura)
        p12, password, _pem = generar_p12_prueba(identificacion="1790012345")
        r = client.post(
            "/api/v1/certificados",
            files={"archivo": ("firma.p12", p12, "application/x-pkcs12")},
            data={"password": password},
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 201, r.text
        # Nombre ÚNICO por test: con dos clientes homónimos la búsqueda es
        # ambigua (y el asistente pide elegir, que es lo correcto), pero
        # entonces el test ya no probaría el camino que quiere probar.
        ident = f"17{uuid.uuid4().int % 100_000_000:08d}"
        nombre = f"Comercial Andrade {uuid.uuid4().hex[:6].upper()} S.A."
        r = client.post(
            "/api/v1/clientes",
            json={
                "tipo_identificacion": "CEDULA",
                "identificacion": ident,
                "razon_social": nombre,
                "email": "gerencia@comandrade.ec",
            },
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 201, r.text
        return {"cliente": r.json(), "identificacion": ident, "nombre": nombre}

    def test_flujo_de_punta_a_punta(self, admin_db, preparado, sri_mock):
        # 1. El usuario pide facturar en una sola línea
        respuestas = _turno(
            Entrante(wa_phone=TELEFONO, texto=f"factura a {preparado['nombre']} por 450 dolares")
        )
        assert any("detalle" in r.texto.lower() for r in respuestas), respuestas

        # 2. Da el detalle → llega el resumen de confirmación
        respuestas = _turno(
            Entrante(wa_phone=TELEFONO, texto="Servicio de consultoría empresarial")
        )
        textos = " ".join(r.texto for r in respuestas)
        assert "Revisa antes de autorizar" in textos
        assert preparado["nombre"] in textos
        assert "450" in textos
        assert "67.50" in textos  # IVA 15%
        assert "517.50" in textos  # total
        # LA promesa que sostiene todo el flujo, literal
        assert "Nada se envía al SRI hasta que tú confirmes." in textos
        botones = [b for r in respuestas for b, _ in r.botones]
        assert "autorizar" in botones

        # 3. TODAVÍA no se envió nada: el comprobante sigue en borrador
        comp = _ultimo_comprobante(admin_db)
        assert comp.estado.value == "PENDIENTE"
        assert comp.clave_acceso is None

        # 4. El usuario confirma → recién ahí sale al SRI
        respuestas = _turno(Entrante(wa_phone=TELEFONO, texto="", boton_id="autorizar"))
        assert any("envié al SRI" in r.texto for r in respuestas), respuestas

        admin_db.expire_all()
        comp = _ultimo_comprobante(admin_db)
        assert comp.clave_acceso is not None and len(comp.clave_acceso) == 49
        assert comp.secuencial is not None
        assert comp.origen == "WHATSAPP"

    def test_confirmar_con_texto_tambien_vale(self, admin_db, preparado, sri_mock):
        """No todo el mundo toca el botón: escribir "si" también confirma."""
        _turno(
            Entrante(wa_phone=TELEFONO, texto=f"factura a {preparado['nombre']} por 100 dolares")
        )
        _turno(Entrante(wa_phone=TELEFONO, texto="Mantenimiento"))
        respuestas = _turno(Entrante(wa_phone=TELEFONO, texto="si"))
        assert any("envié al SRI" in r.texto for r in respuestas), respuestas

    def test_cancelar_no_emite(self, admin_db, preparado):
        _turno(
            Entrante(wa_phone=TELEFONO, texto=f"factura a {preparado['nombre']} por 100 dolares")
        )
        _turno(Entrante(wa_phone=TELEFONO, texto="Consultoría"))
        antes = _ultimo_comprobante(admin_db)
        assert antes.estado.value == "PENDIENTE"

        respuestas = _turno(Entrante(wa_phone=TELEFONO, texto="cancelar"))
        assert any("no envié nada" in r.texto.lower() for r in respuestas)

        admin_db.expire_all()
        despues = admin_db.get(Comprobante, antes.id)
        # Sigue en borrador: cancelar no emite ni consume cupo
        assert despues.estado.value == "PENDIENTE"
        assert despues.clave_acceso is None

    def test_corregir_el_precio_rehace_el_resumen(self, admin_db, preparado):
        _turno(
            Entrante(wa_phone=TELEFONO, texto=f"factura a {preparado['nombre']} por 100 dolares")
        )
        _turno(Entrante(wa_phone=TELEFONO, texto="Consultoría"))
        r = _turno(Entrante(wa_phone=TELEFONO, texto="", boton_id="corregir_precio"))
        assert any("cuánto" in x.texto.lower() or "valor" in x.texto.lower() for x in r)

        respuestas = _turno(Entrante(wa_phone=TELEFONO, texto="200"))
        textos = " ".join(x.texto for x in respuestas)
        assert "Revisa antes de autorizar" in textos
        assert "230.00" in textos  # 200 + 15%

    def test_sin_certificado_avisa_y_no_factura(self, client, ana_tokens, admin_db, preparado):
        """Sin firma no hay comprobante, y el asistente lo dice claro."""
        from app.db.models import Certificado

        for c in admin_db.scalars(
            select(Certificado).where(Certificado.tenant_id == TENANT_A)
        ).all():
            admin_db.delete(c)
        admin_db.commit()

        _turno(Entrante(wa_phone=TELEFONO, texto=f"factura a {preparado['nombre']} por 50 dolares"))
        respuestas = _turno(Entrante(wa_phone=TELEFONO, texto="Servicio"))
        assert any("firma electrónica" in r.texto for r in respuestas), respuestas

    def test_audio_pide_texto(self, admin_db, tenant_con_telefono, conversacion_limpia):
        r = _turno(Entrante(wa_phone=TELEFONO, texto="", tipo="AUDIO"))
        assert "No puedo procesar audios" in r[0].texto

    def test_numero_desconocido_no_recibe_respuesta(self, admin_db):
        from app.core.context import RequestContext
        from app.db.session import apply_rls_context, get_sessionmaker

        db = get_sessionmaker()()
        try:
            ctx = RequestContext(rol="SYSTEM")
            apply_rls_context(db, ctx, is_internal=True)
            with pytest.raises(NumeroNoAutorizado):
                tenant_por_telefono(db, "593000000000")
        finally:
            db.close()

    def test_un_numero_conocido_si_se_resuelve_desde_el_worker(self, admin_db, tenant_con_telefono):
        """La contraparte del test de arriba, que faltaba y por eso no se vio.

        El worker resuelve el número en una sesión de SISTEMA, y `tenants` está
        cerrada incluso para el contexto interno: sin la función segura, esta
        búsqueda devuelve vacío SIEMPRE y en producción todo mensaje de un
        cliente legítimo se habría rechazado como número no autorizado.
        """
        from app.core.context import RequestContext
        from app.db.session import apply_rls_context, get_sessionmaker

        db = get_sessionmaker()()
        try:
            apply_rls_context(db, RequestContext(rol="SYSTEM"), is_internal=True)
            tenant = tenant_por_telefono(db, TELEFONO)
            assert tenant.id == TENANT_A
        finally:
            db.close()


class TestConsumo:
    """3. El consumo aparece en el panel interno."""

    def test_mensaje_del_usuario_no_se_cobra(self, admin_db):
        """Meta no cobra la conversación que abre el usuario."""
        msg = consumo.registrar(
            admin_db,
            tenant_id=TENANT_A,
            wa_phone="593999000001",
            direccion=DireccionMsg.ENTRANTE,
            categoria=CategoriaMsg.USUARIO,
            tipo="TEXTO",
            contenido={"texto": "hola"},
            wa_message_id=f"wamid.{uuid.uuid4().hex}",
        )
        admin_db.commit()
        assert msg.costo == Decimal("0")

    def test_plantilla_de_empresa_se_cobra_con_tarifa_vigente(self, admin_db):
        from app.services.configuracion import sembrar_tarifas

        sembrar_tarifas(admin_db)
        admin_db.commit()

        telefono = f"59399{uuid.uuid4().int % 1_000_000:06d}"
        msg = consumo.registrar(
            admin_db,
            tenant_id=TENANT_A,
            wa_phone=telefono,
            direccion=DireccionMsg.SALIENTE,
            categoria=CategoriaMsg.EMPRESA,
            tipo="PLANTILLA",
            contenido={"plantilla": "factuchat_cupo_agotado"},
            wa_message_id=f"wamid.{uuid.uuid4().hex}",
            cuando=datetime(2026, 9, 15, tzinfo=UTC),
        )
        admin_db.commit()
        # Tarifa de septiembre de 2026, ANTES del alza de octubre
        assert msg.costo == Decimal("0.040000")

    def test_el_alza_de_meta_cambia_el_costo(self, admin_db):
        from app.services.configuracion import sembrar_tarifas

        sembrar_tarifas(admin_db)
        admin_db.commit()
        antes = consumo.costo_de(admin_db, CategoriaMsg.EMPRESA, date(2026, 9, 30))
        despues = consumo.costo_de(admin_db, CategoriaMsg.EMPRESA, date(2026, 10, 1))
        assert antes == Decimal("0.040000")
        assert despues == Decimal("0.052800")

    def test_no_se_cobra_dos_veces_en_la_misma_ventana(self, admin_db):
        from app.services.configuracion import sembrar_tarifas

        sembrar_tarifas(admin_db)
        admin_db.commit()

        telefono = f"59399{uuid.uuid4().int % 1_000_000:06d}"
        ahora = datetime.now(UTC)
        primero = consumo.registrar(
            admin_db,
            TENANT_A,
            telefono,
            DireccionMsg.SALIENTE,
            CategoriaMsg.EMPRESA,
            "PLANTILLA",
            {},
            f"wamid.{uuid.uuid4().hex}",
            ahora,
        )
        segundo = consumo.registrar(
            admin_db,
            TENANT_A,
            telefono,
            DireccionMsg.SALIENTE,
            CategoriaMsg.EMPRESA,
            "TEXTO",
            {},
            f"wamid.{uuid.uuid4().hex}",
            ahora,
        )
        admin_db.commit()
        assert primero.costo > 0
        # Dentro de la ventana de 24 h Meta cobra UNA conversación, no dos
        assert segundo.costo == Decimal("0")

    def test_idempotente_por_wa_message_id(self, admin_db):
        """Meta reenvía webhooks: el mismo mensaje no puede contarse dos veces."""
        wa_id = f"wamid.{uuid.uuid4().hex}"
        telefono = f"59399{uuid.uuid4().int % 1_000_000:06d}"
        uno = consumo.registrar(
            admin_db,
            TENANT_A,
            telefono,
            DireccionMsg.ENTRANTE,
            CategoriaMsg.USUARIO,
            "TEXTO",
            {"texto": "hola"},
            wa_id,
        )
        admin_db.commit()
        dos = consumo.registrar(
            admin_db,
            TENANT_A,
            telefono,
            DireccionMsg.ENTRANTE,
            CategoriaMsg.USUARIO,
            "TEXTO",
            {"texto": "hola"},
            wa_id,
        )
        admin_db.commit()
        assert uno.id == dos.id
        cuantos = admin_db.scalars(
            select(WhatsappMsg).where(WhatsappMsg.wa_message_id == wa_id)
        ).all()
        assert len(cuantos) == 1

    def test_aparece_en_el_panel_interno(self, client, admin_auth, admin_db):
        from app.services.configuracion import sembrar_tarifas

        sembrar_tarifas(admin_db)
        telefono = f"59399{uuid.uuid4().int % 1_000_000:06d}"
        consumo.registrar(
            admin_db,
            TENANT_A,
            telefono,
            DireccionMsg.SALIENTE,
            CategoriaMsg.EMPRESA,
            "PLANTILLA",
            {},
            f"wamid.{uuid.uuid4().hex}",
        )
        admin_db.commit()

        r = client.get("/api/v1/sa/whatsapp/consumo", headers=auth_headers(admin_auth["access"]))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["mensajes"] >= 1
        assert Decimal(d["costo_total"]) > 0
        assert "empresa" in d and "usuario" in d
        assert "proyectado" in d and "pct_presupuesto" in d
        assert isinstance(d["por_cliente"], list)

    def test_cliente_no_ve_el_consumo_global(self, client, ana_tokens):
        r = client.get(
            "/api/v1/sa/whatsapp/consumo", headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 403


class TestPlantillas:
    def test_las_tres_del_plan(self):
        from app.whatsapp.plantillas import PLANTILLAS, Aviso

        assert set(PLANTILLAS) == {
            Aviso.PRE_DECLARACION,
            Aviso.CUPO_AGOTADO,
            Aviso.PAGO_VENCIDO,
        }

    def test_render_con_variables(self, admin_db):
        from app.whatsapp.plantillas import Aviso, preparar

        _p, valores, vista = preparar(
            admin_db,
            Aviso.PRE_DECLARACION,
            {
                "nombre": "Doña Andrade",
                "digito": "4",
                "fecha": "16 de septiembre",
                "enlace": "https://ejemplo/rep",
            },
        )
        assert valores == ["Doña Andrade", "4", "16 de septiembre", "https://ejemplo/rep"]
        assert "Doña Andrade" in vista
        assert "tu noveno dígito es 4".lower() in vista.lower()
        assert "{" not in vista  # no quedaron variables sin sustituir

    def test_falta_una_variable(self, admin_db):
        from app.whatsapp.plantillas import Aviso, preparar

        with pytest.raises(ValueError, match="Faltan variables"):
            preparar(admin_db, Aviso.CUPO_AGOTADO, {"nombre": "Ana"})


@pytest.fixture()
def sri_mock():
    """SRI simulado: la emisión por chat no debe salir a internet."""
    import respx

    from tests.sri_utils import autorizacion_autorizado

    s = get_settings()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(s.sri_recepcion_url_pruebas).mock(
            return_value=httpx.Response(200, content=RECEPCION_RECIBIDA)
        )
        mock.post(s.sri_autorizacion_url_pruebas).mock(
            return_value=httpx.Response(200, content=autorizacion_autorizado("0" * 49))
        )
        yield mock
