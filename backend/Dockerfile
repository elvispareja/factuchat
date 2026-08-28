# Imagen del backend. Python 3.12 fijado (stack obligatorio).
# Producción usará digest fijado y escaneo trivy (OWASP A03, fase de despliegue).
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Librerías de sistema para WeasyPrint (RIDE en PDF, fase 2.4)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 \
        libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Usuario no-root dentro de la imagen (control de despliegue #2)
RUN groupadd -r factuchat && useradd -r -g factuchat -d /app factuchat

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./

FROM base AS dev
RUN pip install -r requirements-dev.txt
COPY . .
RUN chown -R factuchat:factuchat /app
USER factuchat
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS prod
RUN pip install -r requirements.txt
COPY . .
RUN chown -R factuchat:factuchat /app
USER factuchat
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
