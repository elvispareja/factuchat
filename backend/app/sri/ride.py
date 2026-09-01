"""RIDE (representación impresa) de la factura en PDF con WeasyPrint (fase 2.4)."""

import io
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html import escape
from typing import Any

import barcode
from barcode.writer import SVGWriter
from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

# WeasyPrint NO se importa aquí arriba a propósito: al importarse carga las
# librerías nativas de GTK (libgobject y compañía), que en Windows no vienen con
# el paquete y hay que instalar aparte. Como este módulo cuelga de la cadena de
# emisión, ese import reventaba con OSError y tumbaba el EMITIR entero —con un
# 500 opaco— aunque lo que se manda al SRI es el XML firmado y el PDF es solo la
# representación impresa. Con el import dentro de la función, si GTK falta se cae
# al respaldo de xhtml2pdf en vez de quedarse sin PDF.

_env = Environment(
    loader=PackageLoader("app.sri", "templates"),
    autoescape=select_autoescape(["html"]),  # escape SIEMPRE (A05)
)

# Ancho a partir del cual una palabra sin espacios se considera impartible
_CORTE = 24


def _cortable(texto: str) -> Markup:
    """Parte las palabras larguísimas para que no desborden su columna.

    Las descripciones importadas llegan a menudo sin espacios
    («SERVICIO_DE_MANTENIMIENTO_PREVENTIVO_Y_CORRECTIVO…») y el campo admite 300
    caracteres. Una palabra así estira su columna y empuja las cifras fuera del
    papel: el PDF sale con el subtotal cortado, que en una factura es grave.

    Se parte con <br/> y no con CSS ni con caracteres invisibles, porque los dos
    caminos fallan donde importa: `table-layout: fixed` y `overflow-wrap` los
    ignora xhtml2pdf, y el espacio de ancho cero (U+200B) reportlab lo pinta como
    un cuadrado negro. Un <br/> lo entienden los dos motores igual.

    Escapa a mano y devuelve Markup porque el resultado lleva HTML: sin esto, el
    autoescape del entorno mostraría las etiquetas como texto.
    """
    partes = []
    for palabra in str(texto).split(" "):
        if len(palabra) <= _CORTE:
            partes.append(escape(palabra))
        else:
            trozos = [palabra[i : i + _CORTE] for i in range(0, len(palabra), _CORTE)]
            partes.append("<br/>".join(escape(t) for t in trozos))
    return Markup(" ".join(partes))


def _dinero(valor: Any) -> str:
    """Dos decimales siempre, como el resto de las cifras del documento.

    El payload guarda `str(Decimal(...))` sin normalizar, así que un precio
    entero salía como «300» en la misma fila donde el descuento decía «0.00» y
    el subtotal «300.00». En una factura las columnas de dinero se leen en
    vertical y tienen que cuadrar.
    """
    try:
        return str(Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError):
        return str(valor)  # dato raro: mejor enseñarlo tal cual que perderlo


_env.filters["cortable"] = _cortable
_env.filters["dinero"] = _dinero


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


def _pdf_respaldo(plantilla, contexto: dict[str, Any]) -> bytes:
    """Respaldo en Python puro para equipos sin GTK (ver render_ride_factura).

    xhtml2pdf no entiende ni SVG inline ni flexbox, así que el barcode se pide
    con su propia etiqueta (reportlab) y la cabecera sale apilada en vez de en
    dos columnas. El PDF es más feo, pero lleva el mismo contenido obligatorio.
    """
    from xhtml2pdf import pisa

    clave = escape(contexto["clave_acceso"], quote=True)
    # El aire alrededor se controla AQUÍ, con el alto de las barras frente al de
    # su celda (15mm en la plantilla), no con relleno: xhtml2pdf dibuja este
    # código fuera del flujo, así que ni el `padding` del td ni un
    # `padding-bottom` lo desplazan. Con 10mm de barra en 15mm de celda quedan
    # el aire de las demás tarjetas del documento.
    barcode = (
        f'<pdf:barcode value="{clave}" type="code128"'
        ' barWidth="0.38mm" barHeight="8mm" humanReadable="0" />'
    )
    buf = io.BytesIO()
    if pisa.CreatePDF(
        src=plantilla.render(**contexto, barcode_svg=barcode), dest=buf, encoding="utf-8"
    ).err:
        raise OSError("xhtml2pdf no pudo generar el RIDE")
    return buf.getvalue()


def render_ride_factura(contexto: dict[str, Any]) -> bytes:
    """contexto: emisor, factura (payload), clave_acceso, numero_autorizacion,
    fecha_autorizacion, ambiente, items, totales.

    Dos generadores, uno solo manda: en producción (Docker sobre Linux) GTK está
    instalado, WeasyPrint carga y es SIEMPRE el que se usa —da mejor tipografía y
    respeta el CSS de la plantilla—. El respaldo existe solo para desarrollo en
    Windows, donde GTK no viene con el paquete de pip y hay que instalarlo a mano:
    sin él WeasyPrint revienta al importarse y no habría PDF que mirar. La
    selección es automática según si el import funciona; quien llama no elige.
    """
    plantilla = _env.get_template("ride_factura.html")
    try:
        from weasyprint import HTML  # import tardío: carga GTK al importarse
    except (OSError, ImportError):
        return _pdf_respaldo(plantilla, contexto)

    html = plantilla.render(**contexto, barcode_svg=_barcode_svg(contexto["clave_acceso"]))
    return HTML(string=html).write_pdf()
