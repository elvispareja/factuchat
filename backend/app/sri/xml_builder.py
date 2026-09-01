"""Generación de XML de comprobantes electrónicos SRI (ficha técnica 2.31).

Los seis tipos: factura (01), liquidación de compra (03), nota de crédito (04),
nota de débito (05), guía de remisión (06) y comprobante de retención (07).

Los builders reciben dicts ya validados y con Decimals calculados por la capa
de servicios (los totales SIEMPRE se calculan en servidor, OWASP A06).
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from lxml import etree

VERSIONES = {
    "factura": "1.1.0",
    "notaCredito": "1.1.0",
    "notaDebito": "1.0.0",
    "guiaRemision": "1.1.0",
    "comprobanteRetencion": "2.0.0",
    "liquidacionCompra": "1.1.0",
}

# Tabla 17 (tarifas de IVA): código → porcentaje
TARIFAS_IVA = {
    "0": Decimal("0"),
    "2": Decimal("12"),
    "3": Decimal("14"),
    "4": Decimal("15"),
    "5": Decimal("5"),
    "6": Decimal("0"),  # no objeto de impuesto
    "7": Decimal("0"),  # exento
    "8": Decimal("8"),
    "10": Decimal("13"),
}

# Tabla 24: formas de pago
FORMAS_PAGO = {"01", "15", "16", "17", "18", "19", "20", "21"}


def fmt2(v: Decimal | int | str) -> str:
    return str(Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fmt6(v: Decimal | int | str) -> str:
    return str(Decimal(v).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _e(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    el = etree.SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


def _info_tributaria(
    root: etree._Element, emisor: dict[str, Any], cod_doc: str, doc: dict[str, Any]
) -> None:
    it = _e(root, "infoTributaria")
    _e(it, "ambiente", emisor["ambiente"])  # 1 pruebas / 2 producción
    _e(it, "tipoEmision", "1")
    _e(it, "razonSocial", emisor["razon_social"])
    if emisor.get("nombre_comercial"):
        _e(it, "nombreComercial", emisor["nombre_comercial"])
    _e(it, "ruc", emisor["ruc"])
    _e(it, "claveAcceso", doc["clave_acceso"])
    _e(it, "codDoc", cod_doc)
    _e(it, "estab", doc["establecimiento"])
    _e(it, "ptoEmi", doc["punto_emision"])
    _e(it, "secuencial", f"{int(doc['secuencial']):09d}")
    _e(it, "dirMatriz", emisor["dir_matriz"])


def _detalles_venta(
    root: etree._Element, items: list[dict[str, Any]], tag_codigo: str = "codigoPrincipal"
) -> None:
    """tag_codigo: la ficha técnica usa `codigoPrincipal` en factura y
    liquidación de compra, pero `codigoInterno` en nota de crédito y guía."""
    detalles = _e(root, "detalles")
    for item in items:
        d = _e(detalles, "detalle")
        _e(d, tag_codigo, item["codigo"])
        _e(d, "descripcion", item["descripcion"])
        _e(d, "cantidad", fmt6(item["cantidad"]))
        _e(d, "precioUnitario", fmt6(item["precio_unitario"]))
        _e(d, "descuento", fmt2(item.get("descuento", 0)))
        _e(d, "precioTotalSinImpuesto", fmt2(item["total_sin_impuesto"]))
        imps = _e(d, "impuestos")
        imp = _e(imps, "impuesto")
        _e(imp, "codigo", "2")  # IVA
        _e(imp, "codigoPorcentaje", item["codigo_iva"])
        _e(imp, "tarifa", fmt2(item["tarifa_iva"]))
        _e(imp, "baseImponible", fmt2(item["total_sin_impuesto"]))
        _e(imp, "valor", fmt2(item["valor_iva"]))


def _total_con_impuestos(
    parent: etree._Element, impuestos: list[dict[str, Any]], con_tarifa: bool = False
) -> None:
    """con_tarifa: en liquidación de compra 1.1.0 el elemento <tarifa> es
    obligatorio dentro de totalImpuesto (en factura no existe)."""
    tci = _e(parent, "totalConImpuestos")
    for grupo in impuestos:
        ti = _e(tci, "totalImpuesto")
        _e(ti, "codigo", "2")
        _e(ti, "codigoPorcentaje", grupo["codigo_porcentaje"])
        if con_tarifa:
            _e(ti, "tarifa", fmt2(TARIFAS_IVA[grupo["codigo_porcentaje"]]))
        _e(ti, "baseImponible", fmt2(grupo["base"]))
        _e(ti, "valor", fmt2(grupo["valor"]))


def _info_adicional(root: etree._Element, campos: dict[str, str] | None) -> None:
    if not campos:
        return
    ia = _e(root, "infoAdicional")
    for nombre, valor in campos.items():
        campo = _e(ia, "campoAdicional", str(valor)[:300])
        campo.set("nombre", str(nombre)[:300])


def _serializar(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def construir_factura(emisor: dict[str, Any], f: dict[str, Any]) -> bytes:
    root = etree.Element("factura", id="comprobante", version=VERSIONES["factura"])
    _info_tributaria(root, emisor, "01", f)

    info = _e(root, "infoFactura")
    _e(info, "fechaEmision", f["fecha_emision"].strftime("%d/%m/%Y"))
    if f.get("dir_establecimiento"):
        _e(info, "dirEstablecimiento", f["dir_establecimiento"])
    _e(info, "obligadoContabilidad", "SI" if emisor.get("obligado_contabilidad") else "NO")
    _e(info, "tipoIdentificacionComprador", f["comprador"]["tipo_identificacion_codigo"])
    _e(info, "razonSocialComprador", f["comprador"]["razon_social"])
    _e(info, "identificacionComprador", f["comprador"]["identificacion"])
    _e(info, "totalSinImpuestos", fmt2(f["totales"]["total_sin_impuestos"]))
    _e(info, "totalDescuento", fmt2(f["totales"]["total_descuento"]))
    _total_con_impuestos(info, f["totales"]["impuestos"])
    _e(info, "propina", fmt2(f.get("propina", 0)))
    _e(info, "importeTotal", fmt2(f["totales"]["importe_total"]))
    _e(info, "moneda", f.get("moneda", "DOLAR"))
    pagos = _e(info, "pagos")
    for pago in f["pagos"]:
        p = _e(pagos, "pago")
        _e(p, "formaPago", pago["forma"])
        _e(p, "total", fmt2(pago["total"]))
        # Venta a crédito: la tabla 24 no tiene código para «crédito», el plazo
        # va aquí (orden del esquema: formaPago, total, plazo, unidadTiempo).
        if pago.get("plazo"):
            _e(p, "plazo", str(int(pago["plazo"])))
            _e(p, "unidadTiempo", "dias")

    _detalles_venta(root, f["items"])
    _info_adicional(root, f.get("info_adicional"))
    return _serializar(root)


def construir_nota_credito(emisor: dict[str, Any], nc: dict[str, Any]) -> bytes:
    root = etree.Element("notaCredito", id="comprobante", version=VERSIONES["notaCredito"])
    _info_tributaria(root, emisor, "04", nc)

    info = _e(root, "infoNotaCredito")
    _e(info, "fechaEmision", nc["fecha_emision"].strftime("%d/%m/%Y"))
    if nc.get("dir_establecimiento"):
        _e(info, "dirEstablecimiento", nc["dir_establecimiento"])
    _e(info, "tipoIdentificacionComprador", nc["comprador"]["tipo_identificacion_codigo"])
    _e(info, "razonSocialComprador", nc["comprador"]["razon_social"])
    _e(info, "identificacionComprador", nc["comprador"]["identificacion"])
    _e(info, "obligadoContabilidad", "SI" if emisor.get("obligado_contabilidad") else "NO")
    _e(info, "codDocModificado", nc["doc_modificado"]["cod_doc"])
    _e(info, "numDocModificado", nc["doc_modificado"]["numero"])  # 001-001-000000123
    _e(info, "fechaEmisionDocSustento", nc["doc_modificado"]["fecha"].strftime("%d/%m/%Y"))
    _e(info, "totalSinImpuestos", fmt2(nc["totales"]["total_sin_impuestos"]))
    _e(info, "valorModificacion", fmt2(nc["totales"]["importe_total"]))
    _e(info, "moneda", nc.get("moneda", "DOLAR"))
    _total_con_impuestos(info, nc["totales"]["impuestos"])
    _e(info, "motivo", nc["motivo"])

    # La nota de crédito usa codigoInterno, no codigoPrincipal (ficha técnica)
    _detalles_venta(root, nc["items"], tag_codigo="codigoInterno")
    _info_adicional(root, nc.get("info_adicional"))
    return _serializar(root)


def construir_nota_debito(emisor: dict[str, Any], nd: dict[str, Any]) -> bytes:
    root = etree.Element("notaDebito", id="comprobante", version=VERSIONES["notaDebito"])
    _info_tributaria(root, emisor, "05", nd)

    info = _e(root, "infoNotaDebito")
    _e(info, "fechaEmision", nd["fecha_emision"].strftime("%d/%m/%Y"))
    if nd.get("dir_establecimiento"):
        _e(info, "dirEstablecimiento", nd["dir_establecimiento"])
    _e(info, "tipoIdentificacionComprador", nd["comprador"]["tipo_identificacion_codigo"])
    _e(info, "razonSocialComprador", nd["comprador"]["razon_social"])
    _e(info, "identificacionComprador", nd["comprador"]["identificacion"])
    _e(info, "obligadoContabilidad", "SI" if emisor.get("obligado_contabilidad") else "NO")
    _e(info, "codDocModificado", nd["doc_modificado"]["cod_doc"])
    _e(info, "numDocModificado", nd["doc_modificado"]["numero"])
    _e(info, "fechaEmisionDocSustento", nd["doc_modificado"]["fecha"].strftime("%d/%m/%Y"))
    _e(info, "totalSinImpuestos", fmt2(nd["totales"]["total_sin_impuestos"]))
    imps = _e(info, "impuestos")
    for grupo in nd["totales"]["impuestos"]:
        imp = _e(imps, "impuesto")
        _e(imp, "codigo", "2")
        _e(imp, "codigoPorcentaje", grupo["codigo_porcentaje"])
        _e(imp, "tarifa", fmt2(TARIFAS_IVA[grupo["codigo_porcentaje"]]))
        _e(imp, "baseImponible", fmt2(grupo["base"]))
        _e(imp, "valor", fmt2(grupo["valor"]))
    _e(info, "valorTotal", fmt2(nd["totales"]["importe_total"]))

    motivos = _e(root, "motivos")
    for m in nd["motivos"]:
        mo = _e(motivos, "motivo")
        _e(mo, "razon", m["razon"])
        _e(mo, "valor", fmt2(m["valor"]))
    _info_adicional(root, nd.get("info_adicional"))
    return _serializar(root)


def construir_guia_remision(emisor: dict[str, Any], gr: dict[str, Any]) -> bytes:
    root = etree.Element("guiaRemision", id="comprobante", version=VERSIONES["guiaRemision"])
    _info_tributaria(root, emisor, "06", gr)

    info = _e(root, "infoGuiaRemision")
    if gr.get("dir_establecimiento"):
        _e(info, "dirEstablecimiento", gr["dir_establecimiento"])
    _e(info, "dirPartida", gr["dir_partida"])
    _e(info, "razonSocialTransportista", gr["transportista"]["razon_social"])
    _e(info, "tipoIdentificacionTransportista", gr["transportista"]["tipo_identificacion_codigo"])
    _e(info, "rucTransportista", gr["transportista"]["identificacion"])
    _e(info, "obligadoContabilidad", "SI" if emisor.get("obligado_contabilidad") else "NO")
    _e(info, "fechaIniTransporte", gr["fecha_inicio"].strftime("%d/%m/%Y"))
    _e(info, "fechaFinTransporte", gr["fecha_fin"].strftime("%d/%m/%Y"))
    _e(info, "placa", gr["placa"])

    destinatarios = _e(root, "destinatarios")
    for dest in gr["destinatarios"]:
        de = _e(destinatarios, "destinatario")
        _e(de, "identificacionDestinatario", dest["identificacion"])
        _e(de, "razonSocialDestinatario", dest["razon_social"])
        _e(de, "dirDestinatario", dest["direccion"])
        _e(de, "motivoTraslado", dest["motivo_traslado"])
        detalles = _e(de, "detalles")
        for item in dest["items"]:
            d = _e(detalles, "detalle")
            _e(d, "codigoInterno", item["codigo"])
            _e(d, "descripcion", item["descripcion"])
            _e(d, "cantidad", fmt6(item["cantidad"]))
    _info_adicional(root, gr.get("info_adicional"))
    return _serializar(root)


def construir_retencion(emisor: dict[str, Any], ret: dict[str, Any]) -> bytes:
    root = etree.Element(
        "comprobanteRetencion", id="comprobante", version=VERSIONES["comprobanteRetencion"]
    )
    _info_tributaria(root, emisor, "07", ret)

    info = _e(root, "infoCompRetencion")
    _e(info, "fechaEmision", ret["fecha_emision"].strftime("%d/%m/%Y"))
    if ret.get("dir_establecimiento"):
        _e(info, "dirEstablecimiento", ret["dir_establecimiento"])
    _e(info, "obligadoContabilidad", "SI" if emisor.get("obligado_contabilidad") else "NO")
    _e(info, "tipoIdentificacionSujetoRetenido", ret["sujeto"]["tipo_identificacion_codigo"])
    _e(info, "tipoSujetoRetenido", ret["sujeto"].get("tipo_sujeto", "01"))
    _e(info, "parteRel", ret.get("parte_relacionada", "NO"))
    _e(info, "razonSocialSujetoRetenido", ret["sujeto"]["razon_social"])
    _e(info, "identificacionSujetoRetenido", ret["sujeto"]["identificacion"])
    _e(info, "periodoFiscal", ret["periodo_fiscal"])  # mm/aaaa

    docs = _e(root, "docsSustento")
    for ds in ret["docs_sustento"]:
        d = _e(docs, "docSustento")
        _e(d, "codSustento", ds["cod_sustento"])
        _e(d, "codDocSustento", ds["cod_doc"])
        _e(d, "numDocSustento", ds["numero"].replace("-", ""))
        _e(d, "fechaEmisionDocSustento", ds["fecha"].strftime("%d/%m/%Y"))
        _e(d, "pagoLocExt", ds.get("pago_loc_ext", "01"))
        _e(d, "totalSinImpuestos", fmt2(ds["total_sin_impuestos"]))
        _e(d, "importeTotal", fmt2(ds["importe_total"]))
        imps = _e(d, "impuestosDocSustento")
        for i in ds["impuestos"]:
            imp = _e(imps, "impuestoDocSustento")
            _e(imp, "codImpuestoDocSustento", i.get("codigo", "2"))
            _e(imp, "codigoPorcentaje", i["codigo_porcentaje"])
            _e(imp, "baseImponible", fmt2(i["base"]))
            _e(imp, "tarifa", fmt2(TARIFAS_IVA[i["codigo_porcentaje"]]))
            _e(imp, "valorImpuesto", fmt2(i["valor"]))
        rets = _e(d, "retenciones")
        for r in ds["retenciones"]:
            re_ = _e(rets, "retencion")
            _e(re_, "codigo", r["codigo"])  # 1=renta, 2=IVA
            _e(re_, "codigoRetencion", r["codigo_retencion"])
            _e(re_, "baseImponible", fmt2(r["base"]))
            _e(re_, "porcentajeRetener", fmt2(r["porcentaje"]))
            _e(re_, "valorRetenido", fmt2(r["valor"]))
        # <pagos> es obligatorio en cada docSustento del esquema 2.0.0
        pagos = _e(d, "pagos")
        for pago in ds.get("pagos") or [{"forma": "01", "total": ds["importe_total"]}]:
            p = _e(pagos, "pago")
            _e(p, "formaPago", pago["forma"])
            _e(p, "total", fmt2(pago["total"]))
    _info_adicional(root, ret.get("info_adicional"))
    return _serializar(root)


def construir_liquidacion_compra(emisor: dict[str, Any], lc: dict[str, Any]) -> bytes:
    root = etree.Element(
        "liquidacionCompra", id="comprobante", version=VERSIONES["liquidacionCompra"]
    )
    _info_tributaria(root, emisor, "03", lc)

    info = _e(root, "infoLiquidacionCompra")
    _e(info, "fechaEmision", lc["fecha_emision"].strftime("%d/%m/%Y"))
    if lc.get("dir_establecimiento"):
        _e(info, "dirEstablecimiento", lc["dir_establecimiento"])
    _e(info, "obligadoContabilidad", "SI" if emisor.get("obligado_contabilidad") else "NO")
    _e(info, "tipoIdentificacionProveedor", lc["proveedor"]["tipo_identificacion_codigo"])
    _e(info, "razonSocialProveedor", lc["proveedor"]["razon_social"])
    _e(info, "identificacionProveedor", lc["proveedor"]["identificacion"])
    _e(info, "direccionProveedor", lc["proveedor"].get("direccion", ""))
    _e(info, "totalSinImpuestos", fmt2(lc["totales"]["total_sin_impuestos"]))
    _e(info, "totalDescuento", fmt2(lc["totales"]["total_descuento"]))
    _total_con_impuestos(info, lc["totales"]["impuestos"], con_tarifa=True)
    _e(info, "importeTotal", fmt2(lc["totales"]["importe_total"]))
    _e(info, "moneda", lc.get("moneda", "DOLAR"))
    pagos = _e(info, "pagos")
    for pago in lc["pagos"]:
        p = _e(pagos, "pago")
        _e(p, "formaPago", pago["forma"])
        _e(p, "total", fmt2(pago["total"]))

    _detalles_venta(root, lc["items"])
    _info_adicional(root, lc.get("info_adicional"))
    return _serializar(root)
