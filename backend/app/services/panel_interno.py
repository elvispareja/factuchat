"""Dashboard general del panel interno (Superadmin.dc.html, sección `esDash`).

La maqueta muestra latencias concretas —«SRI · recepción · 142 ms»— que allí son
literales de diseño. Aquí NO se inventan: el semáforo se arma con las señales que
el sistema tiene de verdad.

  · SRI: el cortacircuitos que ya vive en Redis (`app/sri/client.py`). Si está
    abierto, el servicio está caído para nosotros y la cola está en pausa; eso es
    mucho más útil que un número de milisegundos.
  · WhatsApp y correo: si el canal está configurado o no. Un canal sin
    credenciales no está «lento», está apagado, y decirlo de otra forma haría que
    nadie fuera a arreglarlo.
  · Firma electrónica: cuántos certificados hay y si alguno está por caducar.

Cuando exista una sonda que mida latencia real, esta es la función que hay que
cambiar, y el panel la mostrará sin tocar nada más.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.ratelimit import get_redis


@dataclass
class Servicio:
    nombre: str
    detalle: str
    estado: str  # ok | aviso | mal | apagado

    def a_json(self) -> dict:
        return {"nombre": self.nombre, "detalle": self.detalle, "estado": self.estado}


def _circuito(destino: str) -> bool:
    """¿El cortacircuitos de ese servicio del SRI está abierto?"""
    try:
        return bool(get_redis().exists(f"sri:circuit:{destino}"))
    except redis.RedisError:
        return False


def _redis_vivo() -> bool:
    try:
        get_redis().ping()
        return True
    except redis.RedisError:
        return False


def salud_de_servicios(db: Session) -> list[dict]:
    """Las cinco filas del semáforo, con el estado real de cada canal."""
    s = get_settings()
    ambiente = "pruebas"
    hay_redis = _redis_vivo()

    servicios: list[Servicio] = []

    for etiqueta, destino in (
        ("SRI · recepción", "recepcion"),
        ("SRI · autorización", "autorizacion"),
    ):
        if not hay_redis:
            servicios.append(Servicio(etiqueta, "Sin Redis: no se puede vigilar", "aviso"))
        elif _circuito(f"{destino}:{ambiente}") or _circuito(destino):
            servicios.append(Servicio(etiqueta, "Circuito abierto: la cola está en pausa", "mal"))
        else:
            servicios.append(Servicio(etiqueta, "Operativo", "ok"))

    if s.wa_access_token and s.wa_app_secret:
        gasto = db.execute(
            text(
                "SELECT coalesce(sum(costo), 0) FROM whatsapp_msgs "
                "WHERE date_trunc('month', created_at) = date_trunc('month', now())"
            )
        ).scalar_one()
        tope = s.wa_presupuesto_mensual
        detalle = f"Operativo · ${gasto:.2f} este mes"
        estado = "ok"
        if tope and float(gasto) >= float(tope) * (s.wa_alerta_pct / 100):
            detalle = f"${gasto:.2f} de ${tope} de presupuesto"
            estado = "aviso"
        servicios.append(Servicio("WhatsApp API", detalle, estado))
    else:
        servicios.append(
            Servicio("WhatsApp API", "Sin credenciales de Meta: canal apagado", "apagado")
        )

    fila = db.execute(
        text(
            "SELECT count(*) FILTER (WHERE activo), "
            "       count(*) FILTER (WHERE activo AND valido_hasta::date - current_date <= 30) "
            "  FROM certificados"
        )
    ).one()
    if fila[0] == 0:
        servicios.append(
            Servicio("Firma electrónica", "Ningún certificado cargado todavía", "apagado")
        )
    elif fila[1]:
        servicios.append(Servicio("Firma electrónica", f"{fila[1]} por vencer en 30 días", "aviso"))
    else:
        servicios.append(Servicio("Firma electrónica", f"{fila[0]} vigentes", "ok"))

    if s.smtp_host:
        servicios.append(Servicio("Correo saliente", f"Operativo · {s.smtp_host}", "ok"))
    else:
        servicios.append(
            Servicio("Correo saliente", "Sin SMTP: los correos quedan en disco", "apagado")
        )

    return [x.a_json() for x in servicios]


def emision_ultimos_30(db: Session) -> dict:
    """Las 30 barras del gráfico y los tres contadores Hoy / Semana / Mes."""
    filas = db.execute(text("SELECT dia, emitidos FROM sa_dashboard_emision()")).all()
    barras = [{"dia": f[0].isoformat(), "n": int(f[1])} for f in filas]
    hoy = datetime.now(UTC).date()
    return {
        "barras": barras,
        "hoy": sum(b["n"] for b in barras if b["dia"] == hoy.isoformat()),
        "semana": sum(b["n"] for b in barras[-7:]),
        "mes": sum(b["n"] for b in barras if b["dia"][:7] == hoy.isoformat()[:7]),
        "maximo": max((b["n"] for b in barras), default=0),
    }
