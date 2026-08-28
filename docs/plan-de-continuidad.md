# Plan de continuidad y recuperación — Factuchat

Versión 1.0 · Control ISO 27001 Anexo A **A.5.30** (preparación de las TIC para la
continuidad del negocio) · Paso 10 de la guía de despliegue de `PLAN.md`.

Este documento responde a una sola pregunta: **si mañana el VPS desaparece, ¿cómo
vuelve Factuchat a emitir facturas, y en cuánto tiempo?** Está escrito para que lo
ejecute una persona con acceso de administrador, de arriba hacia abajo, sin tener
que investigar nada durante la emergencia.

---

## 0. Estado de este procedimiento (léelo antes de confiar en él)

**Este runbook todavía no se ha ejecutado nunca, y hoy no se puede ejecutar
completo.** El sistema está construido y probado (fases 1 a 7) y los tres guiones
que este procedimiento invoca ya están escritos, pero ninguno se ha corrido nunca
en un servidor real, no hay VPS desplegado y quedan piezas que el procedimiento
necesita y todavía no existen. Decirlo aquí es parte del control: un plan de
continuidad que promete un script inexistente —o que da por probado uno que nadie
ha ejecutado— es peor que no tener plan, porque se descubre el día de la caída.

| Pieza que este runbook necesita | ¿Existe hoy? | Dónde vive |
|---|---|---|
| Compose de producción (api, worker, beat, postgres, redis, nginx) | Sí | `deploy/docker-compose.prod.yml` |
| Creación de roles de Postgres al inicializar el clúster | Sí | `deploy/postgres/init/01-roles.sh` |
| Migraciones completas del esquema (0001 a 0009) | Sí | `backend/alembic/versions/` |
| CLI de arranque (primer superadmin, tenants, planes) | Sí | `backend/app/cli.py` |
| Plantilla de configuración de producción | Sí | `deploy/.env.example` |
| Script de endurecimiento del servidor `instalar-servidor.sh` | Sí, **nunca ejecutado** | `deploy/scripts/instalar-servidor.sh` |
| Script de respaldo cifrado cada 6 horas | Sí, **nunca ejecutado** | `deploy/scripts/respaldo.sh` |
| Script de restauración `restaurar.sh` | Sí, **nunca ejecutado** | `deploy/scripts/restaurar.sh` |
| Bloque `server` de 443 con TLS, redirección 301 y HSTS | Sí | `deploy/nginx/templates/factuchat.conf.template` |
| Cliente ACME (Let's Encrypt) que llene el volumen `certs` | Sí, **nunca ejecutado** | servicio `certbot` en el compose + `deploy/scripts/tls-emitir.sh` |
| Imágenes base fijadas por digest (hoy van por etiqueta) | **No** | `deploy/.env.example` |
| Algo que compile el frontend y llene el volumen `static` | **No** | falta `Dockerfile` de `frontend/` o un paso de build |
| Código publicado en el remoto de Git | **No** | ver el bloqueo crítico de abajo |

### Bloqueo crítico: el código no está respaldado

`git ls-files` devuelve **7 archivos**: `PLAN.md`,
`deploy/scripts/instalar-servidor.sh` y las cinco maquetas y logos de `diseno/`.
El último commit es `primer cambio antes del codigo`. Todo el resto del sistema
—`backend/`, `frontend/`, `docs/` y casi todo `deploy/`, incluidos `respaldo.sh` y
`restaurar.sh`— está sin versionar en el disco de la máquina de desarrollo, y por
tanto **no está en `github.com/elvispareja/factuchat.git`**.

El paso «traer el repositorio» de este runbook es hoy una ficción. Si esa máquina
se daña, no se pierde una copia del sistema: se pierde el sistema. Antes que
cualquier otra tarea de continuidad, hay que commitear y empujar `backend/`,
`frontend/`, `deploy/` y `docs/` al remoto. El `.gitignore` ya protege lo que no
debe subir (`.env`, `*.p12`, `*.pem`, `*.key`, `deploy/backups/`), así que el
riesgo de publicar un secreto al hacerlo es bajo, pero conviene revisar el
`git status` antes del primer push.

### Bloqueo crítico: todavía no hay respaldos

El script existe (`deploy/scripts/respaldo.sh`: `pg_dump` en formato custom más el
volumen `comprobantes` y el de `nginx-logs`, todo cifrado con `age` y con
manifiesto de SHA-256), pero **nunca se ha ejecutado**. No hay servidor donde
corra, no hay línea de cron instalada, no hay par de claves `age` generado, no hay
almacenamiento externo contratado y no existe una sola copia fuera del entorno de
desarrollo. Mientras eso siga así, **el RPO real del sistema es la pérdida
total**, no las 6 horas que se declaran más abajo como objetivo. Tener el guion
escrito no es tener respaldos: la casilla se cierra con la primera corrida y con
la primera restauración probada.

### Pendientes de negocio que afectan a la recuperación

- **Dominio sin confirmar.** `APP_DOMAIN` está vacío y las maquetas usan tres
  dominios distintos. `config.py` obliga a que `APP_DOMAIN` esté definido en
  producción (`sin_valores_inseguros_en_produccion`), así que sin esa decisión la
  API ni siquiera arranca. Y sin dominio fijo no hay registro DNS que apuntar ni
  certificado TLS que emitir: **la decisión del dominio es un prerrequisito de
  este plan**, no un detalle cosmético.
- **No hay certificado .p12 real.** Ningún inquilino tiene firma cargada todavía.
- **Faltan las credenciales de Meta** (`WA_APP_SECRET`, `WA_ACCESS_TOKEN`,
  `WA_PHONE_NUMBER_ID`, `WA_VERIFY_TOKEN`).
- **Falta contratar el proveedor de correo entrante** del buzón SRI. La única vía
  de entrada implementada es el webhook firmado; la recolección por IMAP **no está
  escrita** (solo existen las variables de configuración reservadas). El buzón nace
  apagado (`BUZON_ACTIVO=false`), así que esto no bloquea la recuperación del
  núcleo.

---

## 1. Qué hay que recuperar

Un VPS nuevo no es «restaurar la base». Factuchat vive en cinco lugares distintos
y cada uno se recupera de otra forma. Confundirlos es el error clásico: se
restaura la base, todo parece bien, y a los dos días alguien pide el RIDE de una
factura de marzo y no está.

| # | Activo | Dónde vive hoy | Cómo se recupera | Si falta |
|---|---|---|---|---|
| 1 | **Base de datos** | Volumen `pgdata` de Docker | Restaurar el `pg_dump` cifrado | Se pierde todo el negocio: inquilinos, comprobantes, clientes, retenciones, bitácora |
| 2 | **Archivos generados** | Volumen `comprobantes` (`STORAGE_DIR=/var/factuchat/storage`) | Restaurar la copia del volumen | Se pierden los XML firmados y autorizados, los RIDE, los `.eml.enc`/`.xml.enc` del buzón y los comprobantes de pago subidos en el checkout |
| 3 | **Secretos** (`.env`) | En ninguna parte todavía: no existe `.env` en el repositorio ni en el equipo | Se reconstruyen a mano desde la custodia externa | Ver la sección 5: hay secretos cuya pérdida es irreversible |
| 4 | **Código** | Sin versionar en la máquina de desarrollo | `git clone` del remoto | Ver el bloqueo crítico de la sección 0 |
| 5 | **DNS y TLS** | Pendiente (dominio sin confirmar) | Apuntar el registro A y reemitir el certificado | El sistema funciona pero nadie llega, y sin TLS nadie debe llegar |

Detalle importante del activo 2: los XML autorizados **no están en la base**. La
base guarda su hash SHA-256 y el estado, con un trigger que impide editarlos
(migración `0003_motor_emision.py`), pero el archivo está en el volumen. Y como un
reintento genera siempre un documento nuevo con clave de acceso nueva, un XML
autorizado perdido **no se puede regenerar desde el sistema**. La vía de rescate
es reconsultar al SRI por la clave de acceso que sí quedó en la base, usando el
mismo servicio `AutorizacionComprobantesOffline` que ya usa
`backend/app/sri/client.py`. Es un rescate manual, no está automatizado, y por eso
el volumen `comprobantes` tiene que entrar al respaldo con la misma seriedad que
la base. El paso 6 de `PLAN.md` solo nombra `pg_dump`: **eso es insuficiente**, y
`deploy/scripts/respaldo.sh` ya lo corrige copiando el volumen entero en cada
corrida, junto al volcado.

---

## 2. RTO y RPO

Estos números no son aspiraciones: se derivan del procedimiento concreto de la
sección 4 y de la frecuencia de respaldo que fija `PLAN.md` (paso 6).

| Indicador | Valor objetivo | De dónde sale |
|---|---|---|
| **RTO** (tiempo máximo para volver a operar) | **4 horas** | Suma de los pasos de la sección 4: 3 h 55 min con el servidor y los respaldos disponibles |
| **RPO de la base de datos** | **6 horas** | Respaldo cada 6 horas. En el peor caso la caída ocurre justo antes del siguiente volcado, y se pierde todo lo escrito desde el anterior |
| **RPO de los archivos generados** | **6 horas** | `respaldo.sh` copia el volumen `comprobantes` completo en la misma corrida que el volcado, así que los XML y RIDE tienen el mismo RPO que la base, no uno peor |
| **RPO real hoy** | **Pérdida total** | El script está escrito pero no corre en ninguna parte: no hay ningún respaldo tomado |

**Qué significan 6 horas de RPO en este negocio.** Lo que se pierde no es solo
«datos»: son facturas que el SRI ya autorizó. Si el sistema pierde el registro de
una factura que el SRI sí tiene, quedan desincronizados el libro del contribuyente
y el del fisco. La reconciliación se hace consultando al SRI por las claves de
acceso del rango de fechas afectado, y es trabajo manual. Por eso conviene tratar
las 6 horas como techo, no como meta: bajar el intervalo del respaldo a 1 hora
cuesta poco (el volcado de una base de este tamaño es rápido) y reduce el trabajo
de reconciliación en la misma proporción.

Recomendación derivada: el script ya toma base y archivos cada 6 horas y retiene
30 días la copia marcada `-diario`, como pide `PLAN.md`. Si se quiere bajar el RPO
de la base a **1 hora**, basta con cambiar la línea de cron a horaria: la marca
diaria no se rompe, porque el script marca como `-diario` la corrida cuya hora UTC
coincide con `HORA_DIARIA_UTC` (06 por omisión, la 01:00 de Ecuador). Este
documento se actualiza con los números que finalmente queden instalados en el
crontab del servidor.

---

## 3. Escenarios

### Escenario A — Pérdida total del VPS

El proveedor pierde la máquina, la borra por impago, o un compromiso de seguridad
obliga a no volver a confiar en ella.

Procedimiento: el runbook completo de la sección 4. RTO 4 horas, RPO 6 horas.

Si la causa fue un compromiso de seguridad, además: **no se reutiliza nada del
servidor viejo** (ni imágenes, ni claves SSH, ni el `.env` que estaba ahí) y se
rotan `SECRET_KEY`, las contraseñas de Postgres, `BUZON_WEBHOOK_SECRET`,
`WA_ACCESS_TOKEN` y las credenciales SMTP. Las claves de cifrado en reposo
(`CERT_ENC_KEY`, `BUZON_ENC_KEY`, `TOTP_ENC_KEY`) **no se rotan durante la
recuperación**: sin ellas el respaldo no se puede descifrar. Su rotación es un
procedimiento aparte, posterior y con el sistema ya en pie, porque exige recifrar
lo guardado.

### Escenario B — Corrupción de la base de datos

El servidor está sano pero los datos no: una migración a medias, una escritura
masiva errónea, un fallo del volumen.

No se levanta un VPS nuevo. Se detienen `api`, `worker` y `beat` para que nadie
siga escribiendo, se conserva el volumen dañado (es evidencia y puede tener datos
posteriores al último respaldo), se levanta un clúster limpio y se restaura ahí.

El detalle que hace fallar este escenario: **`01-roles.sh` solo se ejecuta cuando
el directorio de datos está vacío.** Es el comportamiento estándar de la imagen
`postgres`. Si se restaura sobre un `pgdata` que ya existe, ese script no corre;
si se restaura en uno nuevo, sí. Y hace falta que corra **antes** del volcado,
porque el dump contiene `ALTER ... OWNER TO factuchat_security` y `GRANT ... TO
factuchat_app`, y esas sentencias fallan si los roles no existen todavía.
`pg_dump` no incluye los roles: son objetos del clúster, no de la base.

Orden obligatorio: clúster vacío → arranca y crea los roles → recién ahí se carga
el volcado.

### Escenario C — Pérdida de una clave de cifrado

Es el escenario más caro y el peor entendido. Tiene su propia sección: la 5.

### Escenario D — Caída prolongada del SRI o de Meta

Esto **no es un desastre y no se recupera: se espera**. No hay que restaurar nada,
y actuar por impaciencia sí puede romper cosas.

**SRI caído.** El sistema ya está construido para esto y no hay que tocarlo:

- El cliente del SRI tiene timeouts, reintentos con backoff exponencial y un
  circuit breaker en Redis (`backend/app/sri/client.py`). Mientras el circuito
  está abierto, la cola queda en pausa.
- Un fallo de canal (403, 404, 429, HTML en vez de SOAP) **nunca** se interpreta
  como veredicto del SRI: se reintenta (`tests/test_emision.py::TestFallosDeCanal`).
- Los comprobantes se quedan en su estado intermedio y `barrer_atascados` los
  retoma cada 10 minutos (`backend/app/tasks/emision.py`).
- Tras una caída, antes de reenviar se le pregunta al SRI si ya tiene el
  documento (`_sri_no_lo_tiene`), así que no se duplican facturas.
- Las retenciones del buzón siguen sin contar como crédito mientras el SRI no
  confirme: un SRI mudo no se lee como permiso
  (`backend/app/buzon/verificacion.py`, `VerificacionPendiente`).

Lo único que hace falta es comunicación: avisar a los inquilinos que el SRI no
responde y que sus comprobantes están encolados, no perdidos. Si la caída se
prolonga, aplica el régimen de contingencia que el propio SRI publique en ese
momento; no lo damos por escrito aquí porque es normativa que cambia.

**Meta (WhatsApp) caído.** El panel deja de recibir mensajes y no se emiten
facturas por chat; el panel web sigue funcionando y es la vía alterna que hay que
comunicar a los clientes. Aquí hay una diferencia honesta con el SRI: el
**backoff y el circuit breaker hacia Meta están pendientes** (`SECURITY.md`, A10,
marcado 🔜 para la fase 5). Mientras no se implementen, una caída larga de Meta
producirá reintentos menos ordenados que los del SRI. No compromete datos, pero sí
gasta cuota y ruido de logs.

---

## 4. Runbook: VPS nuevo desde cero

Suma **3 h 55 min**. Los tiempos suponen que los respaldos son accesibles, que el
código está en el remoto y que las claves están en la custodia. Si alguna de esas
tres cosas falla, este cronómetro no aplica.

> **Dispara el cambio de DNS apenas tengas la IP (fin del paso 1).** El paso 10
> aparece más abajo porque ahí es donde se *verifica*, pero el cambio conviene
> hacerlo en cuanto exista la IP, para que el TTL corra en paralelo con el resto
> del trabajo. Y bájale el TTL del registro A a 300 segundos **hoy, en
> tranquilidad**: es la única mitigación de un TTL alto, y no sirve de nada
> hacerla durante la emergencia.

| Paso | Acción | Tiempo |
|---|---|---|
| 0 | Declarar la contingencia y avisar | 10 min |
| 1 | Levantar el VPS | 20 min |
| 2 | Endurecer el servidor e instalar Docker | 25 min |
| 3 | Traer el repositorio | 10 min |
| 4 | Reconstruir el `.env` | 30 min |
| 5 | Arrancar Postgres vacío (crea los roles) | 10 min |
| 6 | Restaurar base y archivos | 40 min |
| 7 | Verificar el esquema | 10 min |
| 8 | Compilar el frontend y publicar `static` | 15 min |
| 9 | Levantar el compose **sin nginx** | 10 min |
| 10 | Confirmar el DNS | 15 min |
| 11 | Emitir el certificado TLS y levantar nginx | 15 min |
| 12 | Comprobaciones de aceptación | 25 min |
| | **Total** | **3 h 55 min** |

### Paso 0 — Declarar la contingencia y avisar (10 min)

Antes de tocar nada, dos cosas. Primero, anotar la hora de inicio: el RTO se mide
desde aquí, y sin ese dato la prueba anual no tiene evidencia. Segundo, avisar a
los inquilinos por el canal que siga vivo (WhatsApp si Meta responde, correo si
no) que el servicio está caído y que **ninguna factura enviada se ha perdido**.
En un sistema de facturación, el cliente que cree que su factura se perdió la
vuelve a emitir por otro medio y termina con documentos duplicados ante el SRI.
El aviso evita un problema tributario, no solo un disgusto.

### Paso 1 — Levantar el VPS (20 min)

Ubuntu 24.04 LTS limpio, con al menos 4 GB de RAM (Postgres 16, Redis, dos
procesos de Python con WeasyPrint y nginx no caben cómodos en 2 GB). De
preferencia con el mismo proveedor y región, para que las rutas de red hacia
`cel.sri.gob.ec` se comporten igual.

Anotar la IP pública. **Ir ahora mismo a apuntar el registro A** (ver el aviso de
arriba) y volver aquí.

### Paso 2 — Endurecer el servidor e instalar Docker (25 min)

```bash
sudo bash deploy/scripts/instalar-servidor.sh --dry-run      # enseña todo lo que haría
sudo bash deploy/scripts/instalar-servidor.sh                # aplica, dejando el 22 abierto
# ...abrir una sesión NUEVA en el puerto 52222 y comprobar que entra...
sudo bash deploy/scripts/instalar-servidor.sh --confirmar-ssh   # recién ahí cierra el 22
```

> **Va en dos pasadas, y no es un capricho.** La primera aplica todo y mueve SSH a
> `FC_PUERTO_SSH` (**52222** por omisión) dejando el 22 todavía abierto.
> `--confirmar-ssh` comprueba, **antes** de tocar el cortafuegos, que la sesión
> desde la que se lo invoca llegó por el puerto nuevo; si no, aborta sin cambiar
> nada. Cerrar el 22 en la misma pasada en que se cambia el puerto es la forma
> clásica de quedarse fuera del servidor que se está recuperando.
>
> El script cubre los pasos 1, 2, 8 y 9 de la guía de despliegue de `PLAN.md`:
> usuario no-root con sudo; SSH solo con llave y en puerto no estándar;
> `PasswordAuthentication no`; fail2ban (5 intentos en 15 minutos, veto de 1 hora);
> ufw permitiendo únicamente 80, 443 y el puerto de SSH; Docker y Compose;
> `unattended-upgrades`; y logrotate a 12 meses. **Nunca se ha ejecutado en un
> servidor real**, así que el cronómetro de 25 minutos es una estimación, y la
> pasada `--dry-run` de la primera línea no es opcional.

El orden importa: la llave SSH tiene que estar cargada y probada **antes** de
apagar la autenticación por contraseña. Quedarse fuera del servidor que se está
recuperando es una forma tonta de duplicar el RTO.

### Paso 3 — Traer el repositorio (10 min)

```bash
git clone https://github.com/elvispareja/factuchat.git /opt/factuchat
cd /opt/factuchat
git checkout <tag-de-la-version-en-produccion>
```

Usar la etiqueta de la versión que estaba en producción, no `main`. Restaurar una
base de datos con un esquema más nuevo que el código, o al revés, es una forma
segura de perder la tarde. La etiqueta desplegada se registra en el
[procedimiento de soporte y gestión de cambios](procedimiento-soporte-y-gestion-de-cambios.md)
(documento 7 de `/docs`): consultarla ahí antes de hacer el `git checkout`.

### Paso 4 — Reconstruir el `.env` (30 min)

**Aquí es donde la gente descubre tarde el problema.** El `.env` **no está en el
respaldo y no está en el repositorio**: `.gitignore` lo excluye, y un `pg_dump` no
contiene variables de entorno. Es intencional (OWASP A02), y significa que el
archivo se reconstruye a mano, desde la custodia externa de la sección 6. Si esa
custodia no existe, la recuperación se detiene en este paso y no avanza más,
independientemente de lo buenos que sean los respaldos.

```bash
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
sudo chown root:root deploy/.env
```

La plantilla de producción es `deploy/.env.example`, **no** `backend/.env.example`:
esta última es la de desarrollo y trae `ENVIRONMENT=development`, un
`DATABASE_URL` que apunta a `localhost:5433` y ni `FACTUCHAT_DOMINIO` ni
`REDIS_PASSWORD`. Copiarla al servidor deja el compose sin arrancar.

Y completar. Los secretos se dividen en tres grupos y **no se tratan igual**:

| Grupo | Variables | De dónde salen en la recuperación |
|---|---|---|
| **Deben ser idénticos a los de antes** | `CERT_ENC_KEY`, `BUZON_ENC_KEY`, `TOTP_ENC_KEY` | Solo de la custodia externa. Un valor nuevo aquí no da error al arrancar: descifra basura y falla recién al firmar una factura |
| **Se pueden regenerar** | `SECRET_KEY`, contraseñas de Postgres | Generar nuevas. `SECRET_KEY` nueva invalida las sesiones abiertas: todos vuelven a iniciar sesión, y ya |
| **Se recuperan del tercero** | `WA_APP_SECRET`, `WA_ACCESS_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_VERIFY_TOKEN`, `SMTP_*`, `BUZON_WEBHOOK_SECRET`, `SENTRY_DSN` | Consola de Meta, del proveedor de correo y de Sentry. Tener a mano esos accesos es parte del plan |

Para generar los que se regeneran:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # SECRET_KEY
openssl rand -base64 32                                          # claves AES (solo si es una instalación nueva)
```

**Las variables que la plantilla trae vacías y hay que rellenar** son, en el
orden en que aparecen: `FACTUCHAT_DOMINIO`, `POSTGRES_PASSWORD`,
`APP_DB_PASSWORD`, `REDIS_PASSWORD`, `SECRET_KEY`, las tres claves AES
(`TOTP_ENC_KEY`, `CERT_ENC_KEY`, `BUZON_ENC_KEY`), `APP_DOMAIN` y
`CORS_ORIGINS`. `FACTUCHAT_DOMINIO` y `REDIS_PASSWORD` no admiten quedarse en
blanco ni un minuto: el compose las declara con `${…:?}` y `docker compose up`
aborta de inmediato si faltan.

`APP_DB_PASSWORD` tiene que coincidir **exactamente** con la contraseña que va
dentro de `DATABASE_URL` (rol `factuchat_app`), y `POSTGRES_PASSWORD` con la de
`DATABASE_URL_ADMIN` (rol `factuchat`). La plantilla deja esas dos URL escritas
como `${APP_DB_PASSWORD}` y `${POSTGRES_PASSWORD}`; si se prefiere poner la
contraseña literal dentro de la URL, hay que cambiarla en los dos sitios. Es el
error más frecuente de este paso, y se manifiesta como un `password authentication
failed` en el arranque de la API, no en el de Postgres.

Comprobar además que `ENVIRONMENT=production` y `DEBUG=false` siguen como los trae
la plantilla, y que `APP_DOMAIN` tiene el dominio definitivo y coincide con
`FACTUCHAT_DOMINIO`. `config.py` rechaza el arranque si falta cualquiera de ellos,
junto con `SECRET_KEY`, `TOTP_ENC_KEY` y `CERT_ENC_KEY`. Es deliberado: es
preferible que la API no levante a que levante insegura.

### Paso 5 — Arrancar Postgres vacío (10 min)

```bash
cd /opt/factuchat/deploy
docker compose -f docker-compose.prod.yml up -d postgres
docker compose -f docker-compose.prod.yml logs -f postgres   # esperar "database system is ready"
```

Sobre un volumen `pgdata` vacío, la imagen ejecuta `01-roles.sh` y crea
`factuchat_app` (LOGIN, **NOBYPASSRLS**) y `factuchat_security` (NOLOGIN,
BYPASSRLS). Verificar que ocurrió, porque todo lo que sigue depende de ello:

```bash
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U factuchat -d factuchat -c "\du factuchat_app"
```

Si `factuchat_app` no aparece, el volumen no estaba vacío. Parar, borrar el
volumen y repetir. No improvisar creando los roles a mano: `NOBYPASSRLS` es lo que
sostiene el aislamiento entre inquilinos, y un rol creado a la carrera puede
quedar sin esa propiedad.

### Paso 6 — Restaurar base y archivos (40 min)

```bash
AGE_IDENTIDAD=/media/usb/factuchat-respaldos.key \
  sudo -E bash deploy/scripts/restaurar.sh /var/backups/factuchat/copias/<marca-UTC>
```

Recibe **una sola** carpeta de copia —la que se quiera restaurar, con su marca UTC,
por ejemplo `20260825T060000Z-diario`— y no una cadena de copias: cada corrida de
`respaldo.sh` es completa, no incremental. `AGE_IDENTIDAD` es la clave privada del
respaldo, que **no** vive en el VPS: se trae en el momento y se lleva al terminar.

> **El script existe, pero nunca se ha ejecutado sobre una copia real.** Lo que
> hace, en este orden:
>
> 1. Comprueba el SHA-256 de cada fichero cifrado contra `manifiesto.txt` **antes**
>    de tocar nada, y exige que la confirmación se escriba como frase completa.
> 2. Descifra con la identidad `age` de `AGE_IDENTIDAD`, que **también** vive en la
>    custodia externa y **no** es ninguna de las tres claves de cifrado en reposo.
> 3. Recrea los dos roles que `pg_dump` no guarda (`factuchat_app` y
>    `factuchat_security`); el propietario `factuchat` lo crea el entrypoint de la
>    imagen a partir de `POSTGRES_USER`.
> 4. Carga la base con `pg_restore` y el rol propietario `factuchat`, nunca con
>    `factuchat_app`: si ese rol quedara dueño de las tablas dejaría de estar
>    sujeto a sus propias políticas RLS, y el aislamiento entre inquilinos se
>    caería sin un solo error en los registros.
> 5. Restaura los volúmenes anotados en el manifiesto (`comprobantes` y
>    `nginx-logs`), conservando la estructura `{tenant_id}/…` de emisión,
>    `buzon/{tenant_id}/…` y `comprobantes-pago/`. Si el volumen de destino ya
>    tiene contenido **se detiene**: mezclar ficheros de dos momentos distintos
>    deja XML huérfanos. Con `--sobrescribir-ficheros` lo vacía por completo antes
>    de extraer.
> 6. Verifica lo restaurado —`FORCE ROW LEVEL SECURITY` tabla por tabla, roles,
>    revisión de Alembic contra la del manifiesto, inmutabilidad de `audit_log`— e
>    informa de cuántas filas y cuántos ficheros quedaron, que es contra lo que
>    contrasta el paso 12.

La misma verificación se puede correr sin restaurar nada, contra el sistema vivo,
con `./restaurar.sh --solo-verificar`. Es la evidencia mensual del control A.8.13.

### Paso 7 — Verificar el esquema (10 min)

El volcado ya trae tablas, políticas RLS, triggers, funciones `SECURITY DEFINER` y
GRANTs: todo eso son objetos de la base y `pg_dump` los incluye. Lo que hay que
confirmar es que la versión del esquema coincide con la del código:

```bash
docker compose -f docker-compose.prod.yml run --rm api alembic current
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

Si `current` ya está en la última revisión —`0009`, definida en
`backend/alembic/versions/0009_buzon_sri.py`; el identificador es `0009`, no el
nombre del fichero, y así es como sale por pantalla y como queda en
`alembic_version`—, `upgrade head` no hace nada y así debe ser. Si el respaldo era
de una versión anterior a la etiqueta desplegada, `upgrade head` aplica lo que
falte. Si el respaldo fuera **más nuevo** que el código, hay que subir la etiqueta
del paso 3, no bajar la base.

### Paso 8 — Compilar el frontend y publicar `static` (15 min)

```bash
cd /opt/factuchat/frontend
npm ci
npm run build
```

El compose declara un volumen `static` que nginx monta en `/srv/static:ro`, pero
**ningún servicio lo llena**: no hay `Dockerfile` en `frontend/`. Hasta que exista,
el contenido de `frontend/dist/` hay que copiarlo al volumen a mano. Es la pieza
que falta para que este runbook sea de verdad de una sola pasada, y conviene
resolverla añadiendo una etapa de build al compose antes de la primera prueba
anual.

### Paso 9 — Levantar el compose sin nginx (10 min)

```bash
cd /opt/factuchat/deploy
docker compose -f docker-compose.prod.yml up -d postgres redis api worker beat
docker compose -f docker-compose.prod.yml ps
```

**nginx se queda fuera a propósito hasta el paso 11.** Su bloque `server` de 443
apunta a `/etc/letsencrypt/live/${FACTUCHAT_DOMINIO}/fullchain.pem`, y mientras ese
fichero no exista nginx no arranca: un `up -d` de todo aquí deja el contenedor
reiniciándose en bucle y hace perder minutos buscando el fallo donde no está.

`api` y `worker` esperan a que Postgres y Redis pasen su healthcheck antes de
arrancar; **`beat` solo espera a Redis**, así que puede levantar con la base
todavía sin aceptar conexiones y fallar su primer disparo. Postgres y Redis **no
publican puertos**: viven solo en la red interna de Docker. Si en el `ps` aparece
un `0.0.0.0:5432` es que alguien editó el compose durante la emergencia; hay que
revertirlo antes de seguir.

`beat` es el que dispara `barrer_atascados` cada 10 minutos y las tareas
periódicas del buzón. Comprobar en el `ps` que quedó arriba y **sin reinicios**:
si no levanta, el sistema parece sano pero los comprobantes que quedaron a medio
camino en la caída no se retoman nunca.

### Paso 10 — Confirmar el DNS (15 min)

El cambio ya se hizo en el paso 1. Aquí solo se confirma que propagó:

```bash
dig +short <dominio> @1.1.1.1
```

Si todavía responde la IP vieja, es el TTL. Se espera; no se toca nada más.

### Paso 11 — Emitir el certificado TLS y levantar nginx (15 min)

La configuración de nginx ya está escrita y **no hay que tocarla**: el bloque TLS
global (TLS 1.2 y 1.3, ciphers, stapling) vive en `deploy/nginx/nginx.conf`, y los
bloques `server` —el de 80 con el desafío ACME y la redirección 301, y el de 443
completo con HSTS activo (`max-age` de dos años, `includeSubDomains`)— viven en
`deploy/nginx/templates/factuchat.conf.template`, que la imagen procesa con
envsubst metiéndole `FACTUCHAT_DOMINIO`. Las cabeceras de seguridad (CSP sin
inline, `X-Frame-Options DENY`, `X-Content-Type-Options`, `Referrer-Policy`,
`Permissions-Policy`) también están ahí.

> **El círculo del certificado.** nginx no arranca si el bloque 443 apunta a un
> certificado que no existe, y Let's Encrypt no emite nada si nadie responde al
> desafío en el puerto 80. Lo resuelve `deploy/scripts/tls-emitir.sh`, que crea un
> autofirmado temporal para que nginx pueda levantarse, emite el real por webroot
> y recarga. A partir de ahí el servicio `certbot` renueva cada 12 horas y nginx
> se recarga solo cada 6 para tomar el certificado nuevo, sin intervención.
>
> Antes de emitir, el script comprueba que el DNS del dominio apunte a este
> servidor: cada emisión fallida gasta uno de los cinco intentos semanales que
> Let's Encrypt concede por dominio. Con `--prueba` se usa el entorno de pruebas,
> que no consume cuota.

Un solo comando:

```bash
sudo ./deploy/scripts/tls-emitir.sh --prueba   # primero en pruebas
sudo ./deploy/scripts/tls-emitir.sh            # y luego de verdad
docker compose -f docker-compose.prod.yml logs nginx   # no debe reiniciarse
```

Cuidado con el orden: **HSTS ya está activo en el template**, así que empieza a
publicarse en cuanto nginx sirva por 443. Un certificado mal emitido con HSTS ya
publicado deja el dominio inaccesible durante el tiempo del `max-age`, y eso no se
arregla desde el servidor. Por eso el certificado se comprueba (comprobación 2 del
paso 12) inmediatamente después de levantar nginx, no al final de la jornada.

### Paso 12 — Comprobaciones de aceptación (25 min)

No se declara recuperado el sistema hasta que estas ocho comprobaciones pasen. Las
tres primeras dicen que está encendido; las cinco siguientes, que está **correcto**,
que es cosa distinta.

| # | Comprobación | Cómo | Qué se espera |
|---|---|---|---|
| 1 | La API responde | `curl https://<dominio>/api/v1/health` | `{"status":"ok"}` |
| 2 | TLS válido | Abrir el dominio en el navegador | Certificado vigente, sin advertencias, HTTP redirige a HTTPS |
| 3 | Cola viva | `docker compose ... exec worker celery -A app.worker.celery_app inspect ping` | El worker responde |
| 4 | **RLS activa** | Iniciar sesión como un CLIENTE y pedir un id de comprobante de otro inquilino | 404 o vacío, nunca el dato. Es la comprobación más importante: una restauración que deja RLS floja expone a todos los inquilinos entre sí |
| 5 | **Los datos están completos** | Contar comprobantes por estado y contrastar con lo que informó el paso 6 | Los números cuadran; el último comprobante es del rango esperado según el RPO |
| 6 | **Los archivos están** | Descargar el RIDE y el XML de un comprobante AUTORIZADO antiguo | Ambos descargan. Si la base tiene la fila pero el archivo no está, se restauró la base y se olvidó el volumen |
| 7 | **Las claves de cifrado son las correctas** | Con un inquilino que tenga certificado cargado, emitir una factura de prueba en ambiente PRUEBAS (ver `deploy/scripts/emision-prueba-sri.md`) | Llega a AUTORIZADO. Si `CERT_ENC_KEY` no es la de antes, falla al descifrar el .p12: es la única prueba real de que la clave es la correcta |
| 8 | **La bitácora sigue siendo inmutable** | Intentar un `UPDATE` sobre `audit_log` con el rol `factuchat_app` | Falla por permisos y por trigger (`tests/test_rls.py::test_audit_log_es_inmutable`) |

Anotar la hora de fin. La diferencia con el paso 0 es el RTO medido, y es la
evidencia que pide el control A.5.30.

---

## 5. Lo irrecuperable: las claves de cifrado

Todo lo demás de este documento se puede rehacer con tiempo y paciencia. Esto no.
Conviene entenderlo antes de que pase, porque el momento de descubrir que una
clave AES no se puede «recuperar» no es durante una caída.

Factuchat cifra en reposo con AES-256-GCM (`backend/app/core/crypto.py`) usando
tres claves independientes. Son independientes a propósito: si una se compromete o
se rota, el radio de daño no se contagia a lo demás.

| Clave | Qué protege | Dónde está el dato cifrado |
|---|---|---|
| `CERT_ENC_KEY` | El `.p12` de firma de cada inquilino y su contraseña, cifrados por separado con AAD distinto (`factuchat:p12` y `factuchat:p12-password`) | Base de datos, tabla `certificados`, columnas `p12_data_enc` y `p12_password_enc` |
| `BUZON_ENC_KEY` | Los correos entrantes del buzón SRI y los XML de retención, con AAD `factuchat/buzon/correo` | Volumen de archivos: `buzon/{tenant_id}/{id}.eml.enc` y `{retencion_id}.xml.enc` |
| `TOTP_ENC_KEY` | Los secretos TOTP del segundo factor | Base de datos, `users.totp_secret_enc` |

**Estas tres claves no están en ningún respaldo.** Están fuera a propósito: un
respaldo que incluyera la clave con la que se cifra su propio contenido no cifraría
nada. Quien tenga el respaldo tendría los certificados de firma electrónica de
todos los inquilinos.

### Si se pierde `CERT_ENC_KEY`

Los `.p12` guardados quedan como ruido irreversible. No hay clave maestra, ni
respaldo de la clave dentro del sistema, ni forma de derivarla: AES-256-GCM sin la
clave no se descifra, y esa es exactamente la propiedad por la que se eligió.

Consecuencias, ordenadas de menor a mayor gravedad:

- **Las facturas ya emitidas siguen siendo válidas.** El XML autorizado ya está
  firmado y guardado; el SRI ya lo autorizó. Nada de lo pasado se invalida.
- **Ningún inquilino puede emitir hasta volver a cargar su certificado.** La firma
  descifra el `.p12` en memoria del worker en cada emisión
  (`backend/app/sri/firma.py`); sin la clave, toda emisión falla.
- **Cada inquilino tiene que subir de nuevo su propio `.p12`**, con su contraseña,
  por `POST /api/v1/certificados`. Factuchat **no puede hacerlo por ellos**: el
  archivo original está en poder del contribuyente, no del sistema. La subida
  vuelve a validar vigencia y correspondencia con el RUC
  (`backend/app/services/certificados.py`).

En la práctica es una llamada a cada cliente pidiéndole que vuelva a cargar su
firma, con el servicio detenido para todos hasta que lo hagan. Con una cartera
grande, eso es días de interrupción parcial, no horas. Es el peor escenario del
sistema, peor que perder el VPS.

### Si se pierde `BUZON_ENC_KEY`

Los correos custodiados quedan ilegibles: los `.eml.enc` y los `.xml.enc` del
volumen no se pueden abrir nunca más.

Lo que **no** se pierde, y conviene saberlo para no exagerar el daño: los datos ya
extraídos de esos XML viven en claro en la base (`retenciones_recibidas`), porque
el contenido del correo nunca se guardó en una columna —lo haría visible en
`audit_log`, que es inmutable y lo lee el personal interno—. Es decir, **el saldo
de retenciones y el crédito tributario de cada inquilino sobreviven**. Lo que se
pierde es el documento original custodiado: el respaldo probatorio ante una
revisión del SRI.

Mitigación posible: el documento original también lo tiene el agente de retención
que lo emitió y el propio SRI, así que es recuperable pidiéndolo, pero de forma
manual y documento por documento.

### Si se pierde `TOTP_ENC_KEY`

Los secretos TOTP no se pueden descifrar y **nadie del equipo interno pasa el
segundo factor**, que es obligatorio para SUPERADMIN
(`backend/app/services/auth.py`). El panel interno queda cerrado para todos.

La salida existe pero es manual y hay que conocerla de antemano: conectarse con el
rol propietario (`DATABASE_URL_ADMIN`) y limpiar el segundo factor de la cuenta,
para que se vuelva a dar de alta en el siguiente inicio de sesión.

```sql
UPDATE users SET totp_enabled = false, totp_secret_enc = NULL
WHERE lower(email) = lower('<correo del superadmin>');
```

**No existe un comando de CLI para esto**: `backend/app/cli.py` solo tiene
`create-superadmin`, `create-tenant` y `seed-planes`. Tarea derivada: añadir un
`reset-totp` a la CLI, para no depender de escribir SQL a mano bajo presión.

### Y una cuarta clave, la del respaldo

El volcado va cifrado con `age`, usando la clave **pública** del destinatario
(`deploy/scripts/respaldo.sh`, paso 6 de `PLAN.md`): el servidor puede crear
respaldos pero no leerlos, que es justo lo que se quiere si alguien se lleva el
VPS. **La clave privada tiene el mismo estatus que las tres de arriba**: si se
pierde, los respaldos son un montón de bytes inservibles y este plan de
continuidad entero deja de funcionar. Va a la misma custodia, con las mismas
reglas, y es la que `restaurar.sh` exige en `AGE_IDENTIDAD`. El par de claves
**todavía no está generado**: hacerlo es requisito de la primera corrida del
respaldo, no un trámite posterior.

---

## 6. Custodia de las claves

**Estado actual: no hay custodia, y no hay claves.** No existe ningún archivo
`.env` en el proyecto ni en el equipo de desarrollo. Es la mejor noticia de este
documento: las claves de producción **todavía no se han generado**, así que la
custodia se puede establecer bien desde el primer día, en vez de corregirla
después con las claves ya en circulación.

### Regla que debe cumplirse en el momento de generarlas

Al generar `CERT_ENC_KEY`, `BUZON_ENC_KEY`, `TOTP_ENC_KEY` y la clave de cifrado
del respaldo, **antes de desplegar nada**, cada una queda en dos lugares
independientes:

| Copia | Dónde | Para qué sirve |
|---|---|---|
| Copia operativa | Gestor de contraseñas de la organización, en una bóveda separada del resto de credenciales | Es la que se usa en una recuperación normal |
| Copia sellada | Impresa en papel, en sobre firmado y fechado, en caja fuerte física | Es la que sirve cuando el gestor de contraseñas es inaccesible, o cuando el custodio no está disponible |

Tres condiciones que hacen que esto funcione de verdad:

1. **Ninguna copia vive en el VPS, ni en el repositorio, ni en el mismo
   almacenamiento donde están los respaldos.** Una copia guardada junto al
   respaldo cifrado anula el cifrado del respaldo.
2. **Al menos dos personas pueden llegar a una copia.** Un solo custodio es un
   punto único de fallo humano, y en este sistema ese fallo equivale a la pérdida
   irreversible de los certificados de todos los inquilinos.
3. **La copia sellada se verifica en cada prueba anual** (sección 7): se abre, se
   confirma que la clave sirve, y se vuelve a sellar con fecha nueva. Una clave
   custodiada que nadie ha verificado en dos años no es una clave custodiada; es
   una suposición.

### Custodio

| Rol | Responsabilidad |
|---|---|
| Custodio principal | *(pendiente de designar)* Genera las claves, mantiene la copia operativa, ejecuta la prueba anual |
| Custodio suplente | *(pendiente de designar)* Acceso a la copia sellada, actúa si el principal no está disponible |

Mientras estos dos nombres estén en blanco, el plan de continuidad tiene un
agujero que ningún script puede tapar.

### Rotación

`PLAN.md` (paso 5) fija rotación semestral de secretos. Distinguir dos casos, o la
rotación se vuelve un incidente:

- `SECRET_KEY`, contraseñas de base de datos, `BUZON_WEBHOOK_SECRET` y tokens de
  terceros: se cambian y listo. El único efecto de rotar `SECRET_KEY` es que todos
  vuelven a iniciar sesión.
- `CERT_ENC_KEY`, `BUZON_ENC_KEY` y `TOTP_ENC_KEY`: **cambiarlas sin más destruye
  el acceso a lo ya cifrado.** Rotarlas exige descifrar con la clave vieja y
  recifrar con la nueva, en una ventana controlada, conservando la clave vieja
  hasta confirmar que todo el contenido migró. No hay herramienta para esto
  todavía; escribirla es un pendiente conocido, y hasta entonces estas tres claves
  no se rotan.

---

## 7. Registro de la prueba anual de recuperación

El control A.5.30 no se satisface con el documento: se satisface **ejecutándolo**.
`PLAN.md` pide probarlo una vez y guardar la evidencia; a partir de ahí, una vez al
año y después de cualquier cambio grande de infraestructura.

La prueba se hace sobre un VPS desechable, con un respaldo real, y **sin consultar
notas que no estén en este documento**. Si durante la prueba hizo falta averiguar
algo que no está escrito aquí, ese hallazgo se anota y el documento se corrige: ese
es el verdadero producto de la prueba.

Qué se guarda como evidencia: la hora de inicio y fin, la salida de las ocho
comprobaciones del paso 12, y la lista de lo que falló o faltó.

| Fecha | Quién la ejecutó | Escenario probado | Respaldo usado (fecha y hora) | RTO medido | RPO observado | Comprobaciones 1–8 | Hallazgos y correcciones | Firma |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
| | | | | | | | | |
| | | | | | | | | |
| | | | | | | | | |

**La primera fila sigue vacía, y es la casilla más importante de todo el
documento.** Este plan no ha sido probado nunca. Hasta que se ejecute una vez de
principio a fin, los tiempos de la sección 4 son estimaciones razonadas, no hechos
medidos, y el control A.5.30 sigue abierto.
