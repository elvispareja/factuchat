"""Máquina de conversación de emisión (fase 5.2).

Los textos son los de la demo de la landing (`docs/spec-whatsapp.json`), que es
la fuente de verdad. La regla que gobierna todo el flujo está en su propia
burbuja y es literal: «Nada se envía al SRI hasta que tú confirmes.»

El estado de cada conversación vive en Redis con caducidad: si alguien deja una
factura a medias, no queda un borrador colgado ni un cobro fantasma.
"""

import json
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import StrEnum

import redis

from app.core.ratelimit import get_redis

# Una conversación a medias caduca en media hora: más que eso y el usuario ya
# olvidó de qué hablaba.
TTL_ESTADO_S = 30 * 60


class Paso(StrEnum):
    INICIO = "INICIO"
    ESPERA_CLIENTE = "ESPERA_CLIENTE"
    ESPERA_DETALLE = "ESPERA_DETALLE"
    ESPERA_MONTO = "ESPERA_MONTO"
    CONFIRMAR = "CONFIRMAR"
    LISTO = "LISTO"


@dataclass
class EstadoConversacion:
    """Lo que el asistente lleva reunido de esta factura."""

    paso: Paso = Paso.INICIO
    cliente_id: str | None = None
    cliente_nombre: str | None = None
    cliente_identificacion: str | None = None
    detalle: str | None = None
    monto: str | None = None
    comprobante_id: str | None = None
    candidatos: list[dict] = field(default_factory=list)

    def falta(self) -> str | None:
        """Qué dato pedir a continuación. El orden es el de la demo:
        cliente → servicio → precio."""
        if not self.cliente_nombre:
            return "cliente"
        if not self.detalle:
            return "detalle"
        if not self.monto:
            return "monto"
        return None


def _clave(tenant_id: uuid.UUID, wa_phone: str) -> str:
    return f"wa:conv:{tenant_id}:{wa_phone}"


def cargar(tenant_id: uuid.UUID, wa_phone: str) -> EstadoConversacion:
    try:
        crudo = get_redis().get(_clave(tenant_id, wa_phone))
    except redis.RedisError:
        # Sin Redis la conversación arranca de cero: es molesto, no peligroso.
        return EstadoConversacion()
    if not crudo:
        return EstadoConversacion()
    datos = json.loads(crudo)
    datos["paso"] = Paso(datos.get("paso", Paso.INICIO))
    return EstadoConversacion(**datos)


def guardar(tenant_id: uuid.UUID, wa_phone: str, estado: EstadoConversacion) -> None:
    try:
        get_redis().set(
            _clave(tenant_id, wa_phone),
            json.dumps(asdict(estado), default=str),
            ex=TTL_ESTADO_S,
        )
    except redis.RedisError:
        pass


def limpiar(tenant_id: uuid.UUID, wa_phone: str) -> None:
    try:
        get_redis().delete(_clave(tenant_id, wa_phone))
    except redis.RedisError:
        pass


# --------------------------------------------------------------- respuestas


@dataclass
class Respuesta:
    """Lo que el asistente va a mandar. El webhook solo la ejecuta."""

    texto: str
    botones: list[tuple[str, str]] = field(default_factory=list)
    lista: list[tuple[str, str, str]] = field(default_factory=list)
    boton_lista: str = "Ver opciones"


MENU_PRINCIPAL = Respuesta(
    texto="¿Qué necesitas hacer?",
    lista=[
        ("emitir", "Emitir un documento", "Factura, nota, retención, guía o liquidación"),
        ("consultar", "Consultar lo emitido", "Buscar, ver estado o reenviar un documento"),
        ("reporte", "Pedir un reporte", "Mensual, semestral, anual o trimestral"),
        ("cuenta", "Mi cuenta", "Clientes, servicios y mi plan"),
        ("asesor", "Hablar con un asesor", "Una persona del equipo te atiende"),
    ],
    boton_lista="Ver opciones",
)

AYUDA = Respuesta(
    texto=(
        "Puedo emitir tus comprobantes, consultarlos, reenviártelos y darte el "
        "reporte para declarar.\n\n"
        'Con una línea me basta: "factura a Andrade por consultoría, 450".'
    ),
    botones=[("menu", "Ver el menú")],
)

SIN_AUDIO = Respuesta(
    texto=(
        "No puedo procesar audios ni videos 🎤\n\n"
        "Escríbeme lo mismo en texto y lo resuelvo al instante. Con una línea me "
        'basta: "factura a Andrade por consultoría, 450".'
    )
)

CANCELADO = Respuesta(
    texto="Listo, no envié nada. Cuando quieras retomamos.",
    botones=[("menu", "Ver el menú")],
)


def pedir(dato: str) -> Respuesta:
    """Pregunta por el dato que falta, con el ejemplo de la demo."""
    preguntas = {
        "cliente": Respuesta(
            texto="¿A quién le facturo? Dime el nombre, el RUC o la cédula.",
        ),
        "detalle": Respuesta(texto="¿Qué le vendiste? Escríbeme el detalle."),
        "monto": Respuesta(texto="¿Cuánto es? Dime el valor sin impuestos."),
    }
    return preguntas.get(dato, Respuesta(texto="Cuéntame un poco más."))


def elegir_entre(candidatos: list[dict], consulta: str, que: str = "clientes") -> Respuesta:
    """Cuando la búsqueda trae varios, se elige de una lista con su
    identificación: confirmar a quién se factura es parte del trabajo."""
    n = len(candidatos)
    mejor = candidatos[0]
    texto = (
        f"Encontré {n} {que} con “{consulta}”.\n"
        f"El que más se parece a lo que escribiste es:\n"
        f"{mejor['titulo']}\n\n"
        "Abre la lista: van con su RUC o cédula para que confirmes."
    )
    return Respuesta(
        texto=texto,
        lista=[(c["id"], c["titulo"], c.get("subtitulo", "")) for c in candidatos[:10]],
        boton_lista="Ver coincidencias",
    )


def resumen_para_confirmar(
    cliente: str,
    identificacion: str,
    detalle: str,
    subtotal: Decimal,
    iva: Decimal,
    total: Decimal,
    porcentaje_iva: Decimal,
) -> list[Respuesta]:
    """Las tres burbujas de la demo: el resumen, la advertencia y la pregunta.

    La última frase es literal y deliberada: es la promesa que hace segura toda
    la conversación."""
    resumen = Respuesta(
        texto=(
            "*Revisa antes de autorizar*\n\n"
            f"Cliente: {cliente}\n"
            f"Identificación: {identificacion}\n"
            f"Detalle: {detalle}\n\n"
            f"Subtotal: ${subtotal}\n"
            f"IVA {porcentaje_iva:g}%: ${iva}\n"
            f"*Total: ${total}*"
        )
    )
    pregunta = Respuesta(
        texto="Nada se envía al SRI hasta que tú confirmes.",
        botones=[
            ("autorizar", "Autorizar y enviar"),
            ("corregir_precio", "Corregir el precio"),
            ("corregir_detalle", "Cambiar concepto"),
        ],
    )
    return [resumen, pregunta]


def autorizada(cliente: str, numero: str, autorizacion: str, total: Decimal) -> Respuesta:
    return Respuesta(
        texto=(
            "✅ *Factura autorizada*\n\n"
            f"Cliente: {cliente}\n"
            f"Número: {numero}\n"
            f"Autorización: {autorizacion[:20]}…\n"
            f"Total: ${total}"
        )
    )


def en_proceso(numero: str) -> Respuesta:
    return Respuesta(
        texto=(
            f"Ya la envié al SRI. Número {numero}.\n\n"
            "En cuanto el SRI la autorice te aviso por aquí y le llega a tu cliente."
        )
    )


def rechazada(motivo: str) -> Respuesta:
    return Respuesta(
        texto=(
            "El SRI no la aceptó ⚠️\n\n"
            f"{motivo}\n\n"
            "Corrige el dato y la vuelvo a enviar; no se consumió tu cupo."
        ),
        botones=[("reintentar", "Reintentar"), ("menu", "Ver el menú")],
    )


def sin_cupo(tope: int) -> Respuesta:
    return Respuesta(
        texto=(
            f"Usaste los {tope} comprobantes de tu plan este mes.\n\n"
            "Puedes recargar comprobantes o subir de plan para seguir emitiendo."
        ),
        botones=[("recargar", "Recargar"), ("planes", "Ver planes")],
    )


def sin_certificado() -> Respuesta:
    return Respuesta(
        texto=(
            "Todavía no tienes tu firma electrónica cargada, y sin ella el SRI no "
            "acepta comprobantes.\n\n"
            "Súbela desde Mi cuenta en el panel y seguimos."
        )
    )
