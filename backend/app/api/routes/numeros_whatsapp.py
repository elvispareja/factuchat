"""Teléfonos autorizados a emitir por chat (maqueta «Números que pueden facturar»).

Quién puede facturar por WhatsApp en nombre de una empresa lo decide la propia
empresa desde su panel. Antes esto vivía en `tenants.telefono`, una sola
columna que solo se podía tocar por la base de datos; ver la migración 0028.

LA UNICIDAD LA IMPONE EL ÍNDICE, NO ESTE CÓDIGO. No se puede comprobar antes
si un número está en otra cuenta: `whatsapp_numeros` tiene RLS forzada y una
consulta desde aquí solo ve las filas propias —que es exactamente lo que se
quiere, porque preguntar «¿de quién es este teléfono?» no es asunto de un
inquilino—. Así que se intenta insertar y se traduce el choque.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, require_roles, tenant_de
from app.db.models import WhatsappNumero
from app.db.models.enums import Rol
from app.db.session import get_db
from app.schemas.whatsapp_numeros import NumeroIn, NumeroOut, para_mostrar
from app.services.planes import LimitePlanError, exigir_cupo_numeros, plan_vigente

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
            "created_at": n.created_at,
        }
        for i, n in enumerate(numeros)
    ]


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
    """Autoriza un teléfono. Devuelve la lista entera, ya reordenada."""
    tenant_id = tenant_de(user)

    # EL DUPLICADO SE MIRA ANTES QUE EL CUPO, y el orden importa. Con un plan
    # de un solo número, volver a dar de alta el que ya tienes respondía «sube
    # de plan»: cierto de cara al contador, pero una mentira para quien lo lee,
    # porque subir de plan no arregla nada. Lo destapó un test.
    if any(n.numero == body.numero for n in _listar(db)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese número ya está en tu lista.")

    try:
        exigir_cupo_numeros(db, tenant_id, plan_vigente(db, tenant_id))
    except LimitePlanError as e:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={"mensaje": e.mensaje, "funcion": e.funcion, "plan_sugerido": e.plan_sugerido},
        ) from e

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

    return _salida(_listar(db))


@router.delete("/{numero_id}", response_model=list[NumeroOut])
def quitar(
    numero_id: uuid.UUID,
    user: AuthUser = Depends(require_roles(Rol.CLIENTE)),
    db: Session = Depends(get_db),
):
    """Retira la autorización. Desde ese momento el bot deja de reconocerlo.

    Se permite quitar el último: quedarse sin números es una cuenta que no
    factura por chat, no una cuenta rota, y se vuelve a autorizar desde aquí
    mismo cuando haga falta."""
    numero = db.get(WhatsappNumero, numero_id)  # RLS: solo de esta cuenta
    if numero is not None:
        db.delete(numero)
        db.flush()
    # Quitar dos veces no es un error: el resultado es el mismo.
    return _salida(_listar(db))
