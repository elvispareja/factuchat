"""Fabricación de correos y XML de retención para las pruebas del buzón (fase 7).

No se inventa un formato: se arma el mismo `comprobanteRetencion` 2.0.0 que
Factuchat emite (`app/sri/xml_builder.py`), envuelto en el sobre `<autorizacion>`
con el que el SRI reenvía los documentos por correo.
"""

from __future__ import annotations

import zipfile
from decimal import Decimal
from email.message import EmailMessage
from io import BytesIO

RUC_AGENTE = "0992745103001"


def xml_retencion(
    *,
    ruc_retenido: str,
    clave_acceso: str,
    numero: str = "001-001-000001234",
    ruc_agente: str = RUC_AGENTE,
    razon_agente: str = "Comercial Andrade Cía. Ltda.",
    fecha: str = "12/08/2026",
    periodo: str = "08/2026",
    base: Decimal = Decimal("450.00"),
    valor_renta: Decimal = Decimal("41.40"),
    valor_iva: Decimal = Decimal("54.32"),
) -> bytes:
    """Un comprobante de retención con una línea de renta y otra de IVA."""
    estab, pto, sec = numero.split("-")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<comprobanteRetencion id="comprobante" version="2.0.0">
  <infoTributaria>
    <ambiente>1</ambiente>
    <tipoEmision>1</tipoEmision>
    <razonSocial>{razon_agente}</razonSocial>
    <ruc>{ruc_agente}</ruc>
    <claveAcceso>{clave_acceso}</claveAcceso>
    <codDoc>07</codDoc>
    <estab>{estab}</estab>
    <ptoEmi>{pto}</ptoEmi>
    <secuencial>{sec}</secuencial>
    <dirMatriz>Av. Siempre Viva 123</dirMatriz>
  </infoTributaria>
  <infoCompRetencion>
    <fechaEmision>{fecha}</fechaEmision>
    <obligadoContabilidad>SI</obligadoContabilidad>
    <tipoIdentificacionSujetoRetenido>04</tipoIdentificacionSujetoRetenido>
    <razonSocialSujetoRetenido>Empresa Retenida S.A.</razonSocialSujetoRetenido>
    <identificacionSujetoRetenido>{ruc_retenido}</identificacionSujetoRetenido>
    <periodoFiscal>{periodo}</periodoFiscal>
  </infoCompRetencion>
  <docsSustento>
    <docSustento>
      <codSustento>01</codSustento>
      <codDocSustento>01</codDocSustento>
      <numDocSustento>001001000000123</numDocSustento>
      <fechaEmisionDocSustento>{fecha}</fechaEmisionDocSustento>
      <totalSinImpuestos>{base}</totalSinImpuestos>
      <importeTotal>{base}</importeTotal>
      <retenciones>
        <retencion>
          <codigo>1</codigo>
          <codigoRetencion>303</codigoRetencion>
          <baseImponible>{base}</baseImponible>
          <porcentajeRetener>8.00</porcentajeRetener>
          <valorRetenido>{valor_renta}</valorRetenido>
        </retencion>
        <retencion>
          <codigo>2</codigo>
          <codigoRetencion>9</codigoRetencion>
          <baseImponible>{base}</baseImponible>
          <porcentajeRetener>70.00</porcentajeRetener>
          <valorRetenido>{valor_iva}</valorRetenido>
        </retencion>
      </retenciones>
    </docSustento>
  </docsSustento>
</comprobanteRetencion>""".encode()


def envolver_autorizacion(comprobante: bytes, numero_autorizacion: str = "") -> bytes:
    """El sobre con el que el SRI reenvía un documento autorizado."""
    dentro = comprobante.decode("utf-8")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<autorizacion>
  <estado>AUTORIZADO</estado>
  <numeroAutorizacion>{numero_autorizacion}</numeroAutorizacion>
  <fechaAutorizacion>2026-08-12T10:14:00-05:00</fechaAutorizacion>
  <ambiente>PRODUCCION</ambiente>
  <comprobante><![CDATA[{dentro}]]></comprobante>
</autorizacion>""".encode()


def clave_de_prueba(semilla: int) -> str:
    """49 dígitos CON su dígito verificador correcto.

    El verificador módulo 11 es el filtro barato previo a preguntarle al SRI: una
    clave mal formada no llega a consultarse. Fabricarla mal aquí haría que los
    tests probaran otro camino del que corre en producción.
    """
    from app.sri.clave import digito_verificador_mod11

    base = f"{semilla:048d}"
    return base + str(digito_verificador_mod11(base))


def correo(
    *,
    para: str,
    to_visible: str | None = None,
    con_delivered_to: bool = True,
    adjunto: bytes | None = None,
    nombre_adjunto: str = "retencion.xml",
    message_id: str = "<prueba@proveedor.ec>",
    remitente: str = "facturacion@proveedor.ec",
    asunto: str = "Comprobante de retención",
    comprimir: bool = False,
    cuerpo_texto: str | None = None,
) -> bytes:
    """Un mensaje MIME como el que llegaría al buzón."""
    msg = EmailMessage()
    if message_id:
        msg["Message-ID"] = message_id
    msg["From"] = remitente
    # `To` lo escribe el remitente y NO decide de quién es el correo; por eso se
    # puede fijar distinto del destinatario real, que es lo que prueba el caso
    # del lote con varios clientes en copia.
    msg["To"] = to_visible or para
    if con_delivered_to:
        msg["Delivered-To"] = para
    msg["Subject"] = asunto
    msg.set_content(cuerpo_texto or "Adjuntamos su comprobante.")

    if adjunto is not None:
        if comprimir:
            buffer = BytesIO()
            with zipfile.ZipFile(buffer, "w") as z:
                z.writestr(nombre_adjunto, adjunto)
            msg.add_attachment(
                buffer.getvalue(),
                maintype="application",
                subtype="zip",
                filename=nombre_adjunto.replace(".xml", ".zip"),
            )
        else:
            msg.add_attachment(
                adjunto, maintype="application", subtype="xml", filename=nombre_adjunto
            )
    return bytes(msg)
