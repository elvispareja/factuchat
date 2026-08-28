"""Aritmética fiscal (fase 2): el SRI recalcula base×tarifa y rechaza el
comprobante si no cuadra al centavo, así que el redondeo importa."""

from decimal import Decimal

import pytest

from app.services.emision import EmisionError, calcular_items


def _item(cantidad, precio, iva="4", descuento="0", codigo="X"):
    return {
        "codigo": codigo,
        "descripcion": "Item",
        "cantidad": cantidad,
        "precio_unitario": precio,
        "descuento": descuento,
        "codigo_iva": iva,
    }


class TestRedondeo:
    def test_grupo_cuadra_con_base_agrupada(self):
        """Tres ítems cuyo IVA individual redondea hacia arriba: sumar los
        redondeos daría 0.15, pero el SRI calcula 0.99 × 15% = 0.15 (0.1485).
        El valor del grupo DEBE salir de la base agrupada."""
        items, tot = calcular_items([_item("1", "0.33") for _ in range(3)])
        grupo = tot["impuestos"][0]
        esperado = (Decimal(grupo["base"]) * Decimal("15") / Decimal("100")).quantize(
            Decimal("0.01")
        )
        assert Decimal(grupo["valor"]) == esperado
        assert tot["importe_total"] == tot["total_sin_impuestos"] + Decimal(grupo["valor"])

    @pytest.mark.parametrize(
        "cantidad,precio",
        [("1", "0.01"), ("3", "0.33"), ("7", "1.07"), ("11", "9.99"), ("2", "0.05")],
    )
    def test_totales_consistentes(self, cantidad, precio):
        _items, tot = calcular_items([_item(cantidad, precio)])
        suma_grupos = sum(Decimal(g["valor"]) for g in tot["impuestos"])
        assert tot["total_iva"] == suma_grupos
        assert tot["importe_total"] == tot["total_sin_impuestos"] + suma_grupos
        for g in tot["impuestos"]:
            tarifa = Decimal(g["tarifa"])
            assert Decimal(g["valor"]) == (Decimal(g["base"]) * tarifa / 100).quantize(
                Decimal("0.01")
            )


class TestVariasTarifas:
    def test_agrupacion_por_tarifa(self):
        items, tot = calcular_items(
            [
                _item("3", "10.00", iva="4", codigo="A"),  # 30.00 al 15%
                _item("2", "5.50", iva="0", codigo="B"),  # 11.00 al 0%
                _item("1", "20.00", iva="4", descuento="5.00", codigo="C"),  # 15.00 al 15%
            ]
        )
        assert len(items) == 3
        assert tot["total_sin_impuestos"] == Decimal("56.00")
        assert tot["total_descuento"] == Decimal("5.00")

        por_codigo = {g["codigo_porcentaje"]: g for g in tot["impuestos"]}
        assert por_codigo["4"]["base"] == Decimal("45.00")
        assert por_codigo["4"]["valor"] == Decimal("6.75")
        assert por_codigo["0"]["base"] == Decimal("11.00")
        assert por_codigo["0"]["valor"] == Decimal("0.00")
        assert tot["importe_total"] == Decimal("62.75")

    def test_descuento_mayor_al_subtotal_rechazado(self):
        with pytest.raises(EmisionError):
            calcular_items([_item("1", "10.00", descuento="20.00")])

    def test_codigo_iva_desconocido_rechazado(self):
        with pytest.raises(EmisionError):
            calcular_items([_item("1", "10.00", iva="99")])
