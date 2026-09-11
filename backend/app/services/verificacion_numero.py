"""Códigos de un solo uso que prueban que un teléfono es de quien lo autoriza.

Mismas reglas que los códigos de acceso por correo (`app/services/acceso.py`):
seis dígitos con generador criptográfico, del código se guarda solo su sha256,
caduca a los diez minutos, se quema al quinto intento fallido y pedir uno nuevo
invalida el anterior. Si no, pedir diez códigos daría cincuenta intentos.

LA DECISIÓN LA TOMA LA BASE, no este módulo: `sys_verificar_numero` resuelve en
una sola sentencia bajo bloqueo, para que dos intentos simultáneos no gasten el
mismo intento dos veces ni verifiquen dos veces. Ver la migración 0030.

EL CÓDIGO VUELVE POR DOS CAMINOS y los dos acaban en esa función:
  · la plantilla que Factuchat manda a ese WhatsApp, y
  · un mensaje que esa persona escribe al bot desde ese teléfono.
El segundo no depende de que Meta apruebe nada y no cuesta nada.
"""

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimitExceeded, get_redis
from app.db.models import WhatsappNumero
from app.services.acceso import generar

MINUTOS_VIGENCIA = 10
MAX_INTENTOS = 5

# Cada envío a un número sin conversación abierta es una plantilla que Meta
# cobra. Sin freno, un cliente autenticado puede hacer gastar a Factuchat
# pidiendo códigos en bucle, y de paso acosar a un desconocido.
MAX_ENVIOS = 3
VENTANA_ENVIOS_S = 30 * 60

# Seis dígitos seguidos en cualquier parte del mensaje: quien contesta al bot
# escribe «VERIFICAR 482913», «482913» o «mi codigo es 482913».
_SEIS_DIGITOS = re.compile(r"\b(\d{6})\b")


def _hash(codigo: str) -> str:
    return hashlib.sha256(codigo.encode()).hexdigest()


def codigo_en(texto: str) -> str | None:
    """El primer grupo de seis dígitos del mensaje, si lo hay."""
    m = _SEIS_DIGITOS.search(texto or "")
    return m.group(1) if m else None


def limitar_envios(numero: str) -> None:
    """Lanza RateLimitExceeded si ese teléfono ya recibió demasiados códigos.

    La clave es el TELÉFONO y no el inquilino a propósito: lo que se protege es
    a quien recibe, que puede no tener nada que ver con quien pide.
    """
    clave = f"rl:wa_verif:{numero}"
    r = get_redis()
    cuantos = r.incr(clave)
    if cuantos == 1:
        r.expire(clave, VENTANA_ENVIOS_S)
    if int(cuantos) > MAX_ENVIOS:
        raise RateLimitExceeded(retry_after=max(int(r.ttl(clave)), 1))


def emitir(db: Session, numero: WhatsappNumero) -> str:
    """Graba un código nuevo en la fila y lo devuelve EN CLARO para enviarlo.

    Invalida el anterior por construcción: se sobrescribe el hash y el contador
    de intentos vuelve a cero.
    """
    codigo = generar()
    numero.codigo_hash = _hash(codigo)
    numero.codigo_expira = datetime.now(UTC) + timedelta(minutes=MINUTOS_VIGENCIA)
    numero.codigo_intentos = 0
    db.flush()
    return codigo


def ocupado(db: Session, telefono: str) -> bool:
    """¿Otra empresa ya probó tener ese teléfono?

    Va por función segura porque `whatsapp_numeros` tiene RLS forzada y desde
    aquí solo se ven las filas propias. Devuelve un sí o un no: exactamente lo
    que el 409 del alta ya decía antes de que existiera la verificación.
    """
    return bool(db.execute(text("SELECT sys_numero_ocupado(:t)"), {"t": telefono}).scalar())


def comprobar(db: Session, telefono: str, codigo: str, fila_id: uuid.UUID | None = None) -> str:
    """'ok' | 'no' | 'agotado' | 'expirado' | 'ocupado' | 'nada'.

    `fila_id` es de quién es el intento. Dos empresas pueden tener pendiente el
    mismo teléfono, así que un fallo hay que cobrárselo a quien pregunta y no a
    la otra: sin esto, dejar un alta a medias sobre el número de un tercero le
    quemaba a él los intentos. Desde el panel se sabe (la fila ya vino filtrada
    por RLS); desde el chat no, y entonces no se le cobra a nadie.
    """
    return str(
        db.execute(
            text("SELECT sys_verificar_numero(:t, :h, :max, :id)"),
            {"t": telefono, "h": _hash(codigo), "max": MAX_INTENTOS, "id": fila_id},
        ).scalar()
    )


# Lo que se le dice a quien teclea el código en el panel. 'ocupado' se explica
# entero: es el único caso en que el usuario no puede hacer nada por su cuenta.
MOTIVOS = {
    "no": "Ese código no es. Revísalo y vuelve a intentar.",
    "agotado": "Demasiados intentos fallidos. Pide un código nuevo.",
    "expirado": "Ese código ya caducó. Pide uno nuevo.",
    "ocupado": (
        "Ese número acaba de quedar autorizado en otra cuenta de Factuchat. "
        "Un teléfono solo puede facturar para una empresa."
    ),
    "nada": "No hay ninguna verificación pendiente para ese número.",
}
