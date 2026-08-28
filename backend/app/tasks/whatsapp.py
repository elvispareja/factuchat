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

from app.core.context import RequestContext
from app.db.models import Tenant
from app.db.models.enums import CategoriaMsg, DireccionMsg
from app.db.session import apply_rls_context, get_sessionmaker
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


def _a_entrante(m: dict) -> Entrante:
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
    )


def _despachar(db: Session, tenant_id: uuid.UUID, destino: str, respuesta: Respuesta) -> None:
    """Envía una respuesta y registra su consumo."""
    try:
        if respuesta.botones:
            enviado = wa.enviar_botones(destino, respuesta.texto, respuesta.botones)
            tipo = "INTERACTIVO"
        elif respuesta.lista:
            enviado = wa.enviar_lista(
                destino, respuesta.texto, respuesta.boton_lista, respuesta.lista
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


def procesar_mensaje(payload: dict[str, Any], enviar: bool = True) -> list[Respuesta]:
    """Núcleo testeable: con enviar=False no toca la red."""
    respuestas_totales: list[Respuesta] = []

    for m in _extraer_mensajes(payload):
        entrante = _a_entrante(m)
        if not entrante.wa_phone:
            continue

        with _sesion_sistema() as db:
            try:
                tenant = tenant_por_telefono(db, entrante.wa_phone)
                tenant_id = tenant.id
            except NumeroNoAutorizado as e:
                # No se responde a números desconocidos: contestar confirmaría
                # que el número existe y abriría una conversación que se cobra.
                logger.info("Mensaje de número no autorizado %s: %s", entrante.wa_phone, e)
                continue

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
