"""Plantillas de avisos que el sistema envía por iniciativa propia (fase 5.3).

Fuera de la ventana de 24 horas, WhatsApp solo permite escribir con plantillas
aprobadas por Meta. Cada una se registra allá con su nombre y sus variables
posicionales; aquí se guardan el nombre, el orden de las variables y el texto
aprobado, para poder previsualizarlo sin llamar a Meta.

Variables del plan: {nombre}, {plan}, {fecha}, {digito}, {enlace}.
"""

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy.orm import Session

from app.services import parametros

MESES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


class Aviso(StrEnum):
    PRE_DECLARACION = "PRE_DECLARACION"
    CUPO_AGOTADO = "CUPO_AGOTADO"
    PAGO_VENCIDO = "PAGO_VENCIDO"


@dataclass(frozen=True)
class Plantilla:
    """nombre: el registrado en Meta. variables: orden posicional del body."""

    aviso: Aviso
    nombre: str
    idioma: str
    variables: tuple[str, ...]
    texto: str

    def render(self, datos: dict[str, str]) -> str:
        """Vista previa local del mensaje, con las variables sustituidas."""
        salida = self.texto
        for clave, valor in datos.items():
            salida = salida.replace("{" + clave + "}", str(valor))
        return salida

    def valores(self, datos: dict[str, str]) -> list[str]:
        """Los parámetros en el ORDEN que espera Meta. Un orden equivocado
        manda la fecha donde va el nombre y el mensaje sale absurdo."""
        faltan = [v for v in self.variables if v not in datos]
        if faltan:
            raise ValueError(f"Faltan variables para la plantilla: {', '.join(faltan)}")
        return [str(datos[v]) for v in self.variables]


PLANTILLAS: dict[Aviso, Plantilla] = {
    Aviso.PRE_DECLARACION: Plantilla(
        aviso=Aviso.PRE_DECLARACION,
        nombre="factuchat_pre_declaracion",
        idioma="es",
        variables=("nombre", "digito", "fecha", "enlace"),
        texto=(
            "Hola {nombre} 👋\n\n"
            "Tu noveno dígito es {digito}, así que declaras hasta el {fecha}.\n\n"
            "Tu reporte con el número final a pagar, ya descontadas tus retenciones, "
            "está listo aquí: {enlace}"
        ),
    ),
    Aviso.CUPO_AGOTADO: Plantilla(
        aviso=Aviso.CUPO_AGOTADO,
        nombre="factuchat_cupo_agotado",
        idioma="es",
        variables=("nombre", "plan", "enlace"),
        texto=(
            "Hola {nombre}, usaste todos los comprobantes de tu plan {plan} este mes.\n\n"
            "Ningún plan se cobra automáticamente: tú decides si renovar, recargar o "
            "subir de plan pagando solo la diferencia.\n\n"
            "Aquí puedes elegir: {enlace}"
        ),
    ),
    Aviso.PAGO_VENCIDO: Plantilla(
        aviso=Aviso.PAGO_VENCIDO,
        nombre="factuchat_pago_vencido",
        idioma="es",
        variables=("nombre", "plan", "fecha", "enlace"),
        texto=(
            "Hola {nombre}, el pago de tu plan {plan} venció el {fecha}.\n\n"
            "Tus comprobantes y tus datos siguen aquí. Para seguir emitiendo, "
            "regulariza el pago desde este enlace: {enlace}"
        ),
    ),
}


# Qué parámetro guarda el texto editado de cada aviso
CLAVE_PARAMETRO: dict[Aviso, str] = {
    Aviso.PRE_DECLARACION: parametros.AVISO_PRE_DECLARACION,
    Aviso.CUPO_AGOTADO: parametros.AVISO_CUPO_AGOTADO,
    Aviso.PAGO_VENCIDO: parametros.AVISO_PAGO_VENCIDO,
}

_VARIABLE = re.compile(r"\{([a-z_]+)\}")


class TextoInvalido(ValueError):
    """El texto editado no sirve para enviarse."""


def revisar_texto(aviso: Aviso, texto: str) -> str:
    """Comprueba que un texto editado se puede enviar de verdad.

    Meta registra cada plantilla con un número FIJO de variables posicionales.
    Si alguien borra {enlace} del texto pero la plantilla sigue declarando
    cuatro, el envío sale con los parámetros descolocados —la fecha donde va el
    nombre— o Meta lo rechaza y cobra igual el intento. Por eso el texto tiene
    que usar exactamente las mismas variables, ni una más ni una menos.
    """
    limpio = texto.strip()
    if not limpio:
        raise TextoInvalido("El texto no puede quedar vacío")
    if len(limpio) > 900:
        raise TextoInvalido("El texto supera los 900 caracteres que admite una plantilla")

    plantilla = PLANTILLAS[aviso]
    usadas = set(_VARIABLE.findall(limpio))
    declaradas = set(plantilla.variables)
    faltan = declaradas - usadas
    sobran = usadas - declaradas
    if faltan:
        raise TextoInvalido(
            "Faltan variables que la plantilla aprobada por Meta espera: "
            + ", ".join("{" + v + "}" for v in sorted(faltan))
        )
    if sobran:
        raise TextoInvalido(
            "Estas variables no existen en esta plantilla: "
            + ", ".join("{" + v + "}" for v in sorted(sobran))
        )
    return limpio


def texto_de(db: Session, aviso: Aviso) -> str:
    """El texto vigente: el editado desde Configuración si lo hay, si no el de
    fábrica. Un texto guardado que ya no valide se ignora —mejor enviar el de
    fábrica que no enviar nada— pero eso solo puede pasar si se editó la tabla
    a mano, porque el endpoint valida antes de guardar."""
    guardado = parametros.leer_texto(db, CLAVE_PARAMETRO[aviso])
    if guardado:
        try:
            return revisar_texto(aviso, guardado)
        except TextoInvalido:
            pass
    return PLANTILLAS[aviso].texto


def fecha_larga(cuando: date) -> str:
    return f"{cuando.day} de {MESES[cuando.month - 1]}"


def preparar(db: Session, aviso: Aviso, datos: dict[str, str]) -> tuple[Plantilla, list[str], str]:
    """(plantilla, valores en orden, vista previa). Falla si falta una variable
    ANTES de llamar a Meta, que cobra igual el intento fallido.

    La vista previa usa el texto vigente —que puede venir editado— pero el
    NOMBRE y el ORDEN de las variables son siempre los registrados en Meta:
    eso no lo puede cambiar nadie desde el panel.
    """
    plantilla = PLANTILLAS[aviso]
    vigente = texto_de(db, aviso)
    vista = plantilla.render(datos) if vigente == plantilla.texto else _render(vigente, datos)
    return plantilla, plantilla.valores(datos), vista


def _render(texto: str, datos: dict[str, str]) -> str:
    salida = texto
    for clave, valor in datos.items():
        salida = salida.replace("{" + clave + "}", str(valor))
    return salida
