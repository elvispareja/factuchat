"""Enumeraciones del dominio (fase 1.2)."""

import enum


class Rol(enum.StrEnum):
    CLIENTE = "CLIENTE"
    SUPERADMIN = "SUPERADMIN"
    SOPORTE = "SOPORTE"
    LECTURA = "LECTURA"


class EstadoTenant(enum.StrEnum):
    ACTIVO = "ACTIVO"
    SUSPENDIDO = "SUSPENDIDO"
    BAJA = "BAJA"


class AmbienteSRI(enum.StrEnum):
    PRUEBAS = "PRUEBAS"
    PRODUCCION = "PRODUCCION"


class TipoComprobante(enum.StrEnum):
    """Los 6 comprobantes electrónicos del SRI con su código de tabla 4."""

    FACTURA = "FACTURA"  # 01
    LIQUIDACION_COMPRA = "LIQUIDACION_COMPRA"  # 03
    NOTA_CREDITO = "NOTA_CREDITO"  # 04
    NOTA_DEBITO = "NOTA_DEBITO"  # 05
    GUIA_REMISION = "GUIA_REMISION"  # 06
    RETENCION = "RETENCION"  # 07

    @property
    def codigo_sri(self) -> str:
        return {
            TipoComprobante.FACTURA: "01",
            TipoComprobante.LIQUIDACION_COMPRA: "03",
            TipoComprobante.NOTA_CREDITO: "04",
            TipoComprobante.NOTA_DEBITO: "05",
            TipoComprobante.GUIA_REMISION: "06",
            TipoComprobante.RETENCION: "07",
        }[self]


class EstadoComprobante(enum.StrEnum):
    PENDIENTE = "PENDIENTE"
    FIRMADO = "FIRMADO"
    ENVIADO_SRI = "ENVIADO_SRI"
    AUTORIZADO = "AUTORIZADO"
    RECHAZADO = "RECHAZADO"
    DEVUELTO = "DEVUELTO"


class TipoIdentificacion(enum.StrEnum):
    RUC = "RUC"  # 04
    CEDULA = "CEDULA"  # 05
    PASAPORTE = "PASAPORTE"  # 06
    CONSUMIDOR_FINAL = "CONSUMIDOR_FINAL"  # 07
    ID_EXTERIOR = "ID_EXTERIOR"  # 08


class TipoProducto(enum.StrEnum):
    BIEN = "BIEN"
    SERVICIO = "SERVICIO"


class EstadoSuscripcion(enum.StrEnum):
    ACTIVA = "ACTIVA"
    MOROSA = "MOROSA"
    SUSPENDIDA = "SUSPENDIDA"
    CANCELADA = "CANCELADA"


class MetodoPago(enum.StrEnum):
    TRANSFERENCIA = "TRANSFERENCIA"
    PAYPHONE = "PAYPHONE"
    EFECTIVO = "EFECTIVO"
    OTRO = "OTRO"


class EstadoPago(enum.StrEnum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADO = "CONFIRMADO"
    RECHAZADO = "RECHAZADO"


class TipoPromo(enum.StrEnum):
    PORCENTAJE = "PORCENTAJE"
    MONTO_FIJO = "MONTO_FIJO"
    PRECIO_FIJO = "PRECIO_FIJO"  # p. ej. LANZA99: primer mes a $0.99


class DireccionMsg(enum.StrEnum):
    ENTRANTE = "ENTRANTE"
    SALIENTE = "SALIENTE"


class CategoriaMsg(enum.StrEnum):
    """Categorías de conversación de Meta para el tablero de consumo."""

    EMPRESA = "EMPRESA"
    USUARIO = "USUARIO"
    SERVICIO = "SERVICIO"


class EstadoPedido(enum.StrEnum):
    """Los cuatro estados de la pestaña Pedidos de la maqueta."""

    POR_REVISAR = "POR_REVISAR"
    TRANSFERENCIA_POR_CONFIRMAR = "TRANSFERENCIA_POR_CONFIRMAR"
    POR_ENTREGAR = "POR_ENTREGAR"
    PAGADO = "PAGADO"
    ANULADO = "ANULADO"


class EstadoCorreoBuzon(enum.StrEnum):
    RECIBIDO = "RECIBIDO"
    PARSEADO = "PARSEADO"
    DUPLICADO = "DUPLICADO"
    ERROR = "ERROR"
