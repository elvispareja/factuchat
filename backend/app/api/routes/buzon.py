"""Retenciones recibidas del inquilino y webhook del buzón (fase 7).

Dos superficies muy distintas en un mismo archivo:

  · `/retenciones/**` — panel del inquilino. Exige rol CLIENTE y el plan que
    incluye la bandeja (`archivos`), igual que la maqueta.
  · `/buzon/webhook` — correo entrante. Es público por fuerza, así que va
    firmado con HMAC sobre el cuerpo crudo y sin secreto configurado rechaza
    TODO: nunca falla abierto.
"""

from __future__ import annotations

import base64
import hmac
import logging
import uuid
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.exceptions import InvalidTag
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, client_ip, require_roles, tenant_de
from app.buzon import correo as correo_mod
from app.buzon.ingesta import (
    BuzonError,
    RetencionDuplicada,
    RetencionRechazada,
    leer_cifrado,
    registrar_manual,
)
from app.buzon.parser import MAX_XML_BYTES, BuzonParseError
from app.core.config import get_settings
from app.db.models import RetencionRecibida, Tenant
from app.db.models.enums import Rol
from app.db.session import despues_del_commit, get_db
from app.services import parametros, retenciones
from app.services.planes import LimitePlanError, exigir_funcion, plan_vigente
from app.tasks.buzon import ingerir_correo, verificar_retencion

logger = logging.getLogger("factuchat.buzon")

router = APIRouter(tags=["buzon"])
SOLO_CLIENTE = require_roles(Rol.CLIENTE)
TZ = ZoneInfo("America/Guayaquil")


def _error_plan(e: LimitePlanError) -> HTTPException:
    return HTTPException(
        status.HTTP_402_PAYMENT_REQUIRED,
        detail={"mensaje": e.mensaje, "funcion": e.funcion, "plan_sugerido": e.plan_sugerido},
    )


def _exigir_bandeja(db: Session, tenant_id: uuid.UUID) -> None:
    try:
        exigir_funcion(plan_vigente(db, tenant_id), "archivos")
    except LimitePlanError as e:
        raise _error_plan(e) from e


@router.get("/retenciones")
def bandeja(
    user: AuthUser = Depends(SOLO_CLIENTE),
    db: Session = Depends(get_db),
):
    """El crédito acumulado y la lista de comprobantes recibidos.

    Con el módulo apagado la respuesta es la de un buzón vacío, no un error: el
    cliente no debe enterarse de que existe una función que aún no se ha
    encendido.
    """
    tenant_id = tenant_de(user)
    _exigir_bandeja(db, tenant_id)

    hoy = datetime.now(TZ).date()
    desde, hasta = retenciones.semestre_de(hoy)
    credito = retenciones.saldo(db, tenant_id, desde, hasta)
    filas = retenciones.listar(db, tenant_id, desde, hasta)

    return {
        "activo": retenciones.activo(db),
        "buzon": _direccion_visible(db, tenant_id),
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        # «Saldo a tu favor» de la maqueta: renta + IVA juntos, para mostrar
        "saldo": str(credito.total),
        "saldo_renta": str(credito.renta),
        "saldo_iva": str(credito.iva),
        "documentos": credito.documentos,
        "agentes": credito.agentes,
        "retenciones": [retenciones.a_json(r) for r in filas],
    }


@router.post("/retenciones", status_code=status.HTTP_201_CREATED)
def subir_retencion(
    archivo: UploadFile = File(...),
    user: AuthUser = Depends(SOLO_CLIENTE),
    db: Session = Depends(get_db),
):
    """Registrar a mano el comprobante de retención que le entregaron al cliente.

    Vive aquí, junto al GET, porque es la MISMA colección con las MISMAS
    garantías: cambia la puerta de entrada —un fichero subido en vez de un
    correo—, no lo que hay que comprobar antes de convertir un XML en crédito
    tributario. Hace falta porque el buzón por correo está apagado y al cliente
    le retienen igual: su cliente le manda el XML por WhatsApp o se lo da
    impreso, y hasta ahora no había por dónde meterlo.

    Lo que NO cambia respecto al correo: el comprobante tiene que retener a ESTE
    inquilino, no puede estar ya registrada y nace SIN verificar, así que se ve
    en la bandeja pero no suma al saldo hasta que el SRI conteste.
    """
    tenant_id = tenant_de(user)
    # Misma puerta que la bandeja, a propósito: registrar una retención que
    # después no se puede ver no le sirve a nadie. Los planes sin la función
    # «archivos» no registran retenciones, ni por correo ni a mano.
    _exigir_bandeja(db, tenant_id)
    tenant = db.get(Tenant, tenant_id)  # RLS: solo puede ser el suyo
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos tu ficha de contribuyente")

    # El tope de tamaño es esta lectura acotada: lo que pase de ahí no llega a
    # memoria, y el parser —que ya trae las defensas de XML— lo rechaza con su
    # motivo. Ni la extensión ni el content-type deciden nada: los pone quien
    # sube el fichero.
    datos = archivo.file.read(MAX_XML_BYTES + 1)
    try:
        retencion = registrar_manual(db, tenant, datos)
    except RetencionDuplicada as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except (BuzonParseError, RetencionRechazada) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    # Se le pregunta al SRI DESPUÉS del commit: encolar antes deja al worker
    # buscando una fila que todavía no existe. Es el mismo camino que usa el
    # buzón, y el único que pone `verificada` en cierto.
    rid = str(retencion.id)
    despues_del_commit(db, lambda: verificar_retencion.delay(str(tenant_id), rid))
    return retenciones.a_json(retencion)


def _direccion_visible(db: Session, tenant_id: uuid.UUID) -> str | None:
    """La dirección del buzón solo se publica si el módulo está encendido: dar
    una dirección que todavía no recibe nada sería peor que no darla."""
    if not retenciones.activo(db):
        return None
    tenant = db.get(Tenant, tenant_id)
    return correo_mod.direccion_de_tenant(tenant.ruc) if tenant else None


@router.get("/retenciones/{retencion_id}/xml")
def descargar_xml(
    retencion_id: uuid.UUID,
    user: AuthUser = Depends(SOLO_CLIENTE),
    db: Session = Depends(get_db),
):
    """El XML original, descifrado al vuelo. Custodia de siete años."""
    tenant_id = tenant_de(user)
    _exigir_bandeja(db, tenant_id)

    fila = db.get(RetencionRecibida, retencion_id)  # RLS: solo del propio tenant
    if fila is None or not fila.xml_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa retención no tiene XML guardado")
    # El interruptor cubre el buzón entero, listado y descargas; lo que el
    # cliente subió él mismo no lo esconde un módulo que no ha estrenado.
    if not retenciones.activo(db) and fila.origen != retenciones.ORIGEN_MANUAL:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa retención no tiene XML guardado")
    try:
        datos = leer_cifrado(fila.xml_path)
    except (BuzonError, OSError, ValueError, InvalidTag) as e:
        logger.warning("No se pudo descifrar el XML de %s: %s", retencion_id, e)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "No pudimos abrir el archivo. Inténtalo más tarde."
        ) from e

    nombre = f"retencion-{fila.numero.replace('/', '-')}.xml"
    return Response(
        content=datos,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# --------------------------------------------------------------------------
# Correo entrante
# --------------------------------------------------------------------------


# Router aparte, montado SIN el candado de firma: al webhook lo llama el
# proveedor de correo, que no tiene sesión ni certificado. Si colgara del
# router del cliente, exigirle firma lo dejaría devolviendo 401 a todo.
router_webhook = APIRouter(tags=["buzon"])


@router_webhook.post("/buzon/webhook", status_code=status.HTTP_202_ACCEPTED)
async def webhook_correo(request: Request):
    """Recibe un correo entrante en crudo (message/rfc822).

    La firma se calcula sobre el CUERPO CRUDO, antes de mirar nada de él. Sin
    `BUZON_WEBHOOK_SECRET` configurado se rechaza todo: un buzón que acepta
    documentos sin firmar deja que cualquiera altere la declaración de impuestos
    de un cliente.
    """
    s = get_settings()
    if not s.buzon_webhook_secret:
        # Silencio deliberado: no se confirma ni que el endpoint exista
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    crudo = await request.body()
    if len(crudo) > s.buzon_max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Mensaje demasiado grande")

    firma = request.headers.get("X-Buzon-Signature", "")
    esperada = "sha256=" + hmac.new(s.buzon_webhook_secret.encode(), crudo, sha256).hexdigest()
    # compare_digest solo admite cadenas ASCII: una firma con cualquier byte
    # fuera de ese rango lanzaría TypeError y devolvería un 500 en vez de un 403.
    if not firma.isascii() or not hmac.compare_digest(firma, esperada):
        logger.warning("Webhook de buzón con firma inválida")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No autorizado")

    # El destinatario del SOBRE (RCPT TO) lo entrega el proveedor aparte del
    # mensaje. Es el único dato que dice de verdad a quién iba dirigido: las
    # cabeceras To y Cc las escribe el remitente.
    destinatario = request.headers.get("X-Buzon-Recipient")

    # Se responde rápido y el trabajo real va a la cola: el proveedor de correo
    # reintenta si tardamos, y reintentar duplicaría el mensaje.
    ingerir_correo.delay(base64.b64encode(crudo).decode(), destinatario)
    return {"aceptado": True}


# --------------------------------------------------------------------------
# Panel interno
# --------------------------------------------------------------------------

router_interno = APIRouter(prefix="/sa/buzon", tags=["superadmin"])
SOLO_INTERNO = require_roles(Rol.SUPERADMIN, Rol.SOPORTE, Rol.LECTURA)
SOLO_SUPERADMIN = require_roles(Rol.SUPERADMIN)


@router_interno.get("")
def correos(
    limite: int = Query(default=100, le=300),
    user: AuthUser = Depends(SOLO_INTERNO),
    db: Session = Depends(get_db),
):
    """Los correos recibidos por inquilino, con el estado del parseo."""
    from sqlalchemy import select

    from app.db.models import BuzonCorreo

    filas = list(
        db.scalars(select(BuzonCorreo).order_by(BuzonCorreo.recibido_at.desc()).limit(limite)).all()
    )
    # El nombre y el RUC del inquilino NO se traen con un JOIN: `tenants` está
    # cerrada incluso para el personal interno (política de 0002) y se consulta
    # por la función segura sa_tenant_basico, que ya existe para esto.
    fichas = {tid: _ficha(db, tid) for tid in {f.tenant_id for f in filas}}

    return {
        "activo": parametros.buzon_activo(db),
        "dominio": get_settings().dominio_buzon,
        "correos": [
            {
                "id": str(c.id),
                "recibido": c.recibido_at.isoformat(),
                "inquilino": fichas.get(c.tenant_id, {}).get("razon_social", "—"),
                "buzon": (
                    correo_mod.direccion_de_tenant(fichas[c.tenant_id]["ruc"])
                    if fichas.get(c.tenant_id, {}).get("ruc")
                    else None
                ),
                "remitente": c.remitente,
                # La maqueta rotula PROCESADO donde el modelo dice PARSEADO
                "tipo": c.tipo_detectado or "XML adjunto",
                "estado": "PROCESADO" if c.estado.value == "PARSEADO" else c.estado.value,
                "es_error": c.estado.value == "ERROR",
                "motivo_error": c.motivo_error,
            }
            for c in filas
        ],
        "callados": _callados(db),
    }


def _ficha(db: Session, tenant_id: uuid.UUID) -> dict:
    from sqlalchemy import text

    fila = db.execute(
        text("SELECT razon_social, ruc FROM sa_tenant_basico(:t)"), {"t": str(tenant_id)}
    ).first()
    return {"razon_social": fila[0], "ruc": fila[1]} if fila else {}


def _callados(db: Session) -> list[dict]:
    """Inquilinos que llevan demasiado sin recibir nada, como la banda ámbar.

    Va por función segura: cruzar `tenants` con una consulta normal devuelve
    cero filas siempre, porque esa tabla está cerrada también para el personal
    interno. Sin esto, la banda quedaba vacía en producción sin que nada fallara.
    """
    from sqlalchemy import text

    s = get_settings()
    filas = db.execute(text("SELECT razon_social, dias FROM sa_buzones_callados(5)")).all()
    return [
        {"inquilino": f[0], "dias": int(f[1]), "umbral": s.buzon_dias_alerta}
        for f in filas
        if int(f[1]) > 0
    ]


@router_interno.post("/flag")
def alternar_flag(
    activo: bool,
    request: Request,
    user: AuthUser = Depends(SOLO_SUPERADMIN),
    db: Session = Depends(get_db),
):
    """Enciende o apaga el módulo. Solo SUPERADMIN, y queda auditado.

    La escritura en `parametros` la audita sola el listener de la sesión, con
    antes y después; aquí se añade la línea legible que la maqueta muestra en
    Auditoría: «Feature flag BUZON_ACTIVO → true».
    """
    from sqlalchemy import text

    antes = parametros.buzon_activo(db)
    parametros.fijar_bool(db, parametros.BUZON_ACTIVO, activo, user.id)
    db.execute(
        text(
            "INSERT INTO audit_log (id, actor_user_id, actor_rol, accion, tabla, registro_id, "
            "antes, despues, ip, user_agent) VALUES (gen_random_uuid(), :u, :r, :a, "
            "'parametros', NULL, "
            "jsonb_build_object('BUZON_ACTIVO', CAST(:antes AS text)), "
            "jsonb_build_object('BUZON_ACTIVO', CAST(:despues AS text)), :ip, :ua)"
        ),
        {
            "u": user.id,
            "r": user.rol.value,
            "a": f"Feature flag BUZON_ACTIVO → {'true' if activo else 'false'}",
            "antes": "true" if antes else "false",
            "despues": "true" if activo else "false",
            "ip": client_ip(request),
            "ua": (request.headers.get("user-agent") or "")[:400],
        },
    )
    return {
        "activo": activo,
        "etiqueta": f"BUZON_ACTIVO = {'true' if activo else 'false'}",
        "mensaje": (
            f"Feature flag BUZON_ACTIVO → {'true' if activo else 'false'} · registrado en auditoría"
        ),
    }


@router_interno.get("/{correo_id}/crudo")
def xml_crudo(
    correo_id: uuid.UUID,
    user: AuthUser = Depends(SOLO_INTERNO),
    db: Session = Depends(get_db),
):
    """El visor de «XML crudo» de la maqueta.

    El contenido del correo NO vive en ninguna columna —eso lo replicaría en
    claro en la bitácora inmutable—: se descifra aquí, bajo demanda, y solo para
    el personal interno.
    """
    from app.db.models import BuzonCorreo

    fila = db.get(BuzonCorreo, correo_id)
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ese correo no existe")
    if not fila.payload_path or not Path(fila.payload_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El mensaje ya no está almacenado")
    try:
        crudo = leer_cifrado(fila.payload_path)
    except (BuzonError, OSError, ValueError, InvalidTag) as e:
        # Clave rotada o blob corrupto: es el fallo MÁS probable de esta ruta y
        # sin capturarlo el panel devolvía un 500 sin explicación.
        logger.warning("No se pudo descifrar el correo %s: %s", correo_id, e)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "No pudimos descifrar el mensaje"
        ) from e

    entrante = correo_mod.leer_correo(crudo)
    extracto = ""
    if entrante.xmls:
        extracto = entrante.xmls[0].datos[:4000].decode("utf-8", "replace")
    return {
        "id": str(fila.id),
        "estado": fila.estado.value,
        "motivo_error": fila.motivo_error,
        # La maqueta muestra el volcado y, entre corchetes, el motivo del fallo
        "xml": extracto + (f"\n\n[{fila.motivo_error}]" if fila.motivo_error else ""),
    }
