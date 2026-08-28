# Prueba de punta a punta contra el ambiente PRUEBAS del SRI

Requisito del checklist F2. Necesita: el entorno dev levantado, un certificado
de firma **.p12 real** (de pruebas o vigente) y salida a internet hacia
`celcer.sri.gob.ec` (el backend solo permite ese host y `cel.sri.gob.ec`).

> El tenant debe crearse con el RUC REAL del titular del certificado. La subida
> del .p12 verifica que la identificación del certificado corresponda a ese RUC
> y lo rechaza si no coincide, así que el dato tiene que ser exacto.

## Qué se validó ya sin el SRI real

El motor está probado de punta a punta contra un SRI simulado (90 tests), con
la canonicalización, la estructura XAdES-BES y los formatos que exige la ficha
técnica verificados sobre el XML realmente emitido. Lo que SOLO puede confirmar
esta prueba es la aceptación del validador del SRI: firma, esquema y RUC.

## Pasos (PowerShell, desde la raíz del repo)

```powershell
$compose = "deploy/docker-compose.dev.yml"
docker compose -f $compose up -d

# 1. Crear tenant con el RUC real del certificado + usuario
docker compose -f $compose exec api python -m app.cli create-tenant `
  --ruc <RUC_REAL_13_DIGITOS> --razon-social "<RAZON SOCIAL EXACTA>" --email tu@correo.ec
# Crear un usuario CLIENTE para ese tenant (por ahora vía SQL/seed o el wizard de F4)

# 2. Login → token
$login = Invoke-RestMethod -Method POST http://localhost:8000/api/v1/auth/login `
  -ContentType "application/json" -Body '{"email":"...","password":"..."}'
$h = @{ Authorization = "Bearer $($login.access_token)" }

# 3. Subir el .p12 (queda cifrado AES-256-GCM en reposo)
curl.exe -s -X POST http://localhost:8000/api/v1/certificados `
  -H "Authorization: Bearer $($login.access_token)" `
  -F "archivo=@C:\ruta\a\firma.p12" -F "password=CLAVE_DEL_P12"

# 4. Crear establecimiento 001 (seed) y la factura borrador
$factura = Invoke-RestMethod -Method POST http://localhost:8000/api/v1/comprobantes/facturas `
  -Headers $h -ContentType "application/json" -Body '{
    "items":[{"codigo":"SRV1","descripcion":"Servicio de prueba","cantidad":"1",
              "precio_unitario":"1.00","codigo_iva":"4"}],
    "forma_pago":"01"}'

# 5. Emitir (confirmación explícita) — encola firma + envío al SRI
Invoke-RestMethod -Method POST "http://localhost:8000/api/v1/comprobantes/$($factura.id)/emitir" `
  -Headers $h -ContentType "application/json" -Body '{}'

# 6. Arrancar un worker Celery (consume la cola real)
docker compose -f $compose exec -d api celery -A app.worker.celery_app worker -l info

# 7. Polling hasta AUTORIZADO (igual que hará el frontend)
Invoke-RestMethod "http://localhost:8000/api/v1/comprobantes/$($factura.id)" -Headers $h
```

Resultado esperado: `estado = "AUTORIZADO"` con `numero_autorizacion`, y el RIDE
en `GET /api/v1/comprobantes/{id}/ride`. Si el SRI devuelve o rechaza, el campo
`mensajes` trae el motivo legible y `POST .../reintentar` genera documento nuevo.

Guardar la respuesta JSON final como evidencia del checklist F2.
