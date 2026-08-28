"""Planes y gating por plan (fase 3.2).

NOMBRES, PRECIOS, CUPOS y CUPO DE IA salen de Superadmin.dc.html (línea 1158),
que es donde se administran los planes; el dueño del producto confirmó esa
matriz frente a la de Dashboard.dc.html, que quedó obsoleta (usaba otros nombres
y precios). Las BANDERAS de función (stock, tienda, archivos, nums, topes de
clientes y productos) solo están definidas en Dashboard.dc.html y se mapean por
posición de nivel, que es como se corresponden ambas maquetas.

Esta tabla es solo la SEMILLA: los planes viven en la base de datos y el
superadmin los edita con vigencia futura (fase 4).

Las decisiones de bloqueo se toman SIEMPRE en el servidor (OWASP A06): el
frontend solo pinta el estado que el servidor le dice, nunca al revés.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AnalisisIA, ClienteFinal, Comprobante, Plan, Producto, Suscripcion
from app.db.models.enums import EstadoComprobante, EstadoSuscripcion

# 0 = sin límite. "ia" es el cupo mensual de análisis con IA.
LIMITES_POR_PLAN: dict[str, dict] = {
    "Inicial": {
        "precio": Decimal("2.99"),
        "cupo": 10,
        "ia": 0,
        "cli": 20,
        "prod": 10,
        "stock": False,
        "tienda": False,
        "voz": False,
        "masivo": False,
        "nums": 1,
        "acumula": False,
        "archivos": False,
    },
    "Independiente": {
        "precio": Decimal("5.99"),
        "cupo": 30,
        "ia": 20,
        "cli": 100,
        "prod": 100,
        "stock": False,
        "tienda": False,
        "voz": False,
        "masivo": False,
        "nums": 1,
        "acumula": False,
        "archivos": True,
    },
    "Emprendedor": {
        "precio": Decimal("9.99"),
        "cupo": 80,
        "ia": 40,
        "cli": 200,
        "prod": 200,
        "stock": True,
        "tienda": False,
        "voz": False,
        "masivo": False,
        "nums": 1,
        "acumula": True,
        "archivos": True,
    },
    "Empresario": {
        "precio": Decimal("24.99"),
        "cupo": 250,
        "ia": 100,
        "cli": 0,
        "prod": 0,
        "stock": True,
        "tienda": True,
        "voz": True,
        "masivo": True,
        "nums": 2,
        "acumula": True,
        "archivos": True,
    },
}

ORDEN_PLANES = ["Inicial", "Independiente", "Emprendedor", "Empresario"]

# Qué plan hay que contratar para desbloquear cada función: el PRIMERO de la
# lista que la traiga. Se usa para el texto "viene con el plan X" de la maqueta.
FUNCIONES = ("stock", "tienda", "voz", "masivo", "archivos")


def plan_minimo_con(funcion: str) -> str | None:
    for nombre in ORDEN_PLANES:
        if LIMITES_POR_PLAN[nombre].get(funcion):
            return nombre
    return None


class LimitePlanError(Exception):
    """Tope del plan alcanzado. El mensaje es el que ve el usuario."""

    def __init__(self, mensaje: str, funcion: str = "", plan_sugerido: str | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.funcion = funcion
        self.plan_sugerido = plan_sugerido


@dataclass
class PlanVigente:
    nombre: str
    precio: Decimal
    limites: dict

    def permite(self, funcion: str) -> bool:
        return bool(self.limites.get(funcion))

    def tope(self, clave: str) -> int:
        """0 = sin límite."""
        return int(self.limites.get(clave) or 0)


def plan_por_defecto() -> PlanVigente:
    return PlanVigente(
        "Inicial", LIMITES_POR_PLAN["Inicial"]["precio"], LIMITES_POR_PLAN["Inicial"]
    )


def plan_vigente(db: Session, tenant_id: uuid.UUID) -> PlanVigente:
    """Plan de la suscripción activa del tenant. Sin suscripción, el más básico:
    nunca se conceden funciones por ausencia de datos (deny by default)."""
    fila = db.execute(
        select(Plan)
        .join(Suscripcion, Suscripcion.plan_id == Plan.id)
        .where(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.estado.in_([EstadoSuscripcion.ACTIVA, EstadoSuscripcion.MOROSA]),
        )
        .order_by(Suscripcion.inicia.desc())
        .limit(1)
    ).scalar_one_or_none()
    if fila is None:
        return plan_por_defecto()
    limites = fila.limites or LIMITES_POR_PLAN.get(fila.codigo) or {}
    return PlanVigente(fila.nombre, fila.precio_mensual, limites)


# ------------------------------------------------------------------ consumos


def comprobantes_del_periodo(db: Session, tenant_id: uuid.UUID, hoy: date) -> int:
    """Comprobantes que consumen cupo: los que llegaron al SRI. Un borrador o un
    rechazado no gasta cupo del cliente."""
    return int(
        db.execute(
            select(func.count(Comprobante.id)).where(
                Comprobante.tenant_id == tenant_id,
                Comprobante.estado.in_(
                    [
                        EstadoComprobante.ENVIADO_SRI,
                        EstadoComprobante.AUTORIZADO,
                    ]
                ),
                func.date_trunc("month", Comprobante.fecha_emision)
                == func.date_trunc("month", hoy),
            )
        ).scalar_one()
    )


def clientes_guardados(db: Session, tenant_id: uuid.UUID) -> int:
    return int(
        db.execute(
            select(func.count(ClienteFinal.id)).where(ClienteFinal.tenant_id == tenant_id)
        ).scalar_one()
    )


def productos_en_catalogo(db: Session, tenant_id: uuid.UUID) -> int:
    return int(
        db.execute(
            select(func.count(Producto.id)).where(
                Producto.tenant_id == tenant_id, Producto.activo.is_(True)
            )
        ).scalar_one()
    )


# ------------------------------------------------------------------ guardas


def exigir_funcion(plan: PlanVigente, funcion: str) -> None:
    """Guarda de servidor para una función bloqueada por plan."""
    if plan.permite(funcion):
        return
    sugerido = plan_minimo_con(funcion)
    mensajes = {
        "tienda": f"La tienda en línea viene con el plan {sugerido}.",
        "stock": f"El control de inventario viene con el plan {sugerido}.",
        "archivos": f"La bandeja de retenciones viene con el plan {sugerido}.",
        "masivo": f"La carga masiva de clientes viene con el plan {sugerido}.",
        "voz": f"Los mensajes de voz vienen con el plan {sugerido}.",
    }
    raise LimitePlanError(
        mensajes.get(funcion, f"Esta función viene con el plan {sugerido}."),
        funcion=funcion,
        plan_sugerido=sugerido,
    )


def exigir_cupo_clientes(db: Session, tenant_id: uuid.UUID, plan: PlanVigente) -> None:
    tope = plan.tope("cli")
    if tope and clientes_guardados(db, tenant_id) >= tope:
        raise LimitePlanError(
            "Llegaste al límite de tu plan. Tus clientes siguen aquí y puedes seguir "
            "facturándoles, pero para guardar nuevos necesitas subir de plan.",
            funcion="cli",
            plan_sugerido=_siguiente_plan(plan.nombre),
        )


def exigir_cupo_productos(db: Session, tenant_id: uuid.UUID, plan: PlanVigente) -> None:
    tope = plan.tope("prod")
    if tope and productos_en_catalogo(db, tenant_id) >= tope:
        raise LimitePlanError(
            f"Tu plan permite hasta {tope} productos en el catálogo. "
            "Para agregar más, sube de plan.",
            funcion="prod",
            plan_sugerido=_siguiente_plan(plan.nombre),
        )


def exigir_cupo_comprobantes(
    db: Session, tenant_id: uuid.UUID, plan: PlanVigente, hoy: date
) -> None:
    tope = plan.tope("cupo")
    if tope and comprobantes_del_periodo(db, tenant_id, hoy) >= tope:
        raise LimitePlanError(
            f"Usaste los {tope} comprobantes de tu plan este mes. "
            "Puedes recargar comprobantes o subir de plan para seguir emitiendo.",
            funcion="cupo",
            plan_sugerido=_siguiente_plan(plan.nombre),
        )


# Orígenes de un análisis de documento con IA. El del buzón está EXENTO: es la
# promesa publicada en la landing —«Los XML de tu buzón SRI no consumen tus
# análisis con IA; las fotos de documentos sí»—, y se cumple aquí, en el único
# sitio donde se descuenta cupo, no por descuido de nadie.
ORIGEN_IA_EXENTO = {"BUZON"}


def analisis_ia_del_periodo(db: Session, tenant_id: uuid.UUID, hoy: date) -> int:
    """Análisis que SÍ consumieron cupo en el mes en curso."""
    desde = hoy.replace(day=1)
    hasta = date(hoy.year + 1, 1, 1) if hoy.month == 12 else date(hoy.year, hoy.month + 1, 1)
    return int(
        db.execute(
            select(func.count(AnalisisIA.id)).where(
                AnalisisIA.tenant_id == tenant_id,
                AnalisisIA.consume.is_(True),
                AnalisisIA.created_at >= desde,
                AnalisisIA.created_at < hasta,
            )
        ).scalar_one()
    )


def registrar_analisis_ia(
    db: Session,
    tenant_id: uuid.UUID,
    origen: str,
    hoy: date,
    plan: PlanVigente | None = None,
    referencia: str | None = None,
) -> AnalisisIA:
    """Anota un análisis con IA y descuenta cupo, salvo que esté exento.

    Un XML del buzón se lee igual, y queda su fila con `consume=False`: la
    exención es un dato comprobable, no una ausencia de código. Por eso los
    orígenes exentos no necesitan plan: no hay nada que descontar.
    """
    exento = origen in ORIGEN_IA_EXENTO
    if not exento:
        if plan is None:
            raise LimitePlanError("No pudimos comprobar tu plan para este análisis.", funcion="ia")
        tope = plan.tope("ia")
        if tope and analisis_ia_del_periodo(db, tenant_id, hoy) >= tope:
            raise LimitePlanError(
                f"Usaste los {tope} análisis de documentos con IA de tu plan este mes. "
                "Los XML que llegan a tu buzón del SRI no gastan análisis.",
                funcion="ia",
                plan_sugerido=_siguiente_plan(plan.nombre),
            )
    fila = AnalisisIA(tenant_id=tenant_id, origen=origen, consume=not exento, referencia=referencia)
    db.add(fila)
    db.flush()
    return fila


def _siguiente_plan(actual: str) -> str | None:
    if actual not in ORDEN_PLANES:
        return ORDEN_PLANES[0]
    i = ORDEN_PLANES.index(actual)
    return ORDEN_PLANES[i + 1] if i + 1 < len(ORDEN_PLANES) else None


def resumen_para_frontend(db: Session, tenant_id: uuid.UUID, hoy: date) -> dict:
    """Todo lo que el panel necesita para pintar cupos y bloqueos, decidido en
    el servidor. El frontend NO recalcula permisos."""
    plan = plan_vigente(db, tenant_id)
    cupo = plan.tope("cupo")
    usados = min(comprobantes_del_periodo(db, tenant_id, hoy), cupo) if cupo else 0
    restantes = max(0, cupo - usados) if cupo else 0
    return {
        "nombre": plan.nombre,
        "precio": str(plan.precio),
        "cupo": cupo,
        "usados": usados,
        "restantes": restantes,
        "pct_uso": round(usados / cupo * 100) if cupo else 0,
        "pocos": bool(cupo) and restantes <= cupo * 0.15,
        "acumula": plan.permite("acumula"),
        "nota_cupo": (
            "Lo que no uses pasa al mes siguiente."
            if plan.permite("acumula")
            else "Son del mes en curso."
        ),
        "clientes": {
            "usados": clientes_guardados(db, tenant_id),
            "tope": plan.tope("cli"),
        },
        "productos": {
            "usados": productos_en_catalogo(db, tenant_id),
            "tope": plan.tope("prod"),
        },
        "analisis_ia": plan.tope("ia"),
        "numeros_whatsapp": plan.tope("nums"),
        "funciones": {f: plan.permite(f) for f in FUNCIONES},
        "planes_para_desbloquear": {f: plan_minimo_con(f) for f in FUNCIONES},
    }
