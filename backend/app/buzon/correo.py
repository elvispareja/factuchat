"""Lectura del correo entrante del buzón (fase 7.1).

Dos responsabilidades, las dos delicadas porque el remitente es un desconocido:

  1. Sacar los XML de un mensaje MIME —incluidos los que vienen dentro de un
     ZIP, que es como los manda media contabilidad del país—.
  2. Averiguar A QUIÉN pertenece el correo. Y esto se decide SIEMPRE por la
     dirección destinataria, jamás por lo que diga el XML: si el dueño se
     dedujera del RUC escrito dentro del documento, cualquiera podría inyectar
     retenciones en la cuenta de otro contribuyente con solo escribir su RUC.
     El RUC del XML se usa después, y solo para VERIFICAR que coincide.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import uuid
import zipfile
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger("factuchat.buzon")

MAX_ADJUNTOS = 20
MAX_XML_POR_CORREO = 10
MAX_ZIP_DESCOMPRIMIDO = 8 * 1024 * 1024


@dataclass
class AdjuntoXml:
    nombre: str
    datos: bytes


@dataclass
class CorreoEntrante:
    message_id: str
    remitente: str | None
    destinatarios: list[str]
    asunto: str | None
    xmls: list[AdjuntoXml]
    crudo: bytes


def _direccion(valor: str | None) -> str | None:
    """La dirección REAL, no el nombre para mostrar.

    Con una expresión regular, un `To: "victima@buzon…" <otro@buzon…>` devolvía
    la dirección escondida en el nombre para mostrar en vez de la verdadera.
    `getaddresses` sí distingue una de otra.
    """
    if not valor:
        return None
    for _, direccion in getaddresses([str(valor)]):
        if "@" in direccion:
            return direccion.strip().lower()[:320]
    return None


# Cabeceras que pone el SERVIDOR al entregar. `To` y `Cc` NO están, y es la
# decisión central del módulo: las escribe el remitente, igual que el RUC del
# XML, así que aceptarlas dejaría que un tercero decidiera en el buzón de quién
# cae su documento. Un correo cuyo destino real no se sepa se descarta.
CABECERAS_DE_ENTREGA = ("Delivered-To", "X-Original-To", "X-Envelope-To", "X-Forwarded-To")


def _todas_las_direcciones(msg: EmailMessage) -> list[str]:
    salida: list[str] = []
    for cabecera in CABECERAS_DE_ENTREGA:
        for bruto in msg.get_all(cabecera, []):
            for trozo in str(bruto).split(","):
                d = _direccion(trozo)
                if d and d not in salida:
                    salida.append(d)
    return salida


def _xmls_del_zip(datos: bytes) -> list[AdjuntoXml]:
    """Un ZIP de un desconocido: se limita el número de miembros, el tamaño
    descomprimido y se ignoran las rutas (zip slip)."""
    salida: list[AdjuntoXml] = []
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            total = 0
            for info in z.infolist()[:MAX_ADJUNTOS]:
                if info.is_dir() or not info.filename.lower().endswith(".xml"):
                    continue
                total += info.file_size
                if total > MAX_ZIP_DESCOMPRIMIDO:
                    break
                with z.open(info) as f:
                    contenido = f.read(MAX_ZIP_DESCOMPRIMIDO)
                # Solo el nombre base: el del ZIP puede traer ../.. dentro
                nombre = info.filename.replace("\\", "/").split("/")[-1]
                salida.append(AdjuntoXml(nombre=nombre[:200], datos=contenido))
                if len(salida) >= MAX_XML_POR_CORREO:
                    break
    except (zipfile.BadZipFile, OSError, RuntimeError):
        return []
    return salida


def _parece_xml(datos: bytes) -> bool:
    return datos.lstrip()[:200].lstrip().startswith(b"<")


def leer_correo(crudo: bytes, destinatario_sobre: str | None = None) -> CorreoEntrante:
    """Convierte un mensaje MIME crudo en lo que nos interesa de él.

    `destinatario_sobre` es el RCPT TO que el proveedor de correo entrega aparte
    del mensaje. Es el dato más fiable que existe sobre a quién iba dirigido,
    porque no lo escribe el remitente, y por eso manda sobre las cabeceras.
    """
    msg = BytesParser(policy=policy.default).parsebytes(crudo)

    xmls: list[AdjuntoXml] = []
    vistos = 0
    for parte in msg.walk():
        if vistos >= MAX_ADJUNTOS or len(xmls) >= MAX_XML_POR_CORREO:
            break
        if parte.is_multipart():
            continue
        vistos += 1
        nombre = (parte.get_filename() or "").strip()
        tipo = (parte.get_content_type() or "").lower()
        try:
            crudo_parte = parte.get_payload(decode=True)
        except Exception as e:  # noqa: BLE001 — un adjunto roto no tumba el correo
            logger.debug("Adjunto ilegible en correo de buzón: %s", e)
            continue
        # decode=True devuelve bytes o None; cualquier otra cosa no es un adjunto
        if not isinstance(crudo_parte, bytes) or not crudo_parte:
            continue
        datos: bytes = crudo_parte

        bajo = nombre.lower()
        if bajo.endswith(".zip") or tipo in ("application/zip", "application/x-zip-compressed"):
            xmls.extend(_xmls_del_zip(datos))
        elif bajo.endswith(".xml") or "xml" in tipo:
            xmls.append(AdjuntoXml(nombre=(nombre or "adjunto.xml")[:200], datos=datos))
        elif not nombre and tipo == "text/plain" and _parece_xml(datos):
            # Algunos emisores pegan el XML en el cuerpo sin adjuntarlo
            xmls.append(AdjuntoXml(nombre="cuerpo.xml", datos=datos))

    destinatarios = _todas_las_direcciones(msg)
    del_sobre = _direccion(destinatario_sobre)
    if del_sobre:
        # El del sobre va primero: es el que decide, y las cabeceras solo
        # completan por si el proveedor no lo entrega aparte.
        destinatarios = [del_sobre] + [d for d in destinatarios if d != del_sobre]

    return CorreoEntrante(
        message_id=_identificador(msg, crudo),
        remitente=_direccion(msg.get("From")),
        destinatarios=destinatarios,
        asunto=(str(msg.get("Subject") or "").strip()[:500] or None),
        xmls=xmls[:MAX_XML_POR_CORREO],
        crudo=crudo,
    )


def _identificador(msg: EmailMessage, crudo: bytes) -> str:
    """Message-ID del correo, o uno DERIVADO del propio mensaje si no lo trae.

    No vale un UUID al azar: este identificador es a la vez la clave del candado
    y la mitad de la unicidad por inquilino, así que tiene que salir igual cada
    vez que se procese el mismo mensaje. Con un valor aleatorio, una segunda
    entrega del mismo correo se archivaba otra vez, con otra copia cifrada
    completa en disco.
    """
    bruto = str(msg.get("Message-ID") or "").strip()
    limpio = bruto.strip("<>").strip()
    if limpio:
        return limpio[:300]
    return f"sha256-{hashlib.sha256(crudo).hexdigest()}"


def direccion_de_tenant(ruc: str) -> str:
    """La dirección del buzón de un inquilino: su RUC, tal como la maqueta la
    muestra bajo el nombre de cada inquilino (`1791234567001@…`)."""
    return f"{ruc}@{get_settings().dominio_buzon}"


def tenant_por_direccion(db: Session, direcciones: list[str]) -> uuid.UUID | None:
    """Resuelve el inquilino por la dirección a la que se ENTREGÓ el correo.

    Va por función segura (`sys_tenant_por_buzon`) y no por consulta directa:
    la tabla `tenants` está cerrada incluso para el contexto interno, y esa
    barrera —que impide que un fallo del código exponga la cartera entera de
    clientes— no se abre por comodidad del ingestor. La función devuelve como
    mucho un identificador, nunca una lista.
    """
    dominio = get_settings().dominio_buzon.lower()
    candidatos: list[str] = []
    for direccion in direcciones:
        local, _, host = direccion.partition("@")
        if host != dominio:
            continue
        ruc = re.sub(r"\D", "", local)
        if len(ruc) == 13 and ruc not in candidatos:
            candidatos.append(ruc)

    # Si el mensaje apunta a MÁS de un buzón no se elige el primero: no hay
    # forma de saber cuál era el destino real, y adjudicarlo a ciegas metería el
    # documento de un inquilino dentro del ámbito de otro.
    if len(candidatos) != 1:
        return None

    fila = db.execute(
        text("SELECT id FROM sys_tenant_por_buzon(:ruc)"), {"ruc": candidatos[0]}
    ).first()
    return fila[0] if fila is not None else None
