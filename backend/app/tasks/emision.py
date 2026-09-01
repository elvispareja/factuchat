"""Pipeline de emisión en Celery (fase 2.5) — NUNCA en el request.

PENDIENTE → (firmar) FIRMADO → (recepción) ENVIADO_SRI → (autorización)
AUTORIZADO | RECHAZADO | DEVUELTO → (si autorizado) RIDE + correo.

Idempotencia: cada paso verifica el estado bajo FOR UPDATE antes de actuar; una
re-ejecución del task retoma donde quedó sin duplicar comprobantes (la clave de
acceso es única). Los errores transitorios del SRI reintentan con backoff
exponencial; el certificado se descifra solo en memoria y JAMÁS se registra.
"""

import logging
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.ratelimit import get_redis
from app.db.models import Certificado, Comprobante, Tenant
from app.db.models.enums import EstadoComprobante
from app.db.session import apply_rls_context, get_sessionmaker
from app.schemas.comprobantes import OPCIONES_PAGO
from app.services.emision import datos_para_xml, ruta_almacen, transicionar
from app.sri import client as sri_client
from app.sri.client import SRIError, SRITransientError, mensajes_a_json
from app.sri.firma import FirmaError, descifrar_p12, firmar_comprobante, huella_sha256
from app.sri.ride import render_ride_factura
from app.sri.xml_builder import construir_factura
from app.worker import celery_app

logger = logging.getLogger("factuchat.emision")

# Vida del candado de emisión: mayor que el peor caso de una pasada completa
# (dos llamadas al SRI con timeout de 30 s + firma + RIDE)
_LOCK_TTL_S = 300

# El RIDE muestra la forma de pago en palabras, no el código de la tabla 24. Se
# reusa el catálogo que ya alimenta al front; un código antiguo fuera de él (la
# tabla tiene 8 y se ofrecen 3) cae al propio código antes que dejar el hueco.
_ETIQUETA_PAGO = {o.codigo: o.etiqueta for o in OPCIONES_PAGO}


class EmisionAbortada(Exception):
    """El flujo terminó en un estado final no autorizado (no se reintenta)."""


@contextmanager
def _sesion_tenant(tenant_id: str):
    """Sesión del worker con contexto RLS del tenant y auditoría de sistema."""
    db: Session = get_sessionmaker()()
    try:
        ctx = RequestContext(tenant_id=uuid.UUID(tenant_id), rol="SYSTEM")
        db.info["audit_ctx"] = ctx
        apply_rls_context(db, ctx, is_internal=False)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _cargar(db: Session, comprobante_id: str) -> Comprobante:
    comp = db.execute(
        select(Comprobante).where(Comprobante.id == uuid.UUID(comprobante_id)).with_for_update()
    ).scalar_one_or_none()
    if comp is None:
        raise EmisionAbortada("Comprobante no encontrado en el tenant")
    return comp


def _paso_firmar(tenant_id: str, comprobante_id: str) -> None:
    with _sesion_tenant(tenant_id) as db:
        comp = _cargar(db, comprobante_id)
        if comp.estado != EstadoComprobante.PENDIENTE:
            return  # ya firmado por una ejecución anterior
        if comp.clave_acceso is None:
            raise EmisionAbortada("El comprobante no tiene clave de acceso (no fue emitido)")
        tenant = db.get(Tenant, comp.tenant_id)
        if tenant is None:
            raise EmisionAbortada("Tenant no disponible")
        cert = db.scalars(select(Certificado).where(Certificado.activo.is_(True))).first()
        if cert is None:
            comp.sri_mensajes = {"errores": [{"legible": "No hay certificado de firma cargado"}]}
            transicionar(comp, EstadoComprobante.RECHAZADO)
            return
        if cert.valido_hasta is not None and cert.valido_hasta < datetime.now(UTC):
            comp.sri_mensajes = {"errores": [{"legible": "El certificado de firma está caducado"}]}
            transicionar(comp, EstadoComprobante.RECHAZADO)
            return

        emisor, factura = datos_para_xml(tenant, comp)
        xml = construir_factura(emisor, factura)
        try:
            p12, password = descifrar_p12(cert.p12_data_enc, cert.p12_password_enc)
        except Exception:
            # Clave maestra rotada o blob corrupto: sin mensaje, el comprobante
            # quedaría atascado en PENDIENTE para siempre.
            logger.exception("No se pudo descifrar el certificado del tenant %s", tenant_id)
            comp.sri_mensajes = {
                "errores": [
                    {
                        "legible": "No se pudo abrir el certificado de firma. "
                        "Vuelva a cargarlo desde Mi cuenta."
                    }
                ]
            }
            transicionar(comp, EstadoComprobante.RECHAZADO)
            return
        try:
            xml_firmado = firmar_comprobante(xml, p12, password)
        except FirmaError as e:
            comp.sri_mensajes = {"errores": [{"legible": str(e)}]}
            transicionar(comp, EstadoComprobante.RECHAZADO)
            return
        finally:
            del p12, password  # el material sensible no sobrevive al paso

        ruta = ruta_almacen(comp.tenant_id, comp.clave_acceso, "xml")
        ruta.write_bytes(xml_firmado)
        comp.xml_path = str(ruta)
        comp.sha256_xml = huella_sha256(xml_firmado)
        comp.intentos += 1
        transicionar(comp, EstadoComprobante.FIRMADO)
        logger.info("Comprobante %s firmado", comp.clave_acceso)


def _sri_no_lo_tiene(clave: str | None, ambiente: str) -> bool:
    """¿El SRI desconoce esta clave? Solo entonces procede reenviar.

    Ante cualquier duda (error de red, respuesta rara) devuelve False: no
    reenviar y esperar es recuperable; duplicar una factura ante el fisco no.
    """
    if clave is None:
        return False
    try:
        respuesta = sri_client.consultar_autorizacion(clave, ambiente)
    except (SRIError, SRITransientError):
        return False
    return respuesta.estado == "SIN REGISTRO"


def _paso_recepcion(tenant_id: str, comprobante_id: str) -> None:
    # La llamada de red ocurre FUERA de la transacción que actualiza el estado
    with _sesion_tenant(tenant_id) as db:
        comp = _cargar(db, comprobante_id)
        if comp.estado != EstadoComprobante.FIRMADO:
            return
        # Un envío anterior pudo salir sin que llegáramos a confirmarlo (caída
        # del worker tras el POST). No sabemos si llegó, y las dos suposiciones
        # son peligrosas: reenviar a ciegas arriesga duplicar, y no reenviar
        # dejaría colgado un comprobante que nunca salió. Se le pregunta al SRI,
        # que es la única fuente de verdad.
        if comp.enviado_recepcion_at is not None:
            reenviar = _sri_no_lo_tiene(comp.clave_acceso, comp.ambiente.value)
            if not reenviar:
                transicionar(comp, EstadoComprobante.ENVIADO_SRI)
                logger.warning(
                    "Comprobante %s ya estaba en el SRI; se consulta autorización",
                    comp.clave_acceso,
                )
                return
            logger.warning(
                "Comprobante %s no llegó al SRI en el intento anterior; se reenvía",
                comp.clave_acceso,
            )
            comp.enviado_recepcion_at = None
        if not comp.xml_path or not Path(comp.xml_path).exists():
            raise EmisionAbortada("XML firmado no disponible")
        xml_firmado = Path(comp.xml_path).read_bytes()
        ambiente = comp.ambiente.value
        clave = comp.clave_acceso
        # Marca de "en vuelo" CONFIRMADA antes del efecto externo (A10)
        comp.enviado_recepcion_at = datetime.now(UTC)

    respuesta = sri_client.enviar_recepcion(xml_firmado, ambiente)

    with _sesion_tenant(tenant_id) as db:
        comp = _cargar(db, comprobante_id)
        if comp.estado != EstadoComprobante.FIRMADO:
            return
        if respuesta.estado == "RECIBIDA":
            transicionar(comp, EstadoComprobante.ENVIADO_SRI)
            logger.info("Comprobante %s RECIBIDA por el SRI", clave)
        elif sri_client.ya_estaba_registrado(respuesta.mensajes):
            # El SRI ya lo tenía de un envío previo: no es rechazo
            transicionar(comp, EstadoComprobante.ENVIADO_SRI)
            logger.warning("Comprobante %s ya estaba registrado en el SRI", clave)
        else:  # DEVUELTA real: motivo legible para la cola de rechazados
            comp.sri_mensajes = {"recepcion": mensajes_a_json(respuesta.mensajes)}
            transicionar(comp, EstadoComprobante.DEVUELTO)
            logger.warning("Comprobante %s DEVUELTO por recepción", clave)


def _paso_autorizacion(tenant_id: str, comprobante_id: str) -> None:
    with _sesion_tenant(tenant_id) as db:
        comp = _cargar(db, comprobante_id)
        if comp.estado != EstadoComprobante.ENVIADO_SRI:
            return
        ambiente = comp.ambiente.value
        clave = comp.clave_acceso
    if clave is None:
        raise EmisionAbortada("El comprobante no tiene clave de acceso")

    respuesta = sri_client.consultar_autorizacion(clave, ambiente)

    if respuesta.estado in ("EN PROCESO", "SIN REGISTRO"):
        raise SRITransientError("Autorización aún en proceso")

    with _sesion_tenant(tenant_id) as db:
        comp = _cargar(db, comprobante_id)
        if comp.estado != EstadoComprobante.ENVIADO_SRI:
            return
        if respuesta.estado == "AUTORIZADO":
            comp.numero_autorizacion = respuesta.numero_autorizacion or clave
            comp.autorizado_at = datetime.now(UTC)
            comp.sri_mensajes = None
            transicionar(comp, EstadoComprobante.AUTORIZADO)
            logger.info("Comprobante %s AUTORIZADO", clave)
        else:
            comp.sri_mensajes = {"autorizacion": mensajes_a_json(respuesta.mensajes)}
            transicionar(comp, EstadoComprobante.RECHAZADO)
            logger.warning("Comprobante %s NO AUTORIZADO", clave)


def _contexto_ride(tenant: Tenant, comp: Comprobante, emisor: dict) -> dict:
    """Datos que la normativa exige que muestre la representación impresa.

    Sale del payload, que es el snapshot de lo que se mandó al SRI: el RIDE
    tiene que decir lo mismo que el XML autorizado, no lo que hoy diga el
    tenant. La dirección del establecimiento, la forma de pago y la información
    adicional son contenido obligatorio del RIDE aunque no se vean en el panel.
    """
    p = comp.payload
    return {
        "emisor": emisor | {"obligado_contabilidad": tenant.obligado_contabilidad},
        "dir_establecimiento": p.get("dir_establecimiento") or "",
        "establecimiento": comp.establecimiento,
        "punto_emision": comp.punto_emision,
        "secuencial": comp.secuencial,
        "ambiente": comp.ambiente.value,
        # El builder emite siempre <tipoEmision>1</tipoEmision>; si algún día hay
        # contingencia, sale de aquí y la plantilla ya no lo lleva escrito a mano.
        "tipo_emision": "NORMAL",
        "clave_acceso": comp.clave_acceso,
        "numero_autorizacion": comp.numero_autorizacion,
        "fecha_autorizacion": (
            comp.autorizado_at.strftime("%d/%m/%Y %H:%M") if comp.autorizado_at else ""
        ),
        "fecha_emision": comp.fecha_emision.strftime("%d/%m/%Y"),
        "comprador": p["comprador"],
        "items": p["items"],
        "totales": p["totales"],
        "forma_pago": _ETIQUETA_PAGO.get(p.get("forma_pago", ""), p.get("forma_pago", "")),
        "plazo_dias": p.get("plazo_dias"),
        "info_adicional": p.get("info_adicional") or {},
    }


def _paso_ride_y_correo(tenant_id: str, comprobante_id: str) -> None:
    with _sesion_tenant(tenant_id) as db:
        comp = _cargar(db, comprobante_id)
        if comp.estado != EstadoComprobante.AUTORIZADO or comp.clave_acceso is None:
            return
        tenant = db.get(Tenant, comp.tenant_id)
        if tenant is None:
            raise EmisionAbortada("Tenant no disponible")

        ruta = ruta_almacen(comp.tenant_id, comp.clave_acceso, "pdf")
        # El RIDE ya generado no se rehace, pero su existencia NO es la guardia
        # del correo: son pasos independientes con su propia marca.
        if comp.ride_path and ruta.exists():
            pdf = ruta.read_bytes()
        else:
            emisor, _factura = datos_para_xml(tenant, comp)
            try:
                pdf = render_ride_factura(_contexto_ride(tenant, comp, emisor))
            except (OSError, ImportError) as e:
                # Generar el PDF puede fallar por el entorno: WeasyPrint necesita
                # librerías nativas de GTK, y su respaldo (xhtml2pdf) solo está
                # en desarrollo, así que en producción sin GTK sale un
                # ImportError, que NO es OSError y antes escapaba y reventaba la
                # tarea.
                #
                # Llegados aquí el SRI YA autorizó el comprobante y el XML
                # firmado —lo único con validez legal— está guardado. Quedarse
                # sin el PDF no puede invalidar la emisión, ni dejar el
                # comprobante a medias, NI privar al comprador de su factura: se
                # sigue, y el correo sale con el XML solo.
                logger.warning("RIDE no generado para %s: %s", comp.clave_acceso, e)
                pdf = None
            else:
                ruta.write_bytes(pdf)
                comp.ride_path = str(ruta)

        email = comp.payload["comprador"].get("email")
        clave = comp.clave_acceso
        xml_path = comp.xml_path
        razon_social = tenant.razon_social
        correo_pendiente = comp.correo_enviado_at is None

    if email and xml_path and correo_pendiente:
        from app.core.mailer import enviar_correo

        xml_bytes = Path(xml_path).read_bytes()
        # El XML va siempre; el PDF, solo si se pudo generar. Mandar la factura
        # sin su representación impresa es peor que mandarla completa, pero
        # muchísimo mejor que no mandarla: el XML autorizado es el documento.
        adjuntos = [(f"{clave}.xml", xml_bytes, "text", "xml")]
        if pdf is not None:
            adjuntos.insert(0, (f"{clave}.pdf", pdf, "application", "pdf"))
        # Si el envío falla, la excepción sube y Celery reintenta: correo_enviado_at
        # sigue vacío, así que el reintento vuelve a intentarlo (el RIDE ya escrito
        # no bloquea el correo, son guardias independientes).
        enviar_correo(
            destinatario=email,
            asunto=f"Su factura electrónica de {razon_social}",
            cuerpo_html=(
                f"<p>Adjuntamos su factura electrónica autorizada por el SRI.</p>"
                f"<p>Clave de acceso: {clave}</p>"
            ),
            adjuntos=adjuntos,
        )
        with _sesion_tenant(tenant_id) as db:
            comp = _cargar(db, comprobante_id)
            comp.correo_enviado_at = datetime.now(UTC)
        logger.info("RIDE %s enviado por correo", clave)


@contextmanager
def _lock_comprobante(comprobante_id: str):
    """Exclusión mutua por comprobante durante todo el pipeline.

    El lock de BD (FOR UPDATE) se suelta al cerrar cada transacción corta, y las
    llamadas al SRI ocurren FUERA de ellas: sin este candado dos ejecuciones
    simultáneas del task podrían enviar el MISMO XML dos veces a recepción.
    """
    r = get_redis()
    clave = f"emision:lock:{comprobante_id}"
    token = uuid.uuid4().hex
    if not r.set(clave, token, nx=True, ex=_LOCK_TTL_S):
        yield False
        return
    try:
        yield True
    finally:
        # Solo libera si el candado sigue siendo nuestro (no el de un reintento
        # posterior que lo tomó tras expirar el TTL)
        if r.get(clave) == token:
            r.delete(clave)


def ejecutar_pipeline(tenant_id: str, comprobante_id: str) -> str:
    """Cuerpo del pipeline. Deja escapar SRITransientError para que Celery
    reintente con backoff; los tests lo invocan directamente."""
    with _lock_comprobante(comprobante_id) as adquirido:
        if not adquirido:
            logger.info("Comprobante %s ya está siendo procesado", comprobante_id)
            return "en-proceso"
        try:
            _paso_firmar(tenant_id, comprobante_id)
            _paso_recepcion(tenant_id, comprobante_id)
            _paso_autorizacion(tenant_id, comprobante_id)
            _paso_ride_y_correo(tenant_id, comprobante_id)
        except EmisionAbortada as e:
            logger.warning("Emisión abortada %s: %s", comprobante_id, e)
            return "abortada"
        except SRIError as e:
            # Respuesta inválida del SRI. Solo se rechaza si el comprobante NO
            # llegó a salir: una vez enviado, el SRI puede tenerlo y marcarlo
            # RECHAZADO aquí llevaría a reemitirlo y duplicar la factura.
            with _sesion_tenant(tenant_id) as db:
                comp = _cargar(db, comprobante_id)
                comp.sri_mensajes = {"errores": [{"legible": str(e)}]}
                if comp.estado == EstadoComprobante.FIRMADO and comp.enviado_recepcion_at is None:
                    transicionar(comp, EstadoComprobante.RECHAZADO)
                else:
                    logger.error(
                        "Respuesta inválida del SRI para %s ya enviado; queda para barrido: %s",
                        comprobante_id,
                        e,
                    )
            return "error-sri"
    return "ok"


@celery_app.task(
    name="factuchat.emision.procesar",
    autoretry_for=(SRITransientError,),
    retry_backoff=5,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=10,
    acks_late=True,
)
def procesar_emision(tenant_id: str, comprobante_id: str) -> str:
    return ejecutar_pipeline(tenant_id, comprobante_id)


# Minutos de quietud tras los cuales un comprobante a medio camino se considera
# atascado y lo rescata el barrido (los reintentos del task se agotan antes).
MINUTOS_ATASCADO = 45


def _buscar_atascados(limite: int) -> list[tuple[str, str]]:
    """(tenant_id, comprobante_id) de comprobantes detenidos a medio camino.

    Consulta GLOBAL: usa la conexión de administración porque el barrido no
    actúa en nombre de ningún tenant. Solo devuelve identificadores; cada
    comprobante se reprocesa después con el contexto RLS de SU tenant.
    """
    from sqlalchemy import create_engine, text

    from app.core.config import get_settings

    engine = create_engine(get_settings().database_url_admin)
    corte = datetime.now(UTC) - timedelta(minutes=MINUTOS_ATASCADO)
    with engine.connect() as conn:
        filas = conn.execute(
            text(
                "SELECT tenant_id::text, id::text FROM comprobantes"
                " WHERE estado IN ('FIRMADO', 'ENVIADO_SRI') AND updated_at < :corte"
                " ORDER BY updated_at LIMIT :limite"
            ),
            {"corte": corte, "limite": limite},
        ).all()
    engine.dispose()
    return [(f[0], f[1]) for f in filas]


@celery_app.task(name="factuchat.emision.barrer_atascados", acks_late=True)
def barrer_atascados(limite: int = 200) -> int:
    """Reencola comprobantes detenidos a medio camino (A09/A10).

    Sin esto, agotados los reintentos del task un comprobante ya recibido por el
    SRI quedaba en ENVIADO_SRI para siempre: emitido para el fisco, invisible
    para el cliente. Consultar la autorización es idempotente, así que reprocesar
    es seguro.
    """
    atascados = _buscar_atascados(limite)
    for tenant_id, comprobante_id in atascados:
        logger.warning("Reencolando comprobante atascado %s", comprobante_id)
        procesar_emision.delay(tenant_id, comprobante_id)
    return len(atascados)


# Se FUSIONA, no se asigna: otros módulos de tareas también registran entradas
# periódicas y el orden en que el worker los importa no debe decidir cuáles
# sobreviven. Una reasignación aquí dejaría de barrer comprobantes atascados sin
# dar ningún error.
celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "barrer-comprobantes-atascados": {
        "task": "factuchat.emision.barrer_atascados",
        "schedule": 600.0,  # cada 10 minutos
    },
}
