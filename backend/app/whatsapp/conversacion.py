"""Máquina de conversación de emisión (fase 5.2).

Los textos son los de la demo de la landing (`docs/factuchat-chatbot-spec.json`),
que es la fuente de verdad: se copian literales. La
regla que gobierna todo el flujo está en su propia burbuja y es literal: «Nada
se envía al SRI hasta que tú confirmes.»

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


# El saludo de primer contacto se da una vez. Tras tres meses sin escribir se
# repite: para entonces el usuario ya no recuerda cómo se usa.
TTL_SALUDO_S = 90 * 24 * 3600


def _clave_saludo(tenant_id: uuid.UUID, wa_phone: str) -> str:
    return f"wa:saludo:{tenant_id}:{wa_phone}"


def marcar_saludado(tenant_id: uuid.UUID, wa_phone: str) -> bool:
    """Deja constancia del saludo y devuelve True solo la primera vez. Es un
    SET NX: dos mensajes iniciales procesados a la vez no saludan dos veces."""
    try:
        return bool(
            get_redis().set(_clave_saludo(tenant_id, wa_phone), "1", ex=TTL_SALUDO_S, nx=True)
        )
    except redis.RedisError:
        # Sin Redis no hay memoria: mejor no repetir el saludo en cada mensaje
        return False


def olvidar_saludo(tenant_id: uuid.UUID, wa_phone: str) -> None:
    try:
        get_redis().delete(_clave_saludo(tenant_id, wa_phone))
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
    # Título de la sección de la lista (24 caracteres): es la cabecera que ve
    # el usuario al desplegarla
    titulo_lista: str = "Opciones"
    # El pie (footer) de Meta: 60 caracteres y solo en mensajes con botones o lista
    pie: str = ""


PIE_ESTANDAR = "Mensajes concisos · voz desde Emprendedor"

# Lista principal del spec, con la oferta ya reducida a tres documentos: la
# nota de débito, la guía de remisión y la liquidación de compra salieron del
# plan, así que la primera fila no las nombra.
LISTA_PRINCIPAL: list[tuple[str, str, str]] = [
    ("emitir", "Emitir un documento", "Factura, nota de crédito o retención recibida"),
    ("consultar", "Consultar lo emitido", "Buscar, ver estado o reenviar un documento"),
    ("reporte", "Pedir un reporte", "Mensual, semestral, anual o trimestral"),
    ("cuenta", "Mi cuenta", "Clientes, servicios y mi plan"),
    ("asesor", "Hablar con un asesor", "Una persona del equipo te atiende"),
]


def _menu(texto: str) -> Respuesta:
    """Una burbuja con el botón «Ver opciones», que abre la lista principal."""
    return Respuesta(
        texto=texto,
        lista=list(LISTA_PRINCIPAL),
        boton_lista="Ver opciones",
        titulo_lista="¿Qué necesitas hacer?",
        pie=PIE_ESTANDAR,
    )


def saludo(nombre: str | None) -> Respuesta:
    """Nodo `start`, burbuja 1: primer contacto. El nombre es el del perfil de
    WhatsApp; si no viene, se saluda sin él."""
    limpio = (nombre or "").strip()
    hola = f"¡Hola, {limpio}!" if limpio else "¡Hola!"
    return Respuesta(
        texto=(
            f"{hola} 👋 Soy Factuchat®, tu asistente virtual contable.\n\n"
            "Escríbeme con texto, así de simple. Mientras más concreto seas, más "
            "rápido lo resuelvo."
        )
    )


# Nodo `start`, burbuja 2
MENU_INICIAL = _menu(
    "Toca el botón de abajo y elige qué necesitas hacer. También puedes escribirme "
    "con tus palabras."
)

# Nodo `menu`: al volver al menú o escribir hola, ayuda o menú
MENU_PRINCIPAL = _menu("¿Qué más hacemos?")

# Nodo `fallback`: texto libre sin intención reconocible
FALLBACK = _menu(
    "*Con mensajes concisos te resuelvo más rápido 🙂*\n\n"
    "Dime en pocas palabras qué necesitas: “una factura”, “el reporte del mes”, "
    "“mis clientes”. O toca el botón y elige de la lista."
)

# Nodo `muyLargo`: más de 220 caracteres en texto libre, o de 150 contestando
# una pregunta. En el segundo caso se repite la pregunta implícitamente: el
# estado no cambia y el siguiente mensaje sigue siendo la respuesta.
MUY_LARGO_TEXTO = (
    "*Ese mensaje es muy largo 📝*\n\n"
    "Resúmelo en unas cuatro líneas: qué necesitas, para quién y por cuánto. Con un "
    "mensaje concreto emito el documento exacto, sin idas y vueltas."
)
MUY_LARGO = _menu(MUY_LARGO_TEXTO)
MUY_LARGO_EN_PREGUNTA = Respuesta(texto=MUY_LARGO_TEXTO)

# Nodo `audioEnviado`, dos burbujas
SIN_AUDIO = Respuesta(
    texto=(
        "*No puedo procesar audios ni videos 🎤*\n\n"
        "Escríbeme lo mismo en texto y lo resuelvo al instante. Con una línea me "
        'basta: "factura a Andrade por consultoría, 450".'
    )
)
SIN_AUDIO_2 = Respuesta(
    texto=(
        "El texto te deja revisar el dato antes de enviarlo, y a mí me deja "
        "repetírtelo antes de timbrar. En facturación esa doble revisión vale oro."
    )
)

# El submenú de emisión: LOS MISMOS TRES que ofrece el panel, ni uno más.
#
# Van como BOTONES y no como lista porque son exactamente tres, que es el tope
# de Meta para botones, y así se eligen de un toque en vez de abrir una hoja.
# Los rótulos caben en los 20 caracteres que permite la API.
#
# La retención recibida es la rara del trío: no se emite, se guarda. Está aquí
# porque es donde la busca quien acaba de recibirla, y su texto lo aclara.
EMITIR = Respuesta(
    texto="¿Qué documento necesitas?",
    botones=[
        ("factura", "Factura"),
        ("nota_credito", "Nota de crédito"),
        ("retencion_recibida", "Retención recibida"),
    ],
    pie=PIE_ESTANDAR,
)

# Nodos `notaCredito` y `retencion`: explican el documento y dicen qué hace
# falta. Emitir la nota por chat llega en una fase posterior.
NOTA_CREDITO = [
    Respuesta(
        texto=(
            "La nota de crédito sirve para anular o corregir una factura que ya se "
            "autorizó, o cuando el cliente te devuelve algo."
        )
    ),
    # NO se promete buscarla. El bot no guarda estado después de esta respuesta,
    # así que lo que el usuario contestara —«001-001-000000012», «450»— volvía al
    # menú, y «la factura 12» arrancaba una factura nueva. Se dice dónde se hace
    # de verdad, igual que ya hace la retención recibida.
    Respuesta(
        texto=(
            "Por chat todavía no la puedo emitir. Hazla desde el panel, en "
            "*Comprobantes → Nueva nota de crédito*: eliges la factura y te la "
            "deja lista."
        ),
        botones=[("menu", "Ver el menú")],
    ),
]

# Notas de débito, guías de remisión y liquidaciones de compra salieron del plan.
# Se contesta que ya no se hacen, en vez de dejar que ese texto caiga en FACTURAR
# y el bot empiece a armar una factura que nadie pidió.
YA_NO_SE_EMITE = Respuesta(
    texto=(
        "Ese documento ya no se emite en Factuchat. Hoy hay tres: *factura*, "
        "*nota de crédito* y *retención recibida*."
    ),
    botones=[("emitir", "Emitir un documento"), ("menu", "Ver el menú")],
)
# La retención recibida NO se emite: te la hizo tu cliente y te mandó el
# comprobante. Por chat todavía no se puede guardar —hace falta leer el XML—,
# así que se dice con todas las letras y se manda al sitio donde sí se hace.
RETENCION_RECIBIDA = [
    Respuesta(
        texto=(
            "La retención te la hace tu cliente: él te retiene una parte y se la "
            "entrega al SRI a tu nombre. Tú no la emites, la guardas."
        )
    ),
    Respuesta(
        texto=(
            "Guárdala desde el panel, en *Comprobantes → Retenciones recibidas*: ahí "
            "subes el XML que te mandaron y su valor se descuenta solo de lo que "
            "tienes que pagar."
        ),
        botones=[("menu", "Ver el menú")],
    ),
]

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
