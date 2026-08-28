"""Checklist F3: los números del resumen fiscal salen de comprobantes
AUTORIZADOS reales — nunca de borradores, rechazados ni en proceso."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import Comprobante
from app.db.models.enums import AmbienteSRI, EstadoComprobante, TipoComprobante
from app.services.reportes import noveno_digito, proxima_declaracion
from tests.conftest import TENANT_A, auth_headers

# Un mes CERRADO y ajeno al mes en curso: los comprobantes que crean otros
# tests llevan la fecha de hoy y contaminarían el período medido.
HOY = date(2026, 3, 15)


@pytest.fixture()
def comprobantes_del_mes(admin_db):
    """Siembra un mes con documentos en varios estados y tipos."""
    creados = []

    def _add(tipo, estado, subtotal, iva, total, clave):
        c = Comprobante(
            tenant_id=TENANT_A,
            tipo=tipo,
            estado=estado,
            ambiente=AmbienteSRI.PRUEBAS,
            fecha_emision=HOY,
            subtotal=Decimal(subtotal),
            iva=Decimal(iva),
            total=Decimal(total),
            payload={},
            clave_acceso=clave,
        )
        admin_db.add(c)
        creados.append(c)

    # Cuentan: dos facturas autorizadas
    _add(
        TipoComprobante.FACTURA,
        EstadoComprobante.AUTORIZADO,
        "100.00",
        "15.00",
        "115.00",
        "rep1" + "0" * 45,
    )
    _add(
        TipoComprobante.FACTURA,
        EstadoComprobante.AUTORIZADO,
        "200.00",
        "30.00",
        "230.00",
        "rep2" + "0" * 45,
    )
    # Resta: una nota de crédito autorizada
    _add(
        TipoComprobante.NOTA_CREDITO,
        EstadoComprobante.AUTORIZADO,
        "50.00",
        "7.50",
        "57.50",
        "rep3" + "0" * 45,
    )
    # NO cuentan: borrador, en proceso, rechazado, devuelto
    _add(
        TipoComprobante.FACTURA,
        EstadoComprobante.PENDIENTE,
        "999.00",
        "149.85",
        "1148.85",
        "rep4" + "0" * 45,
    )
    _add(
        TipoComprobante.FACTURA,
        EstadoComprobante.ENVIADO_SRI,
        "888.00",
        "133.20",
        "1021.20",
        "rep5" + "0" * 45,
    )
    _add(
        TipoComprobante.FACTURA,
        EstadoComprobante.RECHAZADO,
        "777.00",
        "116.55",
        "893.55",
        "rep6" + "0" * 45,
    )
    _add(
        TipoComprobante.FACTURA,
        EstadoComprobante.DEVUELTO,
        "666.00",
        "99.90",
        "765.90",
        "rep7" + "0" * 45,
    )
    admin_db.commit()

    yield

    for c in admin_db.scalars(
        select(Comprobante).where(Comprobante.clave_acceso.like("rep%"))
    ).all():
        admin_db.delete(c)
    admin_db.commit()


class TestResumenFiscal:
    def test_solo_cuenta_autorizados(self, client, ana_tokens, comprobantes_del_mes):
        r = client.get(
            "/api/v1/reportes/resumen?desde=2026-03-01&hasta=2026-04-01",
            headers=auth_headers(ana_tokens["access_token"]),
        )
        assert r.status_code == 200, r.text
        d = r.json()
        # 100 + 200 de facturas autorizadas; los 999/888/777/666 quedan fuera
        assert Decimal(d["ventas_sin_iva"]) == Decimal("300.00")
        assert Decimal(d["iva_cobrado"]) == Decimal("45.00")
        assert Decimal(d["notas_credito"]) == Decimal("57.50")
        # Total facturado = ventas − notas de crédito
        assert Decimal(d["total_facturado"]) == Decimal("287.50")
        # 3 autorizados (2 facturas + 1 nota de crédito)
        assert d["comprobantes_emitidos"] == 3

    def test_a_pagar_descuenta_notas_y_retenciones(self, client, ana_tokens, comprobantes_del_mes):
        r = client.get(
            "/api/v1/reportes/resumen?desde=2026-03-01&hasta=2026-04-01",
            headers=auth_headers(ana_tokens["access_token"]),
        )
        d = r.json()
        # IVA neto = 45.00 cobrado − 7.50 de la nota de crédito
        assert Decimal(d["a_pagar"]) == Decimal("37.50")

    def test_periodo_sin_movimiento_da_ceros(self, client, ana_tokens, comprobantes_del_mes):
        r = client.get(
            "/api/v1/reportes/resumen?desde=2020-01-01&hasta=2020-02-01",
            headers=auth_headers(ana_tokens["access_token"]),
        )
        d = r.json()
        assert Decimal(d["total_facturado"]) == Decimal("0")
        assert Decimal(d["a_pagar"]) == Decimal("0")
        assert d["comprobantes_emitidos"] == 0

    def test_otro_tenant_no_ve_estas_cifras(self, client, bob_tokens, comprobantes_del_mes):
        r = client.get(
            "/api/v1/reportes/resumen?desde=2026-03-01&hasta=2026-04-01",
            headers=auth_headers(bob_tokens["access_token"]),
        )
        assert r.status_code == 200
        assert Decimal(r.json()["total_facturado"]) == Decimal("0")


class TestProximaDeclaracion:
    def test_noveno_digito_del_ruc(self):
        # RUC del tenant A: 1 7 9 0 0 1 2 3 [4] 5 0 0 1 → noveno dígito = '4'
        assert noveno_digito("1790012345001") == "4"

    @pytest.mark.parametrize(
        "digito,dia",
        [
            ("1", 10),
            ("2", 12),
            ("3", 14),
            ("4", 16),
            ("5", 18),
            ("6", 20),
            ("7", 22),
            ("8", 24),
            ("9", 26),
            ("0", 28),
        ],
    )
    def test_calendario_del_sri(self, digito, dia):
        ruc = f"17900123{digito}5001"
        assert proxima_declaracion(ruc, date(2026, 8, 1))["dia_maximo"] == dia

    def test_pasada_la_fecha_apunta_al_mes_siguiente(self):
        # Noveno dígito 1 → declara hasta el 10; el 15 de agosto ya pasó
        d = proxima_declaracion("179001231" + "5001", date(2026, 8, 15))
        assert d["noveno_digito"] == "1"
        assert d["dia_maximo"] == 10
        assert date.fromisoformat(d["fecha_limite"]) == date(2026, 9, 10)

    def test_antes_de_la_fecha_apunta_a_este_mes(self):
        d = proxima_declaracion("179001231" + "5001", date(2026, 8, 3))
        assert date.fromisoformat(d["fecha_limite"]) == date(2026, 8, 10)

    def test_inicio_expone_la_declaracion(self, client, ana_tokens, comprobantes_del_mes):
        r = client.get("/api/v1/inicio", headers=auth_headers(ana_tokens["access_token"]))
        assert r.status_code == 200, r.text
        d = r.json()
        # Tenant A: RUC 1790012345001 → noveno dígito 4 → declara hasta el 16
        assert d["proxima_declaracion"]["noveno_digito"] == "4"
        assert d["proxima_declaracion"]["dia_maximo"] == 16
        assert "ranking" in d and "ventas_por_dia" in d
