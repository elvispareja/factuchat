"""Utilidades de prueba del motor SRI: certificado .p12 autofirmado y
respuestas SOAP grabadas de los web services."""

import datetime as dt

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

P12_PASSWORD = "ClaveDelP12-123"


def generar_p12_prueba(
    identificacion: str | None = None,
    dias_validez: int = 365,
    dias_desde: int = -1,
) -> tuple[bytes, str, str]:
    """Devuelve (p12_bytes, password, cert_pem) de un certificado autofirmado.

    identificacion: cédula/RUC en el serialNumber del subject, como lo publican
    las entidades certificadoras ecuatorianas. dias_validez negativo produce un
    certificado ya caducado.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    atributos = [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "EC"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Factuchat Pruebas"),
        x509.NameAttribute(NameOID.COMMON_NAME, "FIRMA DE PRUEBAS FACTUCHAT"),
    ]
    if identificacion:
        atributos.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, identificacion))
    subject = issuer = x509.Name(atributos)
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + dt.timedelta(days=dias_desde))
        .not_valid_after(now + dt.timedelta(days=dias_validez))
        .sign(key, hashes.SHA256())
    )
    p12 = pkcs12.serialize_key_and_certificates(
        b"factuchat-pruebas",
        key,
        cert,
        None,
        serialization.BestAvailableEncryption(P12_PASSWORD.encode()),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return p12, P12_PASSWORD, cert_pem


def _envuelto(cuerpo: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soap:Body>{cuerpo}</soap:Body></soap:Envelope>"
    )


RECEPCION_RECIBIDA = _envuelto(
    '<ns2:validarComprobanteResponse xmlns:ns2="http://ec.gob.sri.ws.recepcion">'
    "<RespuestaRecepcionComprobante><estado>RECIBIDA</estado><comprobantes/>"
    "</RespuestaRecepcionComprobante></ns2:validarComprobanteResponse>"
)

# Rechazo GENUINO en recepción: el SRI no registró nada, procede reemitir.
RECEPCION_DEVUELTA = _envuelto(
    '<ns2:validarComprobanteResponse xmlns:ns2="http://ec.gob.sri.ws.recepcion">'
    "<RespuestaRecepcionComprobante><estado>DEVUELTA</estado><comprobantes><comprobante>"
    "<claveAcceso>X</claveAcceso><mensajes><mensaje>"
    "<identificador>35</identificador>"
    "<mensaje>ARCHIVO NO CUMPLE ESTRUCTURA XML</mensaje>"
    "<informacionAdicional>El comprobante no cumple el esquema XSD</informacionAdicional>"
    "<tipo>ERROR</tipo>"
    "</mensaje></mensajes></comprobante></comprobantes>"
    "</RespuestaRecepcionComprobante></ns2:validarComprobanteResponse>"
)


def autorizacion_autorizado(
    clave: str, numero: str | None = None, comprobante: str | None = None
) -> str:
    """En el esquema offline el número de autorización ES la clave de acceso.

    `comprobante` es el XML que el SRI dice tener con esa clave. Importa: la
    verificación de una retención lo contrasta contra la fila, porque saber que
    una clave está autorizada no dice nada del papel que alguien enseñe con esa
    clave escrita encima.
    """
    numero = numero or clave
    return _envuelto(
        '<ns2:autorizacionComprobanteResponse xmlns:ns2="http://ec.gob.sri.ws.autorizacion">'
        "<RespuestaAutorizacionComprobante>"
        f"<claveAccesoConsultada>{clave}</claveAccesoConsultada>"
        "<numeroComprobantes>1</numeroComprobantes>"
        "<autorizaciones><autorizacion>"
        "<estado>AUTORIZADO</estado>"
        f"<numeroAutorizacion>{numero}</numeroAutorizacion>"
        "<fechaAutorizacion>2026-08-24T12:00:00-05:00</fechaAutorizacion>"
        "<ambiente>PRUEBAS</ambiente>"
        f"<comprobante><![CDATA[{comprobante or '<factura/>'}]]></comprobante><mensajes/>"
        "</autorizacion></autorizaciones>"
        "</RespuestaAutorizacionComprobante></ns2:autorizacionComprobanteResponse>"
    )


def autorizacion_rechazado(clave: str) -> str:
    return _envuelto(
        '<ns2:autorizacionComprobanteResponse xmlns:ns2="http://ec.gob.sri.ws.autorizacion">'
        "<RespuestaAutorizacionComprobante>"
        f"<claveAccesoConsultada>{clave}</claveAccesoConsultada>"
        "<numeroComprobantes>1</numeroComprobantes>"
        "<autorizaciones><autorizacion>"
        "<estado>NO AUTORIZADO</estado>"
        "<fechaAutorizacion>2026-08-24T12:00:00-05:00</fechaAutorizacion>"
        "<ambiente>PRUEBAS</ambiente>"
        "<comprobante><![CDATA[<factura/>]]></comprobante>"
        "<mensajes><mensaje>"
        "<identificador>60</identificador>"
        "<mensaje>CLAVE ACCESO REGISTRADA</mensaje>"
        "<informacionAdicional>Firma inválida</informacionAdicional>"
        "<tipo>ERROR</tipo>"
        "</mensaje></mensajes>"
        "</autorizacion></autorizaciones>"
        "</RespuestaAutorizacionComprobante></ns2:autorizacionComprobanteResponse>"
    )


RECEPCION_CLAVE_YA_REGISTRADA = _envuelto(
    '<ns2:validarComprobanteResponse xmlns:ns2="http://ec.gob.sri.ws.recepcion">'
    "<RespuestaRecepcionComprobante><estado>DEVUELTA</estado><comprobantes><comprobante>"
    "<claveAcceso>X</claveAcceso><mensajes><mensaje>"
    "<identificador>43</identificador>"
    "<mensaje>CLAVE ACCESO REGISTRADA</mensaje>"
    "<informacionAdicional>La clave de acceso ya fue registrada</informacionAdicional>"
    "<tipo>ERROR</tipo>"
    "</mensaje></mensajes></comprobante></comprobantes>"
    "</RespuestaRecepcionComprobante></ns2:validarComprobanteResponse>"
)

# Un WAF, un balanceador caído o una ventana de mantenimiento del SRI no
# devuelven SOAP: son fallos de CANAL, jamás un veredicto sobre el comprobante.
HTML_MANTENIMIENTO = (
    "<html><head><title>Servicio no disponible</title></head>"
    "<body><h1>El servicio se encuentra en mantenimiento</h1></body></html>"
)

SOAP_TRUNCADO = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
)


def autorizacion_de_otra_clave(clave_consultada: str) -> str:
    """El SRI responde con la autorización de OTRO comprobante: nunca debe
    aceptarse como autorización del consultado."""
    return _envuelto(
        '<ns2:autorizacionComprobanteResponse xmlns:ns2="http://ec.gob.sri.ws.autorizacion">'
        "<RespuestaAutorizacionComprobante>"
        f"<claveAccesoConsultada>{clave_consultada}</claveAccesoConsultada>"
        "<numeroComprobantes>1</numeroComprobantes>"
        "<autorizaciones><autorizacion>"
        "<estado>AUTORIZADO</estado>"
        "<numeroAutorizacion>9999999999999999999999999999999999999999999999999</numeroAutorizacion>"
        "<fechaAutorizacion>2026-08-24T12:00:00-05:00</fechaAutorizacion>"
        "<mensajes/>"
        "</autorizacion></autorizaciones>"
        "</RespuestaAutorizacionComprobante></ns2:autorizacionComprobanteResponse>"
    )


def autorizacion_vacia(clave: str) -> str:
    """El SRI aún no registra la clave (autorizaciones vacío) → reintento."""
    return _envuelto(
        '<ns2:autorizacionComprobanteResponse xmlns:ns2="http://ec.gob.sri.ws.autorizacion">'
        "<RespuestaAutorizacionComprobante>"
        f"<claveAccesoConsultada>{clave}</claveAccesoConsultada>"
        "<numeroComprobantes>0</numeroComprobantes>"
        "<autorizaciones/>"
        "</RespuestaAutorizacionComprobante></ns2:autorizacionComprobanteResponse>"
    )
