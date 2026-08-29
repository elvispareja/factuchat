"""Panel interno — 11 secciones (fase 4).

Toda consulta cross-tenant pasa por las funciones seguras sa_*, que verifican el
rol REAL en la base de datos y dejan rastro en audit_log. El rol LECTURA puede
mirar; SOPORTE puede actuar sobre inquilinos; solo SUPERADMIN toca configuración.
"""

import calendar
import csv
import io
import uuid
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.api.deps import AuthUser, client_ip, require_roles
from app.db.models import CostRate, Plan, PromoCode, SolicitudContacto, User
from app.db.models.enums import Rol
from app.db.session import get_db
from app.schemas.superadmin import (
    AltaClienteIn,
    AvisosIn,
    CambioPrecioIn,
    EditarClienteIn,
    EstadoTenantIn,
    ImpersonarIn,
    PromoCodeIn,
    TarifaIn,
)
from app.services import (
    configuracion,
    impersonacion,
    marketing,
    panel_interno,
    parametros,
)
from app.services.acceso import bienvenida
from app.services.configuracion import ConfiguracionError
from app.services.impersonacion import ImpersonacionError
from app.services.marketing import PromoError
from app.whatsapp import plantillas
from app.whatsapp.plantillas import Aviso

router = APIRouter(prefix="/sa", tags=["superadmin"])

TZ = ZoneInfo("America/Guayaquil")

# Quién puede qué (matriz de roles del documento /docs)
SOLO_LECTURA = require_roles(Rol.SUPERADMIN, Rol.SOPORTE, Rol.LECTURA)
PUEDE_ACTUAR = require_roles(Rol.SUPERADMIN, Rol.SOPORTE)
SOLO_SUPERADMIN = require_roles(Rol.SUPERADMIN)


def _hoy() -> date:
    return datetime.now(TZ).date()


def _ua(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:400]


def _sa(db: Session, sql: str, params: dict | None = None):
    """Ejecuta una función sa_* traduciendo su 'acceso denegado' a un 403."""
    try:
        return db.execute(text(sql), params or {}).mappings().all()
    except ProgrammingError as e:
        if "acceso denegado" in str(e).lower():
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu rol no permite esta consulta") from e
        raise


# ------------------------------------------------------- 1. dashboard general


@router.get("/metricas")
def metricas(user: AuthUser = Depends(SOLO_LECTURA), db: Session = Depends(get_db)):
    """Todo lo que pinta el Dashboard general, tal como lo define la maqueta:
    los cuatro KPI (MRR, altas, bajas y clientes activos), el gráfico de 30
    días, el semáforo de servicios y las alertas críticas."""
    fila = _sa(db, "SELECT * FROM sa_metricas()")[0]
    k = _sa(db, "SELECT * FROM sa_dashboard_kpis()")[0]
    planes_activos = _sa(db, "SELECT * FROM sa_dashboard_planes()")
    alertas = _sa(db, "SELECT * FROM sa_dashboard_alertas()")

    mrr = Decimal(str(k["mrr"]))
    anterior = Decimal(str(k["mrr_anterior"]))
    # Sin mes anterior con qué comparar no se inventa un porcentaje
    variacion = None
    if anterior > 0:
        variacion = float((mrr - anterior) / anterior * 100)

    return {
        "mrr": str(mrr),
        "mrr_variacion_pct": round(variacion, 1) if variacion is not None else None,
        "altas_mes": k["altas_mes"],
        "altas_con_promo": k["altas_con_promo"],
        "bajas_mes": k["bajas_mes"],
        "cancelaciones": k["cancelaciones"],
        "suspensiones": k["suspensiones"],
        "activos_total": k["activos_total"],
        "activos_por_plan": [
            {"plan": p["plan"], "clientes": p["clientes"]} for p in planes_activos
        ],
        "emision": panel_interno.emision_ultimos_30(db),
        "servicios": panel_interno.salud_de_servicios(db),
        "alertas": [
            {"severidad": a["severidad"], "texto": a["texto"], "seccion": a["seccion"]}
            for a in alertas
        ],
        # Se conservan los contadores de la primera versión: los usan el
        # semáforo de rechazos y el aviso de pagos por confirmar.
        "tenants": {
            "total": fila["tenants_total"],
            "activos": fila["tenants_activos"],
            "morosos": fila["tenants_morosos"],
        },
        "comprobantes_mes": {
            "total": fila["comprobantes_mes"],
            "autorizados": fila["autorizados_mes"],
            "rechazados": fila["rechazados_mes"],
        },
        "ingresos_mes": str(fila["ingresos_mes"]),
        "pagos_pendientes": fila["pagos_pendientes"],
    }


# --------------------------------------------------------------- 2. clientes


def _fila_cliente(f) -> dict:
    return {
        "id": str(f["id"]),
        "ruc": f["ruc"],
        "razon_social": f["razon_social"],
        "email": f["email"],
        "estado": f["estado"],
        # ACTIVO | EN_PRUEBA | SUSPENDIDO | MOROSO | CANCELADO, derivado en la
        # base para que la columna y los filtros digan lo mismo
        "estado_cartera": f["estado_cartera"],
        "plan": f["plan_nombre"],
        "cupo": f["cupo"],
        "usados": f["usados"],
        "suscripcion": f["suscripcion_estado"],
        "ultimo_comp": f["ultimo_comp"].isoformat() if f["ultimo_comp"] else None,
        "alta": f["created_at"].isoformat(),
    }


@router.get("/clientes")
def clientes(user: AuthUser = Depends(SOLO_LECTURA), db: Session = Depends(get_db)):
    return [_fila_cliente(f) for f in _sa(db, "SELECT * FROM sa_clientes()")]


@router.get("/clientes.csv")
def clientes_csv(
    request: Request,
    user: AuthUser = Depends(SOLO_LECTURA),
    db: Session = Depends(get_db),
):
    """Exportar la cartera entera es un acceso masivo a datos de contribuyentes:
    va por su propia función, que lo deja escrito en auditoría."""
    filas = _sa(
        db,
        "SELECT * FROM sa_exportar_clientes(:ip, :ua)",
        {"ip": client_ip(request), "ua": _ua(request)},
    )
    db.commit()  # el rastro de auditoría no puede quedarse sin confirmar

    cabeceras = [
        "RUC",
        "Cliente",
        "Correo",
        "Plan",
        "Estado",
        "Usados",
        "Cupo",
        "Alta",
        "Ultimo comprobante",
    ]
    buffer = io.StringIO()
    # QUOTE_ALL evita que Excel interprete como fórmula un valor que empiece
    # por «=», «+» o «-» (inyección de fórmulas CSV, OWASP A03).
    # (csv.writer ya termina las líneas en CRLF, que es lo que espera Excel)
    escritor = csv.writer(buffer, quoting=csv.QUOTE_ALL)
    escritor.writerow(cabeceras)
    for f in filas:
        c = _fila_cliente(f)
        escritor.writerow(
            [
                c["ruc"],
                c["razon_social"],
                c["email"],
                c["plan"] or "",
                c["estado_cartera"],
                c["usados"],
                c["cupo"],
                c["alta"][:10],
                (c["ultimo_comp"] or "")[:16].replace("T", " "),
            ]
        )

    nombre = f"factuchat-clientes-{_hoy().isoformat()}.csv"
    return Response(
        # BOM para que Excel en Windows abra las tildes bien
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/clientes/{tenant_id}")
def ficha(
    tenant_id: uuid.UUID,
    motivo: str = Query(min_length=3, max_length=300),
    user: AuthUser = Depends(SOLO_LECTURA),
    db: Session = Depends(get_db),
):
    """Abrir una ficha ES un acceso a datos personales: exige motivo y se audita."""
    filas = _sa(
        db,
        "SELECT * FROM sa_ficha_cliente(:t, :m)",
        {"t": str(tenant_id), "m": motivo},
    )
    if not filas:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inquilino no encontrado")
    f = filas[0]
    return {
        "id": str(f["id"]),
        "ruc": f["ruc"],
        "razon_social": f["razon_social"],
        "nombre_comercial": f["nombre_comercial"],
        "email": f["email"],
        "telefono": f["telefono"],
        "estado": f["estado"],
        "ambiente_sri": f["ambiente_sri"],
        "alta": f["created_at"].isoformat(),
        "plan": {"nombre": f["plan_nombre"], "precio": str(f["plan_precio"] or "")},
        "suscripcion": f["suscripcion_estado"],
        "consumo": {
            "comprobantes_mes": f["comprobantes_mes"],
            "clientes": f["clientes"],
            "productos": f["productos"],
        },
        "certificado": {
            "subject": f["cert_subject"],
            "vence": f["cert_vence"].isoformat() if f["cert_vence"] else None,
        },
    }


@router.put("/clientes/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def editar_cliente(
    tenant_id: uuid.UUID,
    body: EditarClienteIn,
    request: Request,
    user: AuthUser = Depends(PUEDE_ACTUAR),
    db: Session = Depends(get_db),
):
    _sa(
        db,
        "SELECT sa_editar_cliente(:t, :rs, :nc, :em, :tel, :m, :ip, :ua)",
        {
            "t": str(tenant_id),
            "rs": body.razon_social,
            "nc": body.nombre_comercial,
            "em": body.email,
            "tel": body.telefono,
            "m": body.motivo,
            "ip": client_ip(request),
            "ua": _ua(request),
        },
    )
    return None


@router.post("/clientes/{tenant_id}/estado", status_code=status.HTTP_204_NO_CONTENT)
def cambiar_estado(
    tenant_id: uuid.UUID,
    body: EstadoTenantIn,
    request: Request,
    user: AuthUser = Depends(PUEDE_ACTUAR),
    db: Session = Depends(get_db),
):
    _sa(
        db,
        "SELECT sa_cambiar_estado_tenant(:t, :e, :m, :ip, :ua)",
        {
            "t": str(tenant_id),
            "e": body.estado.value,
            "m": body.motivo,
            "ip": client_ip(request),
            "ua": _ua(request),
        },
    )
    return None


# --------------------------------------------------------- 3. impersonación


@router.post("/clientes/{tenant_id}/impersonar")
def impersonar(
    tenant_id: uuid.UUID,
    body: ImpersonarIn,
    request: Request,
    user: AuthUser = Depends(PUEDE_ACTUAR),
    db: Session = Depends(get_db),
):
    actor = db.get(User, user.id)
    if actor is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida")
    try:
        sesion = impersonacion.iniciar(
            db, actor, tenant_id, body.motivo, client_ip(request), _ua(request)
        )
    except ImpersonacionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return {
        "token": sesion.token,
        "expira_en": sesion.expira_en,
        "impersonacion_id": str(sesion.impersonacion_id),
        "tenant": {"id": str(sesion.tenant_id), "razon_social": sesion.tenant_nombre},
        "aviso": (
            f"Estás viendo la cuenta de {sesion.tenant_nombre} como soporte · "
            "toda acción queda en auditoría"
        ),
    }


@router.post("/impersonaciones/{impersonacion_id}/salir", status_code=204)
def salir_impersonacion(
    impersonacion_id: uuid.UUID,
    request: Request,
    user: AuthUser = Depends(PUEDE_ACTUAR),
    db: Session = Depends(get_db),
):
    actor = db.get(User, user.id)
    if actor is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida")
    try:
        impersonacion.terminar(db, actor, impersonacion_id, client_ip(request), _ua(request))
    except ImpersonacionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return None


@router.get("/impersonaciones")
def listar_impersonaciones(user: AuthUser = Depends(SOLO_LECTURA), db: Session = Depends(get_db)):
    caducadas = {i.id for i in impersonacion.caducadas_sin_cerrar(db)}
    return [
        {
            "id": str(i.id),
            "actor_user_id": str(i.actor_user_id),
            "tenant_id": str(i.tenant_id),
            "motivo": i.motivo,
            "iniciada": i.iniciada_at.isoformat(),
            "caducada": i.id in caducadas,
        }
        for i in impersonacion.activas(db)
    ]


# ---------------------------------------------------------- 4. comprobantes


@router.get("/comprobantes")
def cola_comprobantes(
    limite: int = Query(default=100, ge=1, le=500),
    user: AuthUser = Depends(SOLO_LECTURA),
    db: Session = Depends(get_db),
):
    return [
        {
            "id": str(f["id"]),
            "tenant_id": str(f["tenant_id"]),
            "cliente": f["razon_social"],
            "ruc": f["ruc"],
            "tipo": f["tipo"],
            "estado": f["estado"],
            "numero": f["numero"],
            "clave_acceso": f["clave_acceso"],
            "total": str(f["total"]),
            "mensajes": f["mensajes"],
            "intentos": f["intentos"],
            "actualizado": f["actualizado"].isoformat(),
        }
        for f in _sa(db, "SELECT * FROM sa_cola_comprobantes(:l)", {"l": limite})
    ]


# ------------------------------------------------------------- 5. marketing


@router.get("/promos")
def listar_promos(user: AuthUser = Depends(SOLO_LECTURA), db: Session = Depends(get_db)):
    promos = db.scalars(select(PromoCode).order_by(PromoCode.vigente_desde.desc())).all()
    return [
        {
            "id": str(p.id),
            "codigo": p.codigo,
            "descripcion": p.descripcion,
            "tipo": p.tipo.value,
            "valor": str(p.valor),
            "meses": p.meses,
            "planes": p.planes,
            "max_usos": p.max_usos,
            "usos": p.usos,
            "vigente_desde": p.vigente_desde.isoformat(),
            "vigente_hasta": p.vigente_hasta.isoformat() if p.vigente_hasta else None,
            "activo": p.activo,
            **marketing.resumen(db, p.id),
        }
        for p in promos
    ]


@router.post("/promos", status_code=status.HTTP_201_CREATED)
def crear_promo(
    body: PromoCodeIn,
    user: AuthUser = Depends(SOLO_SUPERADMIN),
    db: Session = Depends(get_db),
):
    existe = db.scalars(select(PromoCode).where(PromoCode.codigo == body.codigo)).first()
    if existe is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un código con ese nombre")
    promo = PromoCode(**body.model_dump())
    db.add(promo)
    db.flush()
    return {"id": str(promo.id), "codigo": promo.codigo}


@router.get("/promos/{promo_id}/usos")
def usos_promo(
    promo_id: uuid.UUID,
    user: AuthUser = Depends(SOLO_LECTURA),
    db: Session = Depends(get_db),
):
    promo = db.get(PromoCode, promo_id)
    if promo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Código no encontrado")
    return {
        "codigo": promo.codigo,
        "resumen": marketing.resumen(db, promo_id),
        "usos": marketing.usos_de(db, promo_id),
    }


@router.get("/marketing/origenes")
def origenes(user: AuthUser = Depends(SOLO_LECTURA), db: Session = Depends(get_db)):
    return marketing.altas_por_origen(db)


# ------------------------------------------- 6. alta de cliente (wizard 4.2)


@router.post("/clientes", status_code=status.HTTP_201_CREATED)
def alta_cliente(
    body: AltaClienteIn,
    request: Request,
    user: AuthUser = Depends(PUEDE_ACTUAR),
    db: Session = Depends(get_db),
):
    """Wizard "Nuevo cliente": crea el inquilino, su suscripción y, si viene
    código promo, lo aplica congelando el precio cobrado."""
    from app.db.models import Suscripcion
    from app.db.models.enums import EstadoSuscripcion

    hoy = _hoy()
    plan = configuracion.plan_vigente_por_codigo(db, body.plan.upper(), hoy)
    if plan is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ese plan no está vigente")

    # El alta va por función segura: el rol de la app no puede insertar tenants
    try:
        tenant_id = db.execute(
            text("SELECT sa_crear_tenant(:ruc, :rs, :nc, :email, :tel, :dir, :ip, :ua, :origen)"),
            {
                "ruc": body.ruc,
                "rs": body.razon_social,
                "nc": body.nombre_comercial,
                "email": body.email,
                "tel": body.telefono,
                "dir": body.direccion_matriz,
                "ip": client_ip(request),
                "ua": _ua(request),
                "origen": body.origen,
            },
        ).scalar_one()
    except ProgrammingError as e:
        if "ruc duplicado" in str(e).lower():
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un cliente con ese RUC") from e
        if "acceso denegado" in str(e).lower():
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu rol no permite el alta") from e
        raise

    precio = plan.precio_mensual
    uso_promo = None
    if body.codigo_promo:
        try:
            uso_promo = marketing.aplicar(db, body.codigo_promo, tenant_id, plan, hoy)
            precio = uso_promo.precio_cobrado or precio
        except PromoError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    db.add(
        Suscripcion(
            tenant_id=tenant_id,
            plan_id=plan.id,
            estado=EstadoSuscripcion.ACTIVA,
            precio=precio,  # congelado: los cambios de precio futuros no lo tocan
            inicia=hoy,
        )
    )
    db.flush()

    # El inquilino sin usuario es un panel al que nadie puede entrar: hasta
    # ahora el alta lo dejaba así. Se crea su cuenta con el correo del negocio,
    # que es con lo que entrará. No hay contraseña que ponerle: pide su código
    # de seis dígitos desde la pantalla de entrada.
    nombre_cuenta = body.nombre_comercial or body.razon_social
    try:
        db.execute(
            text("SELECT sa_crear_usuario_cliente(:t, :e, :n, :ip, :ua)"),
            {
                "t": str(tenant_id),
                "e": body.email,
                "n": nombre_cuenta,
                "ip": client_ip(request),
                "ua": _ua(request),
            },
        )
    except ProgrammingError as e:
        if "correo duplicado" in str(e).lower():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ese correo ya tiene cuenta en Factuchat. Usa otro para este cliente.",
            ) from e
        raise

    # Después del commit: un correo de bienvenida a una cuenta que no llegó a
    # guardarse es peor que no mandarlo.
    correo, negocio = body.email, body.razon_social
    db.info.setdefault("post_commit", []).append(lambda: bienvenida(correo, nombre_cuenta, negocio))

    return {
        "id": str(tenant_id),
        "ruc": body.ruc,
        "razon_social": body.razon_social,
        "plan": plan.nombre,
        "precio_cobrado": str(precio),
        "acceso_enviado_a": body.email,
        "promo": (
            {
                "codigo": body.codigo_promo,
                "retenido": str(uso_promo.retenido),
                "meses": uso_promo.meses_aplicados,
            }
            if uso_promo
            else None
        ),
    }


# --------------------------------------------------------- 7. configuración


@router.get("/planes")
def listar_planes(user: AuthUser = Depends(SOLO_LECTURA), db: Session = Depends(get_db)):
    hoy = _hoy()
    planes = db.scalars(select(Plan).order_by(Plan.codigo, Plan.vigente_desde)).all()
    return [
        {
            "id": str(p.id),
            "codigo": p.codigo,
            "nombre": p.nombre,
            "precio": str(p.precio_mensual),
            "limites": p.limites,
            "vigente_desde": p.vigente_desde.isoformat(),
            "vigente_hasta": p.vigente_hasta.isoformat() if p.vigente_hasta else None,
            "vigente_ahora": p.vigente_desde <= hoy
            and (p.vigente_hasta is None or p.vigente_hasta > hoy),
            "suscripciones": configuracion.suscripciones_afectadas(db, p.id),
        }
        for p in planes
    ]


@router.post("/planes/{codigo}/precio", status_code=status.HTTP_201_CREATED)
def cambiar_precio(
    codigo: str,
    body: CambioPrecioIn,
    user: AuthUser = Depends(SOLO_SUPERADMIN),
    db: Session = Depends(get_db),
):
    """Crea una versión futura del plan. Las suscripciones vivas NO cambian."""
    try:
        nueva = configuracion.cambiar_precio(
            db,
            codigo.upper(),
            body.precio,
            body.vigente_desde,
            _hoy(),
            body.limites,
        )
    except ConfiguracionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return {
        "id": str(nueva.id),
        "codigo": nueva.codigo,
        "precio": str(nueva.precio_mensual),
        "vigente_desde": nueva.vigente_desde.isoformat(),
        "aviso": "Las suscripciones actuales conservan su precio hasta esa fecha.",
    }


# ------------------------------------------------------- 8. consumo y costos


@router.get("/consumo")
def consumo(user: AuthUser = Depends(SOLO_LECTURA), db: Session = Depends(get_db)):
    """Costo real de cada cliente contra lo que paga (sección Consumo y costos).

    El reparto de costos y el margen se calculan aquí, sobre los componentes que
    devuelve la base. Ninguna de estas cifras se recalcula en el navegador: si
    el panel y un informe dieran márgenes distintos, no habría forma de saber
    cuál creer.

    OJO CON LA COMPARACIÓN. El costo es lo acumulado del mes hasta hoy, pero lo
    que paga el cliente es la mensualidad ENTERA. Comparar los dos a secas hace
    que el margen sea siempre estupendo el día 2 y que la alerta de márgenes
    bajos se vacíe sola cada día 1, justo cuando se mira. Por eso el aviso se
    dispara con el costo PROYECTADO a fin de mes, no con el acumulado.
    """
    hoy = _hoy()
    dias_mes = calendar.monthrange(hoy.year, hoy.month)[1]
    transcurridos = hoy.day

    filas = []
    ingreso_total = Decimal("0")
    costo_total = Decimal("0")

    for f in _sa(db, "SELECT * FROM sa_consumo_por_cliente()"):
        costo = (
            Decimal(str(f["costo_wa"]))
            + Decimal(str(f["costo_ia"]))
            + Decimal(str(f["costo_infra"]))
        )
        paga = Decimal(str(f["paga"]))
        margen = paga - costo
        # Sin ingreso no hay porcentaje que calcular: un cliente en prueba
        # cuesta dinero y paga cero, y eso NO es «-100%», es «todavía no paga».
        margen_pct = round(float(margen / paga * 100)) if paga > 0 else None

        # A este ritmo, ¿cómo acabará el mes? Es lo que hay que vigilar.
        proyectado = (costo * dias_mes / transcurridos).quantize(Decimal("0.000001"))
        margen_fin = paga - proyectado
        margen_fin_pct = round(float(margen_fin / paga * 100)) if paga > 0 else None

        usados = f["usados"]
        por_wa = f["comp_whatsapp"]
        # Un solo redondeo y el otro por diferencia: redondear los dos por
        # separado daba repartos de 99% y de 101%.
        wa_pct = round(por_wa / usados * 100) if usados else None

        ingreso_total += paga
        costo_total += costo

        filas.append(
            {
                "tenant_id": str(f["tenant_id"]),
                "cliente": f["cliente"],
                "plan": f["plan"],
                "suscripcion": f["suscripcion"],
                "cupo": f["cupo"],
                "usados": usados,
                "canal": {
                    "whatsapp_pct": wa_pct,
                    "panel_pct": None if wa_pct is None else 100 - wa_pct,
                },
                "ia_usados": f["ia_usados"],
                "ia_cupo": f["ia_cupo"],
                "costo": str(costo),
                "costo_detalle": {
                    "whatsapp": str(f["costo_wa"]),
                    "ia": str(f["costo_ia"]),
                    "infra": str(f["costo_infra"]),
                },
                "costo_proyectado": str(proyectado),
                "paga": str(paga),
                "margen": str(margen),
                "margen_pct": margen_pct,
                "margen_proyectado_pct": margen_fin_pct,
            }
        )

    # El peor margen primero: la sección existe para que el ojo caiga ahí.
    # Los que aún no pagan van al principio de todo, que son costo puro.
    filas.sort(key=lambda x: (x["margen_proyectado_pct"] is not None, x["margen_proyectado_pct"]))

    margen_global = ingreso_total - costo_total
    return {
        "clientes": filas,
        "periodo": {
            "dias_transcurridos": transcurridos,
            "dias_mes": dias_mes,
            "hasta": hoy.isoformat(),
        },
        "totales": {
            "ingreso": str(ingreso_total),
            "costo": str(costo_total),
            "margen": str(margen_global),
            "margen_pct": (
                round(float(margen_global / ingreso_total * 100)) if ingreso_total > 0 else None
            ),
        },
        # «Cuestan más del 80% de lo que pagan», como la maqueta, pero medido
        # sobre la proyección a fin de mes. Los que aún no pagan entran también:
        # son costo puro.
        "margen_bajo": [
            f
            for f in filas
            if Decimal(f["costo"]) > 0
            and (f["margen_proyectado_pct"] is None or f["margen_proyectado_pct"] < 20)
        ],
    }


@router.get("/tarifas")
def listar_tarifas(user: AuthUser = Depends(SOLO_LECTURA), db: Session = Depends(get_db)):
    hoy = _hoy()
    tarifas = db.scalars(
        select(CostRate).order_by(CostRate.proveedor, CostRate.concepto, CostRate.vigente_desde)
    ).all()
    return [
        {
            "id": str(t.id),
            "proveedor": t.proveedor,
            "concepto": t.concepto,
            "costo_unitario": str(t.costo_unitario),
            "unidad": t.unidad,
            "moneda": t.moneda,
            "vigente_desde": t.vigente_desde.isoformat(),
            "vigente_hasta": t.vigente_hasta.isoformat() if t.vigente_hasta else None,
            "vigente_ahora": t.vigente_desde <= hoy
            and (t.vigente_hasta is None or t.vigente_hasta > hoy),
            "notas": t.notas,
        }
        for t in tarifas
    ]


@router.post("/tarifas", status_code=status.HTTP_201_CREATED)
def crear_tarifa(
    body: TarifaIn,
    user: AuthUser = Depends(SOLO_SUPERADMIN),
    db: Session = Depends(get_db),
):
    try:
        tarifa = configuracion.programar_tarifa(
            db,
            body.proveedor,
            body.concepto,
            body.costo_unitario,
            body.unidad,
            body.vigente_desde,
            body.notas,
            hoy=_hoy(),
        )
    except ConfiguracionError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    return {"id": str(tarifa.id), "vigente_desde": tarifa.vigente_desde.isoformat()}


# ---------------------------------------------- 8.b avisos automáticos


AVISOS_ETIQUETA = {
    Aviso.PRE_DECLARACION: "Pre-declaración (noveno dígito)",
    Aviso.CUPO_AGOTADO: "Cupo agotado",
    Aviso.PAGO_VENCIDO: "Pago vencido",
}


@router.get("/avisos")
def listar_avisos(user: AuthUser = Depends(SOLO_LECTURA), db: Session = Depends(get_db)):
    """Los tres textos que el sistema envía por su cuenta.

    Devuelve el texto vigente y también el de fábrica, para poder volver atrás
    sin tener que buscarlo en el código.
    """
    return [
        {
            "aviso": a.value,
            "etiqueta": AVISOS_ETIQUETA[a],
            "texto": plantillas.texto_de(db, a),
            "texto_original": plantillas.PLANTILLAS[a].texto,
            "editado": plantillas.texto_de(db, a) != plantillas.PLANTILLAS[a].texto,
            "variables": list(plantillas.PLANTILLAS[a].variables),
            "plantilla_meta": plantillas.PLANTILLAS[a].nombre,
        }
        for a in Aviso
    ]


@router.put("/avisos", status_code=status.HTTP_204_NO_CONTENT)
def guardar_avisos(
    body: AvisosIn,
    user: AuthUser = Depends(SOLO_SUPERADMIN),
    db: Session = Depends(get_db),
):
    """Guarda los textos editados. Valida ANTES de escribir: una plantilla a la
    que le falte una variable sale mal enviada o la rechaza Meta, que cobra
    igual el intento. La escritura en `parametros` la audita el listener de la
    sesión."""
    for clave, texto in body.textos.items():
        try:
            aviso = Aviso(clave)
        except ValueError as e:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Aviso desconocido: {clave}"
            ) from e
        try:
            limpio = plantillas.revisar_texto(aviso, texto)
        except plantillas.TextoInvalido as e:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{AVISOS_ETIQUETA[aviso]}: {e}",
            ) from e
        parametros.fijar_texto(db, plantillas.CLAVE_PARAMETRO[aviso], limpio, user.id)
    return None


# ------------------------------------------------------------- 9. auditoría


@router.get("/auditoria")
def auditoria(
    limite: int = Query(default=200, ge=1, le=1000),
    tenant_id: uuid.UUID | None = None,
    accion: str | None = None,
    user: AuthUser = Depends(SOLO_LECTURA),
    db: Session = Depends(get_db),
):
    """SOLO LECTURA por diseño: no existe endpoint que escriba aquí."""
    filas = _sa(
        db,
        "SELECT * FROM sa_auditoria(:l, :t, :a)",
        {"l": limite, "t": str(tenant_id) if tenant_id else None, "a": accion},
    )
    return [
        {
            "id": str(f["id"]),
            "fecha": f["created_at"].isoformat(),
            "actor": f["actor_nombre"],
            "rol": f["actor_rol"],
            "cliente": f["tenant_nombre"],
            "accion": f["accion"],
            "tabla": f["tabla"],
            "registro_id": f["registro_id"],
            "antes": f["antes"],
            "despues": f["despues"],
            "ip": f["ip"],
        }
        for f in filas
    ]


@router.get("/solicitudes")
def solicitudes(
    pendientes: bool = Query(default=True),
    user: AuthUser = Depends(SOLO_LECTURA),
    db: Session = Depends(get_db),
):
    """La bandeja de la landing: pedidos del checkout y consultas de contacto.

    El correo avisa; esto es donde se trabajan. Sin esta pantalla el aviso se
    pierde en una bandeja de entrada y el pedido se queda sin atender."""
    consulta = select(SolicitudContacto).order_by(SolicitudContacto.creada_at.desc()).limit(300)
    if pendientes:
        consulta = consulta.where(SolicitudContacto.atendida.is_(False))
    return [
        {
            "id": str(s.id),
            "tipo": "PEDIDO" if s.plan else "CONSULTA",
            "nombre": s.nombre,
            "email": s.email,
            "telefono": s.telefono,
            "identificacion": s.identificacion,
            "ciudad": s.ciudad,
            "provincia": s.provincia,
            "pais": s.pais,
            "plan": s.plan,
            "metodo_pago": s.metodo_pago,
            "agenda": (
                f"{s.agenda_dia} {s.agenda_hora}" if s.agenda_dia and s.agenda_hora else None
            ),
            "mensaje": s.mensaje,
            "tiene_comprobante": bool(s.comprobante_url),
            "avisado": s.avisado_at is not None,
            "atendida": s.atendida,
            "creada": s.creada_at.isoformat(),
        }
        for s in db.scalars(consulta).all()
    ]


@router.post("/solicitudes/{solicitud_id}/atendida")
def marcar_atendida(
    solicitud_id: uuid.UUID,
    user: AuthUser = Depends(PUEDE_ACTUAR),
    db: Session = Depends(get_db),
):
    """Cerrar una solicitud ya trabajada. Solo quien puede actuar."""
    solicitud = db.get(SolicitudContacto, solicitud_id)
    if solicitud is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa solicitud no existe")
    solicitud.atendida = True
    db.flush()
    return {"id": str(solicitud.id), "atendida": True}


@router.get("/yo")
def yo(user: AuthUser = Depends(SOLO_LECTURA), db: Session = Depends(get_db)):
    """Identidad del operador y qué puede hacer, para que el panel se dibuje."""
    actor = db.get(User, user.id)
    return {
        "nombre": actor.nombre if actor else "",
        "rol": user.rol.value,
        "puede_actuar": user.rol in (Rol.SUPERADMIN, Rol.SOPORTE),
        "es_superadmin": user.rol == Rol.SUPERADMIN,
        "hoy": _hoy().isoformat(),
        "zona": "America/Guayaquil",
    }


def _decimal(valor: str) -> Decimal:
    return Decimal(valor)
