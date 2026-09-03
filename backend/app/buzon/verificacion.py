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

from app.buzon import parser
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

    estado = (respuesta.estado or "").strip().upper()

    # «SIN REGISTRO» NO es un veredicto: es que el SRI todavía no tiene indexada
    # esa clave. Tratarlo como un no definitivo descartaba para siempre la
    # retención legítima que el cliente sube el mismo día que se la entregan, y
    # nadie volvía a preguntar. Es exactamente el caso que `VerificacionPendiente`
    # existe para cubrir.
    if estado in ("SIN REGISTRO", "EN PROCESO"):
        raise VerificacionPendiente(f"El SRI responde «{respuesta.estado}»")

    if estado != "AUTORIZADO":
        _anotar(
            retencion,
            False,
            respuesta.estado or "sin-estado",
            f"El SRI responde «{respuesta.estado}»: no suma crédito",
        )
        return False

    # Que la clave esté autorizada NO basta: dice que EXISTE un comprobante con
    # ese número, no que sea EL QUE ESTÁ AQUÍ. Desde que el propio beneficiario
    # puede subir el XML a mano, quien escribe el papel es quien cobra el
    # crédito: con la clave de una factura suya —que va impresa en cada RIDE que
    # emite— podía fabricarse una retención a su nombre por el importe que
    # quisiera y bajarse el IVA a pagar. Así que se compara contra la copia del
    # SRI, que es la única que no escribió él.
    tenant = db.get(Tenant, retencion.tenant_id)
    desacuerdo = _no_coincide_con_el_sri(retencion, respuesta.comprobante, tenant)
    if desacuerdo is not None:
        logger.warning("Retención %s no coincide con la del SRI: %s", retencion.id, desacuerdo)
        _anotar(retencion, False, "no-coincide", desacuerdo)
        return False

    _anotar(retencion, True, respuesta.estado, "El SRI confirma que está autorizada")
    return True


def _no_coincide_con_el_sri(
    retencion: RetencionRecibida, xml_del_sri: str, tenant: Tenant | None
) -> str | None:
    """Contrasta la fila con el comprobante que devuelve el SRI. Motivo, o None.

    Sin la copia del SRI no se puede afirmar nada, así que su ausencia es un
    «no coincide», nunca un aprobado por omisión.
    """
    if not (xml_del_sri or "").strip():
        return "El SRI no devolvió el comprobante, así que no se puede contrastar"
    try:
        oficial = parser.leer(xml_del_sri.encode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001 — cualquier fallo de lectura es «no comprobable»
        return f"No se pudo leer el comprobante que devolvió el SRI: {e}"

    if oficial.tipo != "RETENCION":
        return "El documento que el SRI tiene con esa clave no es una retención"

    def _dig(v: str | None) -> str:
        return "".join(c for c in (v or "") if c.isdigit())

    if _dig(oficial.ruc_emisor) != _dig(retencion.ruc_agente):
        return "Quien retiene según el SRI no es quien dice el archivo"
    # Y que retenga a ESTE negocio en la copia del SRI, no solo en la subida.
    # Sin esto, con la clave de una retención real hecha a un tercero se podía
    # presentar un archivo propio y quedarse con su crédito.
    retenido = _dig(oficial.identificacion_receptor)
    ruc = _dig(tenant.ruc) if tenant is not None else ""
    if not ruc or retenido not in (ruc, ruc[:10]):
        return "Según el SRI, ese comprobante no te retiene a ti"
    # El importe es lo que se convierte en dinero: si no cuadra, no cuenta.
    if oficial.total_renta != retencion.total_renta or oficial.total_iva != retencion.total_iva:
        return (
            "Los importes no coinciden con los del SRI "
            f"(allí: {oficial.total_renta} de renta y {oficial.total_iva} de IVA)"
        )
    return None


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
