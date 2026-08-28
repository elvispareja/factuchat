"""Checklist F3: un cliente Inicial ve los bloqueos correctos; uno Emprendedor
ve todo; y las cifras del resumen fiscal salen de comprobantes autorizados reales.

El gating se prueba en el SERVIDOR: aunque el panel pintara un botón, la API
tiene que negarse igual (OWASP A06).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import Plan, Suscripcion
from app.db.models.enums import EstadoSuscripcion
from app.services.planes import LIMITES_POR_PLAN
from tests.conftest import TENANT_A, auth_headers


@pytest.fixture()
def suscribir(admin_db):
    """Deja al tenant A en el plan indicado. Devuelve una función."""
    creados: list[uuid.UUID] = []

    def _suscribir(nombre: str):
        limites = LIMITES_POR_PLAN[nombre]
        plan = admin_db.scalars(select(Plan).where(Plan.codigo == nombre.upper())).first()
        if plan is None:
            plan = Plan(
                codigo=nombre.upper(),
                nombre=nombre,
                precio_mensual=limites["precio"],
                vigente_desde=date(2026, 1, 1),
            )
            admin_db.add(plan)
        # Los límites se reescriben siempre: un plan con límites obsoletos
        # concedería funciones que no corresponden.
        plan.limites = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in limites.items()}
        plan.precio_mensual = limites["precio"]
        admin_db.flush()
        # Una sola suscripción vigente por tenant en la prueba
        for vieja in admin_db.scalars(
            select(Suscripcion).where(Suscripcion.tenant_id == TENANT_A)
        ).all():
            admin_db.delete(vieja)
        admin_db.flush()
        sus = Suscripcion(
            tenant_id=TENANT_A,
            plan_id=plan.id,
            estado=EstadoSuscripcion.ACTIVA,
            precio=limites["precio"],
            inicia=date(2026, 1, 1),
        )
        admin_db.add(sus)
        admin_db.commit()
        creados.append(sus.id)

    yield _suscribir

    for sus_id in creados:
        obj = admin_db.get(Suscripcion, sus_id)
        if obj is not None:
            admin_db.delete(obj)
    admin_db.commit()


def _estado(client, tokens):
    r = client.get("/api/v1/panel/estado", headers=auth_headers(tokens["access_token"]))
    assert r.status_code == 200, r.text
    return r.json()["plan"]


class TestEstadoDelPlan:
    def test_inicial_ve_los_bloqueos(self, client, ana_tokens, suscribir):
        suscribir("Inicial")
        plan = _estado(client, ana_tokens)
        assert plan["nombre"] == "Inicial"
        assert plan["cupo"] == 10
        # Inicial no trae NINGUNA de las funciones de pago
        assert plan["funciones"] == {
            "stock": False,
            "tienda": False,
            "voz": False,
            "masivo": False,
            "archivos": False,
        }
        assert plan["clientes"]["tope"] == 20
        assert plan["productos"]["tope"] == 10
        assert plan["analisis_ia"] == 0
        assert plan["numeros_whatsapp"] == 1
        assert plan["acumula"] is False
        assert plan["nota_cupo"] == "Son del mes en curso."
        # Y el panel sabe a qué plan invitar en cada caso
        assert plan["planes_para_desbloquear"]["archivos"] == "Independiente"
        assert plan["planes_para_desbloquear"]["stock"] == "Emprendedor"
        assert plan["planes_para_desbloquear"]["tienda"] == "Empresario"

    def test_empresario_ve_todo(self, client, ana_tokens, suscribir):
        suscribir("Empresario")
        plan = _estado(client, ana_tokens)
        assert plan["nombre"] == "Empresario"
        assert plan["cupo"] == 250
        assert plan["analisis_ia"] == 100
        assert all(plan["funciones"].values())
        # 0 = sin límite
        assert plan["clientes"]["tope"] == 0
        assert plan["productos"]["tope"] == 0
        assert plan["numeros_whatsapp"] == 2
        assert plan["acumula"] is True
        assert plan["nota_cupo"] == "Lo que no uses pasa al mes siguiente."

    @pytest.mark.parametrize(
        "plan,stock,tienda,archivos",
        [
            ("Inicial", False, False, False),
            ("Independiente", False, False, True),
            ("Emprendedor", True, False, True),
            ("Empresario", True, True, True),
        ],
    )
    def test_matriz_completa(self, client, ana_tokens, suscribir, plan, stock, tienda, archivos):
        suscribir(plan)
        funciones = _estado(client, ana_tokens)["funciones"]
        assert funciones["stock"] is stock
        assert funciones["tienda"] is tienda
        assert funciones["archivos"] is archivos

    def test_sin_suscripcion_no_concede_nada(self, client, ana_tokens, admin_db):
        """Deny by default: la ausencia de datos nunca desbloquea funciones."""
        for vieja in admin_db.scalars(
            select(Suscripcion).where(Suscripcion.tenant_id == TENANT_A)
        ).all():
            admin_db.delete(vieja)
        admin_db.commit()
        plan = _estado(client, ana_tokens)
        assert plan["nombre"] == "Inicial"
        assert not any(plan["funciones"].values())


class TestGatingEnServidor:
    def test_inventario_no_se_guarda_sin_el_plan(self, client, ana_tokens, suscribir):
        """Aunque el cliente mande stock, un plan sin la función lo ignora."""
        suscribir("Independiente")
        r = client.post(
            "/api/v1/productos",
            json={
                "codigo": f"P{uuid.uuid4().hex[:6]}",
                "nombre": "Producto con stock",
                "tipo": "BIEN",
                "precio_sin_iva": "10.00",
                "codigo_iva": "4",
                "maneja_inventario": True,
                "stock": "50",
                "stock_minimo": "5",
            },
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 201, r.text
        creado = r.json()
        assert creado["maneja_inventario"] is False
        assert Decimal(creado["stock"]) == Decimal("0")

    def test_inventario_si_se_guarda_con_el_plan(self, client, ana_tokens, suscribir):
        suscribir("Emprendedor")
        r = client.post(
            "/api/v1/productos",
            json={
                "codigo": f"P{uuid.uuid4().hex[:6]}",
                "nombre": "Producto con stock",
                "tipo": "BIEN",
                "precio_sin_iva": "10.00",
                "codigo_iva": "4",
                "maneja_inventario": True,
                "stock": "50",
                "stock_minimo": "5",
            },
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 201, r.text
        creado = r.json()
        assert creado["maneja_inventario"] is True
        assert Decimal(creado["stock"]) == Decimal("50")

    def test_tienda_bloqueada_al_publicar_producto(self, client, ana_tokens, suscribir):
        suscribir("Emprendedor")  # tiene stock, NO tiene tienda
        r = client.post(
            "/api/v1/productos",
            json={
                "codigo": f"P{uuid.uuid4().hex[:6]}",
                "nombre": "Producto de vitrina",
                "tipo": "BIEN",
                "precio_sin_iva": "10.00",
                "codigo_iva": "4",
                "mostrar_en_tienda": True,
            },
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 402
        detalle = r.json()["detail"]
        assert detalle["plan_sugerido"] == "Empresario"
        assert "Empresario" in detalle["mensaje"]

    def test_carga_masiva_bloqueada_sin_el_plan(self, client, ana_tokens, suscribir):
        suscribir("Emprendedor")  # masivo solo lo trae Empresario
        r = client.post(
            "/api/v1/clientes/carga-masiva/analizar",
            files={"archivo": ("clientes.csv", b"identificacion,razon social\n", "text/csv")},
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 402
        assert r.json()["detail"]["plan_sugerido"] == "Empresario"

    def test_tope_de_clientes_corta_el_alta(self, client, ana_tokens, suscribir, admin_db):
        """El tope bloquea GUARDAR nuevos, no facturar a los que ya están."""
        suscribir("Inicial")  # tope de 20
        from app.db.models import ClienteFinal

        existentes = admin_db.scalars(
            select(ClienteFinal).where(ClienteFinal.tenant_id == TENANT_A)
        ).all()
        faltan = max(0, 20 - len(existentes))
        for i in range(faltan):
            admin_db.add(
                ClienteFinal(
                    tenant_id=TENANT_A,
                    tipo_identificacion="CEDULA",
                    identificacion=f"09{i:08d}",
                    razon_social=f"Relleno {i}",
                )
            )
        admin_db.commit()
        try:
            r = client.post(
                "/api/v1/clientes",
                json={
                    "tipo_identificacion": "CEDULA",
                    "identificacion": "1712345999",
                    "razon_social": "Uno más",
                },
                headers=auth_headers(ana_tokens["access_token"]),
            )
            assert r.status_code == 402
            assert "límite de tu plan" in r.json()["detail"]["mensaje"]
        finally:
            # El relleno no puede sobrevivir al test: dejaría a otros tests
            # contra el tope y fallarían por una causa ajena.
            for c in admin_db.scalars(
                select(ClienteFinal).where(ClienteFinal.razon_social.like("Relleno %"))
            ).all():
                admin_db.delete(c)
            admin_db.commit()

    def test_cupo_de_comprobantes_corta_la_emision(self, client, ana_tokens, suscribir, admin_db):
        suscribir("Inicial")  # 10 comprobantes al mes
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app.db.models import Comprobante
        from app.db.models.enums import AmbienteSRI, EstadoComprobante, TipoComprobante

        hoy = datetime.now(ZoneInfo("America/Guayaquil")).date()
        for i in range(10):
            admin_db.add(
                Comprobante(
                    tenant_id=TENANT_A,
                    tipo=TipoComprobante.FACTURA,
                    estado=EstadoComprobante.AUTORIZADO,
                    ambiente=AmbienteSRI.PRUEBAS,
                    fecha_emision=hoy,
                    subtotal=Decimal("1"),
                    iva=Decimal("0.15"),
                    total=Decimal("1.15"),
                    payload={},
                    clave_acceso=f"cupo{i:045d}",
                )
            )
        admin_db.commit()

        r = client.post(
            "/api/v1/comprobantes/facturas",
            json={
                "items": [
                    {
                        "codigo": "X",
                        "descripcion": "Uno más",
                        "cantidad": "1",
                        "precio_unitario": "1.00",
                        "codigo_iva": "4",
                    }
                ],
                "forma_pago": "01",
            },
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 402
        assert "10 comprobantes de tu plan" in r.json()["detail"]["mensaje"]

        # Limpieza para no contaminar otras pruebas
        for c in admin_db.scalars(
            select(Comprobante).where(Comprobante.clave_acceso.like("cupo%"))
        ).all():
            admin_db.delete(c)
        admin_db.commit()
