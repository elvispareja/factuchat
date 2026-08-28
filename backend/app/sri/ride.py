"""RIDE (representación impresa) de la factura en PDF con WeasyPrint (fase 2.4)."""

import io
from typing import Any

import barcode
from barcode.writer import SVGWriter
from jinja2 import Environment, PackageLoader, select_autoescape
from weasyprint import HTML

_env = Environment(
    loader=PackageLoader("app.sri", "templates"),
    autoescape=select_autoescape(["html"]),  # escape SIEMPRE (A05)
)


def _barcode_svg(clave_acceso: str) -> str:
    buf = io.BytesIO()
    code = barcode.get("code128", clave_acceso, writer=SVGWriter())
    code.write(
        buf,
        options={
            "module_height": 8.0,
            "module_width": 0.25,
            "font_size": 0,
            "text_distance": 0,
            "quiet_zone": 1,
        },
    )
    return buf.getvalue().decode()


def render_ride_factura(contexto: dict[str, Any]) -> bytes:
    """contexto: emisor, factura (payload), clave_acceso, numero_autorizacion,
    fecha_autorizacion, ambiente, items, totales."""
    plantilla = _env.get_template("ride_factura.html")
    html = plantilla.render(**contexto, barcode_svg=_barcode_svg(contexto["clave_acceso"]))
    return HTML(string=html).write_pdf()
