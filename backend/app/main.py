"""Aplicación FastAPI de Factuchat.

- Errores genéricos al usuario; detalle solo en Sentry (OWASP A02/A10).
- Contexto de petición (IP, user agent, request_id) para RLS y auditoría.
- CORS restringido a dominios propios.
"""

import logging

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import client_ip, exigir_firma
from app.api.routes import (
    admin,
    auth,
    buzon,
    categorias,
    certificados,
    clientes,
    comprobantes,
    health,
    panel,
    productos,
    publico,
    reportes,
    superadmin,
    tienda,
    whatsapp,
)
from app.core.audit import register_audit_listeners
from app.core.config import get_settings
from app.core.context import RequestContext, clear_context, set_context
from app.core.observabilidad import init_sentry

logger = logging.getLogger("factuchat")


def create_app() -> FastAPI:
    settings = get_settings()

    # Sentry con filtro de secretos y sin variables locales (ver observabilidad.py)
    init_sentry("api")

    register_audit_listeners()

    app = FastAPI(
        title="Factuchat API",
        version="0.1.0",
        # La documentación interactiva solo existe fuera de producción (A02)
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        set_context(
            RequestContext(
                ip=client_ip(request),
                user_agent=(request.headers.get("user-agent") or "")[:400],
            )
        )
        try:
            return await call_next(request)
        finally:
            clear_context()

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # Nunca exponer trazas al usuario; el detalle va a Sentry/logs (A02, A10)
        logger.exception("Error no manejado en %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Error interno. Nuestro equipo fue notificado."},
        )

    api = "/api/v1"
    # Sin firma electrónica cargada el negocio no opera. La barrera va aquí, en
    # el montaje de los routers, y no ruta por ruta: así una ruta nueva de
    # operación nace protegida en vez de olvidada.
    con_firma = [Depends(exigir_firma)]

    app.include_router(health.router, prefix=api)
    app.include_router(auth.router, prefix=api)
    # --- Lo que un cliente sin firma SÍ puede hacer: entrar, ver su estado y
    #     subir su certificado. Nada más; es justo lo que necesita para
    #     desbloquearse.
    app.include_router(certificados.router, prefix=api)
    app.include_router(panel.router, prefix=api)
    # --- Operación: exige firma
    app.include_router(categorias.router, prefix=api, dependencies=con_firma)
    app.include_router(categorias.router_atributos, prefix=api, dependencies=con_firma)
    app.include_router(categorias.router_valores, prefix=api, dependencies=con_firma)
    app.include_router(clientes.router, prefix=api, dependencies=con_firma)
    app.include_router(comprobantes.router, prefix=api, dependencies=con_firma)
    app.include_router(productos.router, prefix=api, dependencies=con_firma)
    app.include_router(reportes.router, prefix=api, dependencies=con_firma)
    app.include_router(admin.router, prefix=api)
    app.include_router(superadmin.router, prefix=api)
    app.include_router(whatsapp.router, prefix=api)
    app.include_router(tienda.router, prefix=api, dependencies=con_firma)
    app.include_router(publico.router, prefix=api)
    app.include_router(buzon.router, prefix=api, dependencies=con_firma)
    app.include_router(buzon.router_webhook, prefix=api)
    app.include_router(buzon.router_interno, prefix=api)

    return app


app = create_app()
