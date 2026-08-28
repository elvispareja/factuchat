#!/usr/bin/env bash
# CI local (fase 1.6) — variante bash del check.ps1
set -euo pipefail
cd "$(dirname "$0")/../.."
COMPOSE="deploy/docker-compose.dev.yml"

echo "== Levantando entorno de desarrollo =="
docker compose -f "$COMPOSE" up -d --build postgres redis api

echo "== ruff =="
docker compose -f "$COMPOSE" exec -T api ruff check app tests
docker compose -f "$COMPOSE" exec -T api ruff format --check app tests

echo "== mypy =="
docker compose -f "$COMPOSE" exec -T api mypy app

echo "== pytest =="
docker compose -f "$COMPOSE" exec -T api pytest

echo "== pip-audit =="
docker compose -f "$COMPOSE" exec -T api pip-audit -r requirements.txt --disable-pip --no-deps

echo "== npm audit =="
npm --prefix frontend audit --audit-level=high

echo "== TODO VERDE =="
