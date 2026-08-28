"""Cliente de los web services del SRI (fase 2.3).

- RecepcionComprobantesOffline.validarComprobante
- AutorizacionComprobantesOffline.autorizacionComprobante

Controles: lista blanca de hosts (OWASP A01/SSRF), timeouts, circuit breaker
sobre Redis (OWASP A10). Los reintentos exponenciales los orquesta Celery.
"""

import base64
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
import redis
from lxml import etree

from app.core.config import get_settings
from app.core.ratelimit import get_redis

logger = logging.getLogger("factuchat.sri")

# Única lista de destinos salientes permitidos para el SRI (SSRF)
HOSTS_PERMITIDOS_SRI = {"celcer.sri.gob.ec", "cel.sri.gob.ec"}

_CB_UMBRAL = 5
_CB_VENTANA_S = 120
_CB_ABIERTO_S = 60

# Mensajes de recepción que significan "el SRI YA tiene este comprobante".
# No son un rechazo: hay que ir a consultar la autorización, no reemitir.
IDENTIFICADORES_YA_REGISTRADO = {"43", "45"}
TEXTOS_YA_REGISTRADO = ("CLAVE ACCESO REGISTRADA", "SECUENCIAL REGISTRADO")


class SRIError(Exception):
    """Error definitivo del SRI (respuesta inválida)."""


class SRITransientError(Exception):
    """Error transitorio: red, timeout, 5xx o circuito abierto → Celery reintenta."""


@dataclass
class MensajeSRI:
    identificador: str = ""
    mensaje: str = ""
    informacion_adicional: str = ""
    tipo: str = ""

    def legible(self) -> str:
        partes = [p for p in (self.mensaje, self.informacion_adicional) if p]
        texto = ". ".join(partes)
        return f"[{self.identificador}] {texto}" if self.identificador else texto


@dataclass
class RespuestaRecepcion:
    estado: str  # RECIBIDA | DEVUELTA
    mensajes: list[MensajeSRI] = field(default_factory=list)


@dataclass
class RespuestaAutorizacion:
    estado: str  # AUTORIZADO | NO AUTORIZADO | EN PROCESO | SIN REGISTRO
    numero_autorizacion: str = ""
    fecha_autorizacion: str = ""
    mensajes: list[MensajeSRI] = field(default_factory=list)


def _verificar_host(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in HOSTS_PERMITIDOS_SRI:
        raise SRIError(f"Destino no permitido: {host}")


def _cb_keys(destino: str) -> tuple[str, str]:
    """Un circuito POR servicio y ambiente: que autorización de pruebas esté
    caída no debe frenar la recepción de producción."""
    return f"sri:circuit:{destino}", f"sri:circuit:{destino}:fails"


def _circuito_abierto(destino: str) -> bool:
    # Redis es una protección, no una dependencia dura: si no responde, se deja
    # pasar la llamada en vez de convertir el fallo en un error no reintentable.
    try:
        return bool(get_redis().exists(_cb_keys(destino)[0]))
    except redis.RedisError:
        logger.warning("Circuit breaker sin Redis: se permite la llamada al SRI")
        return False


def _registrar_fallo(destino: str) -> None:
    key, fails_key = _cb_keys(destino)
    try:
        r = get_redis()
        fails = int(r.incr(fails_key))
        if fails == 1:
            r.expire(fails_key, _CB_VENTANA_S)
        if fails >= _CB_UMBRAL:
            r.set(key, "abierto", ex=_CB_ABIERTO_S)
            r.delete(fails_key)
    except redis.RedisError:
        logger.warning("No se pudo registrar el fallo del SRI en Redis")


def _registrar_exito(destino: str) -> None:
    try:
        get_redis().delete(_cb_keys(destino)[1])
    except redis.RedisError:
        pass


def _post_soap(url: str, body: str, destino: str) -> etree._Element:
    _verificar_host(url)
    if _circuito_abierto(destino):
        raise SRITransientError("Circuito SRI abierto: el servicio no responde")
    s = get_settings()
    try:
        resp = httpx.post(
            url,
            content=body.encode(),
            headers={"Content-Type": "text/xml; charset=utf-8"},
            timeout=s.sri_timeout_seconds,
        )
    except httpx.HTTPError as e:
        _registrar_fallo(destino)
        raise SRITransientError(f"Sin respuesta del SRI: {type(e).__name__}") from e

    # CUALQUIER respuesta que no sea un 200 con SOAP es un problema del canal,
    # no un veredicto del SRI: 403 de un WAF, 404 por URL mal configurada, 429 o
    # una página de mantenimiento en HTML deben REINTENTARSE, nunca interpretarse
    # como rechazo definitivo de un comprobante (A10).
    if resp.status_code != 200:
        _registrar_fallo(destino)
        raise SRITransientError(f"SRI respondió {resp.status_code}")
    try:
        # Parser defensivo: sin resolución de entidades externas (A05/A08)
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        root = etree.fromstring(resp.content, parser=parser)
    except etree.XMLSyntaxError as e:
        _registrar_fallo(destino)
        raise SRITransientError("Respuesta del SRI no es XML válido") from e
    _registrar_exito(destino)
    return root


def _texto(nodo: etree._Element | None) -> str:
    return (nodo.text or "").strip() if nodo is not None else ""


def _parse_mensajes(contenedor: etree._Element | None) -> list[MensajeSRI]:
    out: list[MensajeSRI] = []
    if contenedor is None:
        return out
    for m in contenedor.iter("mensaje"):
        # <mensaje> anidados: el elemento hoja 'mensaje' comparte nombre con el padre
        if m.find("mensaje") is not None or m.find("identificador") is not None:
            out.append(
                MensajeSRI(
                    identificador=_texto(m.find("identificador")),
                    mensaje=_texto(m.find("mensaje")),
                    informacion_adicional=_texto(m.find("informacionAdicional")),
                    tipo=_texto(m.find("tipo")),
                )
            )
    return out


def _urls(ambiente: str) -> tuple[str, str]:
    s = get_settings()
    if ambiente == "PRODUCCION":
        return s.sri_recepcion_url_produccion, s.sri_autorizacion_url_produccion
    return s.sri_recepcion_url_pruebas, s.sri_autorizacion_url_pruebas


def enviar_recepcion(xml_firmado: bytes, ambiente: str) -> RespuestaRecepcion:
    url, _ = _urls(ambiente)
    xml_b64 = base64.b64encode(xml_firmado).decode()
    envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ec="http://ec.gob.sri.ws.recepcion">
  <soapenv:Header/>
  <soapenv:Body>
    <ec:validarComprobante>
      <xml>{xml_b64}</xml>
    </ec:validarComprobante>
  </soapenv:Body>
</soapenv:Envelope>"""
    root = _post_soap(url, envelope, f"recepcion:{ambiente}")

    estado = ""
    for el in root.iter():
        if etree.QName(el).localname == "estado":
            estado = _texto(el)
            break
    if estado not in ("RECIBIDA", "DEVUELTA"):
        # Un cuerpo sin <estado> reconocible (página de mantenimiento, portal de
        # un WAF, respuesta parcial) NO es un veredicto sobre el comprobante:
        # se reintenta. Marcarlo rechazado llevaría a reemitir y duplicar.
        raise SRITransientError(f"Respuesta de recepción no interpretable: {estado!r}")
    return RespuestaRecepcion(estado=estado, mensajes=_parse_mensajes(root))


def ya_estaba_registrado(mensajes: list[MensajeSRI]) -> bool:
    """¿La DEVUELTA se debe a que el SRI YA tiene este comprobante?

    Ocurre cuando un envío anterior llegó pero no pudimos confirmarlo (caída del
    worker, timeout). No es un rechazo: hay que consultar la autorización, jamás
    reemitir, o se duplicaría la factura con el mismo secuencial."""
    for m in mensajes:
        if m.identificador in IDENTIFICADORES_YA_REGISTRADO:
            return True
        texto = f"{m.mensaje} {m.informacion_adicional}".upper()
        if any(t in texto for t in TEXTOS_YA_REGISTRADO):
            return True
    return False


def consultar_autorizacion(clave_acceso: str, ambiente: str) -> RespuestaAutorizacion:
    _, url = _urls(ambiente)
    envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ec="http://ec.gob.sri.ws.autorizacion">
  <soapenv:Header/>
  <soapenv:Body>
    <ec:autorizacionComprobante>
      <claveAccesoComprobante>{clave_acceso}</claveAccesoComprobante>
    </ec:autorizacionComprobante>
  </soapenv:Body>
</soapenv:Envelope>"""
    root = _post_soap(url, envelope, f"autorizacion:{ambiente}")

    # La respuesta DEBE corresponder a la clave consultada: aceptar una
    # autorización ajena marcaría como AUTORIZADO un comprobante que no lo está.
    consultada = ""
    for el in root.iter():
        if etree.QName(el).localname == "claveAccesoConsultada":
            consultada = _texto(el)
            break
    if consultada and consultada != clave_acceso:
        raise SRIError("La respuesta del SRI no corresponde a la clave consultada")

    autorizacion: etree._Element | None = None
    for el in root.iter():
        if etree.QName(el).localname == "autorizacion":
            autorizacion = el
            break
    if autorizacion is None:
        # El SRI aún no registra la clave: reintentar más tarde
        return RespuestaAutorizacion(estado="SIN REGISTRO")

    estado = ""
    numero = ""
    fecha = ""
    for hijo in autorizacion:
        nombre = etree.QName(hijo).localname
        if nombre == "estado":
            estado = _texto(hijo)
        elif nombre == "numeroAutorizacion":
            numero = _texto(hijo)
        elif nombre == "fechaAutorizacion":
            fecha = _texto(hijo)
    return RespuestaAutorizacion(
        estado=estado or "EN PROCESO",
        numero_autorizacion=numero,
        fecha_autorizacion=fecha,
        mensajes=_parse_mensajes(autorizacion),
    )


def mensajes_a_json(mensajes: list[MensajeSRI]) -> list[dict[str, Any]]:
    return [
        {
            "identificador": m.identificador,
            "mensaje": m.mensaje,
            "informacion_adicional": m.informacion_adicional,
            "tipo": m.tipo,
            "legible": m.legible(),
        }
        for m in mensajes
    ]
