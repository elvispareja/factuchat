"""Códigos de acceso de un solo uso enviados por correo.

Sustituyen a la contraseña. El cliente escribe su correo, recibe seis dígitos y
entra con ellos. Cada vez.

POR QUÉ SEIS DÍGITOS BASTAN. No bastan por sí solos: un millón de
combinaciones se agotan en segundos si se puede probar sin límite. La seguridad
está en el resto de las reglas, y quitar cualquiera de ellas rompe el conjunto:

  · caduca a los 10 minutos,
  · vale una sola vez,
  · se quema al quinto intento fallido,
  · pedir uno nuevo invalida el anterior —si no, pedir diez códigos daría
    cincuenta intentos en vez de cinco—,
  · y por encima sigue el límite por IP y por cuenta que ya existía.

Del código se guarda su sha256. En claro solo existe dentro del correo.

QUIÉN NO RECIBE CORREO. El personal interno usa su app de autenticación. La
respuesta del servidor es idéntica en los dos casos a propósito: decir «a esta
cuenta no le mandamos correo porque es interna» sería regalar la lista de
empleados a cualquiera que pruebe direcciones.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.mailer import enviar_correo

MINUTOS_VIGENCIA = 10
MAX_INTENTOS = 5
DIGITOS = 6


def _hash(codigo: str) -> str:
    return hashlib.sha256(codigo.encode()).hexdigest()


def generar() -> str:
    """Seis dígitos con generador criptográfico.

    `secrets` y no `random`: el segundo es predecible a partir de unas pocas
    salidas, y aquí cada salida es una credencial.
    """
    return f"{secrets.randbelow(10**DIGITOS):0{DIGITOS}d}"


def emitir(db: Session, user_id: uuid.UUID, ip: str | None) -> str:
    """Crea el código y lo devuelve EN CLARO para poder enviarlo por correo."""
    codigo = generar()
    db.execute(
        text("SELECT auth_codigo_emitir(:u, :h, :exp, :ip)"),
        {
            "u": str(user_id),
            "h": _hash(codigo),
            "exp": datetime.now(UTC) + timedelta(minutes=MINUTOS_VIGENCIA),
            "ip": ip,
        },
    )
    return codigo


def comprobar(db: Session, user_id: uuid.UUID, codigo: str) -> str:
    """'ok' | 'no' | 'agotado' | 'nada'. La decisión la toma la base en una sola
    sentencia bajo bloqueo, para que dos intentos simultáneos no se pisen."""
    return str(
        db.execute(
            text("SELECT auth_codigo_usar(:u, :h, :max)"),
            {"u": str(user_id), "h": _hash(codigo), "max": MAX_INTENTOS},
        ).scalar()
    )


def enviar(destinatario: str, nombre: str, codigo: str) -> str:
    s = get_settings()
    n = escape(nombre or "")
    cuerpo = f"""
    <div style="font-family:system-ui,sans-serif;max-width:480px;color:#123D2F">
      <p style="font-size:15px;line-height:1.6">Hola {n},</p>
      <p style="font-size:15px;line-height:1.6">Tu código para entrar a Factuchat:</p>
      <p style="margin:24px 0;font-size:34px;font-weight:700;letter-spacing:.18em;
                font-family:ui-monospace,'SF Mono',monospace;color:#123D2F">{codigo}</p>
      <p style="font-size:13.5px;line-height:1.6;color:#3E5A4E">
        Caduca en {MINUTOS_VIGENCIA} minutos y sirve una sola vez.
      </p>
      <p style="font-size:12.5px;color:#8A9A91;line-height:1.6">
        Si no has intentado entrar, ignora este correo: sin el código nadie puede
        acceder a tu cuenta. Si se repite, escríbenos a {escape(s.email_info)}.
      </p>
    </div>
    """
    return enviar_correo(destinatario, f"{codigo} es tu código de Factuchat", cuerpo)


def bienvenida(destinatario: str, nombre: str, negocio: str) -> str:
    """Aviso de que la cuenta existe. NO lleva credencial ninguna.

    Antes este correo traía un enlace para poner la contraseña. Ya no hay
    contraseña: el cliente entra escribiendo su correo y el código de seis
    dígitos que pide desde la propia pantalla. Así que este correo solo cuenta
    que la cuenta está lista y qué le falta.
    """
    s = get_settings()
    n = escape(nombre or "")
    neg = escape(negocio or "")
    cuerpo = f"""
    <div style="font-family:system-ui,sans-serif;max-width:520px;color:#123D2F">
      <p style="font-size:15px;line-height:1.6">Hola {n},</p>
      <p style="font-size:15px;line-height:1.6">
        Tu cuenta de <strong>Factuchat</strong> para <strong>{neg}</strong> ya está lista.
      </p>
      <p style="font-size:15px;line-height:1.6">
        Para entrar no necesitas contraseña: escribe este correo
        (<strong>{escape(destinatario)}</strong>) en la pantalla de acceso y te mandamos
        un código de 6 dígitos. Igual cada vez que entres.
      </p>
      <p style="margin:26px 0">
        <a href="https://{escape(s.dominio_publico)}"
           style="background:#123D2F;color:#FAF9F5;text-decoration:none;
                  padding:13px 26px;border-radius:999px;font-weight:600;font-size:15px">
          Entrar a Factuchat
        </a>
      </p>
      <p style="font-size:13.5px;line-height:1.6;color:#3E5A4E">
        La primera vez te pediremos tu firma electrónica: el archivo .p12 que te dio
        tu entidad certificadora. Es lo único que falta para que puedas emitir, la
        subes tú, y ni el archivo ni su clave los ve nadie de Factuchat.
      </p>
      <p style="font-size:12.5px;color:#8A9A91;line-height:1.6">
        ¿Dudas? Escríbenos a {escape(s.email_info)}.
      </p>
    </div>
    """
    return enviar_correo(destinatario, "Tu cuenta de Factuchat está lista", cuerpo)
