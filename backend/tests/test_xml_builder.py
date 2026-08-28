"""Estructura del XML v2.31 para los 6 comprobantes (fase 2.1)."""

from datetime import date
from decimal import Decimal

from lxml import etree

from app.sri import xml_builder as xb

EMISOR = {
    "ruc": "1790012345001",
    "razon_social": "Empresa A S.A.S.",
    "nombre_comercial": "Empresa A",
    "dir_matriz": "Av. Amazonas N23-45, Quito",
    "obligado_contabilidad": False,
    "ambiente": "1",
}

CLAVE = "2408202601179001234500110010010000001231234567811"

BASE_DOC = {
    "clave_acceso": CLAVE,
    "establecimiento": "001",
    "punto_emision": "001",
    "secuencial": 123,
    "fecha_emision": date(2026, 8, 24),
    "dir_establecimiento": "Av. Amazonas, Quito",
}

COMPRADOR = {
    "tipo_identificacion_codigo": "05",
    "razon_social": "Juana Pérez",
    "identificacion": "1712345678",
}

ITEM = {
    "codigo": "P001",
    "descripcion": "Producto de prueba",
    "cantidad": Decimal("2"),
    "precio_unitario": Decimal("10"),
    "descuento": Decimal("0"),
    "codigo_iva": "4",
    "tarifa_iva": Decimal("15"),
    "total_sin_impuesto": Decimal("20.00"),
    "valor_iva": Decimal("3.00"),
}

TOTALES = {
    "total_sin_impuestos": Decimal("20.00"),
    "total_descuento": Decimal("0"),
    "importe_total": Decimal("23.00"),
    "impuestos": [{"codigo_porcentaje": "4", "base": Decimal("20.00"), "valor": Decimal("3.00")}],
}


def _x(xml_bytes: bytes) -> etree._Element:
    return etree.fromstring(xml_bytes)


def _t(root: etree._Element, ruta: str) -> str:
    nodo = root.find(ruta)
    assert nodo is not None, f"Falta el elemento {ruta}"
    return nodo.text or ""


class TestFactura:
    def test_estructura_completa(self):
        root = _x(
            xb.construir_factura(
                EMISOR,
                {
                    **BASE_DOC,
                    "comprador": COMPRADOR,
                    "items": [ITEM],
                    "totales": TOTALES,
                    "pagos": [{"forma": "01", "total": Decimal("23.00")}],
                    "info_adicional": {"Email": "juana@mail.ec"},
                },
            )
        )
        assert root.tag == "factura"
        assert root.get("id") == "comprobante"
        assert root.get("version") == "1.1.0"
        assert _t(root, "infoTributaria/claveAcceso") == CLAVE
        assert _t(root, "infoTributaria/codDoc") == "01"
        assert _t(root, "infoTributaria/secuencial") == "000000123"
        assert _t(root, "infoFactura/fechaEmision") == "24/08/2026"
        assert _t(root, "infoFactura/tipoIdentificacionComprador") == "05"
        assert _t(root, "infoFactura/totalSinImpuestos") == "20.00"
        assert _t(root, "infoFactura/importeTotal") == "23.00"
        assert _t(root, "infoFactura/totalConImpuestos/totalImpuesto/codigoPorcentaje") == "4"
        assert _t(root, "infoFactura/totalConImpuestos/totalImpuesto/valor") == "3.00"
        assert _t(root, "infoFactura/pagos/pago/formaPago") == "01"
        assert _t(root, "detalles/detalle/cantidad") == "2.000000"
        assert _t(root, "detalles/detalle/impuestos/impuesto/tarifa") == "15.00"
        campo = root.find("infoAdicional/campoAdicional")
        assert campo.get("nombre") == "Email"
        assert campo.text == "juana@mail.ec"

    def test_consumidor_final(self):
        root = _x(
            xb.construir_factura(
                EMISOR,
                {
                    **BASE_DOC,
                    "comprador": {
                        "tipo_identificacion_codigo": "07",
                        "razon_social": "CONSUMIDOR FINAL",
                        "identificacion": "9999999999999",
                    },
                    "items": [ITEM],
                    "totales": TOTALES,
                    "pagos": [{"forma": "01", "total": Decimal("23.00")}],
                },
            )
        )
        assert _t(root, "infoFactura/identificacionComprador") == "9999999999999"


class TestOtrosComprobantes:
    def test_nota_credito(self):
        root = _x(
            xb.construir_nota_credito(
                EMISOR,
                {
                    **BASE_DOC,
                    "comprador": COMPRADOR,
                    "doc_modificado": {
                        "cod_doc": "01",
                        "numero": "001-001-000000100",
                        "fecha": date(2026, 8, 1),
                    },
                    "motivo": "Devolución de mercadería",
                    "items": [ITEM],
                    "totales": TOTALES,
                },
            )
        )
        assert root.tag == "notaCredito"
        assert _t(root, "infoTributaria/codDoc") == "04"
        assert _t(root, "infoNotaCredito/numDocModificado") == "001-001-000000100"
        assert _t(root, "infoNotaCredito/valorModificacion") == "23.00"
        assert _t(root, "infoNotaCredito/motivo") == "Devolución de mercadería"

    def test_nota_debito(self):
        root = _x(
            xb.construir_nota_debito(
                EMISOR,
                {
                    **BASE_DOC,
                    "comprador": COMPRADOR,
                    "doc_modificado": {
                        "cod_doc": "01",
                        "numero": "001-001-000000100",
                        "fecha": date(2026, 8, 1),
                    },
                    "totales": {
                        "total_sin_impuestos": Decimal("5.00"),
                        "importe_total": Decimal("5.75"),
                        "impuestos": [
                            {
                                "codigo_porcentaje": "4",
                                "base": Decimal("5.00"),
                                "valor": Decimal("0.75"),
                            }
                        ],
                    },
                    "motivos": [{"razon": "Interés por mora", "valor": Decimal("5.00")}],
                },
            )
        )
        assert root.tag == "notaDebito"
        assert _t(root, "infoTributaria/codDoc") == "05"
        assert _t(root, "motivos/motivo/razon") == "Interés por mora"
        assert _t(root, "infoNotaDebito/valorTotal") == "5.75"

    def test_guia_remision(self):
        root = _x(
            xb.construir_guia_remision(
                EMISOR,
                {
                    **BASE_DOC,
                    "dir_partida": "Bodega Norte, Quito",
                    "transportista": {
                        "razon_social": "Trans Andes",
                        "tipo_identificacion_codigo": "04",
                        "identificacion": "1791234567001",
                    },
                    "fecha_inicio": date(2026, 8, 24),
                    "fecha_fin": date(2026, 8, 25),
                    "placa": "PBA1234",
                    "destinatarios": [
                        {
                            "identificacion": "1712345678",
                            "razon_social": "Juana Pérez",
                            "direccion": "Calle Sur 1",
                            "motivo_traslado": "Venta",
                            "items": [
                                {
                                    "codigo": "P001",
                                    "descripcion": "Producto",
                                    "cantidad": Decimal("2"),
                                }
                            ],
                        }
                    ],
                },
            )
        )
        assert root.tag == "guiaRemision"
        assert _t(root, "infoTributaria/codDoc") == "06"
        assert _t(root, "infoGuiaRemision/placa") == "PBA1234"
        assert _t(root, "destinatarios/destinatario/motivoTraslado") == "Venta"

    def test_retencion(self):
        root = _x(
            xb.construir_retencion(
                EMISOR,
                {
                    **BASE_DOC,
                    "sujeto": {
                        "tipo_identificacion_codigo": "04",
                        "razon_social": "Proveedor SA",
                        "identificacion": "1791234567001",
                    },
                    "periodo_fiscal": "08/2026",
                    "docs_sustento": [
                        {
                            "cod_sustento": "01",
                            "cod_doc": "01",
                            "numero": "001-001-000000200",
                            "fecha": date(2026, 8, 10),
                            "total_sin_impuestos": Decimal("100.00"),
                            "importe_total": Decimal("115.00"),
                            "impuestos": [
                                {
                                    "codigo_porcentaje": "4",
                                    "base": Decimal("100.00"),
                                    "valor": Decimal("15.00"),
                                }
                            ],
                            "retenciones": [
                                {
                                    "codigo": "1",
                                    "codigo_retencion": "303",
                                    "base": Decimal("100.00"),
                                    "porcentaje": Decimal("10"),
                                    "valor": Decimal("10.00"),
                                }
                            ],
                        }
                    ],
                },
            )
        )
        assert root.tag == "comprobanteRetencion"
        assert root.get("version") == "2.0.0"
        assert _t(root, "infoTributaria/codDoc") == "07"
        assert _t(root, "infoCompRetencion/periodoFiscal") == "08/2026"
        assert _t(root, "docsSustento/docSustento/numDocSustento") == "001001000000200"
        assert _t(root, "docsSustento/docSustento/retenciones/retencion/valorRetenido") == "10.00"

    def test_liquidacion_compra(self):
        root = _x(
            xb.construir_liquidacion_compra(
                EMISOR,
                {
                    **BASE_DOC,
                    "proveedor": {
                        "tipo_identificacion_codigo": "05",
                        "razon_social": "Proveedor Informal",
                        "identificacion": "1712345678",
                        "direccion": "Calle 1",
                    },
                    "items": [ITEM],
                    "totales": TOTALES,
                    "pagos": [{"forma": "01", "total": Decimal("23.00")}],
                },
            )
        )
        assert root.tag == "liquidacionCompra"
        assert _t(root, "infoTributaria/codDoc") == "03"
        assert _t(root, "infoLiquidacionCompra/razonSocialProveedor") == "Proveedor Informal"
