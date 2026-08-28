# Factuchat

Facturación electrónica SRI (Ecuador) por WhatsApp y panel web. Multi-tenant.

## Estructura del monorepo

| Carpeta     | Contenido |
|-------------|-----------|
| `/backend`  | API FastAPI (Python 3.12) + SQLAlchemy 2 + Alembic + Celery |
| `/frontend` | React 18 + Vite + TypeScript (design system extraído de las maquetas) |
| `/deploy`   | Docker Compose, nginx, scripts de instalación, respaldo y verificación |
| `/docs`     | Documentación de seguridad, LOPDP e ISO 27001/9001 |
| `/diseno`   | Maquetas HTML aprobadas — única fuente de verdad visual (no se sirve en producción) |

## Desarrollo local

Requisitos: Docker Desktop y Node 20+.

```powershell
# Levantar entorno de desarrollo (Postgres + Redis + API)
docker compose -f deploy/docker-compose.dev.yml up -d --build

# Correr toda la verificación local (ruff + mypy + pytest + pip-audit)
./deploy/scripts/check.ps1

# Frontend
cd frontend; npm install; npm run dev
```

Copiar `backend/.env.example` a `backend/.env` antes de levantar (el compose de desarrollo trae valores por defecto seguros solo para local).

## Seguridad

Ver [SECURITY.md](SECURITY.md) — mapeo OWASP Top 10 (2025) a código y configuración.

El plan maestro del proyecto está en [PLAN.md](PLAN.md). No avanzar de fase sin su checklist en verde.
