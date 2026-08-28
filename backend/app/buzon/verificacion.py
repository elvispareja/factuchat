"""Verificación de una retención recibida contra el SRI (fase 7.1).

Por qué existe este archivo: **un XML lo escribe cualquiera**. El sobre
`<autorizacion><estado>AUTORIZADO</estado>` también. La dirección del buzón de un
inquilino es su RUC, que aparece en cada factura que emite, así que cualquiera
puede mandarle un comprobante de retención inventado.

Si ese documento se sumara sin comprobar, el sistema le diría al contribuyente
que debe menos IVA del que debe, y declararía de menos con consecuencias
tributarias reales. Por eso una retención solo cuenta como crédito cuando el
SRI, preguntado por su clave de acceso, responde que está AUTORIZADA. Todo lo
demás queda archivado y visible, pero fuera del saldo.

Se reutiliza el mismo cliente del motor de emisión: ya trae lista blanca de
destinos, tiempos de espera, reintentos y cortacircuitos.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import RetencionRecibida, Tenant
from app.sri import client as sri
from app.sri.clave import digito_verificador_mod11

logger = logging.getLogger("factuchat.buzon")


class VerificacionPendiente(Exception):
    """No se pudo preguntar al SRI ahora. Se reintenta; no es un veredicto."""


def clave_bien_formada(clave: str | None) -> bool:
    """49 dígitos con su dígito verificador módulo 11 correcto.

    Es un filtro barato antes de molestar al SRI: una clave con el verificador
    mal no puede corresponder a ningún comprobante autorizado.
    """
    if not clave or len(clave) != 49 or not clave.isdigit():
        return False
    return str(digito_verificador_mod11(clave[:48])) == clave[48]


def verificar(db: Session, retencion: RetencionRecibida, ambiente: str) -> bool:
    """Pregunta al SRI y deja constancia. Devuelve si quedó verificada.

    Lanza `VerificacionPendiente` cuando el fallo es del canal (SRI caído,
    tiempo agotado, circuito abierto): un problema de red no puede convertirse
    en un veredicto de «no autorizada».
    """
    clave = retencion.clave_acceso or ""
    if not clave_bien_formada(clave):
        _anotar(
            retencion,
            False,
            "sin-clave-valida",
            "El comprobante no trae una clave de acceso válida",
        )
        return False

    try:
        respuesta = sri.consultar_autorizacion(clave, ambiente)
    except sri.SRITransientError as e:
        raise VerificacionPendiente(str(e)) from e

    autorizado = (respuesta.estado or "").strip().upper() == "AUTORIZADO"
    _anotar(
        retencion,
        autorizado,
        respuesta.estado or "sin-estado",
        (
            "El SRI confirma que está autorizada"
            if autorizado
            else f"El SRI responde «{respuesta.estado}»: no suma crédito"
        ),
    )
    return autorizado


def _anotar(retencion: RetencionRecibida, ok: bool, estado: str, detalle: str) -> None:
    retencion.verificada = ok
    retencion.verificada_at = datetime.now(UTC)
    retencion.verificacion = {
        "estado": estado,
        "detalle": detalle,
        "consultado_at": datetime.now(UTC).isoformat(),
    }


def ambiente_de(db: Session, tenant_id: uuid.UUID) -> str:
    tenant = db.get(Tenant, tenant_id)
    return tenant.ambiente_sri.value if tenant else "PRUEBAS"
