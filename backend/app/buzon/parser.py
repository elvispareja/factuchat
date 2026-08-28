"""Lectura de los XML que llegan al buzón (fase 7.1).

Aquí se lee XML escrito por DESCONOCIDOS. Todo lo de este módulo parte de esa
premisa:

  · El parser va con `resolve_entities=False`, `no_network=True` y
    `huge_tree=False`, y además se rechaza cualquier DOCTYPE **en todo el
    documento**, no solo en su cabecera: mirar los primeros bytes se esquiva
    rellenando el prólogo con comentarios. Sin esto, un XML ajeno lee ficheros
    del contenedor (XXE) o lo tumba con una bomba de entidades — y este
    contenedor es el que descifra el .p12 de firma.
  · Hay topes de bytes, de líneas y de longitud de cada campo, y ningún valor
    numérico no finito sobrevive: `NaN` e `Infinity` se construyen sin error en
    Decimal y acabarían guardados como crédito tributario.
  · Recorrer el árbol NUNCA es cuadrático. Buscar un dato por cada línea de
    retención convertía un adjunto de 4 MB en horas de CPU y colgaba al worker
    que además firma las facturas de todos los inquilinos.
  · Cualquier excepción del árbol se convierte en `BuzonParseError`: si se
    escapara otra, la transacción se revertiría y el correo desaparecería sin
    dejar rastro en el panel.
  · Nunca se sigue un enlace que venga dentro del correo: el compromiso del
    proyecto es que ninguna URL provista por un tercero se visita (SSRF, A01).

Lo que se espera recibir es lo que reenvía el SRI o el propio emisor: o bien el
sobre `<autorizacion><comprobante><![CDATA[ ... ]]></comprobante></autorizacion>`,
o bien el comprobante desnudo. Se soportan los dos.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, DecimalException

from lxml import etree

MAX_XML_BYTES = 4 * 1024 * 1024
# Un comprobante de retención real tiene unas pocas decenas de líneas. El tope
# existe para que un documento hostil no convierta el parseo en trabajo sin fin.
MAX_LINEAS_RETENCION = 500
# Numeric(12,2) en la base: nada que venga del XML puede superar lo que cabe
MAX_VALOR = Decimal("9999999999.99")

# Raíz del documento → tipo legible, con el código del SRI
TIPOS = {
    "factura": ("FACTURA", "01"),
    "liquidacionCompra": ("LIQUIDACION_COMPRA", "03"),
    "notaCredito": ("NOTA_CREDITO", "04"),
    "notaDebito": ("NOTA_DEBITO", "05"),
    "guiaRemision": ("GUIA_REMISION", "06"),
    "comprobanteRetencion": ("RETENCION", "07"),
}

# <retencion><codigo>: 1 = Impuesto a la Renta, 2 = IVA. Se mantienen separadas
# de punta a punta: son impuestos distintos y solo la de IVA baja el IVA a pagar.
COD_RENTA = "1"
COD_IVA = "2"


class BuzonParseError(Exception):
    """El XML no se pudo leer. El mensaje se le muestra al personal interno."""


@dataclass
class RetencionLinea:
    codigo: str  # 1=renta, 2=IVA
    codigo_retencion: str
    base: Decimal
    porcentaje: Decimal
    valor: Decimal
    doc_sustento: str | None = None


@dataclass
class ComprobanteLeido:
    tipo: str
    codigo_sri: str
    clave_acceso: str | None
    ruc_emisor: str | None
    razon_social_emisor: str | None
    identificacion_receptor: str | None
    fecha_emision: date | None
    numero: str | None
    periodo_fiscal: str | None = None
    total_renta: Decimal = Decimal("0")
    total_iva: Decimal = Decimal("0")
    lineas: list[RetencionLinea] = field(default_factory=list)
    autorizado: bool | None = None
    numero_autorizacion: str | None = None


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
        load_dtd=False,
        dtd_validation=False,
        recover=False,
    )


def _sin_doctype(datos: bytes) -> None:
    """Ningún DOCTYPE, en ninguna parte del documento.

    Es la puerta de las entidades externas, y no hay motivo legítimo para que un
    comprobante del SRI traiga una declaración de tipo de documento. Se mira el
    documento COMPLETO —no solo su cabecera— porque unos kilobytes de comentario
    en el prólogo bastarían para empujarlo fuera de una ventana fija.
    """
    if re.search(rb"<!DOCTYPE", datos, re.IGNORECASE):
        raise BuzonParseError("El XML declara un DOCTYPE y no se procesa")


def _raiz(datos: bytes) -> etree._Element:
    if not datos:
        raise BuzonParseError("El archivo llegó vacío")
    if len(datos) > MAX_XML_BYTES:
        raise BuzonParseError(f"El XML supera los {MAX_XML_BYTES // (1024 * 1024)} MB permitidos")
    _sin_doctype(datos)
    try:
        return etree.fromstring(datos, parser=_parser())
    except etree.XMLSyntaxError as e:
        # El mensaje de lxml ya trae la línea: la maqueta muestra exactamente
        # ese detalle en el visor de "XML crudo" del panel interno.
        raise BuzonParseError(f"XML mal formado: {e.msg} (línea {e.lineno})") from e


def _es_elemento(nodo) -> bool:
    """`iter()` devuelve también comentarios y processing instructions, y sobre
    ellos `QName` lanza ValueError. Un comentario en un XML es de lo más normal,
    así que esto no es defensa contra un ataque: es no perder correos legítimos."""
    return isinstance(nodo.tag, str)


def _elementos(raiz: etree._Element) -> Iterator[etree._Element]:
    for nodo in raiz.iter():
        if _es_elemento(nodo):
            yield nodo


def _local(nodo: etree._Element) -> str:
    return etree.QName(nodo).localname


def _texto(raiz: etree._Element, nombre: str, tope: int = 500) -> str | None:
    """Primer descendiente con ese nombre local, ignorando espacios de nombres.

    El tope no es cosmético: estos valores van a columnas estrechas, y un `<ruc>`
    de 500 caracteres hacía fallar el INSERT y con él la transacción entera, de
    modo que el correo ni siquiera quedaba registrado como erróneo.
    """
    for el in _elementos(raiz):
        if _local(el) == nombre:
            valor = (el.text or "").strip()
            return valor[:tope] if valor else None
    return None


def _decimal(valor: str | None) -> Decimal:
    """Solo números finitos y dentro de lo que admite la columna.

    `Decimal("NaN")` y `Decimal("Infinity")` se construyen SIN error y PostgreSQL
    acepta 'NaN' en una columna numeric: sin esta guarda, un valor así se
    guardaría como crédito tributario y envenenaría todas las sumas.
    """
    if not valor:
        return Decimal("0")
    try:
        d = Decimal(valor.strip().replace(",", "."))
        if not d.is_finite():
            return Decimal("0")
        d = d.quantize(Decimal("0.01"))
    except (DecimalException, ValueError, ArithmeticError):
        return Decimal("0")
    if d < 0 or d > MAX_VALOR:
        return Decimal("0")
    return d


def _fecha(valor: str | None) -> date | None:
    """El SRI escribe dd/mm/aaaa. Se aceptan las variantes que llegan de verdad."""
    if not valor:
        return None
    texto = valor.strip()
    # Algunos emisores añaden la hora; la fecha son los primeros 10 caracteres
    primero = texto.split("T")[0].split(" ")[0]
    for candidato in (texto, primero):
        for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(candidato, formato).date()
            except ValueError:
                continue
    return None


def fecha_de_periodo(periodo: str | None) -> date | None:
    """Primer día del período fiscal (mm/aaaa).

    Sirve de respaldo cuando la fecha de emisión no se puede leer: sin fecha, la
    retención quedaría fuera de todos los rangos y desaparecería del saldo sin
    que nadie se entere.
    """
    if not periodo:
        return None
    m = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{4})\s*", periodo)
    if not m:
        return None
    mes, anio = int(m.group(1)), int(m.group(2))
    if not 1 <= mes <= 12 or not 2000 <= anio <= 2999:
        return None
    return date(anio, mes, 1)


def _solo_digitos(valor: str | None, largos: tuple[int, ...]) -> str | None:
    """Un identificador ecuatoriano: dígitos y con uno de los largos válidos."""
    if not valor:
        return None
    limpio = re.sub(r"\D", "", valor)
    return limpio if len(limpio) in largos else None


def _periodo(valor: str | None) -> str | None:
    """mm/aaaa normalizado, o nada. La columna admite 7 caracteres."""
    if not valor:
        return None
    m = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{4})\s*", valor)
    if not m:
        return None
    mes, anio = int(m.group(1)), int(m.group(2))
    if not 1 <= mes <= 12:
        return None
    return f"{mes:02d}/{anio}"


def desenvolver(datos: bytes) -> bytes:
    """Saca el comprobante del sobre de autorización, si viene envuelto.

    El SRI reenvía `<autorizacion>` con el documento dentro de un CDATA. Si lo
    que llega ya es el comprobante desnudo, se devuelve tal cual.
    """
    raiz = _raiz(datos)
    if _local(raiz) in TIPOS:
        return datos

    for el in _elementos(raiz):
        if _local(el) == "comprobante" and (el.text or "").strip():
            interno = el.text.strip()
            # El contenido del CDATA es XML de nuevo: se vuelve a validar con
            # las mismas defensas, no se confía en que el sobre lo saneara.
            crudo = interno.encode("utf-8", "ignore")
            _sin_doctype(crudo)
            return crudo

    raise BuzonParseError("El XML no contiene ningún comprobante reconocible")


def _autorizacion(datos: bytes) -> tuple[bool | None, str | None]:
    """Estado y número de autorización del sobre, si el correo los trae."""
    try:
        raiz = _raiz(datos)
    except BuzonParseError:
        return None, None
    if _local(raiz) in TIPOS:
        return None, None
    estado = _texto(raiz, "estado", tope=60)
    numero = _texto(raiz, "numeroAutorizacion", tope=60)
    if estado is None:
        return None, numero
    return estado.strip().upper() == "AUTORIZADO", numero


def leer(datos: bytes) -> ComprobanteLeido:
    """Lee un comprobante recibido. Lanza BuzonParseError si no se puede.

    Cualquier excepción inesperada del árbol se traduce también a
    BuzonParseError: quien llama solo captura eso, y una excepción distinta
    revertiría la transacción y perdería el correo entero sin dejar constancia.
    """
    try:
        return _leer(datos)
    except BuzonParseError:
        raise
    except Exception as e:  # noqa: BLE001 — traducir, no tragar
        raise BuzonParseError(f"No se pudo interpretar el XML: {type(e).__name__}") from e


def _leer(datos: bytes) -> ComprobanteLeido:
    autorizado, num_aut = _autorizacion(datos)
    cuerpo = desenvolver(datos)
    raiz = _raiz(cuerpo)

    nombre = _local(raiz)
    if nombre not in TIPOS:
        raise BuzonParseError(f"Tipo de comprobante no reconocido: <{nombre}>")
    tipo, codigo_sri = TIPOS[nombre]

    clave = _texto(raiz, "claveAcceso", tope=60)
    estab = _solo_digitos(_texto(raiz, "estab", tope=20), (3,))
    pto = _solo_digitos(_texto(raiz, "ptoEmi", tope=20), (3,))
    sec = _solo_digitos(_texto(raiz, "secuencial", tope=20), (9,))
    numero = f"{estab}-{pto}-{sec}" if estab and pto and sec else None

    leido = ComprobanteLeido(
        tipo=tipo,
        codigo_sri=codigo_sri,
        clave_acceso=clave if clave and clave.isdigit() and len(clave) == 49 else None,
        ruc_emisor=_solo_digitos(_texto(raiz, "ruc", tope=30), (13,)),
        razon_social_emisor=_texto(raiz, "razonSocial", tope=300),
        identificacion_receptor=None,
        fecha_emision=_fecha(_texto(raiz, "fechaEmision", tope=40)),
        numero=numero,
        autorizado=autorizado,
        numero_autorizacion=num_aut,
    )

    if tipo == "RETENCION":
        _leer_retencion(raiz, leido)
    else:
        leido.identificacion_receptor = _solo_digitos(
            _texto(raiz, "identificacionComprador", tope=30), (10, 13)
        )

    # Respaldo de fecha: sin ella la retención quedaría fuera de todo rango
    if leido.fecha_emision is None:
        leido.fecha_emision = fecha_de_periodo(leido.periodo_fiscal)

    return leido


def _leer_retencion(raiz: etree._Element, leido: ComprobanteLeido) -> None:
    """Detalle del comprobanteRetencion 2.0.0 (y del 1.0.0 antiguo).

    En el esquema 2.0.0 las retenciones cuelgan de cada <docSustento>; en el
    1.0.0 van sueltas bajo <impuestos><impuesto>. Se soportan los dos porque por
    el buzón entra lo que el proveedor tenga, no lo que nos convenga.

    El recorrido es de arriba abajo y el número del documento de sustento se
    resuelve UNA vez por cada <docSustento>. Buscarlo por cada línea hacía el
    parseo cuadrático: con un documento sin `numDocSustento` y muchas líneas, un
    adjunto que cabe de sobra en los topes tenía al worker horas ocupado.
    """
    leido.identificacion_receptor = _solo_digitos(
        _texto(raiz, "identificacionSujetoRetenido", tope=30), (10, 13)
    )
    leido.periodo_fiscal = _periodo(_texto(raiz, "periodoFiscal", tope=20))

    for nodo in _elementos(raiz):
        if len(leido.lineas) >= MAX_LINEAS_RETENCION:
            break
        local = _local(nodo)
        if local == "docSustento":
            sustento = _texto(nodo, "numDocSustento", tope=60)
            _lineas_de(nodo, leido, sustento)
        elif local in ("retencion", "impuesto"):
            # Esquema antiguo: líneas sueltas fuera de cualquier docSustento
            padre = nodo.getparent()
            dentro_de_sustento = False
            while padre is not None:
                if _es_elemento(padre) and _local(padre) == "docSustento":
                    dentro_de_sustento = True
                    break
                padre = padre.getparent()
            if not dentro_de_sustento:
                linea = _linea(nodo, None)
                if linea is not None:
                    leido.lineas.append(linea)

    leido.total_renta = _acotar(
        sum((linea.valor for linea in leido.lineas if linea.codigo == COD_RENTA), Decimal("0"))
    )
    leido.total_iva = _acotar(
        sum((linea.valor for linea in leido.lineas if linea.codigo == COD_IVA), Decimal("0"))
    )


def _acotar(valor: Decimal) -> Decimal:
    return valor if valor <= MAX_VALOR else MAX_VALOR


def _lineas_de(doc_sustento: etree._Element, leido: ComprobanteLeido, sustento: str | None) -> None:
    for nodo in _elementos(doc_sustento):
        if len(leido.lineas) >= MAX_LINEAS_RETENCION:
            return
        if _local(nodo) not in ("retencion", "impuesto"):
            continue
        linea = _linea(nodo, sustento)
        if linea is not None:
            leido.lineas.append(linea)


def _linea(nodo: etree._Element, sustento: str | None) -> RetencionLinea | None:
    codigo = None
    codigo_ret = None
    base = porcentaje = valor = Decimal("0")
    for hijo in nodo:
        if not _es_elemento(hijo):
            continue
        n = _local(hijo)
        texto = (hijo.text or "").strip()
        if n == "codigo":
            codigo = texto[:10]
        elif n == "codigoRetencion":
            codigo_ret = texto[:10]
        elif n == "baseImponible":
            base = _decimal(texto)
        elif n == "porcentajeRetener":
            porcentaje = _decimal(texto)
        elif n == "valorRetenido":
            valor = _decimal(texto)
    if codigo is None or valor <= 0:
        return None
    return RetencionLinea(
        codigo=codigo,
        codigo_retencion=codigo_ret or "",
        base=base,
        porcentaje=porcentaje,
        valor=valor,
        doc_sustento=sustento,
    )
