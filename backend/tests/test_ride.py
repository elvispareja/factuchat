"""La tarjeta DATOS DEL COMPRADOR del RIDE, con dirección y sin ella.

Se renderiza el PDF de verdad, no solo el HTML: en este Windows WeasyPrint no
carga (falta GTK) y `render_ride_factura` cae al respaldo de xhtml2pdf, que es
justo el motor frágil —sin flexbox, ignora `table-layout: fixed`— donde una
dirección larga podría partir la tarjeta o desbordar el papel.
"""

from app.sri.ride import _env, render_ride_factura

CLAVE = "2408202601179001234500110010010000001231234567811"

CONTEXTO = {
    "emisor": {
        "ruc": "1790012345001",
        "razon_social": "Empresa A S.A.S.",
        "nombre_comercial": "Empresa A",
        "dir_matriz": "Av. Amazonas N23-45, Quito",
        "obligado_contabilidad": False,
    },
    "tipo_doc": "FACTURA",
    "doc_modificado": None,
    "motivo": None,
    "dir_establecimiento": "",
    "establecimiento": "001",
    "punto_emision": "001",
    "secuencial": 123,
    "ambiente": "PRUEBAS",
    "tipo_emision": "NORMAL",
    "clave_acceso": CLAVE,
    "numero_autorizacion": CLAVE,
    "fecha_autorizacion": "24/08/2026 10:15",
    "fecha_emision": "24/08/2026",
    "comprador": {
        "razon_social": "Juana Pérez",
        "identificacion": "1712345678",
        "email": "juana@mail.ec",
    },
    "items": [
        {
            "codigo": "P001",
            "descripcion": "Producto de prueba",
            "cantidad": "2",
            "precio_unitario": "10",
            "descuento": "0",
            "total_sin_impuesto": "20.00",
        }
    ],
    "totales": {
        "total_sin_impuestos": "20.00",
        "total_descuento": "0.00",
        "importe_total": "23.00",
        "impuestos": [{"tarifa": "15", "base": "20.00", "valor": "3.00"}],
    },
    "forma_pago": "Efectivo",
    "plazo_dias": None,
    "info_adicional": {},
}


def _con_direccion(direccion: str | None) -> dict:
    comprador = dict(CONTEXTO["comprador"])
    if direccion is not None:
        comprador["direccion"] = direccion
    return {**CONTEXTO, "comprador": comprador}


def _html(contexto: dict) -> str:
    return _env.get_template("ride_factura.html").render(**contexto, barcode_svg="")


class TestDireccionDelComprador:
    def test_con_direccion_sale_impresa(self):
        html = _html(_con_direccion("Av. 6 de Diciembre N34-12 y Colón, Quito"))
        assert "DIRECCIÓN</span>" in html
        assert "Av. 6 de Diciembre N34-12 y Colón, Quito" in html

    def test_sin_direccion_la_tarjeta_queda_como_estaba(self):
        html = _html(_con_direccion(None))
        # «DIRECCIÓN MATRIZ» es del emisor y sigue ahí; el rótulo suelto no.
        assert "DIRECCIÓN</span>" not in html
        assert "DIRECCIÓN MATRIZ" in html

    def test_el_pdf_se_genera_en_los_dos_casos(self):
        for direccion in (None, "Av. 6 de Diciembre N34-12 y Colón, Quito"):
            pdf = render_ride_factura(_con_direccion(direccion))
            assert pdf.startswith(b"%PDF"), f"sin PDF con direccion={direccion!r}"

    def test_una_direccion_sin_espacios_se_parte_y_no_desborda(self):
        """Las importadas vienen con guiones bajos; el filtro `cortable` mete
        los <br/> porque xhtml2pdf ignora overflow-wrap."""
        html = _html(_con_direccion("URB_LOS_CEIBOS_MZ_14_SOLAR_7_ETAPA_SEGUNDA_GUAYAQUIL"))
        assert "<br/>" in html.split("DIRECCIÓN</span>")[1].split("</td>")[0]
        assert render_ride_factura(
            _con_direccion("URB_LOS_CEIBOS_MZ_14_SOLAR_7_ETAPA_SEGUNDA_GUAYAQUIL")
        ).startswith(b"%PDF")
