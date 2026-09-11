"""Procesamiento de webhooks de WhatsApp en Celery (fase 5).

El webhook responde 200 al instante y el trabajo real ocurre aquí: si tardara,
Meta reintentaría y se procesaría dos veces el mismo mensaje.
"""

import json
import logging
import uuid
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import RequestContext
from app.db.models import Tenant
from app.db.models.enums import CategoriaMsg, DireccionMsg
from app.db.session import apply_rls_context, get_sessionmaker
from app.services import verificacion_numero
from app.whatsapp import cliente as wa
from app.whatsapp import consumo
from app.whatsapp.asistente import Entrante, NumeroNoAutorizado, procesar, tenant_por_telefono
from app.whatsapp.conversacion import Respuesta
from app.worker import celery_app

logger = logging.getLogger("factuchat.whatsapp")


@contextmanager
def _sesion_sistema():
    """Sesión SIN tenant: se usa solo para resolver a quién pertenece el número."""
    db: Session = get_sessionmaker()()
    try:
        ctx = RequestContext(rol="SYSTEM")
        db.info["audit_ctx"] = ctx
        apply_rls_context(db, ctx, is_internal=True)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def _sesion_tenant(tenant_id: uuid.UUID):
    db: Session = get_sessionmaker()()
    try:
        ctx = RequestContext(tenant_id=tenant_id, rol="SYSTEM")
        db.info["audit_ctx"] = ctx
        apply_rls_context(db, ctx, is_internal=False)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _extraer_mensajes(payload: dict[str, Any]) -> list[dict]:
    """Aplana la estructura anidada de Meta: entry → changes → value.messages."""
    salida = []
    for entry in payload.get("entry", []):
        for cambio in entry.get("changes", []):
            valor = cambio.get("value", {})
            for m in valor.get("messages", []):
                salida.append(m)
    return salida


def _nombres_de_contacto(payload: dict[str, Any]) -> dict[str, str]:
    """Meta manda, junto a cada mensaje, el nombre del perfil del remitente
    (value.contacts). Es lo que usa el saludo de primer contacto."""
    nombres: dict[str, str] = {}
    for entry in payload.get("entry", []):
        for cambio in entry.get("changes", []):
            for c in (cambio.get("value") or {}).get("contacts", []):
                wa_id = c.get("wa_id")
                # Lo escribe el remitente: fuera caracteres de control y largo acotado
                crudo = str((c.get("profile") or {}).get("name") or "")
                nombre = "".join(ch for ch in crudo if ch.isprintable()).strip()[:80]
                if wa_id and nombre:
                    nombres[wa_id] = nombre
    return nombres


def _extraer_estados(payload: dict[str, Any]) -> list[dict]:
    """Los acuses de Meta sobre lo que enviamos NOSOTROS: sent, delivered, failed."""
    salida = []
    for entry in payload.get("entry", []):
        for cambio in entry.get("changes", []):
            for s in (cambio.get("value") or {}).get("statuses", []):
                salida.append(s)
    return salida


def _registrar_estados(payload: dict[str, Any]) -> None:
    """Deja constancia de los envíos que Meta NO consiguió entregar.

    IMPORTA MÁS DE LO QUE PARECE. La API responde 200 con un identificador de
    mensaje en cuanto ACEPTA el envío, no cuando lo entrega. Si el destinatario
    no tiene WhatsApp, si la cuenta no tiene método de pago o si la plantilla
    está sin aprobar, el mensaje muere después y el motivo viaja solo por aquí.

    Hasta ahora estos avisos se descartaban sin mirarlos, así que un envío
    fallido era indistinguible de uno entregado y la única pista era que el
    cliente dijera «no me llega nada»."""
    for s in _extraer_estados(payload):
        estado = s.get("status")
        destino = s.get("recipient_id", "?")
        if estado != "failed":
            logger.info("WhatsApp %s -> %s (%s)", estado, destino, s.get("id"))
            continue
        for err in s.get("errors") or [{}]:
            logger.warning(
                "WhatsApp NO ENTREGADO a %s: [%s] %s — %s",
                destino,
                err.get("code"),
                err.get("title") or err.get("message") or "sin título",
                (err.get("error_data") or {}).get("details") or "sin detalle",
            )


def _a_entrante(m: dict, nombres: dict[str, str] | None = None) -> Entrante:
    tipo = (m.get("type") or "text").upper()
    texto = ""
    boton_id = None
    lista_id = None

    if tipo == "TEXT":
        texto = (m.get("text") or {}).get("body", "")
        tipo = "TEXTO"
    elif tipo == "INTERACTIVE":
        inter = m.get("interactive") or {}
        if inter.get("type") == "button_reply":
            boton_id = (inter.get("button_reply") or {}).get("id")
            texto = (inter.get("button_reply") or {}).get("title", "")
        elif inter.get("type") == "list_reply":
            lista_id = (inter.get("list_reply") or {}).get("id")
            texto = (inter.get("list_reply") or {}).get("title", "")
        tipo = "INTERACTIVO"
    elif tipo in ("AUDIO", "VOICE"):
        tipo = "AUDIO"
    elif tipo == "VIDEO":
        tipo = "VIDEO"

    return Entrante(
        wa_phone=m.get("from", ""),
        texto=texto,
        tipo=tipo,
        boton_id=boton_id,
        lista_id=lista_id,
        wa_message_id=m.get("id"),
        nombre=(nombres or {}).get(m.get("from", "")) or None,
    )


def _despachar(db: Session, tenant_id: uuid.UUID, destino: str, respuesta: Respuesta) -> None:
    """Envía una respuesta y registra su consumo."""
    try:
        if respuesta.botones:
            enviado = wa.enviar_botones(
                destino, respuesta.texto, respuesta.botones, pie=respuesta.pie
            )
            tipo = "INTERACTIVO"
        elif respuesta.lista:
            enviado = wa.enviar_lista(
                destino,
                respuesta.texto,
                respuesta.boton_lista,
                respuesta.lista,
                titulo_seccion=respuesta.titulo_lista,
                pie=respuesta.pie,
            )
            tipo = "INTERACTIVO"
        else:
            enviado = wa.enviar_texto(destino, respuesta.texto)
            tipo = "TEXTO"
    except (wa.WhatsAppError, wa.WhatsAppTransientError) as e:
        logger.error("No se pudo responder a %s: %s", destino, e)
        raise

    # Responder dentro de la ventana abierta por el usuario no abre conversación
    # nueva: por eso la categoría es SERVICIO y no se cobra aparte.
    consumo.registrar(
        db,
        tenant_id=tenant_id,
        wa_phone=destino,
        direccion=DireccionMsg.SALIENTE,
        categoria=CategoriaMsg.SERVICIO,
        tipo=tipo,
        contenido={"texto": respuesta.texto[:1000]},
        wa_message_id=enviado.wa_message_id or None,
    )


def _verificar_por_chat(db: Session, entrante: Entrante) -> uuid.UUID | None:
    """¿Este mensaje es el código que faltaba? Devuelve el inquilino si sí.

    Se hace en la sesión de SISTEMA, la única que aún no sabe de quién es el
    número: la comprobación va por función segura (`sys_verificar_numero`), que
    es la misma que usa el panel, con su caducidad y su contador de intentos.
    """
    codigo = verificacion_numero.codigo_en(entrante.texto)
    if entrante.tipo != "TEXTO" or codigo is None:
        return None
    if verificacion_numero.comprobar(db, entrante.wa_phone, codigo) != "ok":
        return None

    logger.info("Número %s verificado por chat", entrante.wa_phone)
    try:
        # Ya verificado, la misma consulta de siempre lo resuelve.
        return tenant_por_telefono(db, entrante.wa_phone).id
    except NumeroNoAutorizado:
        # El inquilino se dio de baja entre el alta y el código.
        return None


def procesar_mensaje(payload: dict[str, Any], enviar: bool = True) -> list[Respuesta]:
    """Núcleo testeable: con enviar=False no toca la red."""
    respuestas_totales: list[Respuesta] = []

    # Los acuses de entrega llegan por el mismo webhook que los mensajes.
    _registrar_estados(payload)

    nombres = _nombres_de_contacto(payload)
    for m in _extraer_mensajes(payload):
        entrante = _a_entrante(m, nombres)
        if not entrante.wa_phone:
            continue

        with _sesion_sistema() as db:
            try:
                tenant = tenant_por_telefono(db, entrante.wa_phone)
                tenant_id = tenant.id
            except NumeroNoAutorizado as e:
                # SEGUNDO CAMINO DEL CÓDIGO DE VERIFICACIÓN. Un número que
                # todavía no factura puede estar esperando su código, y
                # escribirlo desde ese mismo teléfono prueba que es suyo mejor
                # que recibir nada. Además es gratis: la conversación la abre el
                # usuario, así que no hace falta plantilla de Meta.
                #
                # Esto NO abre la puerta que cierra el comentario de abajo: solo
                # se sigue adelante si el mensaje trae un código que nosotros
                # emitimos para ESE número. A quien pruebe suerte no se le
                # contesta, así que sigue sin poder averiguar si existe.
                recien_verificado = _verificar_por_chat(db, entrante)
                if recien_verificado is None:
                    # No se responde a números desconocidos: contestar
                    # confirmaría que el número existe y abriría una
                    # conversación que se cobra.
                    logger.info("Mensaje de número no autorizado %s: %s", entrante.wa_phone, e)
                    continue
                tenant_id = recien_verificado

        with _sesion_tenant(tenant_id) as db:
            # Ya con el contexto del inquilino, RLS deja leer su propia ficha
            tenant = db.get(Tenant, tenant_id)
            if tenant is None:
                logger.warning("El inquilino %s desapareció entre sesiones", tenant_id)
                continue

            # El mensaje del usuario abre la ventana de 24 h (Meta no la cobra)
            consumo.registrar(
                db,
                tenant_id=tenant_id,
                wa_phone=entrante.wa_phone,
                direccion=DireccionMsg.ENTRANTE,
                categoria=CategoriaMsg.USUARIO,
                tipo=entrante.tipo,
                contenido={"texto": entrante.texto[:1000]},
                wa_message_id=entrante.wa_message_id,
            )

            respuestas = procesar(db, tenant, entrante)
            respuestas_totales.extend(respuestas)

            if enviar:
                for r in respuestas:
                    _despachar(db, tenant_id, entrante.wa_phone, r)

    return respuestas_totales


@celery_app.task(
    name="factuchat.whatsapp.webhook",
    autoretry_for=(wa.WhatsAppTransientError,),
    retry_backoff=5,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def procesar_webhook(cuerpo: str) -> str:
    try:
        payload = json.loads(cuerpo)
    except json.JSONDecodeError:
        logger.warning("Webhook con cuerpo no JSON")
        return "invalido"
    procesar_mensaje(payload)
    return "ok"


@celery_app.task(name="factuchat.whatsapp.aviso", acks_late=True)
def enviar_aviso(tenant_id: str, wa_phone: str, aviso: str, datos: dict) -> str:
    """Envía una plantilla de aviso. Abre conversación de EMPRESA, que Meta
    cobra: por eso su costo se imputa aquí (fase 5.3 y 5.4)."""
    from app.whatsapp.plantillas import Aviso, preparar

    # El texto puede venir editado desde Configuración: se lee en su propia
    # sesión corta, ANTES de llamar a Meta. Mantener una transacción abierta
    # durante una llamada HTTP es pedir que se acumulen conexiones muertas.
    with _sesion_tenant(uuid.UUID(tenant_id)) as db:
        plantilla, valores, vista = preparar(db, Aviso(aviso), datos)

    enviado = wa.enviar_plantilla(wa_phone, plantilla.nombre, plantilla.idioma, valores)

    with _sesion_tenant(uuid.UUID(tenant_id)) as db:
        consumo.registrar(
            db,
            tenant_id=uuid.UUID(tenant_id),
            wa_phone=wa_phone,
            direccion=DireccionMsg.SALIENTE,
            categoria=CategoriaMsg.EMPRESA,
            tipo="PLANTILLA",
            contenido={"plantilla": plantilla.nombre, "vista_previa": vista[:1000]},
            wa_message_id=enviado.wa_message_id or None,
        )
    return "enviado"


@celery_app.task(name="factuchat.whatsapp.codigo_verificacion", acks_late=True)
def enviar_codigo_verificacion(tenant_id: str, numero: str, codigo: str) -> str:
    """Manda por WhatsApp el código que autoriza a un teléfono a facturar.

    Va por PLANTILLA porque ese número, por definición, todavía no nos ha
    escrito: fuera de la ventana de 24 h Meta no deja texto libre. Y la
    plantilla tiene que ser de categoría AUTHENTICATION y estar APROBADA.

    SIN PLANTILLA CONFIGURADA NO ES UN FALLO. El código sigue llegando por el
    otro camino —que la persona lo escriba al bot desde ese teléfono—, que no
    depende de Meta y no cuesta nada. Por eso esto no reintenta ni propaga: que
    el envío no salga no puede dejar al cliente sin poder verificar.
    """
    s = get_settings()
    if not s.wa_plantilla_verificacion:
        logger.info("Sin plantilla de verificación: el código de %s solo vale por el chat", numero)
        return "sin_plantilla"

    try:
        enviado = wa.enviar_codigo(
            numero, s.wa_plantilla_verificacion, s.wa_plantilla_verificacion_idioma, codigo
        )
    except (wa.WhatsAppError, wa.WhatsAppTransientError) as e:
        logger.warning("No se pudo enviar el código de verificación a %s: %s", numero, e)
        return "fallo"

    with _sesion_tenant(uuid.UUID(tenant_id)) as db:
        # El CÓDIGO NO SE GUARDA en el contenido: la bitácora de mensajes la lee
        # el personal interno, y ahí dejaría de ser un secreto.
        consumo.registrar(
            db,
            tenant_id=uuid.UUID(tenant_id),
            wa_phone=numero,
            direccion=DireccionMsg.SALIENTE,
            categoria=CategoriaMsg.EMPRESA,
            tipo="PLANTILLA",
            contenido={"plantilla": s.wa_plantilla_verificacion, "motivo": "verificacion"},
            wa_message_id=enviado.wa_message_id or None,
        )
    return "enviado"
