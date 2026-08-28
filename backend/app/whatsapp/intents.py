"""Reconocimiento de intención en lenguaje natural (fase 5.2).

Reglas antes que modelo: el usuario ecuatoriano escribe "facturale 20 dolares a
Juan" o "hazme una factura", y eso se resuelve con patrones. La IA queda para lo
que las reglas no cubren (fase posterior), no para lo que sí.

Nada de lo que se decide aquí ejecuta nada por sí solo: el intent solo elige la
conversación. Enviar al SRI exige confirmación explícita (OWASP A06).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class Intent(StrEnum):
    FACTURAR = "FACTURAR"
    CONSULTAR = "CONSULTAR"
    REENVIAR = "REENVIAR"
    REPORTE = "REPORTE"
    AYUDA = "AYUDA"
    CANCELAR = "CANCELAR"
    CONFIRMAR = "CONFIRMAR"
    DESCONOCIDO = "DESCONOCIDO"


def normalizar(texto: str) -> str:
    """Sin tildes y en minúsculas: la gente escribe con y sin ellas."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sin_tildes.lower().strip()


PATRONES: list[tuple[Intent, list[str]]] = [
    (
        Intent.CONFIRMAR,
        [r"^\s*(si|sí|dale|confirmo|confirmar|ok|okey|listo|correcto|de una|ya)\s*$"],
    ),
    (
        Intent.CANCELAR,
        [r"^\s*(no|cancelar|cancela|olvidalo|dejalo|nada|salir|atras)\s*$", r"\bcancel"],
    ),
    # REENVIAR va ANTES que FACTURAR: "reenviame la factura" contiene "factura"
    # y si FACTURAR mirara primero se llevaría todos los reenvíos.
    (
        Intent.REENVIAR,
        [r"\breenv", r"\bvuelve a enviar", r"\bmanda(me)? (de nuevo|otra vez)"],
    ),
    (
        Intent.FACTURAR,
        [
            r"\bfactur",  # facturar, factura, facturale, facturame
            r"\bcobr(ar|ale|arle|o)\b",
            r"\bvend[ií]\b",
            r"\bnota de (credito|debito)\b",
            r"\bemit(ir|e|eme)\b",
        ],
    ),
    (
        Intent.CONSULTAR,
        [
            r"\bconsult",
            r"\bbusca(r|me)?\b",
            r"\bcuanto (le )?(factur|vend)",
            r"\bmis (facturas|comprobantes)\b",
            r"\bultim[ao]s? (factura|comprobante)",
        ],
    ),
    (
        Intent.REPORTE,
        [
            r"\breporte",
            r"\bresumen\b",
            r"\bcuanto (debo|tengo que) (declarar|pagar)",
            r"\bdeclaracion\b",
            r"\bmis ventas\b",
        ],
    ),
    (
        Intent.AYUDA,
        [r"\bayuda\b", r"\bque puedes hacer", r"\bcomo funciona", r"^\s*(hola|buenas|hey)\b"],
    ),
]


@dataclass
class Reconocido:
    intent: Intent
    texto: str
    monto: Decimal | None = None
    nombre: str | None = None
    identificacion: str | None = None
    numero_comprobante: str | None = None
    entidades: dict = field(default_factory=dict)


# "20", "20.50", "$20", "20 dolares", "20 usd"
_MONTO = re.compile(
    r"(?:\$\s*)?(\d{1,7}(?:[.,]\d{1,2})?)\s*(?:d[oó]lares?|usd|dolar)?", re.IGNORECASE
)
_CEDULA_O_RUC = re.compile(r"\b(\d{10}|\d{13})\b")
_NUMERO_COMPROBANTE = re.compile(r"\b(\d{3}-\d{3}-\d{6,9})\b")
# "a Juan", "para Ferretería El Tornillo"
_NOMBRE = re.compile(r"\b(?:a|para)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ][\w\sÁÉÍÓÚÑáéíóúñ.&'-]{2,60})")

PALABRAS_MONEDA = ("dolar", "dolares", "usd", "$")


def _extraer_monto(texto: str) -> Decimal | None:
    """Solo se toma como monto un número que parezca dinero: con símbolo,
    con decimales o acompañado de la palabra. Un '2' suelto en "factura 2
    camisetas" es cantidad, no precio."""
    normalizado = normalizar(texto)
    candidatos = []
    for m in _MONTO.finditer(texto):
        crudo = m.group(1)
        contexto = texto[max(0, m.start() - 3) : m.end() + 12].lower()
        tiene_moneda = any(p in normalizar(contexto) for p in PALABRAS_MONEDA)
        tiene_decimales = "." in crudo or "," in crudo
        if not (tiene_moneda or tiene_decimales):
            continue
        try:
            candidatos.append(Decimal(crudo.replace(",", ".")))
        except InvalidOperation:
            continue
    if candidatos:
        return max(candidatos)
    # Sin pistas de moneda: si hay un único número y el texto habla de facturar,
    # se toma como monto; es el caso "facturale 20 a Juan".
    if "factur" in normalizado or "cobr" in normalizado:
        sueltos = re.findall(r"\b(\d{1,7})\b", texto)
        # Descarta cédulas y RUC, que no son montos
        sueltos = [s for s in sueltos if len(s) not in (10, 13)]
        if len(sueltos) == 1:
            try:
                return Decimal(sueltos[0])
            except InvalidOperation:
                return None
    return None


def reconocer(texto: str) -> Reconocido:
    normalizado = normalizar(texto)

    intent = Intent.DESCONOCIDO
    for candidato, patrones in PATRONES:
        if any(re.search(p, normalizado) for p in patrones):
            intent = candidato
            break

    resultado = Reconocido(intent=intent, texto=texto.strip())

    ident = _CEDULA_O_RUC.search(texto)
    if ident:
        resultado.identificacion = ident.group(1)

    numero = _NUMERO_COMPROBANTE.search(texto)
    if numero:
        resultado.numero_comprobante = numero.group(1)

    if intent in (Intent.FACTURAR, Intent.CONSULTAR, Intent.REENVIAR):
        resultado.monto = _extraer_monto(texto)
        nombre = _NOMBRE.search(texto)
        if nombre:
            limpio = nombre.group(1).strip()
            # Corta en la palabra de moneda si el nombre se comió el monto
            for palabra in (" por ", " de $", " dolares", " usd"):
                if palabra in limpio.lower():
                    limpio = limpio[: limpio.lower().index(palabra)]
            resultado.nombre = limpio.strip(" .,")

    return resultado
