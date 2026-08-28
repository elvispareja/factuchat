"""Tienda interna: pedidos de la vitrina del equipo (fase 6.1).

Cada producto lleva su precio SIN impuesto y su tarifa por separado; el IVA se
calcula al facturar. Esa separación es la que evita dobles cobros y descuadres,
y es literal en la maqueta.

Si el comprador no da sus datos, la venta sale a consumidor final hasta $200:
el mismo tope que rige en el panel y en el chat, decidido en el servidor.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ClienteFinal, Pedido, Producto
from app.db.models.enums import EstadoPedido, MetodoPago, TipoIdentificacion
from app.services.emision import LIMITE_CONSUMIDOR_FINAL, EmisionError, calcular_items

# Qué estado toma un pedido recién creado según cómo se cobra
ESTADO_INICIAL = {
    MetodoPago.TRANSFERENCIA: EstadoPedido.TRANSFERENCIA_POR_CONFIRMAR,
    MetodoPago.PAYPHONE: EstadoPedido.POR_REVISAR,
    MetodoPago.EFECTIVO: EstadoPedido.POR_ENTREGAR,
    MetodoPago.OTRO: EstadoPedido.POR_REVISAR,
}


class TiendaError(Exception):
    """Motivo legible para quien atiende la venta."""


def _siguiente_numero(db: Session, tenant_id: uuid.UUID) -> int:
    actual = db.execute(
        select(func.coalesce(func.max(Pedido.numero), 0)).where(Pedido.tenant_id == tenant_id)
    ).scalar_one()
    return int(actual) + 1


def crear_pedido(
    db: Session,
    tenant_id: uuid.UUID,
    lineas: list[dict],
    metodo_pago: MetodoPago,
    cliente_final_id: uuid.UUID | None = None,
    comprador_nombre: str | None = None,
    comprador_telefono: str | None = None,
    nota: str | None = None,
) -> Pedido:
    """Arma el pedido con los precios del catálogo.

    Los precios NO vienen del cliente: se leen del producto. Aceptar un precio
    enviado desde fuera dejaría cobrar lo que quisiera quien llame a la API.
    """
    if not lineas:
        raise TiendaError("El pedido necesita al menos un producto")

    items_para_calcular = []
    detalle = []
    for linea in lineas:
        producto = db.get(Producto, uuid.UUID(str(linea["producto_id"])))
        if producto is None or not producto.activo:
            raise TiendaError("Uno de los productos ya no está disponible")
        cantidad = Decimal(str(linea.get("cantidad", 1)))
        if cantidad <= 0:
            raise TiendaError("La cantidad debe ser mayor que cero")
        if producto.maneja_inventario and producto.stock is not None and cantidad > producto.stock:
            raise TiendaError(f"Solo quedan {producto.stock:g} unidades de {producto.nombre}")

        items_para_calcular.append(
            {
                "codigo": producto.codigo,
                "descripcion": producto.nombre,
                "cantidad": str(cantidad),
                "precio_unitario": str(producto.precio_sin_iva),
                "codigo_iva": producto.codigo_iva,
            }
        )
        detalle.append(
            {
                "producto_id": str(producto.id),
                "codigo": producto.codigo,
                "nombre": producto.nombre,
                "cantidad": str(cantidad),
                "precio_sin_iva": str(producto.precio_sin_iva),
                "codigo_iva": producto.codigo_iva,
            }
        )

    _items, totales = calcular_items(items_para_calcular)

    cliente = None
    if cliente_final_id is not None:
        cliente = db.get(ClienteFinal, cliente_final_id)
        if cliente is None:
            raise TiendaError("Ese cliente no existe")

    # Consumidor final hasta $200: la misma regla que en el panel y el chat
    es_consumidor_final = (
        cliente is None or cliente.tipo_identificacion == TipoIdentificacion.CONSUMIDOR_FINAL
    )
    if es_consumidor_final and totales["importe_total"] > LIMITE_CONSUMIDOR_FINAL:
        raise TiendaError(
            f"Sin los datos del comprador solo se puede facturar hasta "
            f"${LIMITE_CONSUMIDOR_FINAL}. Pídele la cédula o el RUC para continuar."
        )

    pedido = Pedido(
        tenant_id=tenant_id,
        numero=_siguiente_numero(db, tenant_id),
        estado=ESTADO_INICIAL.get(metodo_pago, EstadoPedido.POR_REVISAR),
        metodo_pago=metodo_pago,
        cliente_final_id=cliente.id if cliente else None,
        comprador_nombre=comprador_nombre or (cliente.razon_social if cliente else None),
        comprador_telefono=comprador_telefono,
        items=detalle,
        subtotal=totales["total_sin_impuestos"],
        iva=totales["total_iva"],
        total=totales["importe_total"],
        nota=nota,
    )
    db.add(pedido)
    db.flush()
    return pedido


def adjuntar_comprobante_pago(
    db: Session, pedido: Pedido, url: str, referencia: str | None = None
) -> Pedido:
    if pedido.metodo_pago != MetodoPago.TRANSFERENCIA:
        raise TiendaError("Solo los pedidos por transferencia llevan comprobante de pago")
    pedido.comprobante_pago_url = url
    pedido.referencia_pago = referencia
    pedido.estado = EstadoPedido.TRANSFERENCIA_POR_CONFIRMAR
    db.flush()
    return pedido


def confirmar_pago(db: Session, pedido: Pedido) -> Pedido:
    """El equipo verificó que el dinero llegó. Ahora se puede facturar."""
    if pedido.estado == EstadoPedido.PAGADO:
        return pedido
    if pedido.estado == EstadoPedido.ANULADO:
        raise TiendaError("Ese pedido está anulado")
    pedido.confirmado_at = datetime.now(UTC)
    pedido.estado = EstadoPedido.POR_ENTREGAR
    db.flush()
    return pedido


def facturar(db: Session, tenant_id: uuid.UUID, pedido: Pedido):
    """Emite el comprobante del pedido y descuenta el inventario.

    Devuelve el comprobante ya en cola: el pedido queda PAGADO porque la venta
    se cerró, aunque el SRI tarde en autorizar.
    """
    from app.services import emision

    if pedido.comprobante_id is not None:
        raise TiendaError("Ese pedido ya tiene su comprobante")
    if pedido.estado == EstadoPedido.ANULADO:
        raise TiendaError("Ese pedido está anulado")
    if pedido.estado == EstadoPedido.TRANSFERENCIA_POR_CONFIRMAR:
        raise TiendaError(
            "Confirma primero que la transferencia llegó; después se emite el comprobante."
        )

    try:
        comprobante = emision.crear_factura(
            db,
            tenant_id=tenant_id,
            cliente_final_id=pedido.cliente_final_id,
            items_in=[
                {
                    "codigo": i["codigo"],
                    "descripcion": i["nombre"],
                    "cantidad": i["cantidad"],
                    "precio_unitario": i["precio_sin_iva"],
                    "codigo_iva": i["codigo_iva"],
                }
                for i in pedido.items
            ],
            forma_pago="01" if pedido.metodo_pago == MetodoPago.EFECTIVO else "20",
            info_adicional={"Pedido": f"#{pedido.numero}", "Origen": "Tienda"},
        )
    except EmisionError as e:
        raise TiendaError(str(e)) from e

    comprobante.origen = "TIENDA"
    pedido.comprobante_id = comprobante.id
    pedido.estado = EstadoPedido.PAGADO
    _descontar_inventario(db, pedido)
    db.flush()
    return comprobante


def _descontar_inventario(db: Session, pedido: Pedido) -> None:
    """Solo baja el stock de lo que lleva conteo; los servicios no tienen."""
    for item in pedido.items:
        producto = db.get(Producto, uuid.UUID(item["producto_id"]))
        if producto is None or not producto.maneja_inventario:
            continue
        producto.stock = (producto.stock or Decimal("0")) - Decimal(item["cantidad"])


def anular(db: Session, pedido: Pedido, motivo: str) -> Pedido:
    if pedido.comprobante_id is not None:
        raise TiendaError(
            "Ese pedido ya se facturó: para anularlo hay que emitir una nota de crédito."
        )
    pedido.estado = EstadoPedido.ANULADO
    pedido.nota = ((pedido.nota or "") + f"\nAnulado: {motivo}").strip()
    db.flush()
    return pedido


def resumen_por_estado(db: Session, tenant_id: uuid.UUID) -> dict[str, int]:
    """Los contadores de las cuatro tarjetas de la pestaña Pedidos."""
    filas = db.execute(
        select(Pedido.estado, func.count(Pedido.id))
        .where(Pedido.tenant_id == tenant_id)
        .group_by(Pedido.estado)
    ).all()
    cuenta = {e.value: 0 for e in EstadoPedido}
    for estado, n in filas:
        cuenta[estado.value] = int(n)
    return cuenta


def vitrina(db: Session) -> list[Producto]:
    """Lo que el equipo ve para armar una venta: lo marcado para la tienda."""
    return list(
        db.scalars(
            select(Producto)
            .where(Producto.activo.is_(True), Producto.mostrar_en_tienda.is_(True))
            .order_by(Producto.nombre)
        ).all()
    )
