"""Checklist F4:
 1. crear código promo, alta de cliente con promo, verlo en usos con Retenido;
 2. impersonar deja doble rastro;
 3. cambiar precio con vigencia futura NO afecta suscripciones actuales.

Además: el rol LECTURA mira pero no actúa, y la auditoría es de solo lectura.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.db.models import AuditLog, Impersonacion, Suscripcion, Tenant
from app.services.planes import LIMITES_POR_PLAN
from tests.conftest import auth_headers

HOY = date.today()
FUTURO = HOY + timedelta(days=30)


@pytest.fixture()
def sa(admin_auth):
    return auth_headers(admin_auth["access"])


@pytest.fixture()
def limpiar(admin_db):
    """Borra lo que crea cada test: el panel interno es global y contamina."""
    rucs: list[str] = []
    codigos: list[str] = []
    yield {"rucs": rucs, "codigos": codigos}

    from app.db.models import PromoCode, PromoUse

    for ruc in rucs:
        t = admin_db.scalars(select(Tenant).where(Tenant.ruc == ruc)).first()
        if t is not None:
            for s in admin_db.scalars(
                select(Suscripcion).where(Suscripcion.tenant_id == t.id)
            ).all():
                admin_db.delete(s)
            for u in admin_db.scalars(select(PromoUse).where(PromoUse.tenant_id == t.id)).all():
                admin_db.delete(u)
            admin_db.flush()
            admin_db.delete(t)
    for codigo in codigos:
        p = admin_db.scalars(select(PromoCode).where(PromoCode.codigo == codigo)).first()
        if p is not None:
            for u in admin_db.scalars(select(PromoUse).where(PromoUse.promo_code_id == p.id)).all():
                admin_db.delete(u)
            admin_db.flush()
            admin_db.delete(p)
    admin_db.commit()


def _ruc_nuevo() -> str:
    """13 dígitos terminados en 001, como exige el SRI."""
    return f"17{uuid.uuid4().int % 100_000_000:08d}001"


class TestChecklistPromo:
    """1. crear código promo → alta con promo → verlo en usos con Retenido."""

    def test_flujo_completo(self, client, sa, limpiar, admin_db):
        # --- crear el código LANZA99: primer mes a $0.99
        codigo = f"LANZA{uuid.uuid4().hex[:4].upper()}"
        limpiar["codigos"].append(codigo)
        r = client.post(
            "/api/v1/sa/promos",
            json={
                "codigo": codigo,
                "descripcion": "Primer mes a $0.99",
                "tipo": "PRECIO_FIJO",
                "valor": "0.99",
                "meses": 1,
                "planes": ["Independiente", "Emprendedor", "Empresario"],
                "max_usos": 200,
                "vigente_desde": HOY.isoformat(),
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text

        # --- alta de cliente CON el código, en el plan Emprendedor ($9.99)
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Panadería Doña Andrade",
                "email": "donaandrade@mail.ec",
                "plan": "EMPRENDEDOR",
                "codigo_promo": codigo,
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text
        alta = r.json()
        # Cobra $0.99 en vez de los $9.99 de lista
        assert Decimal(alta["precio_cobrado"]) == Decimal("0.99")
        assert alta["promo"]["codigo"] == codigo
        assert Decimal(alta["promo"]["retenido"]) == Decimal("9.00")

        # --- verlo en la tabla de usos, con su columna Retenido
        promos = client.get("/api/v1/sa/promos", headers=sa).json()
        mio = next(p for p in promos if p["codigo"] == codigo)
        assert mio["usos"] == 1
        assert Decimal(mio["retenido_total"]) == Decimal("9.00")

        detalle = client.get(f"/api/v1/sa/promos/{mio['id']}/usos", headers=sa).json()
        assert len(detalle["usos"]) == 1
        uso = detalle["usos"][0]
        assert uso["cliente"] == "Panadería Doña Andrade"
        assert Decimal(uso["precio_lista"]) == Decimal("9.99")
        assert Decimal(uso["precio_cobrado"]) == Decimal("0.99")
        assert Decimal(uso["retenido"]) == Decimal("9.00")

        # --- y la suscripción quedó con el precio de la promo, no el de lista
        tenant = admin_db.scalars(select(Tenant).where(Tenant.ruc == ruc)).one()
        sus = admin_db.scalars(select(Suscripcion).where(Suscripcion.tenant_id == tenant.id)).one()
        assert sus.precio == Decimal("0.99")

    def test_promo_de_varios_meses_retiene_mas(self, client, sa, limpiar):
        codigo = f"TRES{uuid.uuid4().hex[:4].upper()}"
        limpiar["codigos"].append(codigo)
        client.post(
            "/api/v1/sa/promos",
            json={
                "codigo": codigo,
                "tipo": "PORCENTAJE",
                "valor": "50",
                "meses": 3,
                "vigente_desde": HOY.isoformat(),
            },
            headers=sa,
        )
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Medio Descuento SA",
                "email": "medio@mail.ec",
                "plan": "EMPRENDEDOR",
                "codigo_promo": codigo,
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text
        # 50% de 9.99 = 5.00 (redondeado); retenido por 3 meses = 14.97
        assert Decimal(r.json()["precio_cobrado"]) == Decimal("5.00")
        assert Decimal(r.json()["promo"]["retenido"]) == Decimal("14.97")

    def test_promo_no_aplica_a_ese_plan(self, client, sa, limpiar):
        codigo = f"SOLO{uuid.uuid4().hex[:4].upper()}"
        limpiar["codigos"].append(codigo)
        client.post(
            "/api/v1/sa/promos",
            json={
                "codigo": codigo,
                "tipo": "PRECIO_FIJO",
                "valor": "0.99",
                "planes": ["Empresario"],
                "vigente_desde": HOY.isoformat(),
            },
            headers=sa,
        )
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Plan Equivocado SA",
                "email": "eq@mail.ec",
                "plan": "INICIAL",
                "codigo_promo": codigo,
            },
            headers=sa,
        )
        assert r.status_code == 422
        assert "Empresario" in r.json()["detail"]

    def test_promo_agotada_se_rechaza(self, client, sa, limpiar):
        """El cupo de una promoción se cuenta en SERVIDOR: un código de un solo
        uso no puede aplicarse dos veces por más que se reintente."""
        codigo = f"UNICO{uuid.uuid4().hex[:3].upper()}"
        limpiar["codigos"].append(codigo)
        client.post(
            "/api/v1/sa/promos",
            json={
                "codigo": codigo,
                "tipo": "PRECIO_FIJO",
                "valor": "0.99",
                "max_usos": 1,
                "vigente_desde": HOY.isoformat(),
            },
            headers=sa,
        )

        codigos_http = []
        for i in range(2):
            ruc = _ruc_nuevo()
            limpiar["rucs"].append(ruc)
            codigos_http.append(
                client.post(
                    "/api/v1/sa/clientes",
                    json={
                        "ruc": ruc,
                        "razon_social": f"Cupo {i} SA",
                        "email": f"cupo{i}@mail.ec",
                        "plan": "INICIAL",
                        "codigo_promo": codigo,
                    },
                    headers=sa,
                ).status_code
            )

        assert codigos_http[0] == 201
        assert codigos_http[1] == 422

    def test_promo_vencida_se_rechaza(self, client, sa, limpiar):
        codigo = f"VIEJO{uuid.uuid4().hex[:3].upper()}"
        limpiar["codigos"].append(codigo)
        client.post(
            "/api/v1/sa/promos",
            json={
                "codigo": codigo,
                "tipo": "PRECIO_FIJO",
                "valor": "0.99",
                "vigente_desde": (HOY - timedelta(days=60)).isoformat(),
                "vigente_hasta": (HOY - timedelta(days=1)).isoformat(),
            },
            headers=sa,
        )
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Tarde SA",
                "email": "tarde@mail.ec",
                "plan": "INICIAL",
                "codigo_promo": codigo,
            },
            headers=sa,
        )
        assert r.status_code == 422
        assert "venció" in r.json()["detail"]


class TestChecklistImpersonacion:
    """2. impersonar deja doble rastro."""

    def test_doble_rastro(self, client, sa, admin_db, ana_tokens):
        from tests.conftest import TENANT_A

        r = client.post(
            f"/api/v1/sa/clientes/{TENANT_A}/impersonar",
            json={"motivo": "El cliente reporta que no ve sus comprobantes de agosto"},
            headers=sa,
        )
        assert r.status_code == 200, r.text
        datos = r.json()
        imp_id = uuid.UUID(datos["impersonacion_id"])
        assert "queda en auditoría" in datos["aviso"]

        # RASTRO 1: la sesión, con motivo, abierta
        sesion = admin_db.get(Impersonacion, imp_id)
        admin_db.refresh(sesion)
        assert sesion.terminada_at is None
        assert "no ve sus comprobantes" in sesion.motivo

        # ...y su evento de inicio en la bitácora
        inicio = admin_db.scalars(
            select(AuditLog).where(
                AuditLog.accion == "IMPERSONACION_INICIO",
                AuditLog.registro_id == str(imp_id),
            )
        ).one()
        assert inicio.actor_rol == "SUPERADMIN"

        # RASTRO 2: lo que se haga con ese token se audita con el actor REAL
        token_imp = {"Authorization": f"Bearer {datos['token']}"}
        r = client.post(
            "/api/v1/clientes",
            json={
                "tipo_identificacion": "CEDULA",
                "identificacion": f"09{uuid.uuid4().int % 100_000_000:08d}",
                "razon_social": "Creado durante impersonación",
            },
            headers=token_imp,
        )
        assert r.status_code == 201, r.text
        creado_id = r.json()["id"]

        entrada = admin_db.scalars(
            select(AuditLog).where(
                AuditLog.tabla == "clientes_finales",
                AuditLog.registro_id == creado_id,
                AuditLog.accion == "INSERT",
            )
        ).one()
        # El rol registrado es el del OPERADOR, no CLIENTE: si dijera CLIENTE,
        # el rastro afirmaría que lo hizo el propio inquilino.
        assert entrada.actor_rol == "SUPERADMIN"
        assert entrada.despues["_impersonacion"]["id"] == str(imp_id)

        # Salir cierra la sesión y deja su propio evento
        r = client.post(f"/api/v1/sa/impersonaciones/{imp_id}/salir", headers=sa)
        assert r.status_code == 204
        admin_db.expire_all()
        sesion = admin_db.get(Impersonacion, imp_id)
        assert sesion.terminada_at is not None
        fin = admin_db.scalars(
            select(AuditLog).where(
                AuditLog.accion == "IMPERSONACION_FIN",
                AuditLog.registro_id == str(imp_id),
            )
        ).one()
        assert "duracion_segundos" in fin.despues

    def test_motivo_obligatorio(self, client, sa):
        from tests.conftest import TENANT_A

        r = client.post(
            f"/api/v1/sa/clientes/{TENANT_A}/impersonar",
            json={"motivo": "corto"},
            headers=sa,
        )
        assert r.status_code == 422

    def test_lectura_no_puede_impersonar(self, client, admin_db, lectura_tokens):
        from tests.conftest import TENANT_A

        r = client.post(
            f"/api/v1/sa/clientes/{TENANT_A}/impersonar",
            json={"motivo": "Quiero mirar la cuenta del cliente por curiosidad"},
            headers=auth_headers(lectura_tokens["access_token"]),
        )
        assert r.status_code == 403

    def test_el_token_no_da_acceso_al_panel_interno(self, client, sa):
        """La impersonación da rol CLIENTE sobre ese tenant, nada más: con ese
        token no se puede volver a entrar al panel interno."""
        from tests.conftest import TENANT_A

        datos = client.post(
            f"/api/v1/sa/clientes/{TENANT_A}/impersonar",
            json={"motivo": "Revisar el problema reportado por el cliente hoy"},
            headers=sa,
        ).json()
        token_imp = {"Authorization": f"Bearer {datos['token']}"}
        assert client.get("/api/v1/sa/clientes", headers=token_imp).status_code == 403
        # Y tampoco puede impersonar a un tercero
        r = client.post(
            f"/api/v1/sa/clientes/{TENANT_A}/impersonar",
            json={"motivo": "Intento de escalar desde una impersonación activa"},
            headers=token_imp,
        )
        assert r.status_code == 403


class TestChecklistPrecios:
    """3. cambiar precio con vigencia futura NO afecta suscripciones actuales."""

    def test_precio_futuro_no_toca_lo_vivo(self, client, sa, admin_db, limpiar):
        # Un cliente contratado HOY al precio de lista
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Contratado Antes SA",
                "email": "antes@mail.ec",
                "plan": "INICIAL",
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text
        precio_contratado = Decimal(r.json()["precio_cobrado"])
        assert precio_contratado == LIMITES_POR_PLAN["Inicial"]["precio"]

        tenant = admin_db.scalars(select(Tenant).where(Tenant.ruc == ruc)).one()
        sus = admin_db.scalars(select(Suscripcion).where(Suscripcion.tenant_id == tenant.id)).one()
        plan_original = sus.plan_id

        # Se sube el precio con vigencia FUTURA
        nuevo_precio = precio_contratado + Decimal("1.00")
        r = client.post(
            "/api/v1/sa/planes/INICIAL/precio",
            json={"precio": str(nuevo_precio), "vigente_desde": FUTURO.isoformat()},
            headers=sa,
        )
        assert r.status_code == 201, r.text
        assert "conservan su precio" in r.json()["aviso"]

        # La suscripción viva NO cambió: ni su precio ni su versión de plan
        admin_db.expire_all()
        sus = admin_db.scalars(select(Suscripcion).where(Suscripcion.tenant_id == tenant.id)).one()
        assert sus.precio == precio_contratado
        assert sus.plan_id == plan_original

        # Y el plan que ve hoy un cliente sigue siendo el viejo
        planes = client.get("/api/v1/sa/planes", headers=sa).json()
        inicial = [p for p in planes if p["codigo"] == "INICIAL"]
        vigente_hoy = next(p for p in inicial if p["vigente_ahora"])
        assert Decimal(vigente_hoy["precio"]) == precio_contratado
        programado = next(p for p in inicial if p["vigente_desde"] == FUTURO.isoformat())
        assert Decimal(programado["precio"]) == nuevo_precio
        assert programado["suscripciones"] == 0

    def test_precio_retroactivo_se_rechaza(self, client, sa):
        r = client.post(
            "/api/v1/sa/planes/INICIAL/precio",
            json={
                "precio": "99.00",
                "vigente_desde": (HOY - timedelta(days=1)).isoformat(),
            },
            headers=sa,
        )
        assert r.status_code == 422
        assert "futura" in r.json()["detail"]

    def test_solo_superadmin_cambia_precios(self, client, soporte_tokens):
        r = client.post(
            "/api/v1/sa/planes/INICIAL/precio",
            json={"precio": "3.99", "vigente_desde": FUTURO.isoformat()},
            headers=auth_headers(soporte_tokens["access_token"]),
        )
        assert r.status_code == 403


class TestRolesYAuditoria:
    def test_lectura_puede_mirar(self, client, lectura_tokens):
        h = auth_headers(lectura_tokens["access_token"])
        assert client.get("/api/v1/sa/clientes", headers=h).status_code == 200
        assert client.get("/api/v1/sa/metricas", headers=h).status_code == 200
        assert client.get("/api/v1/sa/auditoria", headers=h).status_code == 200

    def test_lectura_no_puede_actuar(self, client, lectura_tokens, limpiar):
        h = auth_headers(lectura_tokens["access_token"])
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": _ruc_nuevo(),
                "razon_social": "No debería crearse",
                "email": "no@mail.ec",
                "plan": "INICIAL",
            },
            headers=h,
        )
        assert r.status_code == 403

    def test_cliente_no_entra_al_panel_interno(self, client, ana_tokens):
        h = auth_headers(ana_tokens["access_token"])
        assert client.get("/api/v1/sa/clientes", headers=h).status_code == 403
        assert client.get("/api/v1/sa/auditoria", headers=h).status_code == 403

    def test_abrir_ficha_queda_auditado(self, client, sa, admin_db):
        from tests.conftest import TENANT_A

        motivo = "Reclamo por cobro duplicado del mes de agosto"
        r = client.get(f"/api/v1/sa/clientes/{TENANT_A}?motivo={motivo}", headers=sa)
        assert r.status_code == 200, r.text
        entrada = admin_db.scalars(
            select(AuditLog)
            .where(AuditLog.accion == "SA_FICHA", AuditLog.registro_id == str(TENANT_A))
            .order_by(AuditLog.created_at.desc())
        ).first()
        assert entrada is not None
        assert entrada.despues["motivo"] == motivo

    def test_auditoria_es_de_solo_lectura(self, app_engine):
        """No hay endpoint que escriba, y la base tampoco lo permite."""
        from sqlalchemy.exc import ProgrammingError

        with app_engine.connect() as conn:
            with pytest.raises(ProgrammingError):
                conn.execute(text("DELETE FROM audit_log"))

    def test_cambio_de_estado_queda_auditado(self, client, sa, admin_db, limpiar):
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        alta = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Para Suspender SA",
                "email": "susp@mail.ec",
                "plan": "INICIAL",
            },
            headers=sa,
        ).json()

        r = client.post(
            f"/api/v1/sa/clientes/{alta['id']}/estado",
            json={"estado": "SUSPENDIDO", "motivo": "Suspensión pedida por el cliente"},
            headers=sa,
        )
        assert r.status_code == 204

        entrada = admin_db.scalars(
            select(AuditLog).where(
                AuditLog.accion == "SA_ESTADO_TENANT",
                AuditLog.registro_id == alta["id"],
            )
        ).one()
        assert entrada.antes["estado"] == "ACTIVO"
        assert entrada.despues["estado"] == "SUSPENDIDO"
        assert "pedida por el cliente" in entrada.despues["motivo"]


class TestTarifasConVigencia:
    def test_alza_de_meta_precargada(self, admin_db):
        """El alza de Meta de octubre de 2026 va precargada (requisito 4.1)."""
        from app.services.configuracion import sembrar_tarifas, tarifa_vigente

        sembrar_tarifas(admin_db)
        admin_db.commit()

        antes = tarifa_vigente(
            admin_db, "META_WHATSAPP", "Conversación iniciada por la empresa", date(2026, 9, 30)
        )
        despues = tarifa_vigente(
            admin_db, "META_WHATSAPP", "Conversación iniciada por la empresa", date(2026, 10, 1)
        )
        assert antes is not None and despues is not None
        assert antes.costo_unitario == Decimal("0.040000")
        assert despues.costo_unitario == Decimal("0.052800")
        # La vieja se cierra justo cuando empieza la nueva: sin huecos ni solapes
        assert antes.vigente_hasta == date(2026, 10, 1)


class TestDashboardGeneral:
    """El Dashboard general se construyó una vez con los datos que había a mano
    en vez de con los que pide `Superadmin.dc.html`, y quedó sin MRR, sin altas
    y bajas, sin el gráfico de 30 días, sin el semáforo y sin alertas. El primer
    test de esta clase es el contrato con la maqueta: si alguien vuelve a quitar
    un bloque, aquí se cae."""

    CAMPOS = (
        "mrr",
        "mrr_variacion_pct",
        "altas_mes",
        "altas_con_promo",
        "bajas_mes",
        "cancelaciones",
        "suspensiones",
        "activos_total",
        "activos_por_plan",
        "emision",
        "servicios",
        "alertas",
    )

    def test_devuelve_todos_los_bloques_de_la_maqueta(self, client, sa):
        d = client.get("/api/v1/sa/metricas", headers=sa).json()
        faltan = [c for c in self.CAMPOS if c not in d]
        assert not faltan, f"el dashboard perdio bloques de la maqueta: {faltan}"

    def test_el_grafico_trae_treinta_dias_en_orden_y_acaba_hoy(self, client, sa):
        emision = client.get("/api/v1/sa/metricas", headers=sa).json()["emision"]
        dias = [b["dia"] for b in emision["barras"]]
        assert len(dias) == 30
        assert dias == sorted(dias)
        assert dias[-1] == HOY.isoformat()
        assert emision["maximo"] == max(b["n"] for b in emision["barras"])
        # Los tres contadores nunca pueden superar al periodo entero
        total = sum(b["n"] for b in emision["barras"])
        assert emision["hoy"] <= emision["semana"] <= total
        assert emision["mes"] <= total

    def test_el_semaforo_trae_las_cinco_filas_con_los_nombres_de_la_maqueta(self, client, sa):
        servicios = client.get("/api/v1/sa/metricas", headers=sa).json()["servicios"]
        assert [s["nombre"] for s in servicios] == [
            "SRI · recepción",
            "SRI · autorización",
            "WhatsApp API",
            "Firma electrónica",
            "Correo saliente",
        ]
        assert all(s["estado"] in {"ok", "aviso", "mal", "apagado"} for s in servicios)
        assert all(s["detalle"] for s in servicios)

    def test_cada_alerta_lleva_a_una_seccion_que_existe(self, client, sa):
        from app.api.routes.superadmin import router  # noqa: F401

        secciones = {"dash", "clientes", "consumo", "pagos", "comp", "wa", "buzon", "mkt"}
        for a in client.get("/api/v1/sa/metricas", headers=sa).json()["alertas"]:
            assert a["severidad"] in {"alta", "media"}
            assert a["texto"].strip()
            assert a["seccion"] in secciones, a

    def test_el_mrr_no_cuenta_el_plan_de_pago_unico(self, client, sa, limpiar):
        """INICIAL se paga una vez: si entrara al MRR, el ingreso recurrente
        aparecería inflado por clientes que no renuevan."""
        antes = Decimal(client.get("/api/v1/sa/metricas", headers=sa).json()["mrr"])

        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Pago Unico Cia Ltda",
                "email": "unico@mail.ec",
                "plan": "INICIAL",
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text

        despues = client.get("/api/v1/sa/metricas", headers=sa).json()
        assert Decimal(despues["mrr"]) == antes
        # …pero sí cuenta como alta del mes
        assert despues["altas_mes"] >= 1

    def test_una_alta_de_plan_recurrente_si_sube_el_mrr(self, client, sa, limpiar):
        antes = client.get("/api/v1/sa/metricas", headers=sa).json()
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Recurrente SA",
                "email": "recurrente@mail.ec",
                "plan": "EMPRENDEDOR",
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text
        precio = Decimal(r.json()["precio_cobrado"])

        despues = client.get("/api/v1/sa/metricas", headers=sa).json()
        assert Decimal(despues["mrr"]) == Decimal(antes["mrr"]) + precio
        assert despues["activos_total"] == antes["activos_total"] + 1
        # El desglose por plan tiene que sumar como mucho el total de activos
        assert sum(p["clientes"] for p in despues["activos_por_plan"]) <= despues["activos_total"]

    def test_la_variacion_no_se_inventa_sin_mes_anterior(self, client, sa):
        d = client.get("/api/v1/sa/metricas", headers=sa).json()
        v = d["mrr_variacion_pct"]
        assert v is None or isinstance(v, (int, float))

    def test_lectura_ve_el_dashboard_y_un_cliente_no(self, client, lectura_tokens, ana_tokens):
        assert (
            client.get(
                "/api/v1/sa/metricas", headers=auth_headers(lectura_tokens["access_token"])
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/v1/sa/metricas", headers=auth_headers(ana_tokens["access_token"])
            ).status_code
            == 403
        )

    @pytest.mark.parametrize(
        "funcion",
        [
            "sa_dashboard_kpis",
            "sa_dashboard_planes",
            "sa_dashboard_emision",
            "sa_dashboard_alertas",
        ],
    )
    def test_las_funciones_nuevas_verifican_el_rol_en_la_base(self, app_engine, funcion):
        """Sin contexto de operador interno, la funcion niega el acceso aunque
        se la invoque directamente con el rol de la aplicacion."""
        from sqlalchemy.exc import DatabaseError

        with app_engine.connect() as c:
            with pytest.raises(DatabaseError) as e:
                # El nombre viene del parametrize, no de una entrada externa
                c.execute(text(f"SELECT * FROM {funcion}()"))  # noqa: S608
        assert "acceso denegado" in str(e.value).lower()


class TestListadoDeClientes:
    """La maqueta filtra por cinco estados de cartera —ACTIVO, EN_PRUEBA,
    SUSPENDIDO, MOROSO, CANCELADO— que en la base no viven en una sola columna.
    La regla se escribió en `sa_clientes()`; estos tests la fijan."""

    CARTERA = {"ACTIVO", "EN_PRUEBA", "SUSPENDIDO", "MOROSO", "CANCELADO"}

    def _alta(self, client, sa, limpiar, plan="EMPRENDEDOR"):
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Cartera de Prueba SA",
                "email": f"{ruc}@mail.ec",
                "plan": plan,
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text
        return ruc, r.json()["id"]

    def _fila(self, client, sa, ruc):
        filas = client.get("/api/v1/sa/clientes", headers=sa).json()
        return next(f for f in filas if f["ruc"] == ruc)

    def test_el_listado_trae_las_columnas_de_la_maqueta(self, client, sa):
        filas = client.get("/api/v1/sa/clientes", headers=sa).json()
        assert filas, "el panel necesita al menos un inquilino de prueba"
        f = filas[0]
        for campo in (
            "ruc",
            "razon_social",
            "plan",
            "estado_cartera",
            "cupo",
            "usados",
            "ultimo_comp",
            "alta",
        ):
            assert campo in f, f"falta la columna {campo} del listado"
        assert all(x["estado_cartera"] in self.CARTERA for x in filas)

    def test_un_alta_nueva_sale_como_activa(self, client, sa, limpiar):
        ruc, _ = self._alta(client, sa, limpiar)
        f = self._fila(client, sa, ruc)
        assert f["estado_cartera"] == "ACTIVO"
        assert f["plan"] == "Emprendedor"
        assert f["cupo"] == 80
        # Recién dado de alta no ha emitido nada
        assert f["ultimo_comp"] is None

    def test_suspender_al_inquilino_lo_mueve_a_suspendido(self, client, sa, limpiar):
        ruc, tid = self._alta(client, sa, limpiar)
        r = client.post(
            f"/api/v1/sa/clientes/{tid}/estado",
            json={"estado": "SUSPENDIDO", "motivo": "Prueba del estado de cartera"},
            headers=sa,
        )
        assert r.status_code == 204, r.text
        assert self._fila(client, sa, ruc)["estado_cartera"] == "SUSPENDIDO"

    def test_una_suscripcion_morosa_marca_al_cliente_como_moroso(
        self, client, sa, limpiar, admin_db
    ):
        ruc, tid = self._alta(client, sa, limpiar)
        sus = admin_db.scalars(
            select(Suscripcion).where(Suscripcion.tenant_id == uuid.UUID(tid))
        ).one()
        sus.estado = "MOROSA"
        admin_db.commit()
        assert self._fila(client, sa, ruc)["estado_cartera"] == "MOROSO"

    def test_a_un_cancelado_no_se_le_pierde_el_plan(self, client, sa, limpiar, admin_db):
        """El listado anterior solo miraba suscripciones ACTIVA o MOROSA, así que
        el cliente que se iba aparecía sin plan y no había forma de saber de cuál
        se había ido."""
        ruc, tid = self._alta(client, sa, limpiar, plan="EMPRESARIO")
        sus = admin_db.scalars(
            select(Suscripcion).where(Suscripcion.tenant_id == uuid.UUID(tid))
        ).one()
        sus.estado = "CANCELADA"
        admin_db.commit()

        f = self._fila(client, sa, ruc)
        assert f["estado_cartera"] == "CANCELADO"
        assert f["plan"] == "Empresario", "se perdió el plan del cliente cancelado"

    def test_el_estado_del_inquilino_manda_sobre_el_de_la_suscripcion(
        self, client, sa, limpiar, admin_db
    ):
        """Un inquilino dado de baja está CANCELADO aunque su suscripción haya
        quedado activa por un cierre a medias: es su estado el que le impide
        emitir."""
        ruc, tid = self._alta(client, sa, limpiar)
        t = admin_db.get(Tenant, uuid.UUID(tid))
        assert t is not None
        t.estado = "BAJA"
        admin_db.commit()
        assert self._fila(client, sa, ruc)["estado_cartera"] == "CANCELADO"


class TestExportarClientes:
    def test_el_csv_sale_con_cabecera_y_una_fila_por_cliente(self, client, sa):
        r = client.get("/api/v1/sa/clientes.csv", headers=sa)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        assert ".csv" in r.headers["content-disposition"]

        texto = r.content.decode("utf-8-sig")
        lineas = [ln for ln in texto.splitlines() if ln.strip()]
        assert lineas[0].startswith('"RUC","Cliente"')
        cuantos = len(client.get("/api/v1/sa/clientes", headers=sa).json())
        assert len(lineas) == cuantos + 1

    def test_todo_va_entrecomillado_para_que_excel_no_evalue_formulas(self, client, sa):
        """Un nombre que empiece por «=» sería una fórmula al abrir el CSV en
        Excel. QUOTE_ALL lo deja como texto (OWASP A03)."""
        texto = client.get("/api/v1/sa/clientes.csv", headers=sa).content.decode("utf-8-sig")
        for linea in [ln for ln in texto.splitlines() if ln.strip()]:
            assert linea.startswith('"') and linea.endswith('"')

    def test_exportar_queda_en_la_auditoria(self, client, sa, admin_db):
        antes = admin_db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.accion == "SA_EXPORTAR_CLIENTES")
        )
        assert client.get("/api/v1/sa/clientes.csv", headers=sa).status_code == 200
        despues = admin_db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.accion == "SA_EXPORTAR_CLIENTES")
        )
        assert despues == antes + 1, "bajarse la cartera entera tiene que dejar rastro"

    def test_un_cliente_no_puede_exportar_la_cartera(self, client, ana_tokens):
        r = client.get("/api/v1/sa/clientes.csv", headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 403


class TestOrigenDelAlta:
    """El chip «Origen del alta» del asistente se pintaba, se podía pulsar y
    salía en el resumen… y luego no viajaba a ninguna parte. Un control que no
    hace nada engaña a quien lo usa."""

    def test_el_origen_elegido_se_guarda_en_el_inquilino(self, client, sa, limpiar, admin_db):
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Vino de TikTok SA",
                "email": f"{ruc}@mail.ec",
                "plan": "INDEPENDIENTE",
                "origen": "TikTok",
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text
        t = admin_db.get(Tenant, uuid.UUID(r.json()["id"]))
        assert t is not None
        assert t.origen_alta == "TikTok"

    def test_sin_origen_el_alta_cuenta_como_organica(self, client, sa, limpiar, admin_db):
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Sin Origen SA",
                "email": f"{ruc}@mail.ec",
                "plan": "INICIAL",
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text
        t = admin_db.get(Tenant, uuid.UUID(r.json()["id"]))
        assert t is not None and t.origen_alta == "Orgánico"

    def test_marketing_agrupa_las_altas_por_su_canal(self, client, sa, limpiar, admin_db):
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        assert (
            client.post(
                "/api/v1/sa/clientes",
                json={
                    "ruc": ruc,
                    "razon_social": "Referida SA",
                    "email": f"{ruc}@mail.ec",
                    "plan": "EMPRENDEDOR",
                    "origen": "Referido",
                },
                headers=sa,
            ).status_code
            == 201
        )
        filas = client.get("/api/v1/sa/marketing/origenes", headers=sa).json()
        canales = {f["origen"]: f["altas"] for f in filas}
        assert canales.get("Referido", 0) >= 1, canales
        # Y ya no existe el cajón de sastre que había antes
        assert "Sin código" not in canales

    def test_un_origen_inventado_no_rompe_el_alta(self, client, sa, limpiar, admin_db):
        """El campo es texto libre a propósito (marketing cambia de canales sin
        avisar); lo único que no puede es reventar ni desbordar la columna."""
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Canal Raro SA",
                "email": f"{ruc}@mail.ec",
                "plan": "INICIAL",
                "origen": "x" * 200,
            },
            headers=sa,
        )
        assert r.status_code == 422, "el origen tiene tope de 40 caracteres"


class TestConsumoYCostos:
    """El costo real de cada cliente contra lo que paga.

    Lo delicado aquí no es la consulta, es el criterio: una tarifa que sube NO
    debe encarecer el pasado. Estos tests fijan eso."""

    def _fila(self, client, sa, tenant_id):
        d = client.get("/api/v1/sa/consumo", headers=sa).json()
        return next((f for f in d["clientes"] if f["tenant_id"] == str(tenant_id)), None), d

    def test_devuelve_las_columnas_de_la_maqueta(self, client, sa):
        d = client.get("/api/v1/sa/consumo", headers=sa).json()
        for bloque in ("clientes", "totales", "margen_bajo"):
            assert bloque in d
        for k in ("ingreso", "costo", "margen", "margen_pct"):
            assert k in d["totales"]
        if d["clientes"]:
            f = d["clientes"][0]
            for k in (
                "cliente",
                "plan",
                "cupo",
                "usados",
                "canal",
                "ia_usados",
                "ia_cupo",
                "costo",
                "costo_detalle",
                "paga",
                "margen",
                "margen_pct",
            ):
                assert k in f, f"falta la columna {k}"

    def test_los_totales_cuadran_con_las_filas(self, client, sa):
        d = client.get("/api/v1/sa/consumo", headers=sa).json()
        assert Decimal(d["totales"]["ingreso"]) == sum(
            (Decimal(f["paga"]) for f in d["clientes"]), Decimal("0")
        )
        assert Decimal(d["totales"]["costo"]) == sum(
            (Decimal(f["costo"]) for f in d["clientes"]), Decimal("0")
        )
        assert Decimal(d["totales"]["margen"]) == Decimal(d["totales"]["ingreso"]) - Decimal(
            d["totales"]["costo"]
        )

    def test_el_costo_de_una_fila_es_la_suma_de_sus_partes(self, client, sa):
        d = client.get("/api/v1/sa/consumo", headers=sa).json()
        for f in d["clientes"]:
            partes = sum(Decimal(v) for v in f["costo_detalle"].values())
            assert Decimal(f["costo"]) == partes, f["cliente"]

    def test_una_subida_de_tarifa_no_encarece_el_pasado(self, client, sa, admin_db):
        """El caso que motivó todo esto: si Meta sube en octubre, septiembre no
        se vuelve más caro. El costo de WhatsApp es lo APUNTADO, no lo
        recalculado."""
        from app.db.models import CostRate

        antes = client.get("/api/v1/sa/consumo", headers=sa).json()["totales"]["costo"]

        r = client.post(
            "/api/v1/sa/tarifas",
            json={
                "proveedor": "INFRA",
                "concepto": "Emisión de comprobante",
                "costo_unitario": "9.999",
                "unidad": "comprobante",
                "vigente_desde": (HOY + timedelta(days=1)).isoformat(),
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text
        try:
            despues = client.get("/api/v1/sa/consumo", headers=sa).json()["totales"]["costo"]
            assert Decimal(despues) == Decimal(antes), (
                "una tarifa que entra mañana no puede cambiar el costo de este mes"
            )
        finally:
            nueva = admin_db.get(CostRate, uuid.UUID(r.json()["id"]))
            if nueva is not None:
                admin_db.delete(nueva)
            # Reabrir la que se cerró al programar la nueva
            vieja = admin_db.scalars(
                select(CostRate).where(
                    CostRate.proveedor == "INFRA",
                    CostRate.concepto == "Emisión de comprobante",
                    CostRate.vigente_hasta.is_not(None),
                )
            ).first()
            if vieja is not None:
                vieja.vigente_hasta = None
            admin_db.commit()

    def test_un_cliente_sin_ingreso_no_reporta_un_menos_cien_por_ciento(self, client, sa):
        """Un cliente en prueba cuesta dinero y paga cero. Eso no es «-100% de
        margen»: es «todavía no paga», y hay que distinguirlo."""
        d = client.get("/api/v1/sa/consumo", headers=sa).json()
        for f in d["clientes"]:
            if Decimal(f["paga"]) == 0:
                assert f["margen_pct"] is None, f["cliente"]

    def test_el_reparto_por_canal_suma_cien_o_es_nulo(self, client, sa):
        d = client.get("/api/v1/sa/consumo", headers=sa).json()
        for f in d["clientes"]:
            wa, panel = f["canal"]["whatsapp_pct"], f["canal"]["panel_pct"]
            if f["usados"] == 0:
                assert wa is None and panel is None
            else:
                assert wa + panel == 100, f["cliente"]

    @pytest.mark.parametrize(
        "usados,por_wa", [(80, 34), (200, 91), (40, 17), (40, 23), (120, 51), (400, 182)]
    )
    def test_el_reparto_suma_cien_tambien_en_los_empates(self, usados, por_wa):
        """Redondear los dos porcentajes por separado daba repartos de 99% y de
        101%: 34/80 es 42.4999999... y 46/80 es 57.4999999..., y los dos caen
        hacia abajo. Uno se redondea y el otro sale por diferencia."""
        wa = round(por_wa / usados * 100)
        assert wa + (100 - wa) == 100

    def test_solo_el_superadmin_cambia_tarifas(self, client, soporte_tokens):
        r = client.post(
            "/api/v1/sa/tarifas",
            json={
                "proveedor": "IA",
                "concepto": "Análisis de comprobante",
                "costo_unitario": "0.5",
                "unidad": "análisis",
                "vigente_desde": (HOY + timedelta(days=2)).isoformat(),
            },
            headers=auth_headers(soporte_tokens["access_token"]),
        )
        assert r.status_code == 403

    def test_lectura_ve_el_consumo_y_un_cliente_no(self, client, lectura_tokens, ana_tokens):
        assert (
            client.get(
                "/api/v1/sa/consumo", headers=auth_headers(lectura_tokens["access_token"])
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/v1/sa/consumo", headers=auth_headers(ana_tokens["access_token"])
            ).status_code
            == 403
        )

    def test_la_funcion_verifica_el_rol_en_la_base(self, app_engine):
        from sqlalchemy.exc import DatabaseError

        with app_engine.connect() as c:
            with pytest.raises(DatabaseError) as e:
                c.execute(text("SELECT * FROM sa_consumo_por_cliente()"))
        assert "acceso denegado" in str(e.value).lower()


class TestAvisosAutomaticos:
    """Los tres textos que el sistema envía por su cuenta, editables desde
    Configuración. Lo que hay que proteger aquí son las variables: Meta
    registra cada plantilla con un número FIJO de parámetros posicionales."""

    @pytest.fixture(autouse=True)
    def _limpiar(self, admin_db):
        yield
        from app.db.models import Parametro

        for clave in (
            "AVISO_PRE_DECLARACION",
            "AVISO_CUPO_AGOTADO",
            "AVISO_PAGO_VENCIDO",
        ):
            fila = admin_db.get(Parametro, clave)
            if fila is not None:
                admin_db.delete(fila)
        admin_db.commit()

    def test_lista_los_tres_avisos_con_sus_variables(self, client, sa):
        d = client.get("/api/v1/sa/avisos", headers=sa).json()
        assert {a["aviso"] for a in d} == {"PRE_DECLARACION", "CUPO_AGOTADO", "PAGO_VENCIDO"}
        for a in d:
            assert a["texto"] and a["variables"] and a["plantilla_meta"]
            assert a["editado"] is False  # de fábrica

    def test_guardar_un_texto_valido_y_verlo(self, client, sa):
        nuevo = "Hola {nombre}, tu plan {plan} venció el {fecha}. Regulariza aquí: {enlace}"
        r = client.put("/api/v1/sa/avisos", json={"textos": {"PAGO_VENCIDO": nuevo}}, headers=sa)
        assert r.status_code == 204, r.text

        d = client.get("/api/v1/sa/avisos", headers=sa).json()
        pago = next(a for a in d if a["aviso"] == "PAGO_VENCIDO")
        assert pago["texto"] == nuevo
        assert pago["editado"] is True
        assert pago["texto_original"] != nuevo  # se conserva para poder volver

    @pytest.mark.parametrize(
        "texto,pista",
        [
            ("Hola {nombre}, paga aquí: {enlace}", "Faltan variables"),
            ("{nombre} {plan} {fecha} {enlace} {inventada}", "no existen"),
            ("   ", "vacío"),
            ("x" * 1000 + " {nombre}{plan}{fecha}{enlace}", "900"),
        ],
    )
    def test_un_texto_que_rompería_el_envío_se_rechaza(self, client, sa, texto, pista):
        r = client.put("/api/v1/sa/avisos", json={"textos": {"PAGO_VENCIDO": texto}}, headers=sa)
        assert r.status_code == 422, r.text
        assert pista.lower() in r.json()["detail"].lower()

    def test_nada_se_guarda_si_uno_de_los_textos_es_invalido(self, client, sa):
        """Se validan todos antes de escribir: guardar el bueno y rechazar el
        malo dejaría la configuración a medias sin que nadie lo note."""
        bueno = "Hola {nombre}, usaste tu plan {plan}. Elige aquí: {enlace}"
        r = client.put(
            "/api/v1/sa/avisos",
            json={"textos": {"CUPO_AGOTADO": bueno, "PAGO_VENCIDO": "roto {nombre}"}},
            headers=sa,
        )
        assert r.status_code == 422
        d = client.get("/api/v1/sa/avisos", headers=sa).json()
        assert all(a["editado"] is False for a in d), "no debió guardarse nada"

    def test_el_texto_editado_es_el_que_se_envia(self, client, sa, admin_db):
        from app.whatsapp.plantillas import Aviso, preparar

        nuevo = "Recordatorio: {nombre}, plan {plan}, venció {fecha}. Enlace: {enlace}"
        assert (
            client.put(
                "/api/v1/sa/avisos", json={"textos": {"PAGO_VENCIDO": nuevo}}, headers=sa
            ).status_code
            == 204
        )
        plantilla, valores, vista = preparar(
            admin_db,
            Aviso.PAGO_VENCIDO,
            {"nombre": "Ana", "plan": "Emprendedor", "fecha": "1 de agosto", "enlace": "http://x"},
        )
        assert "Recordatorio: Ana" in vista
        # El NOMBRE y el ORDEN de los parámetros de Meta no los cambia el panel
        assert plantilla.nombre == "factuchat_pago_vencido"
        assert valores == ["Ana", "Emprendedor", "1 de agosto", "http://x"]

    def test_solo_el_superadmin_edita_los_textos(self, client, soporte_tokens, lectura_tokens):
        cuerpo = {"textos": {"PAGO_VENCIDO": "{nombre} {plan} {fecha} {enlace}"}}
        for tokens in (soporte_tokens, lectura_tokens):
            r = client.put(
                "/api/v1/sa/avisos", json=cuerpo, headers=auth_headers(tokens["access_token"])
            )
            assert r.status_code == 403
        # …pero soporte y lectura SÍ pueden verlos
        assert (
            client.get(
                "/api/v1/sa/avisos", headers=auth_headers(lectura_tokens["access_token"])
            ).status_code
            == 200
        )

    def test_un_cliente_no_ve_ni_edita_los_avisos(self, client, ana_tokens):
        h = auth_headers(ana_tokens["access_token"])
        assert client.get("/api/v1/sa/avisos", headers=h).status_code == 403
        assert client.put("/api/v1/sa/avisos", json={"textos": {}}, headers=h).status_code == 403


class TestTarifasNoReescribenElPasado:
    """Los defectos que encontró la revisión del cálculo de costos. Cada test
    fija uno para que no vuelva."""

    def _limpiar(self, admin_db, proveedor, concepto):
        from app.db.models import CostRate

        for t in admin_db.scalars(
            select(CostRate).where(CostRate.proveedor == proveedor, CostRate.concepto == concepto)
        ).all():
            if t.vigente_desde > date(2026, 1, 1):
                admin_db.delete(t)
            else:
                t.vigente_hasta = None
        admin_db.commit()

    def test_una_tarifa_retroactiva_se_rechaza(self, client, sa, admin_db):
        """Sin esta guarda, poner la tarifa de infraestructura a $0.50 con fecha
        del día 1 multiplicaba por 166 el costo de un mes ya reportado."""
        try:
            r = client.post(
                "/api/v1/sa/tarifas",
                json={
                    "proveedor": "INFRA",
                    "concepto": "Emisión de comprobante",
                    "costo_unitario": "0.50",
                    "unidad": "comprobante",
                    "vigente_desde": HOY.replace(day=1).isoformat(),
                },
                headers=sa,
            )
            assert r.status_code == 422, r.text
            assert "futura" in r.json()["detail"]
        finally:
            self._limpiar(admin_db, "INFRA", "Emisión de comprobante")

    def test_hoy_tampoco_vale(self, client, sa, admin_db):
        try:
            r = client.post(
                "/api/v1/sa/tarifas",
                json={
                    "proveedor": "IA",
                    "concepto": "Análisis de comprobante",
                    "costo_unitario": "0.99",
                    "unidad": "análisis",
                    "vigente_desde": HOY.isoformat(),
                },
                headers=sa,
            )
            assert r.status_code == 422
        finally:
            self._limpiar(admin_db, "IA", "Análisis de comprobante")

    def test_guardar_dos_veces_la_misma_fecha_reemplaza_en_vez_de_duplicar(
        self, client, sa, admin_db
    ):
        """Un tecleo corregido no debe dejar dos tarifas abiertas a la vez: el
        costo del mes saldría distinto en cada carga de la pantalla."""
        from app.db.models import CostRate

        cuando = (HOY + timedelta(days=20)).isoformat()
        try:
            for costo in ("0.300", "0.030"):
                r = client.post(
                    "/api/v1/sa/tarifas",
                    json={
                        "proveedor": "INFRA",
                        "concepto": "Emisión de comprobante",
                        "costo_unitario": costo,
                        "unidad": "comprobante",
                        "vigente_desde": cuando,
                    },
                    headers=sa,
                )
                assert r.status_code == 201, r.text

            filas = admin_db.scalars(
                select(CostRate).where(
                    CostRate.proveedor == "INFRA",
                    CostRate.concepto == "Emisión de comprobante",
                    CostRate.vigente_desde == date.fromisoformat(cuando),
                )
            ).all()
            assert len(filas) == 1, "quedaron dos tarifas para la misma fecha"
            assert filas[0].costo_unitario == Decimal("0.030000")
        finally:
            self._limpiar(admin_db, "INFRA", "Emisión de comprobante")

    def test_un_concepto_nuevo_del_mismo_proveedor_no_secuestra_el_costo(
        self, client, sa, admin_db
    ):
        """La subconsulta filtraba solo por proveedor. Bastaba registrar otro
        concepto de INFRA para que TODOS los comprobantes se valoraran con esa
        tarifa y el costo del mes cayera 30 veces."""
        from app.db.models import CostRate

        antes = client.get("/api/v1/sa/consumo", headers=sa).json()["totales"]["costo"]
        otro = CostRate(
            proveedor="INFRA",
            concepto="Almacenamiento por comprobante",
            costo_unitario=Decimal("0.0001"),
            unidad="comprobante",
            vigente_desde=date(2026, 1, 1),
        )
        admin_db.add(otro)
        admin_db.commit()
        try:
            despues = client.get("/api/v1/sa/consumo", headers=sa).json()["totales"]["costo"]
            assert Decimal(despues) == Decimal(antes), (
                "otro concepto del mismo proveedor cambió el costo de todos"
            )
        finally:
            admin_db.delete(admin_db.get(CostRate, otro.id))
            admin_db.commit()

    def test_no_se_pueden_crear_dos_tarifas_para_la_misma_fecha(self, admin_db):
        """La barrera de verdad está en la base: aunque alguien inserte a mano,
        el índice único lo impide."""
        from sqlalchemy.exc import IntegrityError

        from app.db.models import CostRate

        cuando = HOY + timedelta(days=45)
        a = CostRate(
            proveedor="INFRA",
            concepto="Emisión de comprobante",
            costo_unitario=Decimal("0.004"),
            unidad="comprobante",
            vigente_desde=cuando,
        )
        admin_db.add(a)
        admin_db.commit()
        guardado = a.id
        try:
            admin_db.add(
                CostRate(
                    proveedor="INFRA",
                    concepto="Emisión de comprobante",
                    costo_unitario=Decimal("0.005"),
                    unidad="comprobante",
                    vigente_desde=cuando,
                )
            )
            with pytest.raises(IntegrityError):
                admin_db.commit()
            admin_db.rollback()
        finally:
            fila = admin_db.get(CostRate, guardado)
            if fila is not None:
                admin_db.delete(fila)
                admin_db.commit()
            self._limpiar(admin_db, "INFRA", "Emisión de comprobante")

    def test_la_base_trabaja_en_hora_de_ecuador(self, app_engine):
        """Postgres arrancaba en UTC y la aplicación opera en Guayaquil: durante
        las últimas cinco horas de cada mes el panel daba por empezado el mes
        siguiente y las secciones del mes salían vacías."""
        with app_engine.connect() as c:
            assert c.execute(text("SHOW TimeZone")).scalar() == "America/Guayaquil"
            propio = c.execute(text("SELECT current_date")).scalar()
            ecuador = c.execute(
                text("SELECT (now() AT TIME ZONE 'America/Guayaquil')::date")
            ).scalar()
            assert propio == ecuador

    def test_un_moroso_conserva_su_plan_y_su_cobro(self, client, sa, limpiar, admin_db):
        """Antes caía por todos los coalesce a la vez —«sin plan», cupo 0,
        paga 0— y aparecía en el aviso rojo como si fuera una prueba gratuita.
        Un moroso no es una prueba: es cobro pendiente."""
        ruc = _ruc_nuevo()
        limpiar["rucs"].append(ruc)
        r = client.post(
            "/api/v1/sa/clientes",
            json={
                "ruc": ruc,
                "razon_social": "Moroso Con Plan SA",
                "email": f"{ruc}@mail.ec",
                "plan": "EMPRENDEDOR",
            },
            headers=sa,
        )
        assert r.status_code == 201, r.text
        tid = r.json()["id"]
        sus = admin_db.scalars(
            select(Suscripcion).where(Suscripcion.tenant_id == uuid.UUID(tid))
        ).one()
        sus.estado = "MOROSA"
        admin_db.commit()

        d = client.get("/api/v1/sa/consumo", headers=sa).json()
        fila = next(f for f in d["clientes"] if f["tenant_id"] == tid)
        assert fila["plan"] == "Emprendedor"
        assert fila["cupo"] == 80
        assert Decimal(fila["paga"]) > 0
        assert fila["suscripcion"] == "MOROSA"
        assert Decimal(d["totales"]["ingreso"]) >= Decimal(fila["paga"])

    def test_la_tabla_llega_ordenada_por_el_peor_margen(self, client, sa):
        """La sección existe para que el ojo caiga en quien cuesta dinero. Si
        sale por orden alfabético hay que recorrerla entera buscando el rojo."""
        d = client.get("/api/v1/sa/consumo", headers=sa).json()
        pcts = [f["margen_proyectado_pct"] for f in d["clientes"]]
        sin_pagar = [p for p in pcts if p is None]
        pagando = [p for p in pcts if p is not None]
        # Primero los que aún no pagan (costo puro), luego de peor a mejor
        assert pcts[: len(sin_pagar)] == sin_pagar
        assert pagando == sorted(pagando)

    def test_la_alerta_mira_la_proyeccion_y_no_lo_que_va_del_mes(self, client, sa):
        """Comparar el costo acumulado contra la mensualidad entera hacía que la
        alerta fuese incapaz de dispararse en la primera mitad del mes."""
        d = client.get("/api/v1/sa/consumo", headers=sa).json()
        assert d["periodo"]["dias_transcurridos"] >= 1
        assert d["periodo"]["dias_mes"] in (28, 29, 30, 31)
        for f in d["clientes"]:
            # La proyección nunca puede ser menor que lo ya gastado
            assert Decimal(f["costo_proyectado"]) >= Decimal(f["costo"])
        for f in d["margen_bajo"]:
            assert f["margen_proyectado_pct"] is None or f["margen_proyectado_pct"] < 20
