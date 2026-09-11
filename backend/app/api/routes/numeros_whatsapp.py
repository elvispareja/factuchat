"""Teléfonos autorizados a emitir por chat (maqueta «Números que pueden facturar»).

Quién puede facturar por WhatsApp en nombre de una empresa lo decide la propia
empresa desde su panel. Antes esto vivía en `tenants.telefono`, una sola
columna que solo se podía tocar por la base de datos; ver la migración 0028.

DAR DE ALTA NO ES AUTORIZAR. Desde la migración 0030 el número nace PENDIENTE y
no factura hasta que vuelve un código de seis dígitos que prueba que ese
teléfono es de quien lo dio de alta. Sin eso, un dígito mal tecleado daba de
alta el teléfono de un desconocido, y quien quisiera podía dar de alta el de
cualquiera.

LA UNICIDAD LA IMPONE EL ÍNDICE, NO ESTE CÓDIGO. No se puede comprobar antes
si un número está en otra cuenta: `whatsapp_numeros` tiene RLS forzada y una
consulta desde aquí solo ve las filas propias —que es exactamente lo que se
quiere, porque preguntar «¿de quién es este teléfono?» no es asunto de un
inquilino—. Así que se intenta insertar y se traduce el choque. Ojo: el índice
solo cubre los VERIFICADOS, así que dos empresas pueden tener el mismo número
pendiente y el choque salta al verificar, no al dar de alta.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.core.ratelimit import RateLimitExceeded
from app.db.models import WhatsappNumero
from app.db.models.enums import Rol
from app.db.session import despues_del_commit, get_db
from app.schemas.whatsapp_numeros import NumeroIn, NumeroOut, VerificarIn, para_mostrar
from app.services import verificacion_numero as verif
from app.services.planes import LimitePlanError, exigir_cupo_numeros, plan_vigente

logger = logging.getLogger("factuchat.whatsapp")
router = APIRouter(prefix="/numeros-whatsapp", tags=["numeros-whatsapp"])


def _listar(db: Session) -> list[WhatsappNumero]:
    # RLS: solo los de esta cuenta. El orden decide cuál es «Principal».
    return list(
        db.scalars(select(WhatsappNumero).order_by(WhatsappNumero.created_at, WhatsappNumero.id))
    )


def _salida(numeros: list[WhatsappNumero]) -> list[dict]:
    return [
        {
            "id": n.id,
            "numero": n.numero,
            "mostrar": para_mostrar(n.numero),
            "etiqueta": n.etiqueta,
            "principal": i == 0,
            "verificado": n.verificado,
            "created_at": n.created_at,
        }
        for i, n in enumerate(numeros)
    ]


def _programar_envio(db: Session, tenant_id: uuid.UUID, numero: str, codigo: str) -> None:
    """Encola el código DESPUÉS del commit.

    Antes del commit, un fallo posterior dejaría al cliente con un código en el
    teléfono que la base ya no reconoce. Y la llamada a Meta nunca ocurre dentro
    de la transacción: mantener una transacción abierta durante una llamada HTTP
    es pedir que se acumulen conexiones muertas.
    """
    from app.tasks.whatsapp import enviar_codigo_verificacion

    def encolar() -> None:
        try:
            enviar_codigo_verificacion.delay(str(tenant_id), numero, codigo)
        except Exception:  # noqa: BLE001 — la cola caída no puede tumbar el alta
            # El código ya está guardado: se puede pedir de nuevo, y sigue
            # valiendo el camino de escribirlo al bot. Tumbar la petición aquí
            # dejaría al cliente sin número y sin saber por qué.
            logger.exception("No se pudo encolar el código de verificación de %s", numero)

    despues_del_commit(db, encolar)


def _429(e: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Ya se enviaron varios códigos a ese número. Espera unos minutos."},
        headers={"Retry-After": str(e.retry_after)},
    )


@router.get("", response_model=list[NumeroOut])
def listar(
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    return _salida(_listar(db))


@router.post("", response_model=list[NumeroOut], status_code=status.HTTP_201_CREATED)
def autorizar(
    body: NumeroIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    """Da de alta un teléfono PENDIENTE y le manda su código.

    Devuelve la lista entera, ya reordenada. El número aparece sin verificar
    hasta que el código vuelve por `POST /{id}/verificar` o por un mensaje al
    bot desde ese mismo teléfono.
    """
    tenant_id = tenant_de(user)

    # EL DUPLICADO SE MIRA ANTES QUE EL CUPO, y el orden importa. Con un plan
    # de un solo número, volver a dar de alta el que ya tienes respondía «sube
    # de plan»: cierto de cara al contador, pero una mentira para quien lo lee,
    # porque subir de plan no arregla nada. Lo destapó un test.
    if any(n.numero == body.numero for n in _listar(db)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese número ya está en tu lista.")

    # Y antes del cupo, por lo mismo: si el teléfono es de otra empresa, «sube
    # de plan» sería otra mentira. El índice ya no puede frenarlo solo, porque
    # la fila nueva nace pendiente y el índice único solo cubre las verificadas.
    if verif.ocupado(db, body.numero):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ese número ya está autorizado en otra cuenta de Factuchat. "
            "Un teléfono solo puede facturar para una empresa.",
        )

    try:
        exigir_cupo_numeros(db, tenant_id, plan_vigente(db, tenant_id))
    except LimitePlanError as e:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={"mensaje": e.mensaje, "funcion": e.funcion, "plan_sugerido": e.plan_sugerido},
        ) from e

    # El freno va ANTES de escribir: lo que se protege es el teléfono de quien
    # recibe, que puede no tener nada que ver con quien lo teclea aquí.
    try:
        verif.limitar_envios(body.numero)
    except RateLimitExceeded as e:
        return _429(e)

    numero = WhatsappNumero(tenant_id=tenant_id, numero=body.numero, etiqueta=body.etiqueta)
    db.add(numero)
    try:
        # Punto de guardado: sin él, el choque del índice dejaría la
        # transacción entera inservible y ni siquiera podríamos responder.
        with db.begin_nested():
            db.flush()
    except IntegrityError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ese número ya está autorizado en otra cuenta de Factuchat. "
            "Un teléfono solo puede facturar para una empresa.",
        ) from e

    _programar_envio(db, tenant_id, numero.numero, verif.emitir(db, numero))
    return _salida(_listar(db))


@router.post("/{numero_id}/codigo", response_model=list[NumeroOut])
def reenviar(
    numero_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    """Manda un código nuevo. El anterior deja de valer."""
    numero = db.get(WhatsappNumero, numero_id)  # RLS: solo de esta cuenta
    if numero is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ese número no está en tu lista.")
    if numero.verificado:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese número ya está verificado.")

    try:
        verif.limitar_envios(numero.numero)
    except RateLimitExceeded as e:
        return _429(e)

    _programar_envio(db, tenant_de(user), numero.numero, verif.emitir(db, numero))
    return _salida(_listar(db))


@router.post("/{numero_id}/verificar", response_model=list[NumeroOut])
def verificar(
    numero_id: uuid.UUID,
    body: VerificarIn,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    """Comprueba el código y, si es el bueno, deja al número facturando."""
    numero = db.get(WhatsappNumero, numero_id)  # RLS: solo de esta cuenta
    if numero is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ese número no está en tu lista.")
    if numero.verificado:
        # Verificar dos veces no es un error: el resultado es el mismo.
        return _salida(_listar(db))

    resultado = verif.comprobar(db, numero.numero, body.codigo, fila_id=numero.id)
    if resultado != "ok":
        # EL INTENTO GASTADO TIENE QUE SOBREVIVIR A LA RESPUESTA DE ERROR. Al
        # levantar la excepción, `get_db` deshace la transacción, y con ella se
        # iría el contador que acaba de subir: seis dígitos se adivinarían a
        # fuerza de reintentos porque el quinto fallo nunca llegaría. Así que se
        # confirma antes de responder.
        db.commit()
        # 409 y no 422: el código tiene la forma correcta, lo que falla es que
        # no vale. Y el motivo se dice entero, que es lo que deja actuar.
        raise HTTPException(status.HTTP_409_CONFLICT, verif.MOTIVOS[resultado])

    # La fila la cambió la función SQL por debajo del ORM.
    db.expire(numero)
    return _salida(_listar(db))


@router.delete("/{numero_id}", response_model=list[NumeroOut])
def quitar(
    numero_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    """Retira la autorización. Desde ese momento el bot deja de reconocerlo.

    Sirve también para cancelar una verificación a medias: quitar el número
    pendiente libera el hueco y permite volver a empezar.

    Se permite quitar el último: quedarse sin números es una cuenta que no
    factura por chat, no una cuenta rota, y se vuelve a autorizar desde aquí
    mismo cuando haga falta."""
    numero = db.get(WhatsappNumero, numero_id)  # RLS: solo de esta cuenta
    if numero is not None:
        db.delete(numero)
        db.flush()
    # Quitar dos veces no es un error: el resultado es el mismo.
    return _salida(_listar(db))
