"""Interruptores del sistema que se cambian en caliente (fase 7).

Un feature flag que solo vive en una variable de entorno obliga a redesplegar
para encenderlo, y la maqueta pide justo lo contrario: que el superadmin lo
alterne desde el panel y que el cambio quede auditado.

Precedencia: lo que diga la base manda; si no hay fila, vale el valor del
entorno. Así un despliegue nuevo arranca con lo configurado y, en cuanto alguien
toca el interruptor, esa decisión persiste.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Parametro

BUZON_ACTIVO = "BUZON_ACTIVO"

# Textos de los tres avisos automáticos, editables desde Configuración. Viven
# aquí y no en el código para que cambiar una frase no exija un despliegue.
AVISO_PRE_DECLARACION = "AVISO_PRE_DECLARACION"
AVISO_CUPO_AGOTADO = "AVISO_CUPO_AGOTADO"
AVISO_PAGO_VENCIDO = "AVISO_PAGO_VENCIDO"

VERDADEROS = {"1", "true", "t", "si", "sí", "on"}


def leer_bool(db: Session, clave: str, por_defecto: bool) -> bool:
    fila = db.get(Parametro, clave)
    if fila is None:
        return por_defecto
    return fila.valor.strip().lower() in VERDADEROS


def fijar_bool(db: Session, clave: str, valor: bool, actor_id: uuid.UUID | None) -> bool:
    fila = db.get(Parametro, clave)
    texto = "true" if valor else "false"
    if fila is None:
        fila = Parametro(clave=clave, valor=texto, actualizado_por=actor_id)
        db.add(fila)
    else:
        fila.valor = texto
        fila.actualizado_por = actor_id
        fila.actualizado_at = datetime.now(UTC)
    db.flush()
    return valor


def buzon_activo(db: Session) -> bool:
    """El interruptor del módulo de buzón."""
    return leer_bool(db, BUZON_ACTIVO, get_settings().buzon_activo)


def leer_texto(db: Session, clave: str) -> str | None:
    """El texto guardado, o None si nadie lo ha cambiado todavía."""
    fila = db.get(Parametro, clave)
    return fila.valor if fila is not None else None


def fijar_texto(db: Session, clave: str, valor: str, actor_id: uuid.UUID | None) -> str:
    fila = db.get(Parametro, clave)
    if fila is None:
        fila = Parametro(clave=clave, valor=valor, actualizado_por=actor_id)
        db.add(fila)
    else:
        fila.valor = valor
        fila.actualizado_por = actor_id
        fila.actualizado_at = datetime.now(UTC)
    db.flush()
    return valor


def todos(db: Session) -> dict[str, str]:
    return {p.clave: p.valor for p in db.scalars(select(Parametro)).all()}
