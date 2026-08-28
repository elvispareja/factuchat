"""Términos de uso y tratamiento de datos (fase 6.2, exigencia LOPDP).

La maqueta define UN SOLO documento de 9 secciones —las 1 a 4 son los términos
de uso y las 5 a 9 el aviso de tratamiento de datos— y UNA casilla visible que
cubre ambas cosas. El modelo, en cambio, guarda las DOS banderas por separado,
porque legalmente son dos consentimientos distintos.

Un booleano no prueba nada: dentro de un año, con el texto ya actualizado,
sería imposible saber qué aceptó esa persona. Por eso cada constancia guarda la
VERSIÓN del documento, el HASH SHA-256 del texto exacto que se mostró y el
timestamp. La carga de la prueba es del responsable del tratamiento, no del
titular. Y la tabla es append-only: cada aceptación, cada versión nueva y cada
retiro son filas propias; nunca se edita la anterior.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AceptacionTerminos

# Las dos banderas del consentimiento. Se piden juntas en pantalla (una casilla,
# como la maqueta) pero se registran separadas.
CONDICIONES = "TERMINOS"
DATOS = "DATOS_PERSONALES"

ACCION_ACEPTADO = "ACEPTADO"
ACCION_RETIRADO = "RETIRADO"

TITULO = "Términos de uso y tratamiento de datos"
VERSION = "2026.08"
ACTUALIZADO = "agosto de 2026"
PIE = f"Última actualización: {ACTUALIZADO} · Factuchat, Quito, Ecuador"

# Texto literal de la maqueta (Facturas IA.dc.html, líneas 175-199).
SECCIONES: list[tuple[str, list[str]]] = [
    (
        "1. Qué es Factuchat",
        [
            "Factuchat es un servicio de facturación electrónica que opera por WhatsApp. "
            "Emite comprobantes autorizados ante el SRI usando tu certificado de firma "
            "electrónica, y guarda tus documentos para que puedas consultarlos y reenviarlos.",
            "El servicio no reemplaza a tu contador ni presta asesoría tributaria. Tú eres "
            "responsable de la veracidad de los datos que declaras y de la presentación de "
            "tus obligaciones ante la administración tributaria.",
        ],
    ),
    (
        "2. Tu cuenta y tu firma",
        [
            "Para emitir necesitas subir tu certificado de firma electrónica. Se almacena "
            "cifrado y se usa únicamente para firmar los comprobantes que tú autorizas. No "
            "lo compartimos con terceros ni lo usamos para otro fin.",
            "Eres responsable del número de WhatsApp asociado a tu cuenta y de los números "
            "adicionales que autorices. Cualquier comprobante emitido desde esos números se "
            "considera emitido por ti.",
        ],
    ),
    (
        "3. Planes, pagos y vigencia",
        [
            "Los planes se cobran por adelantado e incluyen una cantidad determinada de "
            "comprobantes. Los precios se muestran con IVA incluido. En los planes que lo "
            "indican, los comprobantes no utilizados se acumulan al mes siguiente; en los "
            "demás corresponden al período contratado.",
            "Al terminar tu ciclo cuentas con diez días de gracia para renovar y conservar "
            "lo acumulado. Pasado ese plazo sin renovación, el saldo acumulado se cierra. "
            "Tus comprobantes ya emitidos permanecen disponibles.",
        ],
    ),
    (
        "4. Uso correcto del servicio",
        [
            "El asistente trabaja con texto y con los archivos que tu plan permita. Antes de "
            "enviar cualquier documento al SRI te muestra un resumen para que confirmes. Una "
            "vez autorizado un comprobante, su anulación se realiza mediante los mecanismos "
            "que establece la normativa.",
            "No está permitido usar el servicio para emitir comprobantes falsos, suplantar a "
            "otra persona o vulnerar la normativa tributaria vigente.",
        ],
    ),
    (
        "5. Qué datos recogemos",
        [
            "Recogemos los datos que nos entregas para prestar el servicio: nombres y "
            "apellidos, documento de identificación, correo, teléfono, país, provincia y "
            "ciudad, además de los datos de tus clientes y de los comprobantes que emites.",
            "También conservamos el comprobante de pago que adjuntas y el registro de las "
            "conversaciones necesarias para dar soporte y trazabilidad a tus emisiones.",
        ],
    ),
    (
        "6. Para qué los usamos",
        [
            "Usamos tus datos para emitir y firmar tus comprobantes, transmitirlos al SRI, "
            "entregarlos a tus clientes, generar tus reportes, gestionar tu plan y atender tu "
            "soporte. También para contactarte en el horario que agendaste.",
            "No vendemos tus datos ni los cedemos a terceros con fines comerciales. Los "
            "compartimos únicamente con la administración tributaria, con el procesador de "
            "pagos cuando pagas con tarjeta, y con los proveedores tecnológicos necesarios "
            "para operar el servicio.",
        ],
    ),
    (
        "7. Cuánto tiempo los guardamos",
        [
            "Conservamos tus comprobantes electrónicos por siete años, conforme al plazo que "
            "exige la normativa. El resto de tus datos se conserva mientras tu cuenta esté "
            "activa y durante el tiempo que la ley requiera después.",
        ],
    ),
    (
        "8. Tus derechos",
        [
            "Puedes solicitar en cualquier momento el acceso, la rectificación, la eliminación "
            "o la portabilidad de tus datos, así como retirar esta autorización. Escríbenos "
            "por WhatsApp o a nuestro correo de contacto y atendemos tu solicitud.",
            "El retiro de la autorización puede impedir que sigamos emitiendo comprobantes a "
            "tu nombre, ya que esos datos son indispensables para el servicio.",
        ],
    ),
    (
        "9. Cambios",
        [
            "Si actualizamos este documento te avisamos por el mismo chat antes de que entre "
            "en vigor. Si continúas usando el servicio después del aviso, entendemos que "
            "aceptas la versión actualizada.",
        ],
    ),
]

# Texto de la casilla del checkout, literal de la maqueta
TEXTO_CASILLA = (
    "Acepto los términos y condiciones de uso y el tratamiento de mis datos para "
    "emitir mis comprobantes y activar mi cuenta."
)


@dataclass(frozen=True)
class Documento:
    titulo: str
    version: str
    actualizado: str
    secciones: list[tuple[str, list[str]]]

    @property
    def texto(self) -> str:
        partes = [self.titulo, ""]
        for encabezado, parrafos in self.secciones:
            partes.append(encabezado)
            partes.extend(parrafos)
            partes.append("")
        partes.append(PIE)
        return "\n".join(partes)

    @property
    def sha256(self) -> str:
        """Huella del texto EXACTO que se mostró. Si el texto cambia sin subir
        la versión, el hash lo delata."""
        return hashlib.sha256(self.texto.encode("utf-8")).hexdigest()


DOCUMENTO = Documento(titulo=TITULO, version=VERSION, actualizado=ACTUALIZADO, secciones=SECCIONES)


class TerminosError(Exception):
    """Motivo legible para el usuario."""


def vigente() -> dict:
    """Lo que la landing muestra y el checkout exige aceptar."""
    return {
        "titulo": DOCUMENTO.titulo,
        "version": DOCUMENTO.version,
        "actualizado": DOCUMENTO.actualizado,
        "sha256": DOCUMENTO.sha256,
        "pie": PIE,
        "texto_casilla": TEXTO_CASILLA,
        "secciones": [{"encabezado": e, "parrafos": p} for e, p in DOCUMENTO.secciones],
    }


def registrar(
    db: Session,
    email: str,
    acepta_condiciones: bool,
    acepta_datos: bool,
    nombre: str | None = None,
    identificacion: str | None = None,
    tenant_id: uuid.UUID | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    origen: str = "CHECKOUT",
) -> list[AceptacionTerminos]:
    """Deja constancia de ambos consentimientos, con versión, hash y timestamp.

    Se exigen los dos: sin el tratamiento de datos no hay base legal para
    procesar los datos del contribuyente ni los de sus clientes finales.
    """
    if not (acepta_condiciones and acepta_datos):
        raise TerminosError("Acepta las condiciones para poder continuar.")

    ahora = datetime.now(UTC)
    creadas = []
    for bandera in (CONDICIONES, DATOS):
        constancia = AceptacionTerminos(
            tenant_id=tenant_id,
            email=email.strip().lower()[:320],
            nombre=nombre,
            identificacion=identificacion,
            documento=bandera,
            version=DOCUMENTO.version,
            sha256=DOCUMENTO.sha256,
            aceptado=True,
            ip=ip,
            user_agent=user_agent,
            origen=origen,
            aceptado_at=ahora,
        )
        db.add(constancia)
        creadas.append(constancia)
    db.flush()
    return creadas


def registrar_retiro(
    db: Session,
    email: str,
    canal: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> list[AceptacionTerminos]:
    """El retiro de la autorización (sección 8) también deja su propia fila.

    Nunca se edita ni se borra la aceptación anterior: el histórico completo es
    la prueba, y borrarlo destruiría justamente lo que hay que demostrar.
    """
    ahora = datetime.now(UTC)
    filas = []
    for bandera in (CONDICIONES, DATOS):
        fila = AceptacionTerminos(
            email=email.strip().lower()[:320],
            documento=bandera,
            version=DOCUMENTO.version,
            sha256=DOCUMENTO.sha256,
            aceptado=False,
            ip=ip,
            user_agent=user_agent,
            origen=f"{ACCION_RETIRADO}:{canal}"[:40],
            aceptado_at=ahora,
        )
        db.add(fila)
        filas.append(fila)
    db.flush()
    return filas


def historial(db: Session, email: str) -> list[dict]:
    filas = db.scalars(
        select(AceptacionTerminos)
        .where(AceptacionTerminos.email == email.strip().lower())
        .order_by(AceptacionTerminos.aceptado_at.desc())
    ).all()
    return [
        {
            "documento": a.documento,
            "aceptado": a.aceptado,
            "version": a.version,
            "sha256": a.sha256,
            "aceptado_at": a.aceptado_at.isoformat(),
            "ip": a.ip,
            "origen": a.origen,
            # Si el documento cambió desde entonces, se ve aquí
            "sobre_version_vigente": a.sha256 == DOCUMENTO.sha256,
        }
        for a in filas
    ]


def consentimiento_vigente(db: Session, email: str) -> bool:
    """¿Esta persona tiene AMBOS consentimientos activos sobre el texto actual?

    Se mira la última fila de cada bandera: un retiro posterior invalida la
    aceptación previa aunque esta siga en la tabla.
    """
    ultimo: dict[str, AceptacionTerminos] = {}
    filas = db.scalars(
        select(AceptacionTerminos)
        .where(AceptacionTerminos.email == email.strip().lower())
        .order_by(AceptacionTerminos.aceptado_at)
    ).all()
    for fila in filas:
        ultimo[fila.documento] = fila

    return all(
        bandera in ultimo
        and ultimo[bandera].aceptado
        and ultimo[bandera].sha256 == DOCUMENTO.sha256
        for bandera in (CONDICIONES, DATOS)
    )
