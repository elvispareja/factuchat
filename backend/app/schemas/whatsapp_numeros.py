"""Esquemas de los teléfonos autorizados a facturar por chat.

Aquí vive la normalización del número, y es la pieza más importante del
módulo. Un teléfono ecuatoriano se escribe de cuatro maneras según a quién le
preguntes —`0993053670`, `+593 99 305 3670`, `593993053670`, `+5930993053670`—
y Meta solo reconoce una: dígitos, con código de país y sin el cero de la
marcación nacional.

Ese cero de más ya ha costado dos depuraciones largas: el número queda
guardado, el panel lo muestra bien, y los mensajes del cliente simplemente no
casan con nadie. Por eso se normaliza AL GUARDAR y no al consultar: si se
normalizara en cada consulta bastaría con que una se olvidara.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Un móvil ecuatoriano normalizado son 12 dígitos (593 + 9). Se acepta un rango
# ancho porque nada obliga a que el equipo sea de Ecuador: el contador puede
# estar en Venezuela o el dueño de viaje con una línea española.
MIN_DIGITOS = 8
MAX_DIGITOS = 15


def normalizar(entrada: str) -> str:
    """Deja el teléfono como lo manda Meta: solo dígitos y con código de país.

    Lanza ValueError con un mensaje que se le puede enseñar al cliente."""
    tenia_prefijo = entrada.strip().startswith("+")
    digitos = "".join(c for c in entrada if c.isdigit())
    if not digitos:
        raise ValueError("Escribe un número de teléfono.")

    # `+593 0 99…` — el cero es de la marcación dentro del país y no existe en
    # formato internacional. Después de un código de país nunca va un cero, así
    # que quitarlo no puede romper un número legítimo.
    if digitos.startswith("593") and digitos[3:4] == "0":
        digitos = "593" + digitos[4:]

    if not tenia_prefijo and not digitos.startswith("593"):
        # Sin «+» delante interpretamos marcación ecuatoriana, que es lo que
        # escribe la práctica totalidad de los clientes: `0993053670`.
        if digitos.startswith("0"):
            digitos = "593" + digitos[1:]
        elif len(digitos) == 9 and digitos.startswith("9"):
            digitos = "593" + digitos

    if not (MIN_DIGITOS <= len(digitos) <= MAX_DIGITOS):
        raise ValueError(
            "Ese número no parece válido. Escríbelo como 0993053670 "
            "o, si es de otro país, con el signo + y su código."
        )
    return digitos


def para_mostrar(numero: str) -> str:
    """`593993053670` → `+593 99 305 3670`. Solo para la pantalla."""
    if numero.startswith("593") and len(numero) == 12:
        resto = numero[3:]
        return f"+593 {resto[:2]} {resto[2:5]} {resto[5:]}"
    return f"+{numero}"


class NumeroIn(BaseModel):
    """Alta de un teléfono. El cliente escribe como quiera; se guarda limpio."""

    numero: str = Field(min_length=1, max_length=25)
    # De quién es el teléfono: «Karina, mostrador». Lo ve solo esta cuenta.
    etiqueta: str = Field(min_length=1, max_length=60)

    @field_validator("numero")
    @classmethod
    def _normalizar(cls, v: str) -> str:
        return normalizar(v)

    @field_validator("etiqueta")
    @classmethod
    def _limpiar_etiqueta(cls, v: str) -> str:
        limpia = " ".join(v.split())
        if not limpia:
            raise ValueError("Escribe de quién es el número.")
        return limpia


class NumeroOut(BaseModel):
    """Lo que ve el panel.

    Va `mostrar` ya formateado desde aquí: si lo compusiera el navegador
    habría dos sitios donde vive la misma regla, y el día que cambie solo se
    acordará uno de los dos."""

    id: uuid.UUID
    numero: str
    mostrar: str
    etiqueta: str
    # El primero que se dio de alta es «Principal» en la maqueta: es el del
    # dueño, el que se creó con la cuenta.
    principal: bool
    # Mientras sea false el número NO factura: está esperando su código.
    verificado: bool
    created_at: datetime


class VerificarIn(BaseModel):
    """El código de seis dígitos que llegó al WhatsApp de ese número."""

    codigo: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
