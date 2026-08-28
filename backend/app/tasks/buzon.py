"""Tareas del buzón SRI (fase 7.1).

Dos trabajos:
  · `ingerir_correo` — un correo entrante, del sobre crudo al crédito sumado.
  · `barrer_buzones_callados` — el recordatorio de los 30 días sin recibir nada.

El barrido sigue el molde del de comprobantes atascados: consulta global con la
conexión de administración que devuelve SOLO identificadores, y después un task
por inquilino que actúa DENTRO de su contexto RLS. La conexión de administración
ignora las políticas de fila, así que jamás debe usarse para leer o escribir
datos de un inquilino, solo para saber a quiénes hay que mirar.
"""

from __future__ import annotations

import base64
import logging
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.buzon import correo as correo_mod
from app.buzon import ingesta, verificacion
from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.mailer import enviar_correo
from app.core.ratelimit import get_redis
from app.db.models import RetencionRecibida, Tenant
from app.db.session import apply_rls_context, get_sessionmaker
from app.services import parametros
from app.worker import celery_app

logger = logging.getLogger("factuchat.buzon")

_LOCK_TTL_S = 300


@contextmanager
def _sesion_sistema():
    """Sesión SIN inquilino: solo para averiguar de quién es una dirección."""
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
        # Confirmado: los ficheros cifrados que se escribieron son buenos
        ingesta.olvidar_archivos(db)
    except Exception:
        db.rollback()
        # Un aborto descarta las filas pero no el disco: sin esta limpieza cada
        # reintento dejaba una copia cifrada huérfana que nadie podía relacionar.
        ingesta.limpiar_archivos(db)
        raise
    finally:
        db.close()


class CandadoOcupado(Exception):
    """Otro proceso tiene el correo. NO es un final: hay que volver a intentarlo.

    Si esto se tratara como éxito, Celery haría ACK y el mensaje desaparecería
    del broker. Y el candado puede estar tomado por un worker MUERTO (su
    `finally` no llegó a correr y su transacción se revirtió), así que el correo
    se perdería para siempre: sin fila en la base, sin estado de error y sin
    nadie que lo vuelva a entregar.
    """


@contextmanager
def _candado(clave: str):
    """Un correo a la vez. Celery corre con acks_late y reintentos: sin esto,
    dos ejecuciones simultáneas del mismo mensaje sumarían la retención dos
    veces antes de que ninguna de las dos vea a la otra en la base."""
    r = get_redis()
    token = uuid.uuid4().hex
    if not r.set(clave, token, nx=True, ex=_LOCK_TTL_S):
        yield False
        return
    try:
        yield True
    finally:
        if r.get(clave) == token:
            r.delete(clave)


@celery_app.task(
    name="factuchat.buzon.ingerir_correo",
    bind=True,
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=900,
    acks_late=True,
)
def ingerir_correo(self, crudo_b64: str, destinatario: str | None = None) -> str:
    """Procesa un correo entrante. Recibe el mensaje MIME en base64.

    `destinatario` es el RCPT TO del sobre, que el proveedor de correo entrega
    aparte del mensaje: es lo único que dice de verdad a quién iba dirigido.
    """
    try:
        crudo = base64.b64decode(crudo_b64)
    except Exception:  # noqa: BLE001 — un cuerpo ilegible no se reintenta
        logger.warning("Correo de buzón con cuerpo no decodificable")
        return "cuerpo-invalido"

    try:
        return ingerir(crudo, destinatario)
    except CandadoOcupado as exc:
        # Vuelve a la cola con espera: quien lo tiene puede estar muerto
        raise self.retry(exc=exc, countdown=60, max_retries=20) from exc
    except Exception as exc:  # noqa: BLE001 — el reintento es el manejo
        logger.warning("Fallo al ingerir correo del buzón: %s", exc)
        raise self.retry(exc=exc) from exc


def ingerir(crudo: bytes, destinatario: str | None = None) -> str:
    """Ingesta síncrona, reutilizable desde el webhook, el IMAP y los tests."""
    s = get_settings()
    if len(crudo) > s.buzon_max_bytes:
        logger.warning("Correo de buzón descartado por tamaño (%d bytes)", len(crudo))
        return "demasiado-grande"

    entrante = correo_mod.leer_correo(crudo, destinatario)

    with _sesion_sistema() as db:
        tenant_id = ingesta.resolver_tenant(db, entrante)
    if tenant_id is None:
        # Un correo a una dirección desconocida no tiene dueño, y NO se inventa
        # uno: escribirlo con contexto interno lo pondría fuera de toda política
        # de aislamiento. Se descarta dejando rastro en el registro.
        logger.info(
            "Correo de buzón sin destinatario conocido (%s)",
            ", ".join(entrante.destinatarios) or "sin destinatarios",
        )
        return "sin-destinatario"

    with _candado(f"buzon:lock:{tenant_id}:{entrante.message_id}") as tomado:
        if not tomado:
            raise CandadoOcupado(entrante.message_id)
        nuevas: list[str] = []
        with _sesion_tenant(tenant_id) as db:
            tenant_local = db.get(Tenant, tenant_id)
            if tenant_local is None:
                return "sin-destinatario"
            fila, nuevo = ingesta.registrar(db, tenant_local, entrante)
            if not nuevo:
                return "duplicado"
            ingesta.procesar(db, tenant_local, fila, entrante)
            nuevas = [str(r.id) for r in ingesta.recien_creadas(db)]
            # Recibir algo reabre el reloj del recordatorio de los 30 días
            tenant_local.buzon_alertado_at = None
            estado = fila.estado.value.lower()

        # Una retención solo cuenta como crédito cuando el SRI lo confirma. Se
        # pregunta FUERA de la transacción y después del commit: la consulta es
        # de red y no puede tener abierta una transacción de base de datos.
        for retencion_id in nuevas:
            verificar_retencion.delay(str(tenant_id), retencion_id)
        return estado


@celery_app.task(
    name="factuchat.buzon.verificar_retencion",
    bind=True,
    max_retries=12,
    retry_backoff=True,
    retry_backoff_max=3600,
    acks_late=True,
)
def verificar_retencion(self, tenant_id: str, retencion_id: str) -> str:
    """Pregunta al SRI si esa retención está realmente autorizada.

    Hasta que responda que sí, la retención está guardada y visible pero NO
    cuenta para el saldo: nadie puede bajarle el IVA a un contribuyente con un
    XML que se escribió a sí mismo.
    """
    tid = uuid.UUID(tenant_id)
    with _sesion_tenant(tid) as db:
        retencion = db.get(RetencionRecibida, uuid.UUID(retencion_id))
        if retencion is None:
            return "no-existe"
        if retencion.verificada:
            return "ya-verificada"
        ambiente = verificacion.ambiente_de(db, tid)
        try:
            ok = verificacion.verificar(db, retencion, ambiente)
        except verificacion.VerificacionPendiente as exc:
            # El SRI no contestó. Un problema de red no es un veredicto: se
            # reintenta y la retención sigue sin contar mientras tanto.
            raise self.retry(exc=exc) from exc
    return "verificada" if ok else "no-autorizada"


# --------------------------------------------------------------------------
# Recordatorio de buzón callado
# --------------------------------------------------------------------------


def _buzones_callados(dias: int) -> list[tuple[str, str, str]]:
    """Inquilinos activos que no han recibido nada en `dias`.

    Consulta global con la conexión de administración —que ignora RLS— y por eso
    devuelve SOLO identificadores y datos de contacto del propio inquilino:
    ninguna fila del buzón de nadie sale de aquí.
    """
    s = get_settings()
    engine = create_engine(s.database_url_admin, pool_pre_ping=True)
    corte = datetime.now(UTC) - timedelta(days=dias)
    try:
        with engine.connect() as conn:
            filas = conn.execute(
                text(
                    """
                    SELECT t.id::text, t.razon_social, t.email
                      FROM tenants t
                     WHERE t.estado = 'ACTIVO'
                       AND t.buzon_alertado_at IS NULL
                       AND t.created_at < :corte
                       AND NOT EXISTS (
                           SELECT 1 FROM buzon_correos b
                            WHERE b.tenant_id = t.id AND b.recibido_at >= :corte
                       )
                    """
                ),
                {"corte": corte},
            ).all()
        return [(f[0], f[1], f[2]) for f in filas]
    finally:
        engine.dispose()


@celery_app.task(name="factuchat.buzon.barrer_buzones_callados", acks_late=True)
def barrer_buzones_callados() -> int:
    """Avisa a quien lleva demasiado tiempo sin recibir nada en su buzón.

    Con el módulo apagado no se avisa: recomendarle a alguien que configure el
    reenvío de una función que todavía no ve sería incoherente.
    """
    s = get_settings()
    # El flag EFECTIVO vive en la base: el superadmin lo enciende desde el panel
    # y esa decisión pisa al entorno. Mirar solo el entorno dejaba el
    # recordatorio de los 30 días sin dispararse nunca en el camino normal.
    with _sesion_sistema() as db:
        if not parametros.buzon_activo(db):
            return 0
    callados = _buzones_callados(s.buzon_dias_alerta)
    for tenant_id, razon_social, email in callados:
        avisar_buzon_callado.delay(tenant_id, razon_social, email)
    return len(callados)


@celery_app.task(
    name="factuchat.buzon.avisar_buzon_callado",
    bind=True,
    max_retries=5,
    retry_backoff=True,
    acks_late=True,
)
def avisar_buzon_callado(self, tenant_id: str, razon_social: str, email: str) -> str:
    """Recordatorio de configurar el reenvío desde el SRI."""
    s = get_settings()
    direccion = ""
    with _sesion_sistema() as db:
        if not parametros.buzon_activo(db):
            return "modulo-apagado"

    # Se RECLAMA el aviso antes de mandarlo, con un UPDATE condicional: quien se
    # lleva la fila es quien escribe. Marcar después del envío dejaba la puerta
    # abierta a que dos ejecuciones simultáneas —o un reintento tras un fallo al
    # marcar— le mandaran al cliente el mismo recordatorio dos veces.
    with _sesion_tenant(uuid.UUID(tenant_id)) as db:
        tenant = db.get(Tenant, uuid.UUID(tenant_id))
        if tenant is None:
            return "sin-inquilino"
        reclamado = db.execute(
            text(
                "UPDATE tenants SET buzon_alertado_at = :t "
                "WHERE id = :i AND buzon_alertado_at IS NULL"
            ),
            {"t": datetime.now(UTC), "i": tenant_id},
        ).rowcount
        if not reclamado:
            return "ya-avisado"
        direccion = correo_mod.direccion_de_tenant(tenant.ruc)

    asunto = "Tu buzón de Factuchat sigue vacío"
    cuerpo = (
        "<div style='font-family:system-ui,sans-serif;color:#123D2F'>"
        f"<h2 style='margin:0 0 12px'>Hola, {_escapar(razon_social)}</h2>"
        f"<p style='font-size:14px;line-height:1.6'>Llevas {s.buzon_dias_alerta} días sin recibir "
        "ningún documento en tu buzón. Si tus proveedores ya te están enviando comprobantes, "
        "probablemente falte configurar el reenvío desde el portal del SRI.</p>"
        "<p style='font-size:14px;line-height:1.6'>Tu dirección de buzón es:</p>"
        f"<p style='font-family:ui-monospace,monospace;font-size:15px;background:#F4F6F3;"
        f"border-radius:10px;padding:12px 14px'>{_escapar(direccion)}</p>"
        "<p style='font-size:13px;color:#5A7267'>Cada retención que llega ahí es crédito a tu "
        "favor: baja lo que pagas de impuestos.</p></div>"
    )
    try:
        enviar_correo(email, asunto, cuerpo)
    except Exception as exc:  # noqa: BLE001 — el reintento es el manejo
        # No salió: se suelta el reclamo para que el reintento pueda tomarlo
        with _sesion_tenant(uuid.UUID(tenant_id)) as db:
            db.execute(
                text("UPDATE tenants SET buzon_alertado_at = NULL WHERE id = :i"),
                {"i": tenant_id},
            )
        raise self.retry(exc=exc) from exc
    return "avisado"


def _escapar(v: str | None) -> str:
    if not v:
        return ""
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# El beat de emisión ASIGNA beat_schedule; aquí se FUSIONA. Reasignarlo borraría
# el barrido de comprobantes atascados según el orden en que el worker importe
# los módulos, y ese fallo no da error: solo deja facturas colgadas en silencio.
celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "barrer-buzones-callados": {
        "task": "factuchat.buzon.barrer_buzones_callados",
        "schedule": 86400.0,  # una vez al día
    },
}
