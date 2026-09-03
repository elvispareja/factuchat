"""Esquemas de emisión de facturas. Validación estricta en la frontera (A05)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.sri.xml_builder import FORMAS_PAGO, TARIFAS_IVA


class ItemFacturaIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=25)
    descripcion: str = Field(min_length=1, max_length=300)
    cantidad: Decimal = Field(gt=0, le=Decimal("999999"))
    precio_unitario: Decimal = Field(ge=0, le=Decimal("999999999"))
    # `decimal_places=2` como el recargo de la nota de débito: con milésimas, el
    # detalle del XML sale descuadrado consigo mismo, porque la base se calcula
    # con el descuento SIN redondear (`_d2(bruto - descuento)`) y el campo
    # `descuento` que se imprime va redondeado. Con 0,005 el RIDE enseña
    # 1 × 10,00 − 0,01 = 10,00, una resta que no se sostiene.
    descuento: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    codigo_iva: str = Field(default="4")  # 15% vigente

    @field_validator("codigo_iva")
    @classmethod
    def iva_valido(cls, v: str) -> str:
        if v not in TARIFAS_IVA:
            raise ValueError(f"Código de IVA inválido: {v}")
        return v


class FacturaIn(BaseModel):
    cliente_final_id: uuid.UUID | None = None  # None → consumidor final (hasta $200)
    items: list[ItemFacturaIn] = Field(min_length=1, max_length=200)
    forma_pago: str = Field(default="01")
    # Venta a crédito: el SRI no tiene «código de crédito» en la tabla 24, lo
    # expresa como <plazo>/<unidadTiempo> DENTRO del pago (ficha técnica 2.31).
    plazo_dias: int | None = Field(default=None, ge=1, le=3650)
    info_adicional: dict[str, str] | None = None
    # Correo SOLO para esta factura (pantalla «Se enviará a: …»). Alguien puede
    # pedir que esta vaya a su contador sin que eso cambie su correo habitual:
    # se guarda en el payload del comprobante y NO toca la ficha del cliente.
    # None → se usa el del cliente, como hasta ahora.
    # Cadena VACÍA → no se manda copia a nadie. Son tres cosas distintas y hacen
    # falta las tres: la pantalla de revisión deja borrar el correo, y eso
    # significa «esta no se envía», no «mándala al de siempre».
    email_envio: EmailStr | Literal[""] | None = None
    # Dirección del comprador SOLO para esta factura («+ agregar dirección» del
    # formulario). Mismas tres formas que `email_envio` y por lo mismo:
    # None → la de la ficha del cliente; "" → esta factura va SIN dirección
    # (quien abre el plegable y borra lo que había está pidiendo eso, no «pon la
    # de siempre»); texto → esa, y la ficha no se toca.
    # 300 es el tope del <direccionComprador> del XSD; la ficha del cliente
    # admite 1000, así que lo que venga de ahí se recorta en el snapshot.
    direccion_envio: str | None = Field(default=None, max_length=300)

    @field_validator("forma_pago")
    @classmethod
    def forma_pago_valida(cls, v: str) -> str:
        if v not in FORMAS_PAGO:
            raise ValueError(f"Forma de pago inválida: {v}")
        return v

    @field_validator("info_adicional")
    @classmethod
    def info_acotada(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is not None and len(v) > 15:
            raise ValueError("Máximo 15 campos adicionales")
        return v


class DocModificadoIn(BaseModel):
    """La factura que la nota de crédito anula o corrige, tecleada a mano.

    Solo hace falta cuando esa factura NO está en el sistema (la emitió otro
    programa). Si viene `factura_id`, el servidor la ignora y usa los datos
    reales de la factura: el número y la fecha del XML tienen que ser los que el
    SRI ya autorizó, no los que alguien recuerde.
    """

    numero: str = Field(pattern=r"^\d{3}-\d{3}-\d{9}$")  # 001-001-000000123
    fecha: date


class _NotaSobreFactura(BaseModel):
    """Lo común a las dos notas: contra QUÉ factura van y por qué.

    La de crédito resta y la de débito suma, pero las dos modifican una factura
    ya emitida y las reglas de eso —qué documento citan, que el motivo diga algo,
    a quién van— son las mismas. Cada nota añade solo lo suyo: líneas la de
    crédito, un importe de recargo la de débito.
    """

    cliente_final_id: uuid.UUID | None = None  # None → consumidor final
    # La factura de origen SI está en el sistema. Cuando viene, es la fuente de
    # la verdad: de ella salen número, fecha y el saldo que queda por acreditar.
    factura_id: uuid.UUID | None = None
    doc_modificado: DocModificadoIn | None = None
    # Va IMPRESO en el comprobante (<motivo> del XML), así que se exige algo
    # legible: ni un carácter suelto ni una fila de puntos.
    motivo: str = Field(min_length=1, max_length=300)
    info_adicional: dict[str, str] | None = None
    email_envio: EmailStr | Literal[""] | None = None  # igual que en la factura

    @field_validator("motivo")
    @classmethod
    def motivo_con_sentido(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 5 or not any(c.isalpha() for c in v):
            raise ValueError("El motivo va impreso en el comprobante: explique por qué")
        return v

    @field_validator("info_adicional")
    @classmethod
    def info_acotada(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is not None and len(v) > 15:
            raise ValueError("Máximo 15 campos adicionales")
        return v

    @model_validator(mode="after")
    def hay_documento_modificado(self) -> "_NotaSobreFactura":
        if self.factura_id is None and self.doc_modificado is None:
            raise ValueError(
                "Indique la factura que modifica: elíjala del sistema (factura_id) "
                "o escriba su número y fecha (doc_modificado)"
            )
        return self


class NotaCreditoIn(_NotaSobreFactura):
    items: list[ItemFacturaIn] = Field(min_length=1, max_length=200)


class NotaDebitoIn(_NotaSobreFactura):
    """El RECARGO sobre una factura ya emitida: un interés por mora, un gasto.

    Sin líneas de producto a propósito: una nota de débito no vende nada, cobra
    un importe. El XML admite VARIOS <motivo> con su valor (ver
    `construir_nota_debito`), pero el panel pide uno solo y montar una lista en
    la interfaz por poder hacerlo sería inventarse un formulario que nadie pidió;
    el payload sí se guarda ya en forma de lista, así que el día que hagan falta
    varios no hay que tocar el XML.
    """

    # LO QUE SE QUIERE COBRAR, CON IVA INCLUIDO. Quien teclea esto no es contador
    # («cóbrale 20 dólares de mora»): pedirle la base imponible para que le
    # aparezca un total de 23.00 es pedirle que haga la cuenta al revés. El
    # servidor desglosa base e IVA (ver `crear_nota_debito`).
    #
    # OJO: el total del documento puede quedar a UN CENTAVO del importe tecleado.
    # El IVA se redondea al céntimo y el SRI recalcula base×tarifa, así que hay
    # importes que no son expresables con IVA incluido (10.00 → 8.70 + 1.31 =
    # 10.01). La pantalla de revisión enseña el total real antes de emitir.
    valor_recargo: Decimal = Field(gt=0, le=Decimal("999999999"), decimal_places=2)


class ItemAcreditableOut(BaseModel):
    """Una línea de la factura de origen, tal como se le mandó al SRI.

    La nota de crédito arranca reflejando lo facturado: anularla entera es dejar
    las líneas como están y corregirla en parte es quitar alguna o bajar
    cantidades. Sale del snapshot del payload, que ya viaja con la fila del
    listado: no añade ni una consulta.
    """

    codigo: str
    descripcion: str
    cantidad: str
    precio_unitario: str
    # Lo REBAJADO en esa línea. Sin él la nota se precarga con el precio de
    # tarifa en vez de con lo que el cliente pagó: ver CAMPOS_ITEM en las rutas.
    descuento: str
    codigo_iva: str
    tarifa_iva: str


class FacturaAcreditableOut(BaseModel):
    """Una factura sobre la que TODAVÍA se puede emitir nota de crédito."""

    id: uuid.UUID
    numero: str  # 001-001-000000123
    fecha_emision: str
    cliente: str | None  # None = consumidor final
    cliente_identificacion: str | None
    cliente_final_id: uuid.UUID | None  # el modal precarga con él al mismo cliente
    total: str
    acreditado: str  # lo ya cubierto por notas de crédito
    pendiente: str  # tope del importe de la nueva nota
    items: list[ItemAcreditableOut]  # el modal las precarga; ver ItemAcreditableOut


class EmitirIn(BaseModel):
    establecimiento: str = Field(default="001", pattern=r"^\d{3}$")
    punto_emision: str = Field(default="001", pattern=r"^\d{3}$")


class ComprobanteOut(BaseModel):
    id: uuid.UUID
    tipo: str
    estado: str
    ambiente: str
    numero: str | None  # 001-001-000000123
    clave_acceso: str | None
    numero_autorizacion: str | None
    fecha_emision: str
    subtotal: str
    iva: str
    total: str
    mensajes: list[str]  # motivos legibles (rechazo/devolución)
    intentos: int
    # Columnas CLIENTE y DETALLE del historial. Salen del snapshot del payload
    # (lo que se le mandó al SRI), no de un JOIN: ver _a_out en las rutas.
    cliente: str | None  # razón social; None = consumidor final
    cliente_identificacion: str | None
    cliente_tipo_id: str | None  # RUC | CEDULA | PASAPORTE | ID_EXTERIOR
    detalle: str | None  # «Laptop 14" y 2 más»


class SiguienteNumeroOut(BaseModel):
    """Vista PREVIA del número: no reserva nada (ver emision.siguiente_numero)."""

    numero: str  # 001-001-000001235
    establecimiento: str
    punto_emision: str
    secuencial: int


class OpcionPagoOut(BaseModel):
    codigo: str  # tabla 24 del SRI
    etiqueta: str
    plazo_dias: int | None


# Las tres formas de pago del panel, todas al contado. El soporte de plazo sigue
# en pie (FacturaIn.plazo_dias y el <plazo>/<unidadTiempo> del XML), solo que de
# momento ninguna opción lo usa: cuando haga falta ofrecer venta a crédito, se
# añade aquí una opción con plazo_dias y funciona sin tocar nada más.
OPCIONES_PAGO = [
    OpcionPagoOut(codigo="01", etiqueta="Efectivo", plazo_dias=None),
    OpcionPagoOut(codigo="20", etiqueta="Transferencia", plazo_dias=None),
    OpcionPagoOut(codigo="19", etiqueta="Tarjeta", plazo_dias=None),
]
