# Procedimiento de gestión de incidentes — Factuchat

Versión 1.0 · Fases 1–7 · Documento 5 de 7. Se actualiza después de cada incidente y al
cerrar la fase de despliegue.

Este procedimiento dice qué se hace cuando algo se rompe, cuando alguien entra donde no
debe o cuando se sospecha que un dato salió del sistema. Cubre la plataforma completa
—API, worker, base de datos, buzón SRI, WhatsApp, panel interno y panel de clientes— y
los datos personales que trata: los de los inquilinos, los de sus clientes finales y los
certificados de firma electrónica.

## 0. Lo que hoy falta para que este procedimiento sea ejecutable de punta a punta

Se escribe primero porque un procedimiento que promete lo que el sistema no hace es peor
que no tener procedimiento. Todo lo de esta tabla está pendiente al cerrar la fase 7.

| Pendiente | Consecuencia para la respuesta a incidentes | Dónde se ve |
|---|---|---|
| El despliegue en el VPS no se ha hecho | Nada de esto ha corrido nunca en producción. La primera aplicación real del procedimiento será también su primera prueba | pasos 1–10 al final de `PLAN.md` |
| El dominio definitivo no está confirmado (`APP_DOMAIN` vacío) | No hay dirección estable para avisos, ni certificado TLS, ni dirección de buzón. En producción el arranque falla sin `APP_DOMAIN` | `backend/app/core/config.py` (`sin_valores_inseguros_en_produccion`), `backend/.env.example` |
| No hay certificado `.p12` real cargado | El escenario más grave del catálogo (fuga de certificado) todavía no puede ocurrir, pero tampoco está probado con material real | `backend/app/services/certificados.py` |
| Faltan las credenciales de Meta (`WA_APP_SECRET`, `WA_ACCESS_TOKEN`, `WA_PHONE_NUMBER_ID`) | El canal de WhatsApp no existe todavía; tampoco sirve como vía de aviso a los inquilinos | `backend/.env.example`, `backend/app/whatsapp/firma.py` |
| Falta contratar el proveedor de correo entrante del buzón | Sin `BUZON_WEBHOOK_SECRET` ni `BUZON_IMAP_HOST` no entra ningún correo, y el módulo nace apagado | `deploy/scripts/buzon-sri-puesta-en-marcha.md` §3 |
| **No hay alertas activas** | Nadie es notificado automáticamente de nada. La detección depende hoy de que una persona mire | `SECURITY.md`, sección A09 (las dos únicas casillas ⚠️ del mapeo) |
| El respaldo está escrito, pero no puesto en operación | El procedimiento y sus scripts ya existen (`deploy/scripts/respaldo.sh`, `deploy/scripts/restaurar.sh`); lo que falta es instalar el cron, contratar el destino externo, generar el par de claves `age` y dejar documentada la primera prueba de restauración. Hasta entonces no hay ninguna copia que restaurar | [documento 4](procedimiento-respaldo-restauracion.md), paso 6 del despliegue en `PLAN.md` |
| No hay herramienta de recifrado de secretos | Rotar `CERT_ENC_KEY` o `BUZON_ENC_KEY` exige escribir antes el script; la CLI solo tiene `create-superadmin`, `create-tenant` y `seed-planes` | `backend/app/cli.py` |
| El plazo legal de notificación no está confirmado por asesoría legal | Ver la sección 7.3, que lo trata explícitamente como dato a ratificar | — |

## 1. Qué cuenta como incidente

Un **incidente de seguridad** es cualquier evento que comprometa la confidencialidad, la
integridad o la disponibilidad del servicio o de los datos que custodia.

Una **brecha de datos personales (LOPDP)** es un subconjunto: el incidente en el que
datos personales se pierden, se destruyen, se alteran o quedan expuestos a quien no
debía verlos. No toda caída es una brecha: que el SRI no responda dos horas es un
incidente de disponibilidad del servicio, no una vulneración de datos personales. La
distinción importa porque solo la segunda dispara la obligación de notificar.

Regla de oro: **la duda se resuelve escalando, no minimizando**. Un acceso cruzado entre
inquilinos que no se sabe si llegó a leer datos se trata como si los hubiera leído hasta
demostrar lo contrario con la bitácora.

## 2. Clasificación por gravedad

| Nivel | Criterio | Ejemplos concretos de este sistema |
|---|---|---|
| **G1 — Crítico** | Permite actuar en nombre de un contribuyente, o expone datos de varios inquilinos a la vez | Fuga (o sospecha) del archivo `.p12` de un cliente o de `CERT_ENC_KEY`; fuga de `SECRET_KEY`; compromiso del servidor o del rol `factuchat` de Postgres (superusuario, ignora RLS); fuga de `BUZON_ENC_KEY` con acceso al volumen de almacenamiento |
| **G2 — Alto** | Expone o altera datos de un inquilino, o rompe la integridad tributaria | Acceso cruzado entre inquilinos confirmado; robo de credenciales de un operador con rol SUPERADMIN o SOPORTE; fuga de `WA_APP_SECRET` o de `BUZON_WEBHOOK_SECRET` (permite inyectar retenciones falsas que bajan el IVA declarado); pérdida o corrupción de XML autorizados; base de datos caída |
| **G3 — Medio** | Degrada el servicio o retrasa obligaciones, sin exponer datos | Caída prolongada del SRI; comprobantes atascados que el barrido no rescata; buzón que deja de recibir; abuso del formulario público que supera el rate limit; presupuesto de WhatsApp desbordado |
| **G4 — Bajo** | Molestia acotada, un solo cliente, sin riesgo de datos | Un RIDE que no se envía por correo; un error aislado en Sentry; spam del formulario dentro de los límites |

**Por qué el `.p12` y `CERT_ENC_KEY` son el techo de la escala.** El `.p12` es la firma
electrónica del contribuyente. Quien lo tenga junto con su contraseña puede firmar
comprobantes tributarios a nombre de ese negocio, y esos documentos tienen valor legal
frente al SRI. `CERT_ENC_KEY` es la clave maestra AES-256-GCM que abre **todos** los
`.p12` guardados (`backend/app/sri/firma.py`, `descifrar_p12`), así que su fuga equivale
a la fuga simultánea de la firma de cada inquilino. Por eso el archivo y su contraseña se
cifran por separado con AAD distinto (`factuchat:p12` y `factuchat:p12-password`) y por
eso `BUZON_ENC_KEY` es una clave aparte: para que el radio de daño de la firma no se
extienda a los documentos fiscales del buzón.

**Por qué un webhook sin firma válida es G2 y no G3.** Una retención que entra por el
buzón baja el IVA que el cliente declara. El diseño ya lo contempla: una retención solo
cuenta cuando el SRI confirma que existe y está autorizada
(`backend/app/buzon/verificacion.py`). Pero quien pueda firmar el webhook puede inyectar
documentos autorizados ajenos y ensuciar la contabilidad de un inquilino, y eso es
integridad de datos fiscales.

## 3. Detección: lo que hay hoy y lo que no

### 3.1 Lo que existe y funciona

| Fuente | Qué ve | Dónde está |
|---|---|---|
| Sentry (API y worker) | Excepciones no manejadas, con `include_local_variables=False`, sin cuerpos de petición, sin PII y con un `before_send` que enmascara claves sensibles y cualquier valor binario | `backend/app/core/observabilidad.py`, `backend/app/main.py`, `backend/app/worker.py` |
| `audit_log` inmutable | Quién hizo qué, sobre qué tenant, antes/después en JSON, IP, user agent y `request_id`. Incluye logins, bloqueos, revocación de sesiones, impersonaciones, aperturas de ficha con motivo y cambios de precio | migración `0002_rls_y_funciones.py` (trigger `trg_audit_log_inmutable` + sin GRANT de UPDATE/DELETE), `backend/app/core/audit.py`, `backend/app/db/models/admin.py` |
| Consulta de la bitácora | Panel interno → Auditoría, por función segura `sa_auditoria(limite, tenant, accion)` que verifica el rol real en la base | migración `0005_superadmin.py`, `backend/app/api/routes/superadmin.py` (`/auditoria`) |
| Logs de nginx en JSON | Hora, IP, método, URI, estado, bytes, referer, user agent y tiempo de respuesta | `deploy/nginx/nginx.conf` (`log_format json_log`) |
| Healthchecks de Compose | `pg_isready` en PostgreSQL y `redis-cli ping` en Redis, cada 10 s | `deploy/docker-compose.prod.yml` |
| Barrido de atascados | Cada 10 minutos reencola comprobantes detenidos más de 45 minutos en `FIRMADO` o `ENVIADO_SRI`, dejando un `WARNING` por cada uno | `backend/app/tasks/emision.py` (`barrer_atascados`, `MINUTOS_ATASCADO`) |
| Circuit breaker del SRI | Tras 5 fallos en 120 s abre el circuito 60 s, por servicio y ambiente | `backend/app/sri/client.py` |
| Panel del buzón | Estado de parseo por correo con su motivo de error, y banda de inquilinos que llevan días sin recibir nada | `backend/app/api/routes/buzon.py`, `sa_buzones_callados` en migración `0009` |

### 3.2 Los huecos, dichos con todas sus letras

- **No hay alertas activas.** `SECURITY.md` (A09) ya declara las dos casillas abiertas:
  la proyección del presupuesto de WhatsApp se calcula y se muestra, pero nadie recibe
  aviso; y los rechazos del SRI en ráfaga quedan en la bitácora y en el estado de cada
  comprobante, sin regla que los agrupe. Tampoco hay aviso por logins fallidos repetidos
  ni por uso de impersonación, aunque ambos sí quedan registrados.
- **El endpoint `/api/v1/health` responde `{"status": "ok"}` y nada más**
  (`backend/app/api/routes/health.py`): no comprueba la base ni Redis, así que un
  monitor externo que lo consulte confirma que el proceso vive, no que el sistema sirva.
  El `healthcheck` de `api` en el compose de producción consulta precisamente ese
  endpoint, así que una caída de PostgreSQL deja a `api` marcado como sano. El único
  servicio sin `healthcheck` es `beat`; `nginx`, `api`, `worker`, `postgres` y `redis`
  sí lo tienen.
- **El frontend no reporta a Sentry.** No hay ninguna referencia al SDK en
  `frontend/src` ni en `frontend/package.json`, aunque `PLAN.md` lo pedía. Un error que
  solo ocurre en el navegador del cliente hoy solo se sabe si el cliente lo cuenta.
- **`request_id` no cruza con nginx.** Se genera por petición
  (`backend/app/core/context.py`) y se guarda en cada fila de `audit_log`, lo que permite
  agrupar todas las escrituras de una misma petición; pero no se devuelve al cliente ni
  se escribe en el log de nginx, así que la correlación entre bitácora y log del
  servidor se hace por hora e IP.

**Consecuencia operativa mientras esto siga así:** la detección es humana. Hasta que
existan las alertas del paso 7 del despliegue, el turno de guardia revisa **cada día
laborable**: Sentry (errores nuevos), panel interno → Comprobantes (cola y rechazos),
panel interno → Auditoría (logins fallidos, impersonaciones, cambios de configuración),
panel interno → WhatsApp (consumo contra presupuesto) y, con el buzón encendido, la
columna de parseo y la banda de buzones callados. Esa revisión diaria es parte de este
procedimiento, no una buena costumbre opcional.

## 4. Quién responde y quién decide

El equipo es pequeño; los roles son funciones, no personas distintas.

| Función | Quién la asume | Qué decide |
|---|---|---|
| Coordinador del incidente | El operador con rol SUPERADMIN de turno | Declara el incidente, fija la gravedad, decide contención y corta el servicio si hace falta |
| Apoyo técnico | Quien tenga acceso al VPS y al `.env` | Ejecuta contención y rotación de secretos; nunca improvisa cambios sin dejarlos escritos |
| Comunicación | El coordinador, salvo delegación explícita | Redacta los avisos a inquilinos afectados |
| Decisión legal | El titular del servicio, con asesoría legal externa | Decide si el incidente es una brecha notificable y firma la notificación a la autoridad |

Solo el rol SUPERADMIN puede tocar configuración crítica; SOPORTE actúa sobre inquilinos
(suspender, impersonar con motivo) y LECTURA solo mira. El reparto completo está en
[matriz-roles-accesos.md](matriz-roles-accesos.md) y se aplica en servidor, no en el
panel.

**Hueco a cerrar en el despliegue:** hoy no hay suplente. Con un único SUPERADMIN, si esa
persona no está disponible nadie puede alternar el flag del buzón, cambiar precios ni
crear otro administrador interno. Crear un segundo SUPERADMIN con 2FA propio es parte de
la puesta en producción.

## 5. Ciclo de respuesta

### 5.1 Registrar la hora de conocimiento

Lo primero que se escribe, antes de tocar nada: **fecha y hora en que el equipo supo del
problema**, y cómo se supo. Todos los plazos legales cuentan desde ahí, no desde que se
resuelve. Esa marca abre la ficha del incidente (sección 8).

### 5.2 Contención

Acciones reales disponibles hoy, con su efecto exacto:

| Acción | Cómo se hace | Qué corta de verdad |
|---|---|---|
| Cortar todas las sesiones activas | Rotar `SECRET_KEY` y reiniciar api/worker | Invalida al instante todo token de acceso y de impersonación (JWT HS256). **No** invalida los refresh, que son opacos y se guardan solo como SHA-256 (`backend/app/core/security.py`): el panel renovaría sesión sin más |
| Revocar las sesiones de un usuario | `SELECT auth_revoke_all_sessions(:uid, :motivo, :ip, :ua)` con la conexión de la app | Marca todos sus refresh como revocados y lo deja escrito en `audit_log`. El token de acceso ya emitido sigue valiendo hasta 30 minutos |
| Desactivar una cuenta | `UPDATE users SET is_active = false` con la conexión de administración | Impide login y renovación (`auth_get_user_for_login`, `auth_get_session` devuelven `is_active`), pero no mata el token vigente |
| Suspender un inquilino | Panel interno → cliente → estado, que llama a `sa_cambiar_estado_tenant` (SOPORTE o superior, con motivo, auditado) | Cambia el estado y lo audita con antes/después. **Ojo:** solo el estado `BAJA` bloquea el login; con `SUSPENDIDO` el usuario sigue entrando (`backend/app/services/auth.py`) |
| Apagar el buzón SRI | Panel interno → Buzón SRI → apagar el módulo (solo SUPERADMIN, queda auditado) | Deja de sumar crédito a nadie: el flag se evalúa también donde se calcula el saldo, no solo en el router (`backend/app/services/retenciones.py`) |
| Cerrar el webhook de WhatsApp | Quitar el `location /api/v1/whatsapp/webhook` de `deploy/nginx/templates/factuchat.conf.template` y recargar nginx; o vaciar `WA_ACCESS_TOKEN` **y** `WA_APP_SECRET` a la vez en el `.env` y reiniciar | Por nginx, la ruta deja de servirse sin tocar el arranque de la API. Por `.env`, el webhook rechaza todo: sin secreto no verifica y nunca falla abierto (`backend/app/whatsapp/firma.py`). **Ojo:** vaciar solo `WA_APP_SECRET` dejando `WA_ACCESS_TOKEN` puesto impide arrancar `api`, `worker` y `beat` en producción (`backend/app/core/config.py`, `sin_valores_inseguros_en_produccion`) |
| Cerrar el webhook del buzón | Apagar el módulo desde el panel interno (fila «Apagar el buzón SRI»). Si aun así hay que cortarlo por configuración, poner `BUZON_ACTIVO=false` y vaciar `BUZON_WEBHOOK_SECRET` en la **misma pasada** del `.env`, y reiniciar | Apagar el flag desde el panel no exige reinicio y queda auditado. Sin secreto, el endpoint devuelve 403 mudo a cualquier entrega (`backend/app/api/routes/buzon.py`); pero vaciarlo con `BUZON_ACTIVO=true` y sin `BUZON_IMAP_HOST` impide el arranque de `api`, `worker` y `beat` en producción (`backend/app/core/config.py`), y convierte una contención acotada al buzón en una caída total |
| Parar la emisión | Detener el contenedor `worker` | Los comprobantes quedan en su estado; al volver, el barrido rescata los detenidos y consultar autorización es idempotente |
| Sacar el sitio de línea | Detener `nginx` | Nada entra. Es la contención de último recurso para un G1 |

**Preservar evidencia antes de arreglar.** `audit_log` no se puede alterar —ni por la
aplicación ni por el personal interno: no hay GRANT de UPDATE/DELETE y un trigger lo
impide (`tests/test_rls.py::test_audit_log_es_inmutable`)—, pero los logs de nginx, los
archivos del volumen `factuchat_comprobantes` (`/var/factuchat/storage` dentro de los
contenedores) y el estado de Redis sí se pierden al reiniciar o al rotar.
Antes de tocar contenedores: copiar los logs de nginx del periodo, anotar los
identificadores de los comprobantes y correos implicados, y exportar de la bitácora el
rango de horas relevante.

### 5.3 Erradicación

1. Determinar el alcance con la bitácora: qué actor, qué tenants, qué tablas, en qué
   ventana de tiempo. `sa_auditoria` filtra por tenant y por acción.
2. Rotar los secretos que hayan quedado expuestos, siguiendo la sección 6 al pie de la
   letra: rotar mal deja el sistema peor que la fuga.
3. Corregir la causa en el código o en la configuración, con su prueba (sección 8).
4. Si hubo acceso a datos de un inquilino por parte de personal interno sin motivo
   válido, revisar además las impersonaciones abiertas y cerrarlas
   (`backend/app/services/impersonacion.py`, `caducadas_sin_cerrar`).

### 5.4 Recuperación

- Restaurar desde respaldo cuando aplique, con
  `AGE_IDENTIDAD=/media/usb/factuchat-respaldos.key ./restaurar.sh /var/backups/factuchat/copias/<marca>`
  y la identidad `age` que se custodia fuera del VPS; el procedimiento completo está en el
  [documento 4](procedimiento-respaldo-restauracion.md). **Mientras el cron, el destino
  externo y el par de claves `age` no estén dados de alta no hay copias que restaurar**,
  así que hoy la recuperación se limita a reconstruir el entorno desde el repositorio y
  la base viva.
- Reanudar la emisión: al volver el worker, el barrido reencola lo atascado; el pipeline
  pregunta al SRI si ya tiene el comprobante antes de reenviar, así que no se duplican
  facturas (`backend/app/tasks/emision.py`, `_sri_no_lo_tiene`).
- Verificar el aislamiento antes de declarar el cierre: correr la suite de
  `backend/tests` completa, y en particular `test_rls.py` (acceso cruzado por API y por
  SQL directo) y `test_certificados.py::test_cifrado_en_reposo`.
- Declarar el fin del incidente solo cuando: la causa está corregida, los secretos
  expuestos están rotados, los afectados están avisados y las pruebas pasan.

## 6. Rotación de secretos

Todos los secretos viven en un único `.env` fuera del repositorio, con permisos 600 y
propiedad de root en el servidor (`PLAN.md`, paso 5 del despliegue; plantilla sin
secretos en `backend/.env.example`). `PLAN.md` fija además rotación semestral
documentada: ese calendario arranca el día del despliegue.

**Regla que vale para todas:** el `.env` no puede viajar en el mismo respaldo que el
volcado de la base. Si `CERT_ENC_KEY` y `certificados` caen juntos, el cifrado en reposo
no protege nada.

Resumen de qué se rompe al rotar cada uno:

| Secreto | Qué protege | Qué se rompe si se rota sin más |
|---|---|---|
| `SECRET_KEY` | Firma de los JWT de acceso, impersonación y alta de 2FA | Todas las sesiones abiertas caen; los refresh sobreviven |
| `CERT_ENC_KEY` | `.p12` y su contraseña | **Nadie puede emitir**: cada intento sale como comprobante RECHAZADO |
| `BUZON_ENC_KEY` | Correos y XML del buzón, cifrados en disco | El visor de XML crudo deja de abrir; el crédito tributario ya calculado no se pierde |
| `TOTP_ENC_KEY` | Secretos TOTP de 2FA | El personal interno se queda fuera del panel |
| `WA_APP_SECRET` | Firma del webhook de Meta | Se rechazan los mensajes entrantes mientras no coincida |
| `BUZON_WEBHOOK_SECRET` | Firma del webhook de correo | Se rechazan los correos entrantes mientras no coincida |
| Contraseñas de PostgreSQL | Conexión de la app y de administración | La API no conecta; migraciones, CLI y barrido de atascados fallan |
| `REDIS_PASSWORD` | Cola de Celery, candados por comprobante y circuit breaker del SRI | Los procesos que no se reinicien a la vez dejan de encolar: `REDIS_URL` lleva la contraseña embebida |

### 6.1 `SECRET_KEY`

Firma los JWT HS256: acceso (30 min), impersonación (30 min) y el token de alta de 2FA
(10 min) — `backend/app/core/security.py`, `backend/app/services/impersonacion.py`.

- **Se rompe:** todo token de acceso vigente deja de validar y la API responde 401
  «Sesión inválida o expirada» (`backend/app/api/deps.py`). Los clientes con el panel
  abierto renuevan con su refresh y siguen sin darse cuenta, porque los refresh son
  cadenas opacas de 256 bits guardadas solo como SHA-256: **no dependen de esta clave**.
  Las sesiones de impersonación abiertas mueren en el acto.
- **Si se rota por robo**, rotar no basta: hay que revocar también los refresh de los
  usuarios afectados con `auth_revoke_all_sessions`, que además deja el motivo en la
  bitácora. No existe un comando masivo; hacerlo por SQL directo con la conexión de
  administración funciona, pero **no se audita solo** (los listeners de auditoría son de
  la capa ORM), así que esa acción se anota a mano en la ficha del incidente.
- **Procedimiento:** generar con
  `python -c "import secrets; print(secrets.token_urlsafe(64))"`, sustituir en `.env`,
  reiniciar `api`, `worker` y `beat`. En producción la configuración rechaza el arranque
  si mide menos de 32 caracteres o empieza por `dev-`.

### 6.2 `CERT_ENC_KEY` — la más delicada

Cifra en AES-256-GCM el archivo `.p12` y su contraseña, por separado y con AAD distinto
(`backend/app/services/certificados.py`, `backend/app/sri/firma.py`).

- **Se rompe:** si se cambia la clave sin recifrar, `descifrar_p12` falla en cada firma.
  El pipeline no deja el comprobante colgado: lo pasa a **RECHAZADO** con el mensaje «No
  se pudo abrir el certificado de firma. Vuelva a cargarlo desde Mi cuenta»
  (`backend/app/tasks/emision.py`, `_paso_firmar`). Es decir, **todos los inquilinos
  dejan de poder facturar y reciben un mensaje que los manda a resubir su certificado**.
  Un comprobante rechazado no se «arregla» después: el reintento genera un documento
  nuevo con clave de acceso nueva.
- **No hay herramienta de recifrado.** `backend/app/cli.py` solo tiene
  `create-superadmin`, `create-tenant` y `seed-planes`. Antes de rotar hay que escribir
  el comando de recifrado y probarlo contra una copia.
- **Procedimiento correcto:**
  1. Parar `worker` y `beat` (nadie debe firmar mientras se recifra).
  2. Con las dos claves cargadas en memoria del proceso —la vieja y la nueva— recorrer
     `certificados`, descifrar `p12_data_enc` y `p12_password_enc` con la vieja y volver
     a cifrarlos con la nueva, respetando los mismos AAD.
  3. Escribir la nueva clave en `.env`, reiniciar `api`, `worker` y `beat`.
  4. Emitir una factura de prueba contra el ambiente PRUEBAS del SRI siguiendo
     `deploy/scripts/emision-prueba-sri.md` antes de dar por buena la rotación.
- **Si la clave vieja se perdió**, los `.p12` guardados son irrecuperables: hay que pedir
  a cada inquilino que vuelva a subir su certificado con su contraseña —él la tiene—, y
  `guardar_certificado` reemplaza el anterior. Mientras tanto, ese inquilino no factura.
- **Si la clave se filtró**, rotarla no deshace la fuga: los `.p12` que el atacante ya
  descifró siguen sirviendo. Además de rotar hay que avisar a cada inquilino para que
  **revoque su certificado ante su entidad certificadora** y cargue uno nuevo. Esto es
  G1 y notificable (sección 7).

### 6.3 `BUZON_ENC_KEY`

Cifra el mensaje MIME crudo y el XML extraído, guardados en disco como
`/var/factuchat/storage/buzon/{tenant_id}/{uuid}.eml.enc` con AAD
`factuchat/buzon/correo` (`backend/app/buzon/ingesta.py`). Esa ruta es el punto de
montaje del volumen `factuchat_comprobantes` dentro de `api` y `worker` (`STORAGE_DIR`
en `deploy/docker-compose.prod.yml`), no un directorio del host: para mirar ahí durante
un incidente se entra con `docker run --rm -v factuchat_comprobantes:/datos:ro ...`.

- **Se rompe:** el visor de XML crudo del panel interno deja de abrir los correos
  antiguos. Lo que **no** se pierde es el crédito tributario ya calculado: las retenciones
  viven en columnas normales de `retenciones_recibidas`, protegidas por RLS, no dentro
  del blob. Sí se pierde la posibilidad de aplicar retroactivamente la validación de
  firma XAdES que queda anotada como mejora pendiente del módulo
  (`deploy/scripts/buzon-sri-puesta-en-marcha.md` §9).
- **Procedimiento:** apagar el flag `BUZON_ACTIVO` desde el panel, recifrar los archivos
  del volumen con las dos claves (mismo trabajo pendiente que el punto anterior: no hay
  comando), cambiar la clave en `.env`, reiniciar y volver a encender el flag. En
  producción, encender el buzón sin esta clave es un error de arranque.

### 6.4 `TOTP_ENC_KEY`

Cifra `users.totp_secret_enc` en AES-256-GCM, sin AAD
(`backend/app/core/security.py`).

- **Se rompe:** `decrypt_totp_secret` falla en el login de cualquier cuenta con 2FA
  activo. Como el 2FA es **obligatorio para SUPERADMIN**, el equipo interno se queda
  fuera del panel: es un auto-bloqueo total, y encima ocurre en el peor momento posible
  si se rota durante un incidente.
- **Recuperación si ya pasó:** con la conexión de administración,
  `UPDATE users SET totp_enabled = false, totp_secret_enc = NULL WHERE ...`. En el
  siguiente login, un SUPERADMIN sin 2FA recibe un token de alta de 10 minutos
  (`TotpSetupRequired`) y vuelve a enrolar su aplicación. Esa escritura por SQL directo
  no queda auditada sola: se anota en la ficha del incidente.
- **Procedimiento limpio:** recifrar los secretos con las dos claves, o —dado que son
  pocos usuarios internos— reenrolar a todos de forma coordinada, uno por uno, dejando
  siempre una cuenta con acceso confirmado antes de tocar la siguiente.

### 6.5 `WA_APP_SECRET`, `WA_ACCESS_TOKEN`, `WA_VERIFY_TOKEN`

- `WA_APP_SECRET` no lo generamos nosotros: se regenera en la consola de Meta for
  Developers. Entre que se regenera allí y se actualiza el `.env` con reinicio, **todo
  webhook entrante se rechaza** con firma inválida y esos mensajes de clientes dependen
  de la política de reintentos de Meta. Ventana corta y avisada, nunca en hora pico.
- `WA_ACCESS_TOKEN` permite enviar mensajes con cargo a nuestra cuenta: si se filtra, se
  rota de inmediato (es también un incidente de costo, no solo de seguridad).
- `WA_VERIFY_TOKEN` solo interviene en el alta de la suscripción del webhook.
- En producción la configuración exige `WA_APP_SECRET` si hay `WA_ACCESS_TOKEN`: no se
  puede dejar el canal abierto sin verificación de firma.

### 6.6 `BUZON_WEBHOOK_SECRET` / credenciales IMAP

Se cambia **a la vez** en el proveedor de correo y en el `.env`. Mientras no coincidan,
el endpoint responde 403 mudo y los correos entrantes se pierden salvo que el proveedor
reintente. La recolección por IMAP **no está implementada**: de ella solo existen las
variables de configuración reservadas (`buzon_imap_*` en `backend/app/core/config.py`),
así que hoy no hay ninguna `BUZON_IMAP_PASSWORD` que rotar, y el webhook firmado es la
única vía de entrada.

### 6.7 Contraseñas de PostgreSQL

Hay dos roles con login (`deploy/postgres/init/01-roles.sh`,
[matriz-roles-accesos.md](matriz-roles-accesos.md)):

| Rol | Variable | Quién lo usa |
|---|---|---|
| `factuchat_app` | `DATABASE_URL` (`APP_DB_PASSWORD` al inicializar) | La API y el worker. Sin BYPASSRLS: siempre sujeto a RLS |
| `factuchat` (superusuario) | `DATABASE_URL_ADMIN` (`POSTGRES_PASSWORD`) | Alembic, la CLI y el barrido global de comprobantes atascados |

- **Trampa a evitar:** `01-roles.sh` solo corre la **primera vez** que se inicializa el
  cluster. Editar ese archivo o cambiar `APP_DB_PASSWORD`/`POSTGRES_PASSWORD` en el
  `.env` **no cambia nada** en una base ya existente. La rotación real es
  `ALTER ROLE ... WITH PASSWORD ...` ejecutado en la base, y después actualizar el `.env`.
- **Se rompe si se hace a medias:** con `DATABASE_URL` desfasada la API no conecta y el
  sitio cae entero. Con `DATABASE_URL_ADMIN` desfasada el daño es más silencioso: fallan
  las migraciones, la CLI y `barrer_atascados`, que abre su propio engine con esa
  conexión (`backend/app/tasks/emision.py`, `_buscar_atascados`) — o sea, los
  comprobantes a medio camino dejan de rescatarse cada 10 minutos sin que nadie lo note.
- **Orden seguro:** `ALTER ROLE` → actualizar `.env` → reiniciar `api`, `worker` y
  `beat` → confirmar con una emisión de prueba y con una corrida del barrido.
- Rotar estas contraseñas no invalida sesiones de usuario ni afecta a RLS.
- **`REDIS_PASSWORD` se rota como estas** (`deploy/docker-compose.prod.yml`): Redis
  arranca con `--requirepass` y la variable es obligatoria —el `:?` aborta el arranque si
  falta—, además de no publicar puerto y vivir solo en la red interna de Docker. Protege
  la cola de Celery, los candados por comprobante y el circuit breaker del SRI. Se rota
  cambiando el valor en el `.env` y reiniciando `redis`, `api`, `worker` y `beat` **a la
  vez**: `REDIS_URL` la lleva embebida, así que un reinicio parcial deja a la mitad de los
  procesos sin poder encolar.

## 7. Notificación

### 7.1 Interna

El coordinador avisa al titular del servicio en cuanto declara un G1 o G2, por el canal
más rápido disponible. No se espera a tener el diagnóstico completo: se avisa con lo que
se sabe y se actualiza.

### 7.2 A los inquilinos afectados

Se avisa a **cada inquilino cuyos datos, certificado o comprobantes estén implicados**,
por correo y por WhatsApp cuando el canal esté operativo. El aviso dice, en lenguaje
claro:

1. Qué pasó y cuándo se detectó.
2. Qué datos suyos están implicados (y cuáles no).
3. Qué hemos hecho ya.
4. **Qué tiene que hacer él**: en fuga de certificado, revocarlo ante su entidad
   certificadora y subir uno nuevo; en compromiso de credenciales, cambiar contraseña; en
   retenciones falsas, revisar su declaración antes de presentarla.
5. A quién escribir para preguntar.

No se minimiza ni se adorna. Un inquilino que se entera tarde de que su firma electrónica
estuvo expuesta tiene un problema legal, no un disgusto.

### 7.3 A la autoridad de protección de datos

> **PLAZO A RATIFICAR CON ASESORÍA LEGAL.** No es un dato verificable desde este
> repositorio y no se inventa aquí. La referencia que manejamos, consultada en fuentes
> públicas el 25 de agosto de 2026, es el **artículo 43 de la Ley Orgánica de Protección
> de Datos Personales**: notificación a la autoridad de protección de datos (hoy la
> Superintendencia de Protección de Datos Personales) **dentro de cinco (5) días**;
> comunicación al titular afectado **dentro de tres (3) días** cuando la vulneración
> suponga riesgo para sus derechos y libertades; y del encargado al responsable, **dos
> (2) días**. Antes de dar esta versión por vigente hay que contrastarlo con el texto
> legal, su reglamento general y las resoluciones de procedimiento de la
> Superintendencia, y dejar constancia de esa revisión en el pie del documento.

Reglas que sí sostenemos desde ya, sea cual sea el número final de días:

- **El reloj corre desde que se conoce la vulneración**, no desde que se resuelve. Por
  eso la sección 5.1 pone la hora de conocimiento como primer campo de la ficha.
- **Meta interna: preparar la notificación dentro de las primeras 48 horas.** Trabajar
  contra el plazo legal completo es cómo se llega tarde.
- Se notifica cuando la vulneración pueda suponer un riesgo para los derechos y
  libertades de las personas. La decisión de notificar la toma el titular del servicio
  con asesoría legal, y **se documenta también cuando se decide no notificar**, con su
  razón: esa constancia es lo que se muestra si la autoridad pregunta.
- **Quién notifica depende de qué datos son.** Sobre los datos de los inquilinos y de
  los visitantes de la web, Factuchat actúa como responsable del tratamiento y notifica
  directamente. Sobre los datos de los **clientes finales** que cada inquilino carga en
  el sistema (nombres, cédulas, direcciones, correos), lo previsible es que el
  responsable sea el inquilino y Factuchat el encargado: en ese caso nuestra obligación
  principal es avisar al inquilino para que él notifique. **Este reparto debe quedar
  ratificado por asesoría legal y escrito en el documento 6** (registro de tratamiento de
  datos personales), porque cambia a quién hay que avisar y en qué plazo.
- Contenido que se prepara para la notificación, a ajustar al formato que exija la
  autoridad: naturaleza de la vulneración, categorías y número aproximado de titulares y
  de registros afectados, consecuencias probables, medidas adoptadas y propuestas, y
  punto de contacto.

## 8. Registro del incidente y lección aprendida

### 8.1 La ficha

Cada incidente de gravedad G1, G2 o G3 deja una ficha. Como en la base no existe ninguna
tabla de incidentes —y meterla ahí obligaría a decidir de qué tenant es—, la ficha vive
como archivo versionado en el repositorio, en `docs/incidentes/AAAA-MM-DD-descripcion.md`
(la carpeta se crea con el primer incidente). Dentro **no se copian datos personales**:
se citan identificadores (UUID de tenant, clave de acceso, id de fila de `audit_log`),
nunca nombres, cédulas ni contenidos.

Campos:

| Campo | Qué se anota |
|---|---|
| Identificador y título | `2026-08-25-webhook-buzon`, por ejemplo |
| Hora de conocimiento | Fecha y hora exactas, y cómo se supo |
| Gravedad | G1–G4, y si cambió durante la respuesta |
| Alcance | Sistemas, tablas y tenants implicados; volumen aproximado de registros |
| Cronología | Cada acción con su hora: contención, rotaciones, reinicios, avisos |
| Secretos rotados | Cuáles, cuándo, y si hubo recifrado |
| Acciones no auditadas automáticamente | Todo lo hecho por SQL directo con la conexión de administración |
| ¿Brecha LOPDP? | Sí/no, con la razón; si sí, a quién se notificó y cuándo; si no, por qué |
| Causa raíz | Sin culpables: qué lo permitió |
| Lección y compromisos | Cambios concretos con responsable y fecha |

`audit_log` no se toca: es la fuente, no el cuaderno. La ficha la cita por identificadores
y horas.

### 8.2 La lección tiene que terminar en código

Regla de la casa, que ya es como se construyó este sistema: **todo incidente con causa en
el código deja una prueba que falla antes del arreglo y pasa después**. Hay precedente
verificable: el fallo de la fase 5 en que `tenant_por_telefono` nunca resolvía desde el
worker —que en producción habría rechazado todo mensaje legítimo de WhatsApp— se cerró con
`sys_tenant_por_telefono` en la migración `0009` y con
`tests/test_whatsapp.py::test_un_numero_conocido_si_se_resuelve_desde_el_worker`. Lo mismo
con las defensas del buzón: cada una tiene su caso en `tests/test_buzon.py`.

Y si el incidente cambia o añade un control, se actualiza `SECURITY.md` en la misma
entrega: es el índice de qué existe de verdad y dónde.

### 8.3 Cierre

A los 30 días del cierre, el coordinador revisa que los compromisos de la ficha estén
hechos. Los que no, se replanifican con fecha nueva y queda escrito por qué. Un
compromiso que se arrastra dos revisiones se sube a la reunión de decisión del producto.

## 9. Escenarios previstos

### 9.1 Fuga de un `.p12` o de `CERT_ENC_KEY` — G1

**Cómo se detectaría hoy:** por señal externa (un cliente que ve comprobantes que no
emitió, un aviso de su entidad certificadora) o por la bitácora, si hubo acceso interno a
la ficha o al certificado. No hay alerta automática.
**Contención:** sacar el sitio de línea si el vector sigue abierto; parar el worker para
que nada se firme.
**Erradicación:** rotar `CERT_ENC_KEY` con recifrado (6.2); si la fuga es de un `.p12`
concreto, pedir su revocación ante la entidad certificadora y cargar el nuevo.
**Recuperación:** emisión de prueba en ambiente PRUEBAS antes de reabrir.
**¿Brecha LOPDP?** Sí. El certificado identifica a una persona y permite actuar por ella.

### 9.2 Acceso cruzado entre inquilinos — G2

**Cómo se detectaría hoy:** por reporte de un cliente, por una excepción en Sentry o al
revisar la bitácora. Las pruebas de `test_rls.py` cubren el acceso cruzado por API y por
SQL directo, así que un cruce en producción significa una ruta nueva sin `require_roles`,
una consulta que use la conexión de administración donde no debe, o un fallo de política
RLS.
**Contención:** deshabilitar la ruta implicada o parar la API; si el vector es una
impersonación, cerrarla y revocar las sesiones del operador.
**Erradicación:** corregir con la prueba que reproduce el cruce; revisar si algún módulo
usa `DATABASE_URL_ADMIN` para leer o escribir datos de un tenant (esa conexión ignora RLS
incluso con FORCE, y por eso el barrido de atascados solo devuelve identificadores).
**¿Brecha LOPDP?** Sí, si se confirma que se leyeron datos de otro inquilino. La bitácora
es la que fija el alcance.

### 9.3 Caída del SRI — G3

**Cómo se detecta hoy:** el circuito se abre tras 5 fallos en 120 s y los comprobantes se
quedan en cola; se ve en el panel interno → Comprobantes. Sin alerta activa.
**Qué NO se hace:** interpretar el silencio del SRI como permiso. Un SRI caído no
autoriza nada, y una retención sin confirmar no baja el IVA de nadie.
**Contención y recuperación:** dejar que los reintentos con backoff hagan su trabajo;
avisar a los inquilinos si la caída coincide con fecha de declaración; al volver, el
barrido reencola lo detenido y no se duplica ninguna factura.
**¿Brecha LOPDP?** No. Es disponibilidad, y se registra como incidente operativo.

### 9.4 Comprobantes atascados — G3

**Cómo se detecta hoy:** por los `WARNING` del barrido en el log del worker y por la cola
del panel interno. Sin alerta activa.
**Contención:** si el barrido no los rescata en dos vueltas (20 minutos), revisar si el
problema es la firma (certificado caducado o ilegible), el canal (403/404/429/HTML del
SRI, que nunca se interpretan como veredicto) o Redis.
**Erradicación:** corregir la causa; si fue una rotación mal hecha de `CERT_ENC_KEY`, ir
a 6.2.
**Ojo:** un comprobante que llegó a RECHAZADO no se recupera reintentando el mismo; el
reintento crea un documento nuevo con clave nueva. Al cliente hay que decírselo.
**¿Brecha LOPDP?** No, salvo que se pierdan XML autorizados, que sí es integridad de
datos con valor tributario.

### 9.5 Abuso del formulario público — G3

**Cómo se detecta hoy:** por los 429 en el log JSON de nginx y por solicitudes basura en
el panel interno. El límite es de 5 envíos por IP cada 15 minutos por acción, en Redis
(`backend/app/api/routes/publico.py`), más el `limit_req` global de nginx.
**Contención:** bloquear la IP o el rango en nginx; si el abuso es de subida de
comprobantes, recordar que el tipo MIME y el tope de 5 MB ya se validan y que el nombre
del archivo lo pone el servidor.
**Erradicación:** endurecer el límite o añadir verificación adicional si el patrón se
repite; revisar que ningún pedido basura haya generado un alta real.
**¿Brecha LOPDP?** No por sí mismo. Sí lo sería si el abuso llegara a leer solicitudes
ajenas, cosa que impiden las políticas de `solicitudes_contacto` (migración `0007`):
cualquiera puede INSERTAR, pero el SELECT está reservado al personal interno.

---

**Revisión:** este documento se revisa al desplegar en producción (para incorporar
respaldos, alertas y datos de contacto reales), tras cada incidente G1 o G2, y al menos
una vez al año.
