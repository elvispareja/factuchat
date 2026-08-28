# Política de seguridad de la información — Factuchat

Versión 1.0 · Documento 1 de 7 · Fases 1–7, antes del despliegue · Revisar al desplegar y al cerrar cada fase.

## Por qué esta política es exigente

Factuchat no guarda solo datos de sus clientes: custodia **certificados de firma electrónica (.p12) de terceros y sus contraseñas**, y **documentos tributarios** que ya tienen valor ante el SRI. Quien obtenga un `.p12` puede firmar a nombre del negocio dueño de ese certificado; quien altere un XML de retención le cambia a un contribuyente el impuesto que declara. Por eso los controles de aquí abajo no son buenas intenciones: están puestos en la base de datos y en el código, y hay pruebas que los verifican.

## Alcance

**Sistemas:** API FastAPI, worker y beat de Celery, PostgreSQL 16, Redis, nginx y el panel React, tal como los levanta `deploy/docker-compose.prod.yml`; el repositorio y sus migraciones (`backend/alembic/versions/`); el único archivo `.env` de cada entorno.

**Datos:** certificados `.p12` y sus contraseñas; XML firmados, autorizados y RIDE (volumen `comprobantes`); datos personales de clientes finales (RUC/cédula, nombre, correo); correos y retenciones del buzón SRI; conversaciones de WhatsApp; credenciales, sesiones y secretos TOTP; la bitácora `audit_log`.

**Fuera del alcance:** la infraestructura del SRI y de Meta, y los equipos de los inquilinos.

## Responsable

Responsable de la seguridad de la información: **Libio Elvis Pareja Paredes**, titular del servicio (figura como tal en `backend/app/core/config.py`, `cobro_titular`). La operación diaria la ejecuta el personal interno con los roles `SUPERADMIN`, `SOPORTE` y `LECTURA` definidos en [matriz-roles-accesos.md](matriz-roles-accesos.md); fuera de esos roles nadie tiene acceso a datos de inquilinos.

## Principios que el sistema ya aplica

| Principio | Qué significa aquí y por qué | Dónde está |
|---|---|---|
| **Mínimo privilegio en la base** | Tres roles de Postgres separados por función. La aplicación se conecta como `factuchat_app`, creado **NOBYPASSRLS**: aunque un fallo de código llegara a ejecutar SQL arbitrario, ese rol no puede apagar RLS ni leer otro inquilino. El propietario `factuchat` corre migraciones, la CLI administrativa y dos barridos globales del worker (`_buscar_atascados` y `_buzones_callados`), que por definición no actúan en nombre de ningún inquilino y solo devuelven identificadores; nunca la API. Riesgo residual asumido: esa credencial con BYPASSRLS vive dentro del contenedor del worker, que además procesa XML de terceros. `factuchat_security` es **NOLOGIN**: existe solo para ser dueño de las funciones `auth_*`, `sa_*` y `sys_*`, así que su BYPASSRLS únicamente se ejerce dentro de código auditado. | `deploy/postgres/init/01-roles.sh`; `backend/alembic/versions/0002_rls_y_funciones.py`; dos URLs distintas en `backend/.env.example` (`DATABASE_URL` vs `DATABASE_URL_ADMIN`); `backend/app/tasks/emision.py` y `backend/app/tasks/buzon.py` para los dos barridos |
| **El aislamiento por inquilino lo garantiza la base, no el código** | Toda tabla de negocio tiene RLS `ENABLE` **y** `FORCE`, con política `tenant_id = app_tenant()`, donde `app_tenant()` lee un GUC fijado por transacción en cada petición. Si algún día se olvida un `WHERE tenant_id`, la base devuelve cero filas en vez de las del vecino. El certificado `.p12` está bajo la misma política. | `0002_rls_y_funciones.py` (`ALL_RLS_TABLES`, `FORCE ROW LEVEL SECURITY`), `0003_motor_emision.py` (`certificados_tenant`); `backend/app/db/session.py` (`apply_rls_context`); `backend/tests/test_rls.py` |
| **Denegar por defecto** | Cada ruta declara sus roles con `require_roles(...)`: sin rol declarado no hay acceso. Sin contexto de tenant no hay filas. `audit_log` no tiene política de UPDATE ni DELETE, y la ausencia de política en Postgres significa denegado. En producción el arranque falla si falta una clave, y un webhook sin su secreto rechaza todo en vez de fallar abierto. | `backend/app/api/deps.py`; `0002_rls_y_funciones.py` (`audit_log_insert`, `audit_log_select`); `backend/app/core/config.py` (`sin_valores_inseguros_en_produccion`) |
| **Cifrado en reposo de los secretos** | AES-256-GCM con **una clave por dominio de uso y AAD distinto**: el `.p12` y su contraseña se cifran por separado con `CERT_ENC_KEY`, el buzón con `BUZON_ENC_KEY`, el secreto TOTP con `TOTP_ENC_KEY`. Están separadas a propósito: reusar una sola ampliaría a los documentos de terceros el radio de daño de la firma electrónica y obligaría a rotarlo todo a la vez. El `.p12` se descifra solo en memoria del worker al firmar. | `backend/app/core/crypto.py`; `backend/app/services/certificados.py` y `backend/app/sri/firma.py` (`AAD_P12`, `AAD_P12_PASSWORD`); `backend/app/buzon/ingesta.py` (`AAD_BUZON`); `backend/app/core/security.py` (`encrypt_totp_secret`) |
| **Trazabilidad inmutable** | Toda escritura del ORM inserta su fila en `audit_log` dentro de la **misma transacción** —si la escritura se revierte, la auditoría también— con actor, rol real, inquilino, antes/después en JSON, IP, user agent y momento. Los campos sensibles se enmascaran para que la bitácora no se convierta en el lugar donde los secretos quedan en claro. Nadie la edita: no hay GRANT de UPDATE/DELETE y además un trigger lo bloquea. | `backend/app/core/audit.py` (`SENSITIVE_FIELDS`); `0002_rls_y_funciones.py` (`audit_log_inmutable`, `trg_audit_log_inmutable`); `backend/tests/test_rls.py::test_audit_log_es_inmutable` |
| **Ningún secreto en el repositorio** | Un solo `.env` por entorno, fuera del control de versiones. `.gitignore` bloquea `.env`, `*.p12`, `*.pem` y `*.key`; un hook de pre-commit rechaza el commit que intente colar un `.env`; la plantilla se publica sin valores. En producción, arrancar con la clave de desarrollo es un error de arranque, no una advertencia. | `.gitignore`; `.pre-commit-config.yaml` (hook `no-env-files`); `backend/.env.example`; `backend/app/core/config.py` |
| **La seguridad se comprueba, no se declara** | 17 archivos de prueba en `backend/tests/` cubren aislamiento entre inquilinos, inmutabilidad de la bitácora, cifrado del certificado y defensas del buzón. El pre-commit corre ruff, mypy, pytest, `pip-audit` y `npm audit` antes de cada commit. | `backend/tests/`; `.pre-commit-config.yaml`; mapeo control por control en [SECURITY.md](../SECURITY.md) |

## Obligaciones de quien opera el servicio

1. El `.env` de producción vive con permisos `600` y propietario root en el VPS. No se manda por WhatsApp, correo ni chat, y no se copia a un equipo personal.
2. PostgreSQL y Redis solo en la red `interna` (`internal: true` en `deploy/docker-compose.prod.yml`). Nunca se publica su puerto, ni "un momentito para depurar".
3. Sin credenciales por defecto: el primer superadmin se crea por consola con contraseña fuerte (`backend/app/cli.py`, `create-superadmin`) y el rol `SUPERADMIN` tiene 2FA TOTP obligatorio.
4. Los datos de un inquilino se consultan por las funciones `sa_*`, que verifican el rol real en la base. Abrir la ficha de un inquilino, cambiar su estado o darlo de alta exigen además motivo escrito y dejan fila en `audit_log` (`sa_ficha_cliente`, `sa_cambiar_estado_tenant`, `sa_crear_tenant`); los listados y las métricas agregadas del panel interno comprueban el rol pero no piden motivo ni se auditan uno a uno. Abrir la ficha de un cliente por curiosidad es una falta: queda registrada con nombre y hora. La impersonación deja doble rastro y solo dura 30 minutos.
5. Un `.p12` o un XML no salen del entorno de producción por ningún motivo. Si hace falta depurar, se hace con datos de prueba.
6. Sentry va sin variables locales ni cuerpos de petición (`backend/app/core/observabilidad.py`): un volcado completo sacaría del sistema el certificado ya descifrado.
7. Se actualiza `SECURITY.md` al cerrar cada fase, y esta política cuando cambie el alcance, el responsable o alguno de los principios.
8. Cualquier sospecha de acceso indebido se comunica al responsable el mismo día. El procedimiento formal es el [documento 5](procedimiento-gestion-incidentes.md), que incluye la notificación LOPDP.

## Lo que a esta fecha NO está resuelto

Se declara aquí porque un documento que promete lo que el sistema no hace es peor que no tener documento.

- **Dominio sin confirmar.** `APP_DOMAIN` está vacío y las maquetas usan dominios distintos; `config.py` usa `factuchat.ec` como respaldo y en producción no arranca sin él. Hay que fijarlo antes de emitir TLS y de repartir direcciones de buzón.
- **No hay certificado de firma real.** La cadena de cifrado y validación está probada (`backend/tests/test_certificados.py`), pero la emisión de punta a punta contra el ambiente PRUEBAS del SRI con un `.p12` real sigue pendiente; el runbook está en `deploy/scripts/emision-prueba-sri.md`.
- **Faltan las credenciales de Meta.** Sin `WA_APP_SECRET` y `WA_ACCESS_TOKEN` el canal de WhatsApp no está en operación.
- **Falta contratar el proveedor de correo entrante del buzón.** `BUZON_ACTIVO` nace apagado y así se queda hasta tener el proveedor y `BUZON_WEBHOOK_SECRET`.
- **El despliegue en el VPS no se ha hecho.** Los guiones y la configuración del servidor están escritos, pero no se han ejecutado en ninguna máquina. En consecuencia: el bloque TLS global vive activo en `deploy/nginx/nginx.conf` y el `server` de 443 con la cabecera HSTS (dos años, `includeSubDomains`) vive activo —sin comentar— en `deploy/nginx/templates/factuchat.conf.template`, pero ninguno surte efecto todavía porque no hay certificado emitido (el cliente ACME sí está: servicio `certbot` en el compose, y `deploy/scripts/tls-emitir.sh` para la primera emisión); el respaldo cifrado (`deploy/scripts/respaldo.sh`) y la restauración guiada (`deploy/scripts/restaurar.sh`) están escritos y validados, junto con el procedimiento ([documento 4](procedimiento-respaldo-restauracion.md)), pero falta ejecutarlos y dejar evidencia de la primera prueba de restauración, que exige el VPS; las imágenes se fijan por etiqueta y no por digest; y no hay alertas activas — el presupuesto de WhatsApp y los rechazos del SRI en ráfaga se ven en el panel pero no notifican a nadie (dos casillas ⚠️ en A09 de `SECURITY.md`).
- **Pendiente de aprobación.** Los siete documentos del listado de [docs/README.md](README.md) están escritos, pero ese índice todavía marca como «Pendiente» el 1, el 2, el 5 y el 6. Del documento 7 siguen pendientes de aprobación los tiempos de respuesta.

## Cómo se revisa esta política

Se revisa al cerrar cada fase, obligatoriamente antes del despliegue en producción, después de cualquier incidente de seguridad y, en ausencia de todo lo anterior, una vez al año. Cada revisión sube el número de versión de la cabecera y deja escrito qué cambió. La aprueba el responsable nombrado arriba. El detalle técnico control por control vive en [SECURITY.md](../SECURITY.md); quién puede hacer qué, en [matriz-roles-accesos.md](matriz-roles-accesos.md).
