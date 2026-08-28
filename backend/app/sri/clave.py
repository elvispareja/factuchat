"""Clave de acceso SRI: 49 dígitos (ficha técnica de comprobantes electrónicos).

Estructura: fecha(8 ddmmaaaa) + codDoc(2) + ruc(13) + ambiente(1) + serie(6)
+ secuencial(9) + código numérico(8) + tipo emisión(1) + dígito verificador(1).
"""

import secrets
from datetime import date


def digito_verificador_mod11(digitos: str) -> int:
    """Módulo 11 con pesos 2..7 de derecha a izquierda. 11→0, 10→1."""
    if not digitos.isdigit():
        raise ValueError("La clave debe contener solo dígitos")
    total = 0
    peso = 2
    for ch in reversed(digitos):
        total += int(ch) * peso
        peso = peso + 1 if peso < 7 else 2
    resto = 11 - (total % 11)
    if resto == 11:
        return 0
    if resto == 10:
        return 1
    return resto


def generar_clave_acceso(
    fecha_emision: date,
    codigo_documento: str,
    ruc: str,
    ambiente: str,  # "1" pruebas, "2" producción
    establecimiento: str,
    punto_emision: str,
    secuencial: int,
    codigo_numerico: str | None = None,
    tipo_emision: str = "1",  # emisión normal
) -> str:
    if len(ruc) != 13 or not ruc.isdigit():
        raise ValueError("RUC inválido para clave de acceso")
    if ambiente not in ("1", "2"):
        raise ValueError("Ambiente inválido (1=pruebas, 2=producción)")
    if codigo_numerico is None:
        # Aleatorio criptográfico: también hace de sal anti-adivinación de claves
        codigo_numerico = f"{secrets.randbelow(100_000_000):08d}"
    if len(codigo_numerico) != 8 or not codigo_numerico.isdigit():
        raise ValueError("Código numérico debe tener 8 dígitos")

    base = (
        fecha_emision.strftime("%d%m%Y")
        + codigo_documento
        + ruc
        + ambiente
        + establecimiento.zfill(3)
        + punto_emision.zfill(3)
        + f"{secuencial:09d}"
        + codigo_numerico
        + tipo_emision
    )
    if len(base) != 48:
        raise ValueError(f"Clave base inválida: {len(base)} dígitos")
    return base + str(digito_verificador_mod11(base))
