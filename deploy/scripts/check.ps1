# CI local (fase 1.6): ruff + mypy + pytest + pip-audit dentro del contenedor
# (Python 3.12 de producción) y npm audit sobre el frontend.
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
$compose = "$root\deploy\docker-compose.dev.yml"

Write-Host "== Levantando entorno de desarrollo =="
docker compose -f $compose up -d --build postgres redis api
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "== ruff =="
docker compose -f $compose exec -T api ruff check app tests
if ($LASTEXITCODE -ne 0) { exit 1 }
docker compose -f $compose exec -T api ruff format --check app tests
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "== mypy =="
docker compose -f $compose exec -T api mypy app
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "== pytest =="
docker compose -f $compose exec -T api pytest
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "== pip-audit =="
docker compose -f $compose exec -T api pip-audit -r requirements.txt --disable-pip --no-deps
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "== npm audit =="
Push-Location "$root\frontend"
npm audit --audit-level=high
$npmExit = $LASTEXITCODE
Pop-Location
if ($npmExit -ne 0) { exit 1 }

Write-Host "== TODO VERDE ==" -ForegroundColor Green
