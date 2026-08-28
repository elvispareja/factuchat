# Procedimiento de respaldo y restauración — Factuchat

Versión 1.0 · Controles ISO 27001 Anexo A: **A.8.13** (copias de respaldo) y **A.5.30**
(continuidad TIC) · Implementa el paso 6 de la lista de despliegue de [PLAN.md](../PLAN.md).

> **Estado honesto a la fecha de esta versión.** El procedimiento está definido y sus
> scripts escritos, pero **todavía no está en operación**: el despliegue en el VPS no se
> ha hecho, el par de claves de cifrado no se ha generado y el almacenamiento externo no
> está contratado. La tabla de pruebas mensuales de la sección 9 está **vacía a
> propósito**: se llena con ejecuciones reales, no con promesas. El detalle completo de
> lo que falta está en la sección 10.

---

## 1. Por qué un respaldo solo de la base de datos no sirve

Factuchat guarda el **dato** en PostgreSQL y el **documento** en disco. La tabla
`comprobantes` no contiene el XML firmado: contiene la ruta al fichero que lo contiene.
La ruta la construye `ruta_almacen()` en `backend/app/services/emision.py:467`:

```
STORAGE_DIR / {tenant_id} / {clave_acceso}.{xml|pdf}
```

Lo mismo pasa con el buzón. `_ruta_payload()` en `backend/app/buzon/ingesta.py:52` deja el
correo entrante cifrado en `STORAGE_DIR/buzon/{tenant_id}/{correo_id}.eml.enc`, y el XML
de la retención en `{retencion_id}.xml.enc` (línea 365). En la base solo quedan los campos
leídos del documento y la ruta.

Un respaldo que se lleve únicamente el volcado de PostgreSQL restaura filas que apuntan a
ficheros que ya no existen. En la práctica:

- `GET /api/v1/comprobantes/{id}/ride` responde error: el PDF no está.
- El XML autorizado —el documento con valor tributario, cuyo hash SHA-256 sí sobrevive en
  la base porque la migración `0003_motor_emision.py` lo guarda— desaparece. Queda la
  huella sin el original.
- El visor de XML crudo del buzón no puede mostrar nada: el contenido del correo **no vive
  en ninguna columna** a propósito (ver SECURITY.md, A04), así que sin el fichero `.enc` la
  retención pierde su documento de respaldo justo cuando el SRI lo pida.

Al revés también hay que entenderlo: **el certificado de firma .p12 NO está en disco**.
Vive en la base, en la tabla `certificados`, cifrado AES-256-GCM en las columnas
`p12_data_enc` y `p12_password_enc` (`backend/app/db/models/certificado.py:25-26`). O sea
que el volcado de PostgreSQL sí se lleva los certificados de todos los inquilinos, en
forma cifrada. Eso condiciona todo lo demás de este documento.

| Qué | Dónde vive de verdad | Consecuencia si falta |
|---|---|---|
| Filas de negocio, bitácora `audit_log`, certificados .p12 cifrados, secretos TOTP cifrados | PostgreSQL | Sin base no hay sistema |
| XML firmados y RIDE en PDF | Volumen `comprobantes`, subcarpeta `{tenant_id}/` | Filas huérfanas; se pierde el documento tributario |
| Correos y XML del buzón, cifrados con `BUZON_ENC_KEY` | Volumen `comprobantes`, subcarpeta `buzon/{tenant_id}/` | Retenciones sin documento fuente |
| Comprobantes de pago subidos en el checkout público | Volumen `comprobantes`, subcarpeta `comprobantes-pago/` (`backend/app/api/routes/publico.py:237`) | Pedidos por transferencia sin prueba de pago |

Los tres subárboles están en **un solo volumen** de Docker, `comprobantes`, declarado al
final de `deploy/docker-compose.prod.yml` y montado en `api` y `worker` sobre
`/var/factuchat/storage`. Con el nombre de proyecto `factuchat` que fija ese mismo archivo,
el volumen real se llama `factuchat_comprobantes`.

---

## 2. Qué se respalda

| Activo | Origen | Frecuencia | Retención |
|---|---|---|---|
| Volcado completo de PostgreSQL (`pg_dump --format=custom`) | Servicio `postgres` | Cada 6 horas | 7 días |
| Volumen `factuchat_comprobantes` entero | Volumen | Cada 6 horas (copia completa) | 7 días |
| Volumen `factuchat_nginx-logs` entero | Volumen | Cada 6 horas (copia completa) | 7 días |
| La corrida de las 06:00 UTC, marcada `-diario` | Base + los dos volúmenes | Diaria | **30 días** |
| Evidencia de la prueba de restauración | Este documento | Mensual | Indefinida |

Notas que explican las decisiones:

**Por qué el volumen también entra en el ciclo de 6 horas.** Si la base se respalda cada 6
horas y los ficheros solo una vez al día, una restauración a media tarde devuelve filas de
comprobantes emitidos esa mañana cuyo XML y cuyo RIDE no están en la copia. Es exactamente
el problema de la sección 1, pero autoinfligido. Los ficheros del almacén son inmutables
una vez escritos —un reintento de emisión genera documento nuevo con clave nueva, nunca
edita el anterior—, así que la copia sale barata aunque se tome entera cada vez.

**No hay respaldo incremental, y es deliberado.** `respaldo.sh` empaqueta el volumen
completo en cada corrida (`tar -C /datos -czf -`): no lleva lista de lo copiado antes ni
marca de qué fichero es nuevo. Cada carpeta de copia se basta a sí misma, que es justo lo
que hace la restauración simple y segura. La copia marcada `-diario` no se diferencia en
contenido de las demás —todas son completas—, solo en retención: 30 días frente a 7. Así no
hay cadena que encadenar ni corrida perdida que la rompa.

**Los logs de nginx ya entran en el respaldo, pero todavía no llegan a 12 meses.** El
control A.8.15 pide 12 meses de trazabilidad. Los logs salen en JSON estructurado
(`deploy/nginx/nginx.conf`, directiva `log_format json_log`) hacia el volumen `nginx-logs`,
que es un volumen de Docker: la regla de logrotate del paso 9 apunta a `/var/log/factuchat`
y nunca lo alcanza. Por eso `respaldo.sh` lo lleva en `VOLUMENES_FICHEROS` junto a
`comprobantes`; sin eso, los registros de acceso no se rotarían ni se copiarían. Lo que
hereda, sin embargo, es la retención del respaldo: 7 días intradía y 30 en la copia
`-diario`. **Los 12 meses siguen pendientes** y salen de una de dos vías: un archivo mensual
aparte con su propia retención, o montar `/var/log/factuchat/nginx:/var/log/nginx` en el
servicio `nginx` del compose para que logrotate tenga qué rotar. Anotado en la sección 10.

**La bitácora inmutable viaja dentro del volcado.** `audit_log` es una tabla más del
volcado, y es la evidencia de A09 y de LOPDP: quién tocó qué, con antes y después. No
necesita tratamiento aparte, pero conviene saber que perder el volcado es perder la
bitácora.

---

## 3. Qué NO se respalda, y por qué

| Activo | Decisión | Motivo |
|---|---|---|
| `.env` (secretos) | **Fuera del respaldo**, custodia separada | Sección 4 |
| Redis | No se respalda | Estado transitorio, no verdad del sistema |
| Volúmenes `certs` y `acme` (Let's Encrypt) | No se respalda | Se vuelve a emitir por ACME |
| Volumen `static` | No se respalda | Se reconstruye desde el repositorio |
| Imágenes Docker y código | No se respalda | Salen de git y de las etiquetas fijadas en `deploy/.env.example` (fijarlas por digest sigue pendiente) |

**El `.env` va aparte, y esta es la decisión más importante del documento.** Un juego
completo de respaldo se lleva material cifrado muy sensible: el .p12 y los secretos TOTP de
**todos** los inquilinos viajan en el volcado de PostgreSQL, y los correos y XML del buzón
viajan en el volumen. Las claves que abren esos tres cifrados —`CERT_ENC_KEY`,
`TOTP_ENC_KEY` y `BUZON_ENC_KEY`— viven únicamente en el `.env`. Meter el `.env` dentro del
respaldo pone el candado y la llave en la misma caja: cada copia pasaría a ser, por sí
sola, el compromiso completo del sistema. Quien consiga **un** juego de respaldo tendría la
firma electrónica de todos los clientes. Con el `.env` fuera, un respaldo robado es un
montón de texto cifrado.

**Redis no se respalda porque no es la verdad de nada.** Guarda la cola de Celery, los
candados por comprobante, los contadores de rate limit y el estado del circuit breaker
hacia el SRI. En producción arranca con `--appendonly no`
(`deploy/docker-compose.prod.yml`, servicio `redis`), o sea que ni siquiera persiste de
forma durable a propósito. Restaurar una cola vieja sería peor que no restaurarla:
reinyectaría tareas ya ejecutadas. El estado durable está en PostgreSQL, y los comprobantes
que quedaron a medio camino los recoge la tarea periódica `barrer_atascados`
(`backend/app/tasks/emision.py:393`, programada cada 10 minutos en el beat).

**Los certificados TLS se vuelven a emitir.** Un certificado de Let's Encrypt se renueva
solo con el desafío ACME; restaurarlo no aporta y arrastra el riesgo de reinstalar una
clave privada vieja. Único cuidado: Let's Encrypt tiene límites de emisión por dominio, así
que no conviene repetir restauraciones de prueba contra el dominio real. Las pruebas de
restauración se hacen sin TLS o con un dominio de prueba.

**El código y las imágenes salen del repositorio.** Restaurar binarios desde una copia
rompería el control de A08 «despliegue solo desde el repositorio» (SECURITY.md). La
recuperación clona el repo en el commit correspondiente y reconstruye.

---

## 4. Las claves sin las cuales el respaldo no sirve para nada

Sacar el `.env` del respaldo resuelve un problema y crea otro: si se pierde el `.env`, el
respaldo es indescifrable. Las dos mitades hay que decirlas juntas.

| Secreto | Qué deja de funcionar si se pierde |
|---|---|
| `CERT_ENC_KEY` | Los .p12 de `certificados` no se pueden abrir: nadie firma. Cada inquilino tendría que volver a subir su certificado y su contraseña |
| `BUZON_ENC_KEY` | Los `.eml.enc` y `.xml.enc` del buzón quedan ilegibles: las retenciones recibidas pierden su documento fuente |
| `TOTP_ENC_KEY` | Los secretos TOTP quedan ilegibles. Como el 2FA es **obligatorio** para SUPERADMIN (`backend/app/services/auth.py`, `TotpSetupRequired`), el equipo interno se queda fuera y hay que re-enrolar por CLI |
| `APP_DB_PASSWORD` / `DATABASE_URL` | La aplicación no se conecta: la contraseña con la que se recree el rol `factuchat_app` tiene que ser la misma que lleva `DATABASE_URL` (ver sección 8, paso 4) |
| `SECRET_KEY` | Se invalidan las sesiones JWT en curso. Molesto, no fatal: todos vuelven a iniciar sesión |

Regla de custodia: **la copia del `.env` y la clave privada de descifrado no pueden vivir
en el VPS, ni en el mismo lugar donde se guardan los respaldos.** Si están junto a los
respaldos, el cifrado es decorativo. Van en un gestor de contraseñas del equipo o en sobre
sellado, con al menos dos custodios, y se actualizan cada vez que se rote un secreto (la
rotación semestral es el paso 5 de la lista de despliegue).

---

## 5. Cifrado con `age`: la pública en el VPS, la privada fuera

El par de claves se genera en una máquina de administración, **nunca en el VPS**:

```bash
age-keygen -o factuchat-respaldos.key   # imprime la clave pública age1...
```

- La **clave pública** (`age1...`) se copia al VPS, por ejemplo en
  `/etc/factuchat/respaldo.pub`, con permisos de lectura para el usuario que corre el
  respaldo. Con ella el servidor puede **cifrar**, y nada más.
- La **clave privada** (`factuchat-respaldos.key`) se queda fuera del VPS, en la misma
  custodia que el `.env`. Y se guarda por duplicado: una clave privada perdida convierte
  todo el histórico de respaldos en ruido.

El porqué es directo: si la clave privada vive en el servidor, quien tome el servidor toma
también todos los respaldos, y entonces el respaldo externo deja de proteger contra el
único escenario para el que se hizo —que alguien entre al VPS y borre o robe. Con este
esquema, un atacante con control del VPS puede crear respaldos nuevos, pero no leer los
viejos.

```bash
# Cifrar (en el VPS)
... | age -R /etc/factuchat/respaldo.pub -o respaldo.age

# Descifrar (en la máquina de recuperación, nunca en el VPS)
age -d -i factuchat-respaldos.key bd.dump.age > bd.dump
```

Prohibición explícita, porque es la tentación clásica: no se sube la clave privada al VPS
«un momento, solo para probar la restauración». Las restauraciones se prueban en otra
máquina (sección 8, paso 0).

---

## 6. Destino externo, RPO y RTO

El destino tiene que estar **fuera del VPS**. Requisitos que debe cumplir el que se
contrate:

1. La credencial que vive en el VPS puede **escribir y crear**, no borrar ni sobrescribir.
   Un atacante que tome el servidor no debe poder vaciar el histórico.
2. Versionado o bloqueo de objetos si el proveedor lo ofrece.
3. Preferiblemente un proveedor distinto al del VPS: si se compromete la cuenta, no se
   pierden las dos cosas a la vez.
4. Borrado automático por política de retención, no a mano.

| Parámetro | Valor |
|---|---|
| Proveedor y bucket / servidor destino | **Por definir** — se anota aquí antes del primer despliegue |
| RPO (pérdida máxima aceptada) | 6 horas |
| RTO objetivo (servicio en un VPS nuevo) | 4 horas (paso 10 de PLAN.md) |
| RTO medido | **Sin medir**: se obtiene en la primera prueba de la sección 9 |

Sobre el RPO, con honestidad: seis horas de pérdida en un sistema de facturación son
comprobantes emitidos que no aparecen. Hay un atenuante real y una limitación real. El
atenuante: un comprobante en estado AUTORIZADO también existe en el SRI, así que el hecho
tributario no desaparece del mundo aunque desaparezca de Factuchat, y el cliente puede
consultarlo con su clave de acceso. La limitación: **Factuchat no tiene hoy ninguna
herramienta para reimportar desde el SRI un comprobante perdido**. El cliente del SRI sabe
preguntar por una clave de acceso (`backend/app/sri/client.py`, usado por `_sri_no_lo_tiene`
en `backend/app/tasks/emision.py`), pero no existe un comando que reconstruya filas a
partir de eso. Queda anotado como pendiente en la sección 10.

---

## 7. Procedimiento de respaldo

Implementado en **`deploy/scripts/respaldo.sh`**, pensado para el crontab de **root** del VPS
(`5 0,6,12,18 * * *`): a las 00:05, 06:05, 12:05 y 18:05 **UTC**, que en Ecuador son las
19:05, 01:05, 07:05 y 13:05. El minuto 05 evita el minuto en punto, cuando arranca todo el
mundo sus tareas; el crontab es el de root y no el del usuario de operación porque para
hablar con Docker haría falta meterlo en el grupo `docker`, y eso equivale a root sin
contraseña.

No existe una corrida diaria aparte: la de las **06:00 UTC** —la 01:00 de acá, la hora más
tranquila— es la que el script marca con el sufijo `-diario` y retiene 30 días, porque
`HORA_DIARIA_UTC` vale `06`. Si se cambia el horario del cron hay que mover
`HORA_DIARIA_UTC` en la misma proporción: si ninguna corrida cae en esa hora, no se crea
jamás una carpeta `-diario`, la copia de 30 días nunca existe y el fallo es silencioso,
porque los respaldos intradía se siguen tomando con normalidad.

Las reglas que el script tiene que respetar, y el motivo de cada una:

**1. El volcado se toma con el rol propietario `factuchat`, nunca con `factuchat_app`.**
Esto no es preferencia, es que no funciona de otra forma. Comprobado sobre el entorno de
desarrollo el 2026-08-25:

```
$ pg_dump -U factuchat_app -d factuchat ...
pg_dump: error: query failed: ERROR:  permission denied for table alembic_version
```

El rol de la aplicación ni siquiera tiene permiso sobre la tabla de migraciones, que es
justo lo que se espera de él. Y aunque lo tuviera, tampoco funcionaría: `pg_dump` fija
`row_security = off`, y un rol sin `BYPASSRLS` recibe un error en lugar de un volcado
parcial. Comprobado también:

```
$ psql -U factuchat_app -c "SET row_security = off; SELECT count(*) FROM comprobantes;"
SET
ERROR:  query would be affected by row-level security policy for table "comprobantes"
```

Que falle así es bueno: PostgreSQL prefiere negarse a entregar un volcado incompleto.

**2. Jamás usar `--enable-row-security` en `pg_dump`.** Ese flag hace que el volcado
*funcione* estando sujeto a RLS: en vez de fallar, produce un archivo que contiene
únicamente las filas visibles en el contexto de tenant actual —es decir, prácticamente
ninguna, porque `app_tenant()` devuelve NULL sin GUC. Un respaldo que parece correcto y
está vacío es peor que uno que falla.

**3. `set -euo pipefail`, sin excepción.** En una tubería
`pg_dump | gzip | age`, sin `pipefail` el código de salida es el de `age`, que devuelve 0
aunque `pg_dump` haya muerto a la mitad. El resultado es un archivo cifrado, de tamaño
plausible, que contiene un volcado truncado. Es el fallo clásico de los respaldos y solo se
descubre el día que hacen falta.

**4. Nada sin cifrar toca el disco.** El volcado sale de `pg_dump` ya comprimido
(`--compress=6`) y va por tubería directa a `age`; los volúmenes van por `tar -czf -` y de
ahí a `age`. Si por alguna razón hiciera falta un temporal, va en un directorio 0700
propiedad de root y se borra en un `trap` de salida.

**5. La corrida registra su huella.** Antes de subir, se calcula el SHA-256 del archivo
cifrado y se guarda junto al índice de respaldos. En la restauración se vuelve a calcular
sobre lo descargado: es la única forma de saber que el archivo llegó entero, porque en el
VPS no se puede descifrar para comprobarlo.

**6. Un fallo tiene que hacer ruido.** Salida distinta de cero manda aviso al administrador
por el mismo canal que el resto de alertas (paso 7 de la lista de despliegue). Un respaldo
que falla en silencio es un respaldo que no existe.

---

## 8. Procedimiento de restauración, paso a paso

Implementado en **`deploy/scripts/restaurar.sh`**. Requisitos previos: la clave privada de
`age`, la copia del `.env` en custodia, acceso al repositorio y una máquina destino.

### Paso 0 — Elegir dónde se restaura

En una prueba mensual, **nunca sobre producción**. Se restaura en un VPS o una máquina
aparte. Restaurar «encima para ver si funciona» convierte un simulacro en un incidente.

### Paso 1 — Traer los archivos y verificar su integridad

Se descarga **una sola carpeta de copia**: la de la marca UTC que se quiera restaurar. Cada
carpeta es completa y se basta a sí misma —no hay incrementales que encadenar— y
`restaurar.sh` recibe exactamente una como argumento. Dentro está `manifiesto.txt`, que va
en claro justamente para esto: trae el SHA-256 de cada fichero cifrado y del contenido en
claro, además de la revisión de Alembic y las cuentas de filas de origen. Se recalcula el
SHA-256 de cada `.age` descargado y se compara con el del manifiesto, como dice el paso 5 de
la sección 7. Un archivo que no cuadra no se usa: se baja de nuevo o se retrocede a la copia
anterior.

### Paso 2 — Descifrar

```bash
# La base es un pg_dump --format=custom, comprimido por dentro: NI gzip NI SQL
age -d -i factuchat-respaldos.key <copia>/bd.dump.age > bd.dump

# Los volúmenes sí son tar comprimidos con gzip
age -d -i factuchat-respaldos.key <copia>/comprobantes.tar.gz.age | gzip -dc | tar -xf -
```

En la máquina de recuperación. Nunca en el VPS de producción. Tras descifrar se compara el
SHA-256 de `bd.dump` con el que anota `manifiesto.txt` en `sha256_claro_bd`, y el de cada
volumen con `sha256_claro_<volumen>`: es la comprobación de que el archivo llegó entero y
sin alterar, y es la única prueba real de que la clave privada custodiada abre los
respaldos. `restaurar.sh` hace las dos comparaciones por su cuenta y aborta si no cuadran.

### Paso 3 — Levantar la infraestructura desde el repositorio

```bash
git clone <repo> factuchat && cd factuchat
# .env recuperado de la custodia, permisos 600 propiedad root
install -m 600 -o root -g root /ruta/custodia/.env deploy/.env
docker compose -f deploy/docker-compose.prod.yml up -d postgres
```

Sobre un volumen `pgdata` **vacío**, PostgreSQL ejecuta `deploy/postgres/init/01-roles.sh`,
que crea `factuchat_app` con la contraseña de `APP_DB_PASSWORD` y `factuchat_security`.

### Paso 4 — Comprobar que los tres roles existen ANTES de restaurar

Este es el paso que la gente se salta, y el que deja la aplicación muerta después de una
restauración que «salió bien».

**`pg_dump` no exporta roles.** Los roles son objetos del clúster, no de la base de datos.
Medido sobre el volcado del entorno de desarrollo el 2026-08-25:

| En el volcado | Cantidad |
|---|---|
| `CREATE ROLE` | **0** |
| `GRANT ... TO factuchat_app` / `factuchat_security` | 71 |
| `ALTER FUNCTION ... OWNER TO factuchat_security` | 26 |
| `CREATE POLICY` | 44 |
| `ENABLE` / `FORCE ROW LEVEL SECURITY` | 54 |

O sea: el volcado da por hecho que los roles existen y falla si no están. Verificado:

```
$ psql -c "GRANT USAGE ON SCHEMA public TO rol_que_no_existe;"
ERROR:  role "rol_que_no_existe" does not exist
```

Y hay una variante peor que el fallo limpio. **Si se restaura sin `--exit-on-error`** —o sin
`ON_ERROR_STOP=1`, si alguien convirtió antes el volcado a SQL plano—, la carga sigue
adelante y solo deja avisos: las tablas y los datos entran, pero fallan los 71 `GRANT` y los
26 `ALTER FUNCTION ... OWNER TO`. Queda una base que parece restaurada y en la que:

- Las 26 funciones `SECURITY DEFINER` —las `auth_*`, `sa_*` y `sys_*` que verifican el rol
  real en base de datos y escriben en `audit_log`— quedan **propiedad del superusuario del
  clúster** en lugar de `factuchat_security`. Ejecutarlas pasaría a correr con privilegios
  de superusuario, mucho más de lo que el diseño concede.
- `factuchat_app` no tiene `EXECUTE` sobre ellas, así que el login no funciona igual.

Comprobación obligatoria antes de restaurar (salida esperada al lado):

```sql
SELECT rolname, rolcanlogin, rolbypassrls, rolsuper
FROM pg_roles WHERE rolname LIKE 'factuchat%' ORDER BY 1;
```

| rolname | login | bypassrls | super |
|---|---|---|---|
| `factuchat` | t | t | t |
| `factuchat_app` | t | **f** | f |
| `factuchat_security` | **f** | t | f |

Si el volumen `pgdata` no estaba vacío, el script de init **no se ejecuta** —solo corre en
la primera inicialización de un directorio de datos vacío— y hay que crear los roles a
mano, con los mismos atributos que `deploy/postgres/init/01-roles.sh`:

```sql
CREATE ROLE factuchat_app LOGIN PASSWORD '<el mismo APP_DB_PASSWORD del .env>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE factuchat_security NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
GRANT USAGE ON SCHEMA public TO factuchat_app;
GRANT USAGE ON SCHEMA public TO factuchat_security;
```

La contraseña tiene que coincidir exactamente con la de `DATABASE_URL` en el `.env`
restaurado. Si no coincide, todo lo demás sale bien y la API no arranca.

### Paso 5 — Restaurar la base

```bash
pg_restore -U factuchat -d factuchat --single-transaction --exit-on-error bd.dump
```

`pg_restore` y no `psql -f`, porque el volcado está en formato custom. `--single-transaction`
es lo que hace que o entre todo o no entre nada: una restauración a medias es el peor
resultado posible, porque parece que funciona. Es la misma orden que ejecuta `restaurar.sh`.

Con el rol `factuchat`, que es superusuario. Este es el único momento del sistema en que
saltarse RLS es lo correcto: la carga escribe filas de todos los inquilinos y no hay ningún
contexto de tenant fijado, así que las políticas —que exigen `tenant_id = app_tenant()`—
rechazarían absolutamente todo. Restaurar como `factuchat_app` es imposible, no
desaconsejable.

El contrapeso está en el paso 7: precisamente porque se restauró con un rol que lo ve todo,
la verificación **no puede hacerse con ese rol**.

### Paso 6 — Restaurar el volumen de ficheros

El contenido se descomprime dentro del volumen `factuchat_comprobantes`, respetando los
tres subárboles (`{tenant_id}/`, `buzon/`, `comprobantes-pago/`).

Cuidado con la propiedad de los ficheros: los contenedores `api` y `worker` corren como el
usuario no privilegiado `factuchat` creado en `backend/Dockerfile` (`useradd -r` en la línea
17; `USER factuchat` en la línea 35, que es la etapa `prod` que usa el compose), no como
root. Si los ficheros quedan propiedad de root, la API no puede leerlos y el worker no
puede escribir junto a ellos. El UID concreto lo asigna `useradd -r` al construir la imagen,
así que se consulta en vez de suponerlo:

```bash
# 1. UID y GID reales del usuario dentro de la imagen
docker compose -f deploy/docker-compose.prod.yml run --rm -T --entrypoint sh api \
  -c 'id -u; id -g'

# 2. Descomprimir dentro del volumen y dejar el dueño correcto, con un
#    contenedor auxiliar que sí corre como root
docker run --rm \
  -v factuchat_comprobantes:/destino \
  -v "$PWD":/origen:ro \
  alpine sh -c 'tar -xzf /origen/comprobantes.tar.gz -C /destino \
                && chown -R <uid>:<gid> /destino'
```

En la práctica lo resuelve `restaurar.sh`, que extrae con `--same-owner` desde un contenedor
que corre como root y así conserva el dueño original de cada fichero; lo que no puede quedar
es la carpeta con dueño equivocado. La copia trae también `nginx-logs.tar.gz.age`, y
`restaurar.sh` restaura todos los volúmenes que anote el manifiesto en `volumenes=`, no solo
`comprobantes`.

### Paso 7 — Verificar como `factuchat_app`, no como superusuario

El segundo error clásico. Conectado como `factuchat` todo funciona, todas las filas se ven
y todas las comprobaciones pasan: eso no dice nada sobre si la aplicación va a funcionar.
La verificación se hace **con el rol que usa la aplicación**.

```sql
-- 1. Conectar como factuchat_app: ya prueba que la contraseña coincide con el .env

-- 2. Sin contexto de tenant no se debe ver nada
SELECT count(*) FROM comprobantes;                  -- esperado: 0

-- 3. Con contexto, solo lo de ese inquilino
SET app.tenant_id = '<uuid de un tenant conocido>';
SELECT count(*) FROM comprobantes;                  -- esperado: solo los suyos

-- 4. La bitácora sigue siendo inmutable
UPDATE audit_log SET accion = 'x';                  -- esperado: ERROR audit_log es inmutable
```

Y como superusuario, las tres comprobaciones estructurales (valores del entorno actual, a
la altura de la migración `0009`):

```sql
SELECT count(*) FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
 WHERE r.rolname = 'factuchat_security';            -- esperado: 26
SELECT count(*) FROM pg_class
 WHERE relrowsecurity AND relforcerowsecurity
   AND relnamespace = 'public'::regnamespace;       -- esperado: 27
SELECT count(*) FROM pg_policies WHERE schemaname = 'public';  -- esperado: 44
```

Si el número de funciones propiedad de `factuchat_security` no da 26, la restauración
arrastró el fallo del paso 4 y hay que rehacerla. El equivalente automatizado de estas
comprobaciones es `backend/tests/test_rls.py::TestAislamientoPostgres`, que se puede correr
contra la base restaurada.

### Paso 8 — Comprobar la coherencia entre base y ficheros

Es lo que detecta el fallo de la sección 1. Para una muestra de comprobantes en estado
AUTORIZADO, verificar que el XML y el RIDE existen realmente en el volumen, y que al menos
un `.eml.enc` del buzón está donde dice la fila. Una restauración con la base al día y el
volumen de anteayer pasa todas las pruebas del paso 7 y falla aquí.

### Paso 9 — Levantar el resto y probar de punta a punta

```bash
docker compose -f deploy/docker-compose.prod.yml up -d
```

Con el healthcheck de `api` en verde (`/api/v1/health`), la prueba mínima es:

1. Inicio de sesión de un SUPERADMIN con su 2FA → prueba que `TOTP_ENC_KEY` es la correcta.
2. Descarga de un RIDE ya emitido → prueba el volumen y la coherencia con la base.
3. Apertura de un XML crudo del buzón → prueba `BUZON_ENC_KEY`.
4. Firma de un comprobante → prueba `CERT_ENC_KEY`, que es la única forma de confirmar que
   los .p12 restaurados siguen siendo utilizables. El guion está en
   [`deploy/scripts/emision-prueba-sri.md`](../deploy/scripts/emision-prueba-sri.md), contra
   el ambiente PRUEBAS del SRI.

Si el punto 4 no se puede hacer todavía por falta de certificado real, se hace con un .p12
de pruebas y **se anota en la casilla de incidencias** que la prueba de firma fue parcial.
No se da por buena en silencio.

### Paso 10 — Destruir el entorno de prueba y anotar el resultado

Un entorno restaurado contiene datos personales reales de clientes finales (LOPDP) y los
certificados de firma de todos los inquilinos. Dejarlo encendido «por si acaso» es crear
una segunda producción que nadie vigila y que nadie endureció. Se apaga, se borran los
volúmenes y se borran los archivos descifrados del disco. Después se llena la fila del
registro de la sección 9.

---

## 9. Registro de pruebas de restauración

Una prueba al mes, en la primera semana. **Este registro es la evidencia que pide el
auditor**: el procedimiento escrito demuestra intención, la tabla llena demuestra que
funciona.

Reglas de llenado:

- Una prueba fallida se registra como fallida. Un registro vacío es honesto; uno maquillado
  es una no conformidad grave y, peor, esconde un respaldo que no sirve.
- Cada incidencia lleva acción correctiva y una re-prueba que también se anota.
- «Tiempo hasta servicio» se mide desde que se empieza a descargar hasta que la
  comprobación del paso 9 pasa. Es el RTO real, y es el número que hay que comparar contra
  las 4 horas objetivo.

| Fecha | Quién | Respaldo usado (fecha y hora) | Resultado | Tiempo hasta servicio | Incidencias y acción correctiva |
|---|---|---|---|---|---|
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |

---

## 10. Estado de implementación

| Elemento | Estado |
|---|---|
| Procedimiento definido y documentado | Hecho: este documento |
| `deploy/scripts/respaldo.sh` y `deploy/scripts/restaurar.sh` | Escritos en esta misma fase de despliegue. Antes de la primera corrida en el VPS hay que confirmar que coinciden con lo definido aquí; si difieren, se corrige el que esté mal |
| Par de claves `age` generado y custodiado | **Pendiente**: se genera al desplegar |
| Almacenamiento externo contratado | **Pendiente**: proveedor sin definir (sección 6) |
| Cron instalado en el VPS | **Pendiente**: el despliegue en el VPS no se ha hecho |
| Custodia del `.env` y de la clave privada | **Pendiente**: se formaliza al desplegar |
| Retención de 12 meses de los logs de nginx (A.8.15) | **Pendiente**: `respaldo.sh` ya copia el volumen `nginx-logs` en cada corrida, pero con la retención del respaldo (7 días intradía, 30 en la copia `-diario`). Falta el archivo mensual aparte, o montar `/var/log/factuchat/nginx:/var/log/nginx` en el servicio `nginx` para que logrotate lo alcance (sección 2) |
| Primera prueba de restauración | **Pendiente**: la tabla de la sección 9 está vacía |
| RTO medido | **Sin medir** |
| Reimportación de comprobantes desde el SRI | **No existe.** Hay consulta por clave de acceso en `backend/app/sri/client.py`, pero ningún comando que reconstruya filas perdidas a partir de ella |
| Alerta activa ante fallo del respaldo | **Pendiente**: depende del canal de avisos del paso 7 de PLAN.md, que sigue siendo la casilla abierta de A09 en SECURITY.md |

Dependencias externas que afectan a este procedimiento y que **no dependen del código**:

- **Dominio definitivo sin confirmar** (`APP_DOMAIN` está vacío en `backend/.env.example`, y
  las maquetas usan tres dominios distintos). Afecta a los certificados TLS de la máquina de
  restauración y a las direcciones del buzón.
- **No hay certificado .p12 real todavía.** Hasta que lo haya, la prueba de firma del paso 9
  solo puede hacerse con un certificado de pruebas, y así debe anotarse.
- **Faltan las credenciales de Meta para WhatsApp** y **falta contratar el proveedor de
  correo entrante del buzón**. Ninguno de los dos bloquea el respaldo, pero un entorno
  restaurado no podrá ejercitar esos dos caminos de punta a punta.

Este documento se revisa al cerrar el despliegue y cada vez que cambie el modelo de datos,
se añada un volumen o se rote una clave.
