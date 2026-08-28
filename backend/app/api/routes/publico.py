"""Landing pública: términos, checkout y contacto (fase 6.2).

Endpoints SIN autenticación: aquí llega gente que todavía no es cliente. Por eso
llevan rate limiting por IP y validación estricta — es la superficie más expuesta
del sistema.
"""

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import redis
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.core.config import get_settings
from app.core.ratelimit import get_redis
from app.db.models import Plan, SolicitudContacto
from app.db.models.enums import MetodoPago
from app.db.session import despues_del_commit, get_db
from app.schemas.tienda import CheckoutIn, ContactoIn
from app.services import configuracion, terminos
from app.services.terminos import TerminosError
from app.tasks.notificaciones import aviso_solicitud

logger = logging.getLogger("factuchat.publico")
router = APIRouter(prefix="/publico", tags=["publico"])

TZ = ZoneInfo("America/Guayaquil")

# Un formulario público sin freno es un buzón de spam y un vector de abuso
LIMITE_ENVIOS = 5
VENTANA_S = 900
MAX_COMPROBANTE_BYTES = 5 * 1024 * 1024
TIPOS_COMPROBANTE = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


def _wa_link(s) -> str | None:
    """Enlace wa.me del número de atención. Sin número configurado no se inventa
    ninguno: la maqueta traía 593000000000 de relleno y eso no puede publicarse."""
    numero = "".join(c for c in (s.contacto_telefono_e164 or "") if c.isdigit())
    return f"https://wa.me/{numero}" if numero else None


def _limitar(request: Request, accion: str) -> None:
    ip = client_ip(request)
    clave = f"rl:publico:{accion}:{ip}"
    try:
        r = get_redis()
        n = r.incr(clave)
        if int(n) == 1:
            r.expire(clave, VENTANA_S)
        if int(n) > LIMITE_ENVIOS:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Recibimos varios envíos desde aquí. Espera unos minutos e inténtalo de nuevo.",
            )
    except redis.RedisError:
        # Sin Redis se deja pasar: el formulario no puede caerse por eso
        logger.warning("Rate limit público sin Redis")


@router.get("/terminos")
def documento_legal():
    """El documento que la landing muestra y el checkout exige aceptar."""
    return terminos.vigente()


@router.get("/planes")
def planes_publicos(db: Session = Depends(get_db)):
    """Los planes vigentes HOY, con su precio actual. Sale de la base, no de
    una constante: si el superadmin programó un cambio, la landing lo refleja
    el día que entra en vigor."""
    hoy = datetime.now(TZ).date()
    salida = []
    for fila in db.scalars(select(Plan).order_by(Plan.precio_mensual)).all():
        vigente = fila.vigente_desde <= hoy and (
            fila.vigente_hasta is None or fila.vigente_hasta > hoy
        )
        if not vigente or not fila.activo:
            continue
        limites = fila.limites or {}
        salida.append(
            {
                "codigo": fila.codigo,
                "nombre": fila.nombre,
                "precio": str(fila.precio_mensual),
                "cupo": limites.get("cupo"),
                "analisis_ia": limites.get("ia"),
                "tienda": bool(limites.get("tienda")),
                "stock": bool(limites.get("stock")),
                "acumula": bool(limites.get("acumula")),
            }
        )
    return salida


@router.post("/checkout", status_code=status.HTTP_201_CREATED)
def checkout(
    body: CheckoutIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Las tres vías del checkout terminan aquí: información/agenda,
    transferencia y Payphone. Ninguna activa la cuenta por sí sola —eso lo hace
    el equipo desde el panel interno— pero todas dejan su registro."""
    _limitar(request, "checkout")
    hoy = datetime.now(TZ).date()

    plan = configuracion.plan_vigente_por_codigo(db, body.plan.upper(), hoy)
    if plan is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ese plan no está disponible")

    # La aceptación se registra ANTES de crear nada: si falla, no queda un
    # pedido huérfano sin base legal para tratar sus datos.
    try:
        terminos.registrar(
            db,
            email=body.email,
            acepta_condiciones=body.acepta.condiciones,
            acepta_datos=body.acepta.datos,
            nombre=f"{body.nombres} {body.apellidos}".strip(),
            identificacion=body.identificacion,
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:400],
            origen="CHECKOUT",
        )
    except TerminosError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    solicitud = SolicitudContacto(
        nombre=f"{body.nombres} {body.apellidos}".strip(),
        email=str(body.email),
        telefono=body.telefono,
        identificacion=body.identificacion,
        ciudad=body.ciudad,
        provincia=body.provincia,
        pais=body.pais,
        plan=plan.nombre,
        metodo_pago=body.metodo_pago.value,
        agenda_dia=body.agenda_dia,
        agenda_hora=body.agenda_hora,
        mensaje=body.mensaje,
        codigo_promo=body.codigo_promo,
    )
    db.add(solicitud)
    db.flush()

    # El aviso al equipo se encola DESPUÉS del commit: si la transacción se
    # deshiciera, nadie recibiría un correo sobre un pedido que no existe.
    despues_del_commit(db, lambda i=str(solicitud.id): aviso_solicitud.delay(i))

    referencia = f"FC-{str(solicitud.id).replace('-', '')[:6].upper()}"
    siguiente = {
        MetodoPago.TRANSFERENCIA: (
            "Te mostramos las cuentas, transfieres y subes el comprobante. "
            "Activamos tu plan al confirmar el pago."
        ),
        MetodoPago.PAYPHONE: ("Al confirmar te llevamos a Payphone para completar la transacción."),
        MetodoPago.OTRO: ("Un asesor te escribe por WhatsApp para confirmar tu pedido."),
        MetodoPago.EFECTIVO: ("Un asesor te escribe por WhatsApp para coordinar el pago."),
    }[body.metodo_pago]

    # La referencia la genera el servidor, no el navegador: la maqueta la sacaba
    # de Date.now() y eso colisiona.
    base_wa = _wa_link(get_settings())
    texto = "\n".join(
        linea
        for linea in [
            f"Hola Factuchat, quiero el plan {plan.nombre} (${plan.precio_mensual}).",
            f"Referencia: {referencia}",
            f"Nombre: {body.nombres} {body.apellidos}".strip(),
            f"Identificación: {body.identificacion}" if body.identificacion else "",
            f"Teléfono: {body.telefono}" if body.telefono else "",
            f"Correo: {body.email}",
            f"Ciudad: {body.ciudad}, {body.provincia}, {body.pais}".replace(", ,", ","),
            (
                f"Quiero que me llamen el {body.agenda_dia} a las {body.agenda_hora}."
                if body.agenda_dia and body.agenda_hora
                else ""
            ),
            body.mensaje or "",
        ]
        if linea
    )

    return {
        "id": str(solicitud.id),
        "referencia": referencia,
        "plan": plan.nombre,
        "precio": str(plan.precio_mensual),
        "metodo_pago": body.metodo_pago.value,
        "siguiente_paso": siguiente,
        "sube_comprobante": body.metodo_pago == MetodoPago.TRANSFERENCIA,
        "wa_link": f"{base_wa}?text={quote(texto)}" if base_wa else None,
    }


@router.post("/checkout/{solicitud_id}/comprobante", status_code=status.HTTP_201_CREATED)
def subir_comprobante(
    solicitud_id: uuid.UUID,
    request: Request,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Foto o PDF de la transferencia. Se valida el tipo y el tamaño: es una
    subida pública, así que no se guarda nada sin revisar qué es."""
    _limitar(request, "comprobante")

    if archivo.content_type not in TIPOS_COMPROBANTE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Sube una foto (JPG, PNG o WEBP) o un PDF de tu comprobante.",
        )
    contenido = archivo.file.read(MAX_COMPROBANTE_BYTES + 1)
    if len(contenido) > MAX_COMPROBANTE_BYTES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "El archivo supera los 5 MB permitidos."
        )
    if not contenido:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El archivo llegó vacío.")

    # Nombre generado por nosotros: el del usuario nunca toca el sistema de
    # archivos (evita travesía de rutas y colisiones)
    extension = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "application/pdf": "pdf",
    }[archivo.content_type]
    destino = Path(get_settings().storage_dir) / "comprobantes-pago"
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / f"{solicitud_id}.{extension}"

    # La solicitud se completa por función segura: quien envió el formulario no
    # puede leer la tabla ni enumerar pedidos ajenos, solo completar el suyo.
    adjuntado = db.execute(
        text("SELECT publico_adjuntar_comprobante(:id, :url)"),
        {"id": str(solicitud_id), "url": str(ruta)},
    ).scalar_one()
    if not adjuntado:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Ese pedido no existe o ya tiene su comprobante"
        )

    ruta.write_bytes(contenido)
    return {
        "recibido": True,
        "mensaje": "Recibimos tu comprobante. Activamos tu plan al confirmar el pago.",
    }


@router.post("/contacto", status_code=status.HTTP_201_CREATED)
def contacto(body: ContactoIn, request: Request, db: Session = Depends(get_db)):
    """Formulario de contacto: guarda la consulta y devuelve el enlace de
    WhatsApp con el mensaje ya redactado."""
    _limitar(request, "contacto")

    solicitud = SolicitudContacto(
        nombre=body.nombre,
        email=str(body.email),
        telefono=body.telefono,
        pais="Ecuador",
        mensaje=f"{body.asunto}\n\n{body.mensaje}",
    )
    db.add(solicitud)
    db.flush()
    despues_del_commit(db, lambda i=str(solicitud.id): aviso_solicitud.delay(i))

    # El texto se arma aquí para que el enlace salga igual desde la web y desde
    # cualquier otro canal. quote() y no el texto crudo: va dentro de una URL.
    base = _wa_link(get_settings())
    texto = (
        f"Hola Factuchat, escribo desde la web.\n"
        f"Nombre: {body.nombre}\n"
        f"Email: {body.email}\n"
        + (f"Teléfono: {body.telefono}\n" if body.telefono else "")
        + f"Asunto: {body.asunto}\n\n{body.mensaje}"
    )
    return {
        "id": str(solicitud.id),
        "wa_link": f"{base}?text={quote(texto)}" if base else None,
        "mensaje": "Se abre WhatsApp con tu mensaje listo para enviar.",
    }


@router.get("/config")
def configuracion_publica():
    """Datos que la landing necesita para pintarse: dominio, contacto, horario y
    las cuentas de cobro. Salen del servidor —no del bundle— porque el dominio
    todavía no está confirmado y las cuentas son dato del negocio."""
    s = get_settings()
    cuentas = []
    for fila in s.cobro_cuentas:
        banco, _, numero = fila.partition("|")
        if banco and numero:
            cuentas.append({"banco": banco, "numero": numero})
    return {
        "dominio": s.dominio_publico,
        "email": s.email_info,
        "email_ventas": s.email_ventas,
        "telefono": s.contacto_telefono,
        "telefono_e164": s.contacto_telefono_e164,
        "direccion": s.contacto_direccion,
        "maps_url": s.contacto_maps_url,
        "horario": s.contacto_horario,
        "whatsapp": _wa_link(s),
        "cobro": {
            "titular": s.cobro_titular,
            "identificacion": s.cobro_titular_identificacion,
            "email": s.email_ventas,
            "cuentas": cuentas,
        },
    }


@router.get("/paises")
def paises():
    """Cobertura del servicio. Solo Ecuador está en operación; el resto,
    'Muy pronto' — incluido Panamá."""
    return [
        {"pais": "Ecuador", "estado": "En operación", "disponible": True},
        {"pais": "Panamá", "estado": "Muy pronto", "disponible": False},
        {"pais": "Perú", "estado": "Muy pronto", "disponible": False},
        {"pais": "Colombia", "estado": "Muy pronto", "disponible": False},
        {"pais": "Chile", "estado": "Muy pronto", "disponible": False},
    ]


def _decimal(v: str) -> Decimal:
    return Decimal(v)


def _hoy() -> date:
    return datetime.now(TZ).date()
