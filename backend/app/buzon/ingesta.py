"""Ingesta del buzón: de un correo crudo a crédito tributario (fase 7.1).

El orden de este archivo es el orden de las garantías:

  1. **De quién es** lo decide la dirección de entrega, nunca el XML.
  2. **Se registra siempre**, aunque el flag esté apagado y aunque el parseo
     falle: la maqueta lo dice explícitamente («mientras el flag esté apagado
     los correos solo se registran para depurar»).
  3. **No se cuenta dos veces**: candado en Redis mientras se procesa,
     deduplicación por (tenant, message_id) y por (tenant, clave de acceso).
  4. **El XML del emisor debe apuntar al inquilino**: si el RUC retenido no es
     el suyo, el documento se rechaza. Es el mismo control que ya se aplica al
     certificado de firma.
  5. **Nada en claro en disco**: el mensaje completo se guarda cifrado con su
     propia clave, con nombre derivado del UUID de la fila —jamás del asunto ni
     del nombre del adjunto, que los escribe el remitente—.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.buzon import correo as correo_mod
from app.buzon.parser import BuzonParseError, ComprobanteLeido, leer
from app.core.config import get_settings
from app.core.crypto import aesgcm_decrypt, aesgcm_encrypt
from app.db.models import BuzonCorreo, RetencionRecibida, Tenant
from app.db.models.enums import EstadoCorreoBuzon
from app.services import planes

logger = logging.getLogger("factuchat.buzon")

# Dominios de uso separados: un blob de correo no puede reutilizarse como .p12
AAD_BUZON = b"factuchat/buzon/correo"

ORIGEN_BUZON = "BUZON"
ORIGEN_MANUAL = "MANUAL"


class BuzonError(Exception):
    """Fallo de ingesta que NO es culpa del contenido del correo."""


class RetencionRechazada(Exception):
    """El XML se leyó, pero no puede acreditarse. El motivo SE LE MUESTRA al
    cliente que lo subió: por eso está redactado para él y no para el log."""


class RetencionDuplicada(RetencionRechazada):
    """Esa retención ya está registrada, por la puerta que fuera."""


def _ruta_payload(tenant_id: uuid.UUID, correo_id: uuid.UUID) -> Path:
    """Carpeta por inquilino, nombre por UUID de la fila.

    Derivar el nombre del Message-ID, del asunto o del nombre del adjunto —todos
    escritos por el remitente— permitiría escribir fuera del directorio o pisar
    el archivo de otro inquilino.
    """
    destino = Path(get_settings().storage_dir) / "buzon" / str(tenant_id)
    destino.mkdir(parents=True, exist_ok=True)
    return destino / f"{correo_id}.eml.enc"


def _clave() -> str:
    s = get_settings()
    if not s.buzon_enc_key:
        raise BuzonError("BUZON_ENC_KEY no está configurada: no se guarda nada sin cifrar")
    return s.buzon_enc_key


def _anotar(db: Session, ruta: Path) -> None:
    """Apunta el fichero recién escrito en la sesión.

    Los ficheros se escriben ANTES del commit, y un aborto posterior descarta las
    filas pero no el disco. Sin este registro, cada reintento dejaba una copia
    cifrada huérfana —de hasta 15 MB— que ya nadie podía relacionar ni borrar.
    Quien abre la transacción las limpia si se revierte.
    """
    db.info.setdefault("buzon_archivos", []).append(ruta)


def limpiar_archivos(db: Session) -> None:
    """Borra los ficheros escritos por una transacción que no llegó a confirmar."""
    for ruta in db.info.pop("buzon_archivos", []):
        try:
            Path(ruta).unlink(missing_ok=True)
        except OSError as e:  # noqa: PERF203 — un fallo por fichero no detiene el resto
            logger.warning("No se pudo borrar el fichero huérfano %s: %s", ruta, e)


def olvidar_archivos(db: Session) -> None:
    """Tras el commit los ficheros ya son buenos: se deja de vigilarlos."""
    db.info.pop("buzon_archivos", None)


def recien_creadas(db: Session) -> list[RetencionRecibida]:
    """Las retenciones que esta ingesta acaba de crear, para mandarlas a
    verificar contra el SRI en cuanto la transacción confirme."""
    return list(db.info.get("buzon_nuevas", []))


def guardar_cifrado(db: Session, tenant_id: uuid.UUID, correo_id: uuid.UUID, crudo: bytes) -> str:
    ruta = _ruta_payload(tenant_id, correo_id)
    blob = aesgcm_encrypt(_clave(), crudo, AAD_BUZON, "BUZON_ENC_KEY")
    ruta.write_text(blob, encoding="ascii")
    _anotar(db, ruta)
    return str(ruta)


def leer_cifrado(ruta: str) -> bytes:
    """Descifra el mensaje guardado. Lo usa el visor de XML crudo del panel
    interno, que es la única forma de ver el contenido de un correo."""
    blob = Path(ruta).read_text(encoding="ascii")
    return aesgcm_decrypt(_clave(), blob, AAD_BUZON, "BUZON_ENC_KEY")


def _tipo_legible(leido: ComprobanteLeido) -> str:
    return {
        "RETENCION": "Retención recibida",
        "FACTURA": "Factura recibida",
        "NOTA_CREDITO": "Nota de crédito recibida",
        "NOTA_DEBITO": "Nota de débito recibida",
        "GUIA_REMISION": "Guía de remisión recibida",
        "LIQUIDACION_COMPRA": "Liquidación de compra recibida",
    }.get(leido.tipo, "XML adjunto")


def resolver_tenant(db: Session, entrante: correo_mod.CorreoEntrante) -> uuid.UUID | None:
    """Devuelve solo el identificador: quien resuelve la dirección no necesita
    —ni debe— llevarse la ficha del inquilino."""
    return correo_mod.tenant_por_direccion(db, entrante.destinatarios)


def registrar(
    db: Session,
    tenant: Tenant,
    entrante: correo_mod.CorreoEntrante,
) -> tuple[BuzonCorreo, bool]:
    """Deja constancia del correo. Devuelve (fila, es_nuevo).

    Se ejecuta con el contexto RLS del inquilino: PostgreSQL, y no este código,
    es quien garantiza que la fila caiga en el buzón correcto.
    """
    previo = db.scalars(
        select(BuzonCorreo).where(BuzonCorreo.message_id == entrante.message_id)
    ).first()
    if previo is not None:
        return previo, False

    fila = BuzonCorreo(
        tenant_id=tenant.id,
        message_id=entrante.message_id,
        remitente=entrante.remitente,
        asunto=(entrante.asunto or "")[:500] or None,
        estado=EstadoCorreoBuzon.RECIBIDO,
    )
    db.add(fila)
    db.flush()
    fila.payload_path = guardar_cifrado(db, tenant.id, fila.id, entrante.crudo)
    return fila, True


def procesar(db: Session, tenant: Tenant, fila: BuzonCorreo, entrante: correo_mod.CorreoEntrante):
    """Parsea los XML del correo y suma lo que corresponda.

    Un correo puede traer varios comprobantes; se procesan todos, pero el estado
    de la fila lo marca el primero que sea útil.
    """
    if not entrante.xmls:
        fila.estado = EstadoCorreoBuzon.ERROR
        fila.motivo_error = "El correo no traía ningún XML adjunto"
        fila.procesado_at = datetime.now(UTC)
        return fila

    creadas: list[RetencionRecibida] = []
    primer_error: str | None = None
    duplicado = False

    for adjunto in entrante.xmls:
        try:
            leido = leer(adjunto.datos)
        except BuzonParseError as e:
            primer_error = primer_error or str(e)
            continue

        if fila.tipo_detectado is None:
            fila.tipo_detectado = _tipo_legible(leido)
            fila.clave_acceso = leido.clave_acceso
            fila.xml_sha256 = hashlib.sha256(adjunto.datos).hexdigest()

        if leido.tipo != "RETENCION":
            # Facturas y notas recibidas se archivan; no son crédito tributario
            continue

        motivo = _por_que_no_acredita(leido, tenant)
        if motivo:
            primer_error = primer_error or motivo
            continue

        existente = _ya_registrada(db, tenant, leido)
        if existente is not None:
            duplicado = True
            continue

        try:
            nueva = _crear_retencion(db, tenant, fila.id, leido, adjunto.datos)
            creadas.append(nueva)
            db.info.setdefault("buzon_nuevas", []).append(nueva)
        except IntegrityError:
            # Otro proceso la insertó entre el SELECT y el INSERT. El punto de
            # guardado deja la transacción utilizable: sin él, el choque
            # arrastraría el registro del correo entero.
            duplicado = True

    fila.procesado_at = datetime.now(UTC)
    if creadas:
        fila.estado = EstadoCorreoBuzon.PARSEADO
        # Regla 7.2: el XML del buzón se lee, pero NO gasta cupo de IA. Pasa por
        # el MISMO punto donde se descuenta cualquier otro análisis, y sale
        # exento con constancia (consume=False). Así la exención publicada en la
        # landing es comprobable y no depende de que nadie se acuerde de contar.
        planes.registrar_analisis_ia(
            db,
            tenant_id=tenant.id,
            origen=ORIGEN_BUZON,
            hoy=datetime.now(UTC).date(),
            referencia=fila.clave_acceso or fila.message_id[:300],
        )
    elif duplicado:
        fila.estado = EstadoCorreoBuzon.DUPLICADO
    elif primer_error:
        fila.estado = EstadoCorreoBuzon.ERROR
        fila.motivo_error = primer_error[:500]
    else:
        # XML válido pero sin retenciones: una factura recibida, por ejemplo
        fila.estado = EstadoCorreoBuzon.PARSEADO
    db.flush()
    return fila


def _por_que_no_es_suya(leido: ComprobanteLeido, tenant: Tenant) -> str | None:
    """El documento tiene que retener a ESTE inquilino. Devuelve el motivo si no.

    Dos agujeros que hubo que cerrar, los dos con el mismo final —un tercero que
    conozca el RUC del cliente (está en cada factura que emite, y la dirección
    del buzón ES ese RUC) le baja el IVA que declara—:

      · Un comprobante SIN `identificacionSujetoRetenido` no se comprobaba en
        absoluto: la ausencia del dato saltaba el control en vez de fallarlo.
      · La comparación por prefijo abierto (`ruc.startswith(retenido[:10])`)
        aceptaba una identificación de dos dígitos: «17» es prefijo de casi
        cualquier RUC de Pichincha.

    Ahora la identificación es obligatoria y se compara con longitudes fijas: o
    el RUC completo, o la cédula de 10 dígitos que forma su raíz.
    """
    retenido = (leido.identificacion_receptor or "").strip()
    if not retenido:
        return "El comprobante no dice a quién retiene, así que no se puede acreditar"
    if len(retenido) not in (10, 13):
        return f"La identificación del sujeto retenido no es válida: {retenido}"
    if retenido != tenant.ruc and retenido != tenant.ruc[:10]:
        return f"El comprobante retiene a {retenido}, que no es el RUC de este buzón"
    return None


def _por_que_no_acredita(leido: ComprobanteLeido, tenant: Tenant) -> str | None:
    """Por qué una retención legible NO se puede acreditar. Nada si sí se puede.

    Los tres motivos son de la RETENCIÓN, no del correo, así que valen igual
    para lo que entra por el buzón y para lo que el cliente sube a mano: la
    puerta cambia, las razones para rechazarla no.
    """
    motivo = _por_que_no_es_suya(leido, tenant)
    if motivo:
        return motivo
    if leido.autorizado is False:
        # El sobre del SRI dice que NO está autorizada: no es crédito de nadie.
        return "El SRI no autorizó este comprobante, así que no suma crédito"
    if leido.fecha_emision is None:
        # Sin fecha utilizable la retención quedaría fuera de todos los rangos:
        # no aparecería en el saldo ni en la bandeja, y su clave ya habría
        # ocupado el índice único, así que un reenvío tampoco la recuperaría.
        return "El comprobante no trae una fecha de emisión ni un período fiscal legibles"
    return None


def registrar_manual(db: Session, tenant: Tenant, xml: bytes) -> RetencionRecibida:
    """Registra una retención que el propio cliente sube (origen MANUAL).

    Mismas garantías que por correo y por los mismos motivos: el documento tiene
    que retener a ESTE inquilino, no puede estar ya registrada —da igual por qué
    puerta entrara la primera vez— y nace SIN verificar, así que se ve pero no
    suma hasta que el SRI conteste. Lo único que cambia es que no hay correo del
    que colgarla: `buzon_correo_id` se queda a null.

    Lanza `BuzonParseError` si el XML no se puede leer y `RetencionRechazada`
    —o su hija `RetencionDuplicada`— si se lee pero no acredita: los dos traen
    un motivo escrito para el cliente.
    """
    leido = leer(xml)
    if leido.tipo != "RETENCION":
        raise RetencionRechazada(
            f"El archivo es un comprobante de otro tipo ({_tipo_legible(leido)}), "
            "no una retención: no genera crédito tributario"
        )
    motivo = _por_que_no_acredita(leido, tenant)
    if motivo:
        raise RetencionRechazada(motivo)

    ya = _ya_registrada(db, tenant, leido)
    if ya is not None:
        raise RetencionDuplicada(f"Esa retención ya estaba registrada ({ya.numero})")
    try:
        return _crear_retencion(db, tenant, None, leido, xml, origen=ORIGEN_MANUAL)
    except IntegrityError as e:
        # Dos subidas a la vez, o el buzón insertándola entre el SELECT y este
        # INSERT: el índice único es el que decide, no el orden de llegada.
        raise RetencionDuplicada("Esa retención ya estaba registrada") from e


def _ya_registrada(
    db: Session, tenant: Tenant, leido: ComprobanteLeido
) -> RetencionRecibida | None:
    """Deduplicación de la retención en sí, no del correo que la trajo.

    Se busca por las DOS llaves a la vez, no por una u otra. Escoger una rama
    dejaba pasar a la gemela: una primera copia con la clave de acceso ilegible
    se guardaba con clave nula, y cuando el mismo comprobante llegaba con su
    clave correcta la consulta por clave no la encontraba —y los índices únicos
    parciales tampoco chocaban, porque cubren conjuntos disjuntos—. El crédito
    se contaba dos veces.
    """
    condiciones = []
    if leido.clave_acceso:
        condiciones.append(RetencionRecibida.clave_acceso == leido.clave_acceso)
    if leido.numero:
        condiciones.append(
            and_(
                RetencionRecibida.numero == leido.numero,
                RetencionRecibida.ruc_agente == leido.ruc_emisor,
            )
        )
    if not condiciones:
        return None
    return db.scalars(
        select(RetencionRecibida).where(RetencionRecibida.tenant_id == tenant.id, or_(*condiciones))
    ).first()


def _crear_retencion(
    db: Session,
    tenant: Tenant,
    correo_id: uuid.UUID | None,
    leido: ComprobanteLeido,
    xml: bytes,
    origen: str = ORIGEN_BUZON,
) -> RetencionRecibida:
    """La fila de crédito. `correo_id` es null cuando no vino de un correo."""
    base = max((linea.base for linea in leido.lineas), default=Decimal("0"))
    retencion = RetencionRecibida(
        tenant_id=tenant.id,
        buzon_correo_id=correo_id,
        origen=origen,
        clave_acceso=leido.clave_acceso,
        numero=leido.numero or (leido.clave_acceso or "")[:30] or "sin-numero",
        ruc_agente=leido.ruc_emisor,
        razon_social_agente=(leido.razon_social_emisor or "Sin razón social")[:300],
        fecha_emision=leido.fecha_emision,
        periodo_fiscal=leido.periodo_fiscal,
        concepto=_concepto(leido),
        base_imponible=base,
        total_renta=leido.total_renta,
        total_iva=leido.total_iva,
        detalle={
            "lineas": [
                {
                    "codigo": linea.codigo,
                    "codigo_retencion": linea.codigo_retencion,
                    "base": str(linea.base),
                    "porcentaje": str(linea.porcentaje),
                    "valor": str(linea.valor),
                    "doc_sustento": linea.doc_sustento,
                }
                for linea in leido.lineas
            ],
            "autorizado": leido.autorizado,
            "numero_autorizacion": leido.numero_autorizacion,
        },
    )
    # Punto de guardado: si otro proceso insertó la misma retención entre el
    # SELECT y este INSERT, el choque no puede arrastrar el registro del correo.
    punto = db.begin_nested()
    try:
        db.add(retencion)
        db.flush()
    except IntegrityError:
        punto.rollback()
        raise
    else:
        punto.commit()

    # El XML se custodia siete años, cifrado igual que el correo. SIN clave no
    # hay dónde dejarlo a salvo, y en claro no se guarda nunca: la fila se
    # registra igual y `xml_path` queda a null. Lo que sostiene el crédito son
    # los datos y la clave de acceso —con ella se le vuelve a preguntar al SRI y
    # se rebaja el documento de su portal—, no el adjunto. Por el correo esta
    # rama no se alcanza: `registrar` ya falla antes si falta la clave.
    if get_settings().buzon_enc_key:
        ruta = (
            Path(get_settings().storage_dir) / "buzon" / str(tenant.id) / f"{retencion.id}.xml.enc"
        )
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(aesgcm_encrypt(_clave(), xml, AAD_BUZON, "BUZON_ENC_KEY"), encoding="ascii")
        _anotar(db, ruta)
        retencion.xml_path = str(ruta)
    return retencion


def _concepto(leido: ComprobanteLeido) -> str | None:
    """Un resumen legible de qué se retuvo, como la columna «Concepto» de la
    maqueta: «Retención renta 8% e IVA 70%»."""
    renta = [linea for linea in leido.lineas if linea.codigo == "1"]
    iva = [linea for linea in leido.lineas if linea.codigo == "2"]
    trozos = []
    if renta:
        trozos.append(f"renta {_pct(renta[0].porcentaje)}")
    if iva:
        trozos.append(f"IVA {_pct(iva[0].porcentaje)}")
    return f"Retención {' e '.join(trozos)}" if trozos else None


def _pct(valor: Decimal) -> str:
    entero = valor.quantize(Decimal("1")) if valor == valor.to_integral_value() else valor
    return f"{entero}%"
