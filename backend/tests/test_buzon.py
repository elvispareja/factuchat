"""Checklist F7: un correo de prueba se parsea y se suma al saldo de retenciones
del inquilino CORRECTO — y solo de ese.

Además: el flag BUZON_ACTIVO, la deduplicación, el cifrado en reposo, las
defensas del parser frente a XML hostil y la regla 7.2 (los XML del buzón no
consumen cupo de análisis con IA).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select, text

from app.buzon import ingesta, verificacion
from app.buzon.parser import BuzonParseError, leer
from app.core.config import get_settings
from app.db.models import AnalisisIA, BuzonCorreo, RetencionRecibida, Tenant
from app.services import planes, reportes, retenciones
from tests import buzon_utils
from tests.buzon_utils import (
    clave_de_prueba,
    correo,
    envolver_autorizacion,
    xml_retencion,
)
from tests.conftest import TENANT_A, TENANT_B, auth_headers
from tests.sri_utils import autorizacion_autorizado, autorizacion_rechazado

RUC_A = "1790012345001"
RUC_B = "1790099999001"


@pytest.fixture()
def buzon_encendido(admin_db):
    """El módulo encendido, con clave de cifrado. Nace apagado, como la maqueta."""
    s = get_settings()
    previa_key = s.buzon_enc_key
    previo_dominio = s.buzon_dominio
    # Clave de 32 bytes en base64, solo para la prueba
    s.buzon_enc_key = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    s.buzon_dominio = "buzon.factuchat.test"

    admin_db.execute(
        text(
            "INSERT INTO parametros (clave, valor) VALUES ('BUZON_ACTIVO', 'true') "
            "ON CONFLICT (clave) DO UPDATE SET valor = 'true'"
        )
    )
    admin_db.commit()
    yield
    admin_db.execute(text("DELETE FROM parametros WHERE clave = 'BUZON_ACTIVO'"))
    admin_db.execute(text("DELETE FROM analisis_ia"))
    admin_db.execute(text("DELETE FROM retenciones_recibidas"))
    admin_db.execute(text("DELETE FROM buzon_correos"))
    admin_db.commit()
    s.buzon_enc_key = previa_key
    s.buzon_dominio = previo_dominio


class SriSimulado:
    """El SRI de las pruebas. `veredicto` se cambia dentro de un test para
    probar qué pasa cuando la clave NO está autorizada o el servicio se cae."""

    def __init__(self) -> None:
        self.veredicto = "AUTORIZADO"
        self.caido = False

    def responder(self, peticion) -> httpx.Response:
        if self.caido:
            return httpx.Response(503, text="mantenimiento")
        clave = _clave_consultada(peticion)
        # Devuelve EL MISMO documento que se fabricó con esa clave: el SRI de
        # verdad reenvía su copia, y la verificación la contrasta contra la fila.
        guardado = buzon_utils.REGISTRO.get(clave)
        cuerpo = (
            autorizacion_autorizado(clave, comprobante=guardado.decode() if guardado else None)
            if self.veredicto == "AUTORIZADO"
            else autorizacion_rechazado(clave)
        )
        return httpx.Response(200, text=cuerpo)


@pytest.fixture(autouse=True)
def sri_autoriza():
    """La verificación contra el SRI es lo que convierte una retención en
    crédito: sin ella el saldo se queda en cero, así que casi todas las pruebas
    la necesitan encendida."""
    s = get_settings()
    simulado = SriSimulado()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(s.sri_autorizacion_url_pruebas).mock(side_effect=simulado.responder)
        yield simulado


def _clave_consultada(peticion) -> str:
    """Saca la clave del cuerpo SOAP para responder por ESA clave: el cliente
    rechaza una autorización que no corresponde a lo que preguntó."""
    import re as _re

    cuerpo = peticion.content.decode("utf-8", "replace")
    m = _re.search(r"<claveAccesoComprobante>(\d+)</claveAccesoComprobante>", cuerpo)
    return m.group(1) if m else "0" * 49


@pytest.fixture()
def sa(admin_auth):
    return auth_headers(admin_auth["access"])


@pytest.fixture()
def soporte_auth(soporte_tokens):
    return auth_headers(soporte_tokens["access_token"])


def _con_plan(admin_db, tenant_id, codigo: str):
    """Suscribe al inquilino a un plan concreto y lo deja como estaba al salir."""
    from app.db.models import Plan, Suscripcion
    from app.db.models.enums import EstadoSuscripcion

    plan = admin_db.scalars(select(Plan).where(Plan.codigo == codigo)).one()
    previas = admin_db.scalars(select(Suscripcion).where(Suscripcion.tenant_id == tenant_id)).all()
    guardadas = [
        {"plan_id": s.plan_id, "estado": s.estado, "precio": s.precio, "inicia": s.inicia}
        for s in previas
    ]
    for s in previas:
        admin_db.delete(s)
    admin_db.flush()
    nueva = Suscripcion(
        tenant_id=tenant_id,
        plan_id=plan.id,
        estado=EstadoSuscripcion.ACTIVA,
        precio=plan.precio_mensual,
        inicia=date(2026, 1, 1),
    )
    admin_db.add(nueva)
    admin_db.commit()
    yield
    obj = admin_db.get(Suscripcion, nueva.id)
    if obj is not None:
        admin_db.delete(obj)
    for datos in guardadas:
        admin_db.add(Suscripcion(tenant_id=tenant_id, **datos))
    admin_db.commit()


@pytest.fixture()
def con_archivos_a(admin_db):
    """El plan Independiente ya trae la bandeja de retenciones."""
    yield from _con_plan(admin_db, TENANT_A, "INDEPENDIENTE")


@pytest.fixture()
def con_archivos_b(admin_db):
    yield from _con_plan(admin_db, TENANT_B, "INDEPENDIENTE")


@pytest.fixture()
def plan_inicial_a(admin_db):
    """El plan Inicial NO trae la bandeja: es el muro de la maqueta."""
    yield from _con_plan(admin_db, TENANT_A, "INICIAL")


def _direccion(ruc: str) -> str:
    return f"{ruc}@{get_settings().dominio_buzon}"


def _ingerir(crudo: bytes, destinatario: str | None = None) -> str:
    """Ingiere y, si creó retenciones, las verifica contra el SRI simulado.

    En producción la verificación es un task aparte; aquí se encadena para que
    el test recorra el MISMO camino y el saldo refleje lo que reflejaría de
    verdad: sin verificación, una retención no cuenta.
    """
    from app.tasks import buzon as tareas

    encolados: list[tuple[str, str]] = []
    original = tareas.verificar_retencion.delay
    tareas.verificar_retencion.delay = lambda t, r: encolados.append((t, r))
    try:
        estado = tareas.ingerir(crudo, destinatario)
    finally:
        tareas.verificar_retencion.delay = original

    for tenant_id, retencion_id in encolados:
        tareas.verificar_retencion(tenant_id, retencion_id)
    return estado


def _ingerir_sin_verificar(crudo: bytes, destinatario: str | None = None) -> str:
    """Solo la ingesta: deja las retenciones pendientes de verificar."""
    from app.tasks import buzon as tareas

    original = tareas.verificar_retencion.delay
    tareas.verificar_retencion.delay = lambda t, r: None
    try:
        return tareas.ingerir(crudo, destinatario)
    finally:
        tareas.verificar_retencion.delay = original


# ---------------------------------------------------------------- CHECKLIST F7


class TestChecklistF7:
    """El correo llega, se parsea y suma al inquilino correcto. Solo a ese."""

    def test_correo_de_prueba_suma_al_tenant_correcto(self, buzon_encendido, admin_db):
        clave = clave_de_prueba(7000001)
        xml = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave)
        mensaje = correo(
            para=_direccion(RUC_A),
            adjunto=envolver_autorizacion(xml, "2408202601179001234500110010010000012341234567813"),
            message_id="<f7-uno@proveedor.ec>",
        )

        assert _ingerir(mensaje) == "parseado"

        # 1. El correo quedó registrado en el buzón de A
        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        fila = admin_db.scalars(
            select(BuzonCorreo).where(BuzonCorreo.message_id == "f7-uno@proveedor.ec")
        ).one()
        assert fila.tenant_id == TENANT_A
        assert fila.tipo_detectado == "Retención recibida"
        assert fila.clave_acceso == clave

        # 2. La retención se creó con renta e IVA SEPARADOS
        ret = admin_db.scalars(
            select(RetencionRecibida).where(RetencionRecibida.clave_acceso == clave)
        ).one()
        assert ret.tenant_id == TENANT_A
        assert ret.total_renta == Decimal("41.40")
        assert ret.total_iva == Decimal("54.32")
        assert ret.razon_social_agente == "Comercial Andrade Cía. Ltda."
        assert ret.numero == "001-001-000001234"
        assert ret.concepto == "Retención renta 8% e IVA 70%"

        # 3. Suma al saldo de A
        saldo_a = retenciones.saldo(admin_db, TENANT_A, date(2026, 7, 1), date(2027, 1, 1))
        assert saldo_a.iva == Decimal("54.32")
        assert saldo_a.renta == Decimal("41.40")
        assert saldo_a.total == Decimal("95.72")
        assert saldo_a.documentos == 1

        # 4. Y SOLO a A: el saldo de B sigue en cero
        saldo_b = retenciones.saldo(admin_db, TENANT_B, date(2026, 7, 1), date(2027, 1, 1))
        assert saldo_b.total == Decimal("0")
        assert saldo_b.documentos == 0

    def test_postgres_impide_ver_la_retencion_de_otro(self, buzon_encendido, app_engine, admin_db):
        """La segunda barrera: aunque el código fallara, RLS no deja pasar."""
        clave = clave_de_prueba(7000002)
        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave),
                message_id="<f7-rls@proveedor.ec>",
            )
        )

        with app_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT set_config('app.tenant_id', :t, true),"
                    " set_config('app.is_internal','false',true)"
                ),
                {"t": str(TENANT_B)},
            )
            n = conn.execute(
                text("SELECT count(*) FROM retenciones_recibidas WHERE clave_acceso = :c"),
                {"c": clave},
            ).scalar()
            assert n == 0, "el inquilino B ve una retención de A"

            correos_b = conn.execute(text("SELECT count(*) FROM buzon_correos")).scalar()
            assert correos_b == 0

    def test_el_resumen_fiscal_descuenta_solo_el_iva(self, buzon_encendido, admin_db):
        """La retención de renta NO baja el IVA a pagar: es otro impuesto."""
        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(
                    ruc_retenido=RUC_A,
                    clave_acceso=clave_de_prueba(7000003),
                    fecha="12/08/2026",
                ),
                message_id="<f7-iva@proveedor.ec>",
            )
        )
        r = reportes.resumen_fiscal(
            admin_db, TENANT_A, desde=date(2026, 8, 1), hasta=date(2026, 9, 1)
        )
        assert r.retenciones_recibidas == Decimal("54.32")  # IVA
        assert r.retenciones_renta == Decimal("41.40")  # renta, informada aparte


# ------------------------------------------------------------------- 7.2 IA


class TestReglaSieteDos:
    """Los XML del buzón no consumen análisis con IA. Las fotos sí."""

    def test_el_xml_del_buzon_no_gasta_cupo(self, buzon_encendido, admin_db):
        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000010)),
                message_id="<f7-ia@proveedor.ec>",
            )
        )
        fila = admin_db.scalars(select(AnalisisIA).where(AnalisisIA.tenant_id == TENANT_A)).one()
        assert fila.origen == "BUZON"
        assert fila.consume is False
        # Y por tanto no cuenta contra el tope del plan
        assert planes.analisis_ia_del_periodo(admin_db, TENANT_A, datetime.now(UTC).date()) == 0

    def test_una_foto_si_gasta_cupo_y_topa(self, buzon_encendido, admin_db):
        """El contador existe de verdad: si no, la exención no probaría nada."""
        plan = planes.PlanVigente("Independiente", Decimal("5.99"), {"ia": 2})
        hoy = datetime.now(UTC).date()
        planes.registrar_analisis_ia(admin_db, TENANT_A, "FOTO", hoy, plan=plan)
        planes.registrar_analisis_ia(admin_db, TENANT_A, "FOTO", hoy, plan=plan)
        assert planes.analisis_ia_del_periodo(admin_db, TENANT_A, hoy) == 2

        with pytest.raises(planes.LimitePlanError) as e:
            planes.registrar_analisis_ia(admin_db, TENANT_A, "FOTO", hoy, plan=plan)
        assert "buzón" in str(e.value).lower()

        # Con el cupo agotado, un XML del buzón sigue entrando
        planes.registrar_analisis_ia(admin_db, TENANT_A, "BUZON", hoy)
        admin_db.rollback()


# ------------------------------------------------------------ deduplicación


class TestDeduplicacion:
    def test_el_mismo_correo_dos_veces_no_suma_dos_veces(self, buzon_encendido, admin_db):
        mensaje = correo(
            para=_direccion(RUC_A),
            adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000020)),
            message_id="<f7-dup@proveedor.ec>",
        )
        assert _ingerir(mensaje) == "parseado"
        assert _ingerir(mensaje) == "duplicado"

        saldo = retenciones.saldo(admin_db, TENANT_A)
        assert saldo.documentos == 1

    def test_el_mismo_xml_en_otro_correo_se_marca_duplicado(self, buzon_encendido, admin_db):
        """Un reenvío trae el mismo comprobante con otro Message-ID."""
        clave = clave_de_prueba(7000021)
        xml = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave)
        assert _ingerir(correo(para=_direccion(RUC_A), adjunto=xml, message_id="<a@x.ec>")) == (
            "parseado"
        )
        assert _ingerir(correo(para=_direccion(RUC_A), adjunto=xml, message_id="<b@x.ec>")) == (
            "duplicado"
        )
        assert retenciones.saldo(admin_db, TENANT_A).documentos == 1

    def test_un_message_id_ajeno_no_bloquea_el_correo_de_otro(self, buzon_encendido, admin_db):
        """0001 dejaba message_id con UNIQUE GLOBAL: un remitente hostil podía
        quemar un identificador y dejar sin su retención al inquilino de al lado."""
        repetido = "<mismo-id@atacante.ec>"
        assert (
            _ingerir(
                correo(
                    para=_direccion(RUC_B),
                    adjunto=xml_retencion(
                        ruc_retenido=RUC_B, clave_acceso=clave_de_prueba(7000030)
                    ),
                    message_id=repetido,
                )
            )
            == "parseado"
        )

        # El mismo identificador, ahora para el inquilino A: debe entrar igual
        assert (
            _ingerir(
                correo(
                    para=_direccion(RUC_A),
                    adjunto=xml_retencion(
                        ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000031)
                    ),
                    message_id=repetido,
                )
            )
            == "parseado"
        )

        assert retenciones.saldo(admin_db, TENANT_A).documentos == 1
        assert retenciones.saldo(admin_db, TENANT_B).documentos == 1


# ------------------------------------------------------------------ defensas


class TestDefensas:
    def test_el_to_del_remitente_no_decide_el_dueno(self, buzon_encendido, admin_db):
        """`To` y `Cc` los escribe el remitente, igual que el RUC del XML.

        Un agente que manda su lote mensual con varios clientes en el `To` no
        puede meter el comprobante de uno en el buzón de otro.
        """
        mensaje = correo(
            para=_direccion(RUC_A),  # el destinatario REAL (Delivered-To)
            to_visible=f"{_direccion(RUC_B)}, {_direccion(RUC_A)}",  # lo que dice el remitente
            adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000210)),
            message_id="<f7-to@proveedor.ec>",
        )
        assert _ingerir(mensaje) == "parseado"

        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        fila = admin_db.scalars(
            select(BuzonCorreo).where(BuzonCorreo.message_id == "f7-to@proveedor.ec")
        ).one()
        assert fila.tenant_id == TENANT_A, "el To del remitente desvió el correo"
        assert retenciones.saldo(admin_db, TENANT_B).documentos == 0

    def test_sin_cabecera_de_entrega_no_se_adivina_el_dueno(self, buzon_encendido, admin_db):
        """Si nadie fiable dice a quién se entregó, se descarta. Antes se caía a
        `To` y se adjudicaba a ciegas al primero que resolviera."""
        mensaje = correo(
            para=_direccion(RUC_A),
            con_delivered_to=False,
            adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000211)),
            message_id="<f7-sin-entrega@proveedor.ec>",
        )
        assert _ingerir(mensaje) == "sin-destinatario"

        # Pero con el destinatario del SOBRE, que da el proveedor, sí entra
        assert _ingerir(mensaje, _direccion(RUC_A)) == "parseado"

    def test_un_correo_a_dos_buzones_no_se_adjudica_a_ciegas(self, buzon_encendido):
        """Con dos destinos válidos no hay forma de saber cuál era el real."""
        from app.buzon import correo as correo_mod
        from app.core.context import RequestContext
        from app.db.session import apply_rls_context, get_sessionmaker

        db = get_sessionmaker()()
        try:
            apply_rls_context(db, RequestContext(rol="SYSTEM"), is_internal=True)
            assert (
                correo_mod.tenant_por_direccion(db, [_direccion(RUC_A), _direccion(RUC_B)]) is None
            )
            assert correo_mod.tenant_por_direccion(db, [_direccion(RUC_A)]) == TENANT_A
        finally:
            db.close()

    def test_el_dueno_lo_decide_la_direccion_no_el_xml(self, buzon_encendido, admin_db):
        """Un XML que retiene a OTRO no suma nada, aunque llegue a mi buzón."""
        mensaje = correo(
            para=_direccion(RUC_A),
            adjunto=xml_retencion(ruc_retenido=RUC_B, clave_acceso=clave_de_prueba(7000040)),
            message_id="<f7-ajeno@proveedor.ec>",
        )
        assert _ingerir(mensaje) == "error"

        assert retenciones.saldo(admin_db, TENANT_A).documentos == 0
        assert retenciones.saldo(admin_db, TENANT_B).documentos == 0

        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        fila = admin_db.scalars(
            select(BuzonCorreo).where(BuzonCorreo.message_id == "f7-ajeno@proveedor.ec")
        ).one()
        assert "no es el RUC de este buzón" in (fila.motivo_error or "")

    @pytest.mark.parametrize(
        "identificacion,motivo",
        [
            ("", "no dice a quién retiene"),  # sin el dato, el control no se saltaba: falla
            ("17", "no dice a quién retiene"),  # «17» valía por prefijo abierto
            ("1790012345", None),  # la cédula raíz del RUC sí es suya
        ],
    )
    def test_identificacion_del_retenido(self, buzon_encendido, admin_db, identificacion, motivo):
        """Dos formas de saltarse «esta retención es mía», las dos con el mismo
        final: un tercero le baja el IVA al cliente con un XML inventado."""
        xml = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000300))
        if identificacion == "":
            xml = xml.replace(
                b"<identificacionSujetoRetenido>"
                + RUC_A.encode()
                + b"</identificacionSujetoRetenido>",
                b"",
            )
        else:
            xml = xml.replace(
                b"<identificacionSujetoRetenido>"
                + RUC_A.encode()
                + b"</identificacionSujetoRetenido>",
                b"<identificacionSujetoRetenido>"
                + identificacion.encode()
                + b"</identificacionSujetoRetenido>",
            )

        estado = _ingerir(
            correo(para=_direccion(RUC_A), adjunto=xml, message_id="<f7-ident@proveedor.ec>")
        )
        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        if motivo:
            assert estado == "error"
            fila = admin_db.scalars(
                select(BuzonCorreo).where(BuzonCorreo.message_id == "f7-ident@proveedor.ec")
            ).one()
            assert motivo in (fila.motivo_error or "")
            assert retenciones.saldo(admin_db, TENANT_A).documentos == 0
        else:
            assert estado == "parseado"
            assert retenciones.saldo(admin_db, TENANT_A).documentos == 1

    def test_una_retencion_no_autorizada_no_suma(self, buzon_encendido, admin_db):
        """El sobre del SRI dice NO AUTORIZADO: no es crédito de nadie."""
        xml = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000301))
        sobre = envolver_autorizacion(xml).replace(
            b"<estado>AUTORIZADO</estado>", b"<estado>NO AUTORIZADO</estado>"
        )
        assert (
            _ingerir(
                correo(para=_direccion(RUC_A), adjunto=sobre, message_id="<f7-noaut@proveedor.ec>")
            )
            == "error"
        )
        assert retenciones.saldo(admin_db, TENANT_A).documentos == 0

    def test_una_retencion_inventada_no_baja_el_impuesto(
        self, buzon_encendido, admin_db, sri_autoriza
    ):
        """El agujero central de la fase: cualquiera puede escribir un XML.

        Con el SRI diciendo que esa clave NO está autorizada, la retención queda
        archivada y visible, pero fuera del saldo: nadie le baja el IVA a un
        contribuyente con un documento que se escribió a sí mismo.
        """
        clave = clave_de_prueba(7000302)
        sri_autoriza.veredicto = "NO AUTORIZADO"
        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave),
                message_id="<f7-falsa@proveedor.ec>",
            )
        )

        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        ret = admin_db.scalars(
            select(RetencionRecibida).where(RetencionRecibida.clave_acceso == clave)
        ).one()
        assert ret.verificada is False
        assert "no suma crédito" in (ret.verificacion or {}).get("detalle", "")

        # Está guardada y el cliente la ve, pero NO cuenta
        assert retenciones.saldo(admin_db, TENANT_A).total == Decimal("0")
        assert len(retenciones.listar(admin_db, TENANT_A)) == 1
        r = reportes.resumen_fiscal(
            admin_db, TENANT_A, desde=date(2026, 8, 1), hasta=date(2026, 9, 1)
        )
        assert r.retenciones_recibidas == Decimal("0")

    def test_mientras_el_sri_no_responde_la_retencion_no_cuenta(
        self, buzon_encendido, admin_db, sri_autoriza
    ):
        """Un problema de red no es un veredicto, pero tampoco un permiso."""
        clave = clave_de_prueba(7000303)
        sri_autoriza.caido = True
        _ingerir_sin_verificar(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave),
                message_id="<f7-caido@proveedor.ec>",
            )
        )
        assert retenciones.saldo(admin_db, TENANT_A).total == Decimal("0")
        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        ret = admin_db.scalars(
            select(RetencionRecibida).where(RetencionRecibida.clave_acceso == clave)
        ).one()
        assert ret.verificada is False

    def test_una_clave_con_verificador_malo_ni_se_consulta(self):
        assert verificacion.clave_bien_formada(clave_de_prueba(1)) is True
        mala = clave_de_prueba(1)[:48] + ("0" if clave_de_prueba(1)[48] != "0" else "1")
        assert verificacion.clave_bien_formada(mala) is False
        assert verificacion.clave_bien_formada(None) is False
        assert verificacion.clave_bien_formada("123") is False

    def test_correo_a_direccion_desconocida_se_descarta(self, buzon_encendido, admin_db):
        mensaje = correo(
            para=f"9999999999999@{get_settings().dominio_buzon}",
            adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000041)),
            message_id="<f7-nadie@proveedor.ec>",
        )
        assert _ingerir(mensaje) == "sin-destinatario"

        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        n = admin_db.execute(text("SELECT count(*) FROM buzon_correos")).scalar()
        assert n == 0, "se guardó un correo sin dueño"

    def test_xxe_no_lee_ficheros_del_contenedor(self):
        """Un XML ajeno no puede leer /etc/passwd ni salir a la red."""
        malicioso = b"""<?xml version="1.0"?>
<!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<comprobanteRetencion id="comprobante" version="2.0.0">
  <infoTributaria><ruc>&xxe;</ruc></infoTributaria>
</comprobanteRetencion>"""
        with pytest.raises(BuzonParseError) as e:
            leer(malicioso)
        assert "DOCTYPE" in str(e.value)

    def test_bomba_de_entidades_no_tumba_el_worker(self):
        bomba = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<comprobanteRetencion><razonSocial>&lol3;</razonSocial></comprobanteRetencion>"""
        with pytest.raises(BuzonParseError):
            leer(bomba)

    def test_el_doctype_no_se_cuela_empujandolo_con_relleno(self):
        """Mirar solo los primeros bytes se esquiva rellenando el prólogo."""
        relleno = b"<!-- " + b"x" * 4000 + b" -->"
        colado = (
            b'<?xml version="1.0"?>'
            + relleno
            + b'<!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            + b"<comprobanteRetencion><razonSocial>&xxe;</razonSocial></comprobanteRetencion>"
        )
        with pytest.raises(BuzonParseError) as e:
            leer(colado)
        assert "DOCTYPE" in str(e.value)

    def test_un_comentario_no_revienta_el_parser(self):
        """Un comentario XML es de lo más normal en exportaciones reales; antes
        lanzaba ValueError, se perdía la transacción y el correo desaparecía."""
        con_comentario = xml_retencion(
            ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000200)
        ).replace(b"<infoTributaria>", b"<!-- exportado por el ERP --><infoTributaria>")
        leido = leer(con_comentario)
        assert leido.tipo == "RETENCION"
        assert leido.total_iva == Decimal("54.32")

    def test_valores_no_finitos_no_se_guardan_como_credito(self):
        """NaN e Infinity se construyen sin error en Decimal, y PostgreSQL los
        acepta en una columna numeric: envenenarían todas las sumas."""
        for veneno in (b"NaN", b"Infinity", b"sNaN", b"1E999999999", b"-50.00"):
            xml = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000201)).replace(
                b"<valorRetenido>54.32</valorRetenido>",
                b"<valorRetenido>" + veneno + b"</valorRetenido>",
            )
            leido = leer(xml)
            assert leido.total_iva == Decimal("0"), f"{veneno!r} sobrevivió"
            assert leido.total_iva.is_finite()

    def test_un_documento_con_muchas_lineas_no_cuelga_el_worker(self):
        """El recorrido no puede ser cuadrático: buscar el documento de sustento
        por CADA línea convertía un adjunto que cabe en los topes en horas de
        CPU, y el worker es el mismo que firma las facturas de todos."""
        import time

        lineas = b"".join(
            b"<retencion><codigo>1</codigo><codigoRetencion>303</codigoRetencion>"
            b"<baseImponible>1.00</baseImponible><porcentajeRetener>1.00</porcentajeRetener>"
            b"<valorRetenido>0.01</valorRetenido></retencion>"
            for _ in range(3000)
        )
        # Sin numDocSustento: es lo que disparaba el rescaneo del subárbol entero
        hostil = (
            b'<?xml version="1.0"?><comprobanteRetencion version="2.0.0">'
            b"<infoTributaria><ruc>0992745103001</ruc></infoTributaria>"
            b"<infoCompRetencion><identificacionSujetoRetenido>"
            + RUC_A.encode()
            + b"</identificacionSujetoRetenido>"
            b"<periodoFiscal>08/2026</periodoFiscal></infoCompRetencion>"
            b"<docsSustento><docSustento><retenciones>"
            + lineas
            + b"</retenciones></docSustento></docsSustento>"
            b"</comprobanteRetencion>"
        )
        inicio = time.monotonic()
        leido = leer(hostil)
        tardanza = time.monotonic() - inicio
        assert tardanza < 5, f"el parseo tardó {tardanza:.1f}s: sigue siendo cuadrático"
        # Y hay tope de líneas
        assert len(leido.lineas) <= 500

    def test_un_ruc_kilometrico_no_tumba_el_registro_del_correo(self, buzon_encendido, admin_db):
        """Los valores del XML van a columnas estrechas: sin acotarlos, el INSERT
        fallaba y la transacción se llevaba por delante el registro del correo."""
        xml = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000202)).replace(
            b"<ruc>0992745103001</ruc>", b"<ruc>" + b"9" * 500 + b"</ruc>"
        )
        estado = _ingerir(
            correo(para=_direccion(RUC_A), adjunto=xml, message_id="<f7-largo@proveedor.ec>")
        )
        # Lo importante: el correo quedó registrado, pase lo que pase
        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        n = admin_db.execute(
            text("SELECT count(*) FROM buzon_correos WHERE message_id = 'f7-largo@proveedor.ec'")
        ).scalar()
        assert n == 1, f"el correo se perdió (estado {estado})"

    def test_xml_mal_formado_deja_el_motivo_visible(self, buzon_encendido, admin_db):
        """La maqueta muestra el motivo del fallo entre corchetes en el visor."""
        roto = b'<?xml version="1.0"?><comprobanteRetencion><infoTributaria></comprobanteRetencion>'
        mensaje = correo(para=_direccion(RUC_A), adjunto=roto, message_id="<f7-roto@proveedor.ec>")
        assert _ingerir(mensaje) == "error"

        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        fila = admin_db.scalars(
            select(BuzonCorreo).where(BuzonCorreo.message_id == "f7-roto@proveedor.ec")
        ).one()
        assert "XML mal formado" in (fila.motivo_error or "")
        assert "línea" in (fila.motivo_error or "")

    def test_el_correo_se_guarda_cifrado(self, buzon_encendido, admin_db):
        clave = clave_de_prueba(7000050)
        mensaje = correo(
            para=_direccion(RUC_A),
            adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave),
            message_id="<f7-cifra@proveedor.ec>",
        )
        _ingerir(mensaje)

        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        fila = admin_db.scalars(
            select(BuzonCorreo).where(BuzonCorreo.message_id == "f7-cifra@proveedor.ec")
        ).one()

        # En disco no queda nada legible: ni las cabeceras, que en un .eml van
        # en claro, ni el remitente, ni la dirección del inquilino.
        crudo_en_disco = Path(fila.payload_path).read_bytes()
        assert b"facturacion@proveedor.ec" not in crudo_en_disco
        assert _direccion(RUC_A).encode() not in crudo_en_disco
        assert b"Message-ID" not in crudo_en_disco

        # Y se recupera byte a byte
        assert ingesta.leer_cifrado(fila.payload_path) == mensaje

        # El XML de la retención también se custodia cifrado
        ret = admin_db.scalars(
            select(RetencionRecibida).where(RetencionRecibida.clave_acceso == clave)
        ).one()
        xml_en_disco = Path(ret.xml_path).read_bytes()
        assert b"comprobanteRetencion" not in xml_en_disco
        assert b"comprobanteRetencion" in ingesta.leer_cifrado(ret.xml_path)

    def test_el_contenido_del_correo_no_llega_a_la_bitacora(self, buzon_encendido, admin_db):
        """audit_log es inmutable y lo lee el personal interno: si el XML cayera
        ahí en claro, el cifrado en reposo no serviría de nada."""
        clave = clave_de_prueba(7000051)
        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave),
                message_id="<f7-audit@proveedor.ec>",
            )
        )
        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        volcado = admin_db.execute(
            text(
                "SELECT coalesce(string_agg(coalesce(antes::text,'') || "
                "coalesce(despues::text,''), ' '), '') FROM audit_log "
                "WHERE tabla IN ('buzon_correos','retenciones_recibidas')"
            )
        ).scalar_one()
        assert "comprobanteRetencion" not in volcado
        assert "infoTributaria" not in volcado

    def test_un_zip_con_el_xml_dentro_tambien_entra(self, buzon_encendido, admin_db):
        """Media contabilidad del país manda el comprobante comprimido."""
        assert (
            _ingerir(
                correo(
                    para=_direccion(RUC_A),
                    adjunto=xml_retencion(
                        ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000060)
                    ),
                    message_id="<f7-zip@proveedor.ec>",
                    comprimir=True,
                )
            )
            == "parseado"
        )
        assert retenciones.saldo(admin_db, TENANT_A).documentos == 1


# ----------------------------------------------------------------- feature flag


class TestFeatureFlag:
    def test_apagado_el_saldo_es_cero_aunque_haya_documentos(self, buzon_encendido, admin_db):
        """El flag se evalúa también donde se suma el saldo: encender el módulo
        no puede ser el efecto secundario de que alguien reciba un correo."""
        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000070)),
                message_id="<f7-flag@proveedor.ec>",
            )
        )
        assert retenciones.saldo(admin_db, TENANT_A).documentos == 1

        admin_db.execute(text("UPDATE parametros SET valor='false' WHERE clave='BUZON_ACTIVO'"))
        admin_db.commit()
        admin_db.expire_all()

        assert retenciones.activo(admin_db) is False
        assert retenciones.saldo(admin_db, TENANT_A).total == Decimal("0")
        assert retenciones.listar(admin_db, TENANT_A) == []
        # Y el IVA a pagar no se toca
        r = reportes.resumen_fiscal(
            admin_db, TENANT_A, desde=date(2026, 8, 1), hasta=date(2026, 9, 1)
        )
        assert r.retenciones_recibidas == Decimal("0")

    def test_con_el_flag_apagado_el_correo_igual_se_registra(self, buzon_encendido, admin_db):
        """La maqueta: «mientras el flag esté apagado, los clientes no ven nada
        y los correos solo se registran para depurar»."""
        admin_db.execute(text("UPDATE parametros SET valor='false' WHERE clave='BUZON_ACTIVO'"))
        admin_db.commit()

        assert (
            _ingerir(
                correo(
                    para=_direccion(RUC_A),
                    adjunto=xml_retencion(
                        ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000071)
                    ),
                    message_id="<f7-apagado@proveedor.ec>",
                )
            )
            == "parseado"
        )

        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        n = admin_db.execute(text("SELECT count(*) FROM buzon_correos")).scalar()
        assert n == 1

    def test_solo_el_superadmin_alterna_el_flag(self, client, sa, soporte_auth):
        r = client.post("/api/v1/sa/buzon/flag?activo=true", headers=soporte_auth)
        assert r.status_code == 403

        r = client.post("/api/v1/sa/buzon/flag?activo=true", headers=sa)
        assert r.status_code == 200, r.text
        assert r.json()["etiqueta"] == "BUZON_ACTIVO = true"
        assert "registrado en auditoría" in r.json()["mensaje"]

        r = client.post("/api/v1/sa/buzon/flag?activo=false", headers=sa)
        assert r.json()["etiqueta"] == "BUZON_ACTIVO = false"

    def test_alternar_el_flag_queda_auditado(self, client, sa, admin_db):
        client.post("/api/v1/sa/buzon/flag?activo=true", headers=sa)
        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        acciones = (
            admin_db.execute(
                text(
                    "SELECT accion FROM audit_log WHERE tabla = 'parametros' "
                    "ORDER BY created_at DESC"
                )
            )
            .scalars()
            .all()
        )
        assert "Feature flag BUZON_ACTIVO → true" in acciones
        admin_db.execute(text("DELETE FROM parametros WHERE clave = 'BUZON_ACTIVO'"))
        admin_db.commit()


# --------------------------------------------------------------- API del panel


class TestBandejaDelInquilino:
    def test_la_bandeja_exige_el_plan(self, client, ana_tokens, plan_inicial_a):
        """Con el plan Inicial sale el muro, igual que en la maqueta."""
        r = client.get("/api/v1/retenciones", headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 402
        assert "bandeja de retenciones" in r.json()["detail"]["mensaje"]
        assert r.json()["detail"]["plan_sugerido"] == "Independiente"

    def test_un_inquilino_no_ve_la_retencion_de_otro_por_la_api(
        self, buzon_encendido, client, bob_tokens, con_archivos_b
    ):
        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000080)),
                message_id="<f7-api@proveedor.ec>",
            )
        )
        r = client.get("/api/v1/retenciones", headers=auth_headers(bob_tokens["access_token"]))
        assert r.status_code == 200, r.text
        assert r.json()["retenciones"] == []
        assert r.json()["saldo"] == "0"

    def test_la_direccion_del_buzon_es_el_ruc(
        self, buzon_encendido, client, ana_tokens, con_archivos_a
    ):
        r = client.get("/api/v1/retenciones", headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 200, r.text
        assert r.json()["buzon"] == f"{RUC_A}@{get_settings().dominio_buzon}"

    def test_el_xml_se_descarga_descifrado(
        self, buzon_encendido, client, ana_tokens, con_archivos_a, admin_db
    ):
        clave = clave_de_prueba(7000081)
        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave),
                message_id="<f7-bajar@proveedor.ec>",
            )
        )
        datos = client.get(
            "/api/v1/retenciones", headers=auth_headers(ana_tokens["access_token"])
        ).json()
        assert len(datos["retenciones"]) == 1
        rid = datos["retenciones"][0]["id"]

        r = client.get(
            f"/api/v1/retenciones/{rid}/xml", headers=auth_headers(ana_tokens["access_token"])
        )
        assert r.status_code == 200
        assert b"comprobanteRetencion" in r.content
        assert clave.encode() in r.content


class TestWebhook:
    def test_sin_secreto_configurado_rechaza_todo(self, client):
        """Nunca falla abierto: un buzón sin firma acepta documentos de
        cualquiera, y esos documentos cambian la declaración de un cliente."""
        s = get_settings()
        previo = s.buzon_webhook_secret
        s.buzon_webhook_secret = ""
        try:
            r = client.post("/api/v1/buzon/webhook", content=b"cualquier cosa")
            assert r.status_code == 403
        finally:
            s.buzon_webhook_secret = previo

    def test_firma_invalida_se_rechaza(self, client):
        s = get_settings()
        previo = s.buzon_webhook_secret
        s.buzon_webhook_secret = "secreto-de-prueba"
        try:
            r = client.post(
                "/api/v1/buzon/webhook",
                content=b"correo",
                headers={"X-Buzon-Signature": "sha256=00"},
            )
            assert r.status_code == 403
        finally:
            s.buzon_webhook_secret = previo

    def test_firma_valida_encola(self, client, monkeypatch):
        import hmac
        from hashlib import sha256

        from app.api.routes import buzon as rutas

        encolados: list[str] = []
        monkeypatch.setattr(
            rutas.ingerir_correo,
            "delay",
            lambda payload, destinatario=None: encolados.append(payload),
        )

        s = get_settings()
        previo = s.buzon_webhook_secret
        s.buzon_webhook_secret = "secreto-de-prueba"
        try:
            cuerpo = correo(para=_direccion(RUC_A), message_id="<f7-hook@proveedor.ec>")
            firma = "sha256=" + hmac.new(b"secreto-de-prueba", cuerpo, sha256).hexdigest()
            r = client.post(
                "/api/v1/buzon/webhook", content=cuerpo, headers={"X-Buzon-Signature": firma}
            )
            assert r.status_code == 202, r.text
            assert len(encolados) == 1
        finally:
            s.buzon_webhook_secret = previo


class TestAlertaTreintaDias:
    def test_avisa_al_buzon_callado_una_sola_vez(self, buzon_encendido, admin_db, monkeypatch):
        from app.tasks import buzon as tareas

        enviados: list[tuple[str, str]] = []
        monkeypatch.setattr(
            tareas,
            "enviar_correo",
            lambda destinatario, asunto, cuerpo_html, adjuntos=None: (
                enviados.append((destinatario, cuerpo_html)) or "ok"
            ),
        )
        admin_db.execute(
            text("UPDATE tenants SET buzon_alertado_at = NULL WHERE id = :t"), {"t": TENANT_A}
        )
        admin_db.commit()

        tenant = admin_db.get(Tenant, TENANT_A)
        tareas.avisar_buzon_callado(str(TENANT_A), tenant.razon_social, tenant.email)
        assert len(enviados) == 1
        assert f"{RUC_A}@{get_settings().dominio_buzon}" in enviados[0][1]

        # Reintentar no manda un segundo correo
        assert tareas.avisar_buzon_callado(str(TENANT_A), tenant.razon_social, tenant.email) == (
            "ya-avisado"
        )
        assert len(enviados) == 1

        admin_db.execute(
            text("UPDATE tenants SET buzon_alertado_at = NULL WHERE id = :t"), {"t": TENANT_A}
        )
        admin_db.commit()

    def test_recibir_algo_reabre_el_reloj(self, buzon_encendido, admin_db):
        admin_db.execute(
            text("UPDATE tenants SET buzon_alertado_at = :t WHERE id = :i"),
            {"t": datetime.now(UTC) - timedelta(days=1), "i": TENANT_A},
        )
        admin_db.commit()

        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000090)),
                message_id="<f7-reloj@proveedor.ec>",
            )
        )
        admin_db.expire_all()
        assert admin_db.get(Tenant, TENANT_A).buzon_alertado_at is None


class TestPanelInterno:
    def test_lista_los_correos_de_todos_los_inquilinos(self, buzon_encendido, client, sa):
        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000100)),
                message_id="<f7-panel-a@proveedor.ec>",
            )
        )
        _ingerir(
            correo(
                para=_direccion(RUC_B),
                adjunto=xml_retencion(ruc_retenido=RUC_B, clave_acceso=clave_de_prueba(7000101)),
                message_id="<f7-panel-b@proveedor.ec>",
            )
        )
        r = client.get("/api/v1/sa/buzon", headers=sa)
        assert r.status_code == 200, r.text
        datos = r.json()
        buzones = {c["buzon"] for c in datos["correos"]}
        assert _direccion(RUC_A) in buzones
        assert _direccion(RUC_B) in buzones
        # La maqueta rotula PROCESADO donde el modelo dice PARSEADO
        assert all(c["estado"] in ("PROCESADO", "ERROR", "DUPLICADO") for c in datos["correos"])

    def test_el_visor_de_xml_crudo_descifra(self, buzon_encendido, client, sa):
        roto = b'<?xml version="1.0"?><comprobanteRetencion><infoTributaria>'
        _ingerir(correo(para=_direccion(RUC_A), adjunto=roto, message_id="<f7-visor@proveedor.ec>"))
        lista = client.get("/api/v1/sa/buzon", headers=sa).json()["correos"]
        con_error = [c for c in lista if c["es_error"]]
        assert con_error, "no hay ninguna fila con error"

        r = client.get(f"/api/v1/sa/buzon/{con_error[0]['id']}/crudo", headers=sa)
        assert r.status_code == 200, r.text
        assert "comprobanteRetencion" in r.json()["xml"]
        # El motivo va entre corchetes al final del volcado, como la maqueta
        assert r.json()["xml"].rstrip().endswith("]")

    def test_un_inquilino_no_entra_al_panel_interno(self, client, ana_tokens):
        r = client.get("/api/v1/sa/buzon", headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 403

    def test_la_banda_de_buzones_callados_trae_filas(self, buzon_encendido, client, sa, admin_db):
        """La banda ámbar cruza `tenants`, que está cerrada incluso para el
        personal interno: sin función segura devolvía cero filas SIEMPRE y en
        producción habría estado vacía desde el primer día sin que nada fallara.
        """
        admin_db.execute(
            text("UPDATE tenants SET created_at = now() - interval '13 days' WHERE id = :t"),
            {"t": TENANT_B},
        )
        admin_db.commit()

        datos = client.get("/api/v1/sa/buzon", headers=sa).json()
        assert datos["callados"], "la banda ámbar salió vacía"
        uno = datos["callados"][0]
        assert uno["dias"] >= 13
        assert uno["umbral"] == get_settings().buzon_dias_alerta
        assert uno["inquilino"]


class TestBarridoDeLosTreintaDias:
    def test_el_barrido_encuentra_al_que_no_recibe_nada(
        self, buzon_encendido, admin_db, monkeypatch
    ):
        """Nadie probaba el barrido, y además leía el flag de un sitio distinto
        al resto de la fase: con el módulo encendido desde el panel, el
        recordatorio no se disparaba nunca."""
        from app.tasks import buzon as tareas

        admin_db.execute(
            text(
                "UPDATE tenants SET created_at = now() - interval '60 days', "
                "buzon_alertado_at = NULL WHERE id IN (:a, :b)"
            ),
            {"a": TENANT_A, "b": TENANT_B},
        )
        admin_db.commit()

        encolados: list[tuple] = []
        monkeypatch.setattr(
            tareas.avisar_buzon_callado, "delay", lambda *args: encolados.append(args)
        )
        assert tareas.barrer_buzones_callados() >= 2
        assert len(encolados) >= 2

    def test_con_el_modulo_apagado_no_se_avisa_a_nadie(
        self, buzon_encendido, admin_db, monkeypatch
    ):
        """Recomendarle a alguien que configure el reenvío de una función que
        todavía no ve sería incoherente."""
        from app.tasks import buzon as tareas

        admin_db.execute(text("UPDATE parametros SET valor='false' WHERE clave='BUZON_ACTIVO'"))
        admin_db.execute(text("UPDATE tenants SET created_at = now() - interval '60 days'"))
        admin_db.commit()

        encolados: list[tuple] = []
        monkeypatch.setattr(
            tareas.avisar_buzon_callado, "delay", lambda *args: encolados.append(args)
        )
        assert tareas.barrer_buzones_callados() == 0
        assert encolados == []

    def test_quien_ya_recibio_algo_no_entra_en_el_barrido(
        self, buzon_encendido, admin_db, monkeypatch
    ):
        from app.tasks import buzon as tareas

        admin_db.execute(
            text(
                "UPDATE tenants SET created_at = now() - interval '60 days', "
                "buzon_alertado_at = NULL"
            )
        )
        admin_db.commit()
        _ingerir(
            correo(
                para=_direccion(RUC_A),
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000400)),
                message_id="<f7-barrido@proveedor.ec>",
            )
        )

        encolados: list[tuple] = []
        monkeypatch.setattr(
            tareas.avisar_buzon_callado, "delay", lambda *args: encolados.append(args)
        )
        tareas.barrer_buzones_callados()
        assert all(str(TENANT_A) != a[0] for a in encolados), "avisó a quien sí recibió"


class TestCandado:
    def test_un_correo_no_se_pierde_si_el_candado_esta_tomado(self, buzon_encendido):
        """Si «candado ocupado» se tratara como éxito, Celery haría ACK y el
        mensaje desaparecería del broker. Y el candado puede ser de un worker
        muerto, así que el correo se perdería para siempre."""
        from app.core.ratelimit import get_redis
        from app.tasks.buzon import CandadoOcupado, ingerir

        mensaje = correo(
            para=_direccion(RUC_A),
            adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000410)),
            message_id="<f7-candado@proveedor.ec>",
        )
        r = get_redis()
        clave_lock = f"buzon:lock:{TENANT_A}:f7-candado@proveedor.ec"
        r.set(clave_lock, "otro-worker", ex=60)
        try:
            with pytest.raises(CandadoOcupado):
                ingerir(mensaje)
        finally:
            r.delete(clave_lock)

        # Suelto el candado, el mismo mensaje entra bien
        assert _ingerir(mensaje) == "parseado"

    def test_el_candado_excluye_de_verdad(self, buzon_encendido):
        from app.tasks.buzon import _candado

        clave = "buzon:lock:prueba-exclusion"
        with _candado(clave) as primero:
            assert primero is True
            with _candado(clave) as segundo:
                assert segundo is False


class TestCosturaWebhook:
    def test_del_webhook_a_la_ingesta_de_punta_a_punta(self, buzon_encendido, client, admin_db):
        """La costura webhook → base64 → cola → ingesta, entera.

        Cada mitad estaba probada por separado; un cambio en la codificación
        habría roto producción con la suite en verde.
        """
        import hmac as _hmac
        from hashlib import sha256 as _sha256

        from app.api.routes import buzon as rutas
        from app.tasks import buzon as tareas

        s = get_settings()
        previo = s.buzon_webhook_secret
        s.buzon_webhook_secret = "secreto-de-costura"

        # `delay` ejecuta el task EN EL ACTO, con los mismos argumentos
        original = rutas.ingerir_correo.delay
        rutas.ingerir_correo.delay = lambda payload, destinatario=None: tareas.ingerir_correo(
            payload, destinatario
        )
        try:
            cuerpo = correo(
                para=_direccion(RUC_A),
                con_delivered_to=False,  # el destino llega SOLO por el sobre
                adjunto=xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave_de_prueba(7000420)),
                message_id="<f7-costura@proveedor.ec>",
            )
            firma = "sha256=" + _hmac.new(b"secreto-de-costura", cuerpo, _sha256).hexdigest()
            r = client.post(
                "/api/v1/buzon/webhook",
                content=cuerpo,
                headers={
                    "X-Buzon-Signature": firma,
                    "X-Buzon-Recipient": _direccion(RUC_A),
                },
            )
            assert r.status_code == 202, r.text
        finally:
            rutas.ingerir_correo.delay = original
            s.buzon_webhook_secret = previo

        admin_db.execute(text("SELECT set_config('app.is_internal','true',true)"))
        n = admin_db.execute(
            text("SELECT count(*) FROM buzon_correos WHERE message_id = 'f7-costura@proveedor.ec'")
        ).scalar()
        assert n == 1, "el correo no llegó a la base pasando por el webhook"

    def test_por_que_la_firma_se_comprueba_ascii_antes_de_compararla(self):
        """Starlette decodifica las cabeceras como latin-1, así que un byte
        alto llega al endpoint como carácter no ASCII. `compare_digest` solo
        admite ASCII: sin la guarda lanzaría TypeError y devolvería un 500 en
        vez del 403 que corresponde. El cliente de pruebas no puede mandar esa
        cabecera, así que se comprueba la razón directamente."""
        import hmac as _hmac

        firma = "sha256=ñ"
        assert firma.isascii() is False
        with pytest.raises(TypeError):
            _hmac.compare_digest(firma, "sha256=abc")


class TestVariosComprobantes:
    def test_un_correo_con_dos_retenciones_suma_las_dos(self, buzon_encendido, admin_db):
        """Los lotes del SRI traen varios comprobantes en el mismo mensaje."""
        from email import policy
        from email.parser import BytesParser

        base = correo(
            para=_direccion(RUC_A),
            adjunto=xml_retencion(
                ruc_retenido=RUC_A,
                clave_acceso=clave_de_prueba(7000430),
                numero="001-001-000000001",
            ),
            message_id="<f7-lote@proveedor.ec>",
        )
        msg = BytesParser(policy=policy.default).parsebytes(base)
        msg.add_attachment(
            xml_retencion(
                ruc_retenido=RUC_A,
                clave_acceso=clave_de_prueba(7000431),
                numero="001-001-000000002",
            ),
            maintype="application",
            subtype="xml",
            filename="segunda.xml",
        )
        assert _ingerir(bytes(msg)) == "parseado"

        saldo = retenciones.saldo(admin_db, TENANT_A)
        assert saldo.documentos == 2
        assert saldo.iva == Decimal("108.64")  # 54.32 × 2


class TestNoBastaConQueLaClaveExista:
    """El papel tiene que ser EL QUE EL SRI TIENE, no uno con esa clave escrita.

    Mientras la retención solo llegaba por correo, el que escribía el XML era un
    tercero y el contribuyente era la víctima. Desde que se puede subir a mano,
    quien escribe el papel es quien cobra el crédito: con la clave de una
    factura suya —impresa en cada RIDE que emite— podía fabricarse una retención
    a su nombre por el importe que quisiera y bajarse el IVA a pagar.
    """

    def _falsificada(self, clave: str, **cambios) -> bytes:
        """El XML legítimo queda registrado como «lo que tiene el SRI»; el que
        se presenta es otro con la misma clave."""
        legitimo = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave)
        assert buzon_utils.REGISTRO[clave] == legitimo
        falso = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave, **cambios)
        buzon_utils.REGISTRO[clave] = legitimo  # el SRI sigue teniendo el bueno
        return falso

    def _verificar(self, admin_db, xml: bytes) -> RetencionRecibida:
        from app.buzon import ingesta, verificacion

        tenant = admin_db.get(Tenant, TENANT_A)
        fila = ingesta.registrar_manual(admin_db, tenant, xml)
        admin_db.flush()
        verificacion.verificar(admin_db, fila, "PRUEBAS")
        admin_db.commit()  # si no, el borrado de la fixture choca con la fila viva
        return fila

    def test_un_importe_inflado_no_cuenta(self, buzon_encendido, admin_db):
        clave = clave_de_prueba(7100501)
        fila = self._verificar(
            admin_db, self._falsificada(clave, valor_iva=Decimal("9999999.99"))
        )
        assert fila.verificada is False
        assert "importes" in fila.verificacion["detalle"].lower()

    def test_un_agente_inventado_no_cuenta(self, buzon_encendido, admin_db):
        clave = clave_de_prueba(7100502)
        fila = self._verificar(
            admin_db, self._falsificada(clave, ruc_agente="1790099999001")
        )
        assert fila.verificada is False

    def test_la_clave_de_otro_documento_no_sirve(self, buzon_encendido, admin_db):
        """La clave de una FACTURA está autorizada, pero no es una retención."""
        clave = clave_de_prueba(7100503)
        presentada = xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave)
        # DESPUÉS de fabricarla, porque `xml_retencion` registra la suya: lo que
        # el SRI tiene con esa clave es una factura, no una retención.
        buzon_utils.REGISTRO[clave] = b'<factura id="comprobante" version="1.1.0"/>'
        fila = self._verificar(admin_db, presentada)
        assert fila.verificada is False

    def test_la_legitima_si_cuenta(self, buzon_encendido, admin_db):
        """La contraprueba: sin esto, un fallo de lectura daría todo por falso."""
        clave = clave_de_prueba(7100504)
        fila = self._verificar(
            admin_db, xml_retencion(ruc_retenido=RUC_A, clave_acceso=clave)
        )
        assert fila.verificada is True, fila.verificacion
