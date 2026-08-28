"""Carga masiva de clientes desde Excel/CSV con vista previa (fase 3.1).

Dos pasos, como en la maqueta: primero se analiza y se devuelve la vista previa
con los errores fila por fila, y solo después se confirma. Nada se guarda en el
primer paso. El archivo del usuario JAMÁS se ejecuta ni se interpreta como
fórmula: se lee como texto (OWASP A05).
"""

import csv
import io
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ClienteFinal
from app.db.models.enums import TipoIdentificacion

MAX_FILAS = 5000
MAX_BYTES = 5 * 1024 * 1024

COLUMNAS = {
    "identificacion": {"identificacion", "identificación", "cedula", "cédula", "ruc", "id"},
    "razon_social": {"razon_social", "razón social", "razon social", "nombre", "cliente"},
    "email": {"email", "correo", "e-mail"},
    "telefono": {"telefono", "teléfono", "celular", "movil", "móvil"},
    "direccion": {"direccion", "dirección"},
}


@dataclass
class FilaCarga:
    numero: int
    identificacion: str = ""
    razon_social: str = ""
    email: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    tipo_identificacion: str = ""
    errores: list[str] = field(default_factory=list)
    duplicado: bool = False

    @property
    def valida(self) -> bool:
        return not self.errores and not self.duplicado


class CargaMasivaError(Exception):
    """Problema con el archivo entero (no con una fila)."""


def _normalizar(cabecera: str) -> str | None:
    limpio = cabecera.strip().lower().lstrip("﻿")
    for destino, alias in COLUMNAS.items():
        if limpio in alias:
            return destino
    return None


def _tipo_identificacion(ident: str) -> tuple[str, str | None]:
    """(tipo, error). Reglas del SRI: RUC 13 terminado en 001, cédula 10."""
    if not ident.isdigit():
        return "", "La identificación debe ser solo números"
    if len(ident) == 13:
        if not ident.endswith("001"):
            return "", "RUC inválido: debe terminar en 001"
        return TipoIdentificacion.RUC.value, None
    if len(ident) == 10:
        return TipoIdentificacion.CEDULA.value, None
    return "", "La identificación debe tener 10 dígitos (cédula) o 13 (RUC)"


def analizar(contenido: bytes, nombre_archivo: str) -> list[FilaCarga]:
    """Vista previa: no toca la base de datos."""
    if len(contenido) > MAX_BYTES:
        raise CargaMasivaError("El archivo supera los 5 MB permitidos")

    if nombre_archivo.lower().endswith((".xlsx", ".xls")):
        raise CargaMasivaError(
            "Guarda tu archivo como CSV (en Excel: Archivo → Guardar como → CSV) y vuelve a subirlo"
        )

    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            texto = contenido.decode("latin-1")
        except UnicodeDecodeError as e:
            raise CargaMasivaError("No se pudo leer el archivo: revisa su codificación") from e

    muestra = texto[:4096]
    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t")
    except csv.Error:
        dialecto = csv.excel
    lector = csv.reader(io.StringIO(texto), dialecto)

    try:
        cabeceras = next(lector)
    except StopIteration as e:
        raise CargaMasivaError("El archivo está vacío") from e

    mapa = {i: _normalizar(c) for i, c in enumerate(cabeceras)}
    if "identificacion" not in mapa.values() or "razon_social" not in mapa.values():
        raise CargaMasivaError(
            "El archivo necesita al menos las columnas 'Identificación' y 'Razón social'"
        )

    filas: list[FilaCarga] = []
    vistas: set[str] = set()
    for numero, valores in enumerate(lector, start=2):
        if numero - 1 > MAX_FILAS:
            raise CargaMasivaError(f"El archivo supera las {MAX_FILAS} filas permitidas")
        if not any(v.strip() for v in valores):
            continue

        fila = FilaCarga(numero=numero)
        for i, valor in enumerate(valores):
            destino = mapa.get(i)
            if destino is None:
                continue
            # Se guarda como TEXTO: un valor que empiece por = nunca se evalúa
            limpio = valor.strip()
            if destino == "identificacion":
                fila.identificacion = re.sub(r"[\s\-.]", "", limpio)
            elif destino == "razon_social":
                fila.razon_social = limpio[:300]
            elif destino == "email":
                fila.email = limpio[:320] or None
            elif destino == "telefono":
                fila.telefono = limpio[:20] or None
            elif destino == "direccion":
                fila.direccion = limpio[:1000] or None

        if not fila.razon_social:
            fila.errores.append("Falta la razón social")
        if not fila.identificacion:
            fila.errores.append("Falta la identificación")
        else:
            tipo, error = _tipo_identificacion(fila.identificacion)
            if error:
                fila.errores.append(error)
            else:
                fila.tipo_identificacion = tipo
            if fila.identificacion in vistas:
                fila.errores.append("Repetido dentro del archivo")
            vistas.add(fila.identificacion)
        if fila.email and "@" not in fila.email:
            fila.errores.append("Correo inválido")

        filas.append(fila)

    if not filas:
        raise CargaMasivaError("El archivo no tiene filas con datos")
    return filas


def marcar_existentes(db: Session, tenant_id: uuid.UUID, filas: list[FilaCarga]) -> None:
    """Marca las que ya están guardadas: se omiten, no se duplican."""
    identificaciones = [f.identificacion for f in filas if f.identificacion]
    if not identificaciones:
        return
    existentes = set(
        db.scalars(
            select(ClienteFinal.identificacion).where(
                ClienteFinal.tenant_id == tenant_id,
                ClienteFinal.identificacion.in_(identificaciones),
            )
        ).all()
    )
    for fila in filas:
        if fila.identificacion in existentes:
            fila.duplicado = True


def guardar(db: Session, tenant_id: uuid.UUID, filas: list[FilaCarga], tope: int) -> int:
    """Guarda las filas válidas respetando el tope del plan. Devuelve cuántas."""
    guardadas = 0
    for fila in filas:
        if not fila.valida:
            continue
        if tope and guardadas >= tope:
            break
        db.add(
            ClienteFinal(
                tenant_id=tenant_id,
                tipo_identificacion=TipoIdentificacion(fila.tipo_identificacion),
                identificacion=fila.identificacion,
                razon_social=fila.razon_social,
                email=fila.email,
                telefono=fila.telefono,
                direccion=fila.direccion,
            )
        )
        guardadas += 1
    db.flush()
    return guardadas
