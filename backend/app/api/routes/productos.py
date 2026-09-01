"""Artículos y servicios (fase 3.1), con inventario gated por plan (3.2)."""

import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.core.config import get_settings
from app.db.models import (
    Atributo,
    AtributoValor,
    Categoria,
    Producto,
    ProductoAtributo,
    ProductoVariante,
    VarianteAtributo,
)
from app.db.models.enums import Rol, TipoProducto
from app.db.session import get_db
from app.schemas.productos import ProductoAtributoIn, ProductoIn, ProductoOut, VarianteIn
from app.services.planes import (
    LimitePlanError,
    exigir_cupo_productos,
    exigir_funcion,
    plan_vigente,
)
from app.sri.xml_builder import TARIFAS_IVA

router = APIRouter(prefix="/productos", tags=["productos"])


def _aplicar(producto: Producto, body: ProductoIn, permite_stock: bool) -> None:
    producto.codigo = body.codigo
    producto.nombre = body.nombre
    producto.descripcion = body.descripcion
    producto.tipo = body.tipo
    producto.precio_sin_iva = body.precio_sin_iva
    producto.codigo_iva = body.codigo_iva
    producto.porcentaje_iva = TARIFAS_IVA[body.codigo_iva]
    producto.mostrar_en_tienda = body.mostrar_en_tienda
    producto.categoria_id = body.categoria_id
    # Sin la función de inventario en el plan, el catálogo funciona igual pero
    # sin conteo: los campos de stock simplemente no se guardan.
    if permite_stock:
        producto.maneja_inventario = body.maneja_inventario
        producto.stock = body.stock
        producto.stock_minimo = body.stock_minimo
    else:
        producto.maneja_inventario = False
        producto.stock = Decimal("0")
        producto.stock_minimo = None


def _validar_categoria(db: Session, body: ProductoIn) -> None:
    # Postgres SIEMPRE salta RLS al comprobar una FK (es un chequeo de
    # integridad referencial, no una consulta): sin esta validación explícita,
    # un categoria_id de OTRO tenant pasaría el INSERT/UPDATE igual, aunque
    # ese tenant jamás pueda hacer SELECT de esa fila. Por eso se valida aquí
    # con db.get() (que sí respeta RLS).
    if body.categoria_id is not None and db.get(Categoria, body.categoria_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Categoría no encontrada")


def _validar_par(db: Session, categoria_id: uuid.UUID, item: ProductoAtributoIn) -> None:
    """Ese valor existe, es de ese atributo y el atributo es de esa categoría.

    Mismo motivo que _validar_categoria: db.get() respeta RLS, la FK no. Sin
    este chequeo un producto podría terminar con un atributo de OTRA categoría
    (o de otro tenant) o con un valor que no es de ese atributo.
    """
    atributo = db.get(Atributo, item.atributo_id)  # RLS: solo del propio tenant
    if atributo is None or atributo.categoria_id != categoria_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "El atributo no pertenece a la categoría seleccionada"
        )
    valor = db.get(AtributoValor, item.atributo_valor_id)  # RLS: solo del propio tenant
    if valor is None or valor.atributo_id != item.atributo_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "El valor no pertenece al atributo seleccionado"
        )


def _validar_atributos(db: Session, body: ProductoIn) -> None:
    if not body.atributos:
        return
    if body.categoria_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Selecciona una categoría antes de asignar atributos"
        )
    # Repetir el atributo con OTRO valor es lo normal desde que hay variantes
    # (Talla=38 y Talla=39: de ahí salen las combinaciones). Lo que sigue sin
    # valer es repetir el MISMO par, que además rompería el UNIQUE.
    pares = [(item.atributo_id, item.atributo_valor_id) for item in body.atributos]
    if len(pares) != len(set(pares)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "No puedes repetir el mismo valor de atributo"
        )
    for item in body.atributos:
        _validar_par(db, body.categoria_id, item)


def _validar_variantes(db: Session, body: ProductoIn, producto_id: uuid.UUID | None = None) -> None:
    if not body.variantes:
        return
    if body.categoria_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Selecciona una categoría antes de crear variantes"
        )
    codigos = [v.codigo for v in body.variantes]
    if len(codigos) != len(set(codigos)):
        # El código va impreso en el comprobante: repetirlo deja dos cosas
        # distintas con el mismo SKU (y revienta el UNIQUE del negocio).
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hay dos variantes con el mismo código")
    # El UNIQUE es (tenant_id, codigo): abarca TODO el negocio, no solo este
    # producto. Sin este aviso, reusar sin querer un SKU de otro producto —fácil,
    # porque se autogeneran a partir del código del producto— explotaba en un
    # error de integridad que el usuario veía como un 500 sin explicación.
    consulta = select(ProductoVariante.codigo).where(ProductoVariante.codigo.in_(codigos))
    if producto_id is not None:
        consulta = consulta.where(ProductoVariante.producto_id != producto_id)
    ajeno = db.scalars(consulta).first()  # RLS: solo mira dentro del propio tenant
    if ajeno is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"El código «{ajeno}» ya lo usa otro producto"
        )
    combinaciones: set[frozenset] = set()
    for variante in body.variantes:
        atributos = [item.atributo_id for item in variante.valores]
        if len(atributos) != len(set(atributos)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Una variante no puede llevar dos valores del mismo atributo",
            )
        combinacion = frozenset(
            (item.atributo_id, item.atributo_valor_id) for item in variante.valores
        )
        if combinacion in combinaciones:
            # Serían dos stocks para la misma talla/color: nadie sabría cuál baja.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Hay dos variantes con la misma combinación de valores"
            )
        combinaciones.add(combinacion)
        for item in variante.valores:
            _validar_par(db, body.categoria_id, item)


def _sincronizar_atributos(tenant_id: uuid.UUID, producto: Producto, body: ProductoIn) -> None:
    # Diff, no borrar y recrear: en un mismo flush SQLAlchemy hace los INSERT
    # antes que los DELETE, así que reenviar un par que ya estaba —lo normal al
    # editar cualquier cosa del producto— chocaría contra el UNIQUE.
    deseados = {(item.atributo_id, item.atributo_valor_id) for item in body.atributos}
    actuales = {(fila.atributo_id, fila.atributo_valor_id): fila for fila in producto.atributos}
    for atributo_id, valor_id in deseados - actuales.keys():
        producto.atributos.append(
            ProductoAtributo(
                tenant_id=tenant_id, atributo_id=atributo_id, atributo_valor_id=valor_id
            )
        )
    for par, fila in actuales.items():
        if par not in deseados:
            producto.atributos.remove(fila)  # delete-orphan la borra


def _sincronizar_valores(
    tenant_id: uuid.UUID, variante: ProductoVariante, item: VarianteIn
) -> None:
    # Se actualiza en sitio en vez de borrar y recrear porque el UNIQUE
    # (variante_id, atributo_id) reventaría: en un mismo flush SQLAlchemy hace
    # los INSERT antes que los DELETE, y la talla que no cambia se reinsertaría
    # antes de que se borrara la vieja.
    por_atributo = {fila.atributo_id: fila for fila in variante.valores}
    for valor in item.valores:
        fila = por_atributo.pop(valor.atributo_id, None)
        if fila is None:
            variante.valores.append(
                VarianteAtributo(
                    tenant_id=tenant_id,
                    atributo_id=valor.atributo_id,
                    atributo_valor_id=valor.atributo_valor_id,
                )
            )
        else:
            fila.atributo_valor_id = valor.atributo_valor_id
    for sobrante in por_atributo.values():
        variante.valores.remove(sobrante)  # delete-orphan la borra


def _sincronizar_variantes(tenant_id: uuid.UUID, producto: Producto, body: ProductoIn) -> None:
    """Diff por código, NO borrar y recrear como hace _sincronizar_atributos.

    La variante lleva el stock y los pedidos la referencian por id: recrearla
    en cada PUT vaciaría el inventario y dejaría al pedido apuntando a una fila
    borrada. Se empareja por `codigo` y no por combinación de valores porque el
    código es la identidad que el negocio ve, la que va impresa en el
    comprobante y la única con UNIQUE en la base; la combinación sí cambia de
    forma legítima (corregir "Rojo" por "Rojo oscuro" no crea otro par de
    zapatos).
    """
    pendientes = {v.id: v for v in producto.variantes}
    por_codigo = {v.codigo: v for v in producto.variantes}
    for item in body.variantes:
        # Por id primero: es lo que sobrevive a un cambio de código. El código
        # queda como respaldo para quien mande una variante ya existente sin id
        # (una integración, un script), y así no se le duplica el inventario.
        variante = pendientes.pop(item.id, None) if item.id is not None else None
        if variante is None:
            variante = por_codigo.get(item.codigo)
            if variante is not None:
                pendientes.pop(variante.id, None)
        if variante is None:
            variante = ProductoVariante(tenant_id=tenant_id, codigo=item.codigo, stock=item.stock)
            producto.variantes.append(variante)
        else:
            variante.codigo = item.codigo
            if "stock" in item.model_fields_set:
                # El stock solo se pisa si el cliente lo manda EXPLÍCITAMENTE:
                # editar el nombre del producto con un cuerpo que no trae stock
                # no puede vaciar el inventario.
                variante.stock = item.stock
        variante.precio_sin_iva = item.precio_sin_iva
        variante.activo = True
        _sincronizar_valores(tenant_id, variante, item)
    for sobrante in pendientes.values():
        # ponytail: se borra la variante quitada; si algún día hay que conservar
        # el histórico de pedidos pendientes, pasar a baja lógica (activo=False).
        producto.variantes.remove(sobrante)


def _producto_o_404(db: Session, producto_id: uuid.UUID) -> Producto:
    producto = db.get(Producto, producto_id)  # RLS: solo del propio tenant
    if producto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Producto no encontrado")
    return producto


@router.get("", response_model=list[ProductoOut])
def listar(
    tipo: TipoProducto | None = Query(default=None),
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    consulta = select(Producto).where(Producto.activo.is_(True))
    if tipo is not None:
        consulta = consulta.where(Producto.tipo == tipo)
    return db.scalars(consulta.order_by(Producto.nombre)).all()


@router.post("", response_model=ProductoOut, status_code=status.HTTP_201_CREATED)
def crear(
    body: ProductoIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    tenant_id = tenant_de(user)
    plan = plan_vigente(db, tenant_id)
    try:
        exigir_cupo_productos(db, tenant_id, plan)
        if body.mostrar_en_tienda:
            exigir_funcion(plan, "tienda")
    except LimitePlanError as e:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "mensaje": e.mensaje,
                "funcion": e.funcion,
                "plan_sugerido": e.plan_sugerido,
            },
        ) from e

    # Todo lo que puede rechazarse, ANTES de escribir nada
    _validar_categoria(db, body)
    _validar_atributos(db, body)
    _validar_variantes(db, body)

    producto = Producto(tenant_id=tenant_id)
    _aplicar(producto, body, plan.permite("stock"))
    db.add(producto)
    db.flush()  # asigna producto.id, que necesitan atributos y variantes

    _sincronizar_atributos(tenant_id, producto, body)
    _sincronizar_variantes(tenant_id, producto, body)
    db.flush()
    return producto


@router.put("/{producto_id}", response_model=ProductoOut)
def actualizar(
    producto_id: uuid.UUID,
    body: ProductoIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    producto = _producto_o_404(db, producto_id)
    plan = plan_vigente(db, tenant_de(user))
    try:
        if body.mostrar_en_tienda and not producto.mostrar_en_tienda:
            exigir_funcion(plan, "tienda")
    except LimitePlanError as e:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "mensaje": e.mensaje,
                "funcion": e.funcion,
                "plan_sugerido": e.plan_sugerido,
            },
        ) from e
    _validar_categoria(db, body)
    _validar_atributos(db, body)
    _validar_variantes(db, body, producto_id)  # sus propios códigos no son «ajenos»

    _aplicar(producto, body, plan.permite("stock"))
    _sincronizar_atributos(tenant_de(user), producto, body)
    # Omitir «variantes» y mandarla vacía son cosas distintas: lo primero es un
    # cuerpo que no habla del inventario (una edición parcial, o un formulario
    # que aún no cargó la matriz) y lo segundo es «bórralas». Sin esta
    # distinción, guardar el nombre de un producto le vaciaba el stock entero.
    if "variantes" in body.model_fields_set:
        _sincronizar_variantes(tenant_de(user), producto, body)
    db.flush()
    return producto


@router.delete("/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar(
    producto_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    producto = _producto_o_404(db, producto_id)
    # Baja lógica: el histórico de comprobantes debe seguir siendo legible
    producto.activo = False
    db.flush()
    return None


# --- Imagen del producto ---------------------------------------------------
#
# Una sola imagen por producto: la miniatura del catálogo y de la tienda. No
# viaja en el JSON del producto (va por multipart, en su propio endpoint) y su
# ruta en disco no sale nunca hacia el navegador.

MAX_IMAGEN_BYTES = 2 * 1024 * 1024
MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _extension_real(contenido: bytes) -> str | None:
    """El tipo según los BYTES de cabecera, no según lo que diga el cliente.

    El `content_type` y el nombre del archivo los elige quien sube: los dos se
    falsifican escribiéndolos. Renombrar un .php o un .svg con script a .jpg es
    el ataque obvio aquí, y el SVG además ejecuta JavaScript al servirse.
    """
    if contenido.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    # RIFF....WEBP: los 4 bytes de en medio son el tamaño del archivo.
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "webp"
    return None


@router.post("/{producto_id}/imagen", response_model=ProductoOut)
def subir_imagen(
    producto_id: uuid.UUID,
    archivo: UploadFile = File(...),
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    """Sube o reemplaza la imagen del producto."""
    producto = _producto_o_404(db, producto_id)

    # Se mide lo LEÍDO, un byte más del límite: el Content-Length de la
    # petición es un número que manda el cliente y puede mentir.
    contenido = archivo.file.read(MAX_IMAGEN_BYTES + 1)
    if len(contenido) > MAX_IMAGEN_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La imagen supera los 2 MB permitidos")
    extension = _extension_real(contenido)
    if extension is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sube una imagen JPG, PNG o WEBP")

    destino = Path(get_settings().storage_dir) / str(tenant_de(user)) / "productos"
    destino.mkdir(parents=True, exist_ok=True)
    # El nombre lo ponemos NOSOTROS. El `archivo.filename` no toca el disco:
    # «../../etc/passwd» es un nombre de archivo válido y escribiría fuera.
    ruta = destino / f"{uuid.uuid4()}.{extension}"
    ruta.write_bytes(contenido)

    anterior = producto.imagen_path
    producto.imagen_path = str(ruta)
    db.flush()
    if anterior:
        # Después de guardar la nueva: si no, cada reemplazo dejaría el archivo
        # viejo en disco para siempre.
        Path(anterior).unlink(missing_ok=True)
    return producto


@router.get("/{producto_id}/imagen")
def descargar_imagen(
    producto_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    """Devuelve el archivo. Pasa por aquí y no por StaticFiles a propósito:
    montar var/storage serviría los archivos de todos los inquilinos sin RLS."""
    producto = _producto_o_404(db, producto_id)
    ruta = Path(producto.imagen_path) if producto.imagen_path else None
    if ruta is None or not ruta.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El producto no tiene imagen")
    # Defensa en profundidad: hoy esta columna solo la escribe subir_imagen con
    # un nombre generado aquí, pero si algún día la llenara un import o un
    # script, esto sería una lectura arbitraria de archivos del servidor.
    base = Path(get_settings().storage_dir).resolve()
    if not ruta.resolve().is_relative_to(base):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El producto no tiene imagen")
    return Response(
        content=ruta.read_bytes(),
        media_type=MEDIA_TYPES.get(ruta.suffix.lstrip("."), "application/octet-stream"),
        headers={
            # El nombre del archivo lleva un uuid4 y solo cambia al reemplazar la
            # imagen, así que el navegador puede quedárselo. Sin esto, un catálogo
            # de 200 productos vuelve a descargar 200 archivos en cada visita.
            "Cache-Control": "private, max-age=3600",
            # El tipo lo decidimos nosotros por los bytes; que el navegador no
            # husmee el contenido y lo trate como otra cosa.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{producto_id}/imagen", status_code=status.HTTP_204_NO_CONTENT)
def borrar_imagen(
    producto_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    producto = _producto_o_404(db, producto_id)
    if producto.imagen_path:
        Path(producto.imagen_path).unlink(missing_ok=True)
        producto.imagen_path = None
        db.flush()
    return None
