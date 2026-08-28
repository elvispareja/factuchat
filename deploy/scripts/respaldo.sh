#!/usr/bin/env bash
#
# respaldo.sh — Respaldo cifrado de Factuchat (paso 6 de PLAN.md, control A.8.13)
# =============================================================================
#
# QUÉ RESPALDA Y POR QUÉ
# ----------------------
# 1. La base de datos, con `pg_dump` en formato custom. NO se copia el volumen
#    `pgdata` con tar: copiar en caliente el directorio de datos de PostgreSQL
#    produce un respaldo roto (páginas a medio escribir, WAL desincronizado).
#    `pg_dump` corre dentro de una transacción y da una foto consistente.
#
# 2. El volumen `comprobantes`. Ahí viven los XML firmados y los RIDE de cada
#    inquilino (`STORAGE_DIR`, ver docker-compose.prod.yml). Una fila de
#    `comprobantes` que apunte a un XML autorizado que ya no existe no sirve de
#    nada: el XML es el documento con valor tributario, la fila solo lo indexa.
#
#    AVISO IMPORTANTE sobre el buzón: NO existe un volumen `buzon` aparte. Los
#    correos del buzón SRI se guardan cifrados dentro del MISMO volumen
#    `comprobantes`, en `${STORAGE_DIR}/buzon/<tenant_id>/<correo_id>.eml.enc` (correo crudo)
#    y `<retencion_id>.xml.enc` (XML de la retención)
#    (backend/app/buzon/ingesta.py, `_ruta_payload`). Los comprobantes de pago
#    que suben los clientes desde la landing también, en
#    `${STORAGE_DIR}/comprobantes-pago/` (backend/app/api/routes/publico.py).
#    Respaldando `comprobantes` quedan los tres cubiertos. Si algún día se
#    separan en volúmenes distintos, añádelos a VOLUMENES_FICHEROS.
#
# 3. NO se respaldan: `certs` y `acme` (Let's Encrypt reemite en minutos),
#    ni `static` (sale del build). `nginx-logs` SÍ se respalda, más abajo: es
#    un volumen de Docker y la regla de logrotate del paso 9 apunta a
#    /var/log/factuchat, así que nunca lo alcanza — y son la evidencia de A.8.15.
#
# CIFRADO — POR QUÉ `age` CON CLAVE PÚBLICA
# -----------------------------------------
# Se cifra con la clave PÚBLICA del destinatario. La clave PRIVADA no está en
# el VPS y no debe estarlo nunca: si estuviera, quien tome el servidor se lleva
# el servidor Y todo el histórico de respaldos. Con solo la pública, el servidor
# puede crear respaldos pero no leerlos. Esa clave privada vive fuera (gestor de
# contraseñas del responsable, copia impresa en sobre sellado, o ambas) y es el
# secreto más valioso de la operación: sin ella los respaldos son basura.
#
# Consecuencia honesta y deliberada: aquí NO se puede verificar de verdad que un
# respaldo se descifra, porque hacerlo exigiría la clave privada. Lo que sí se
# verifica en cada corrida es que el fichero no está vacío, que su cabecera es
# un contenedor `age` válido dirigido a un destinatario, y que su SHA-256 queda
# anotado para comprobarlo en destino. La prueba real de descifrado es la
# restauración mensual FUERA del VPS (pasos 6 y 10 de PLAN.md), con restaurar.sh.
# Para hacerla desde la máquina del operador: AGE_IDENTIDAD_PRUEBA=/ruta/clave
# y este script hará el descifrado completo más `pg_restore --list`.
#
# EL .env NO ENTRA EN EL RESPALDO (INCLUIR_ENV=false por omisión)
# --------------------------------------------------------------
# El .env guarda CERT_ENC_KEY, BUZON_ENC_KEY y TOTP_ENC_KEY, que son las claves
# maestras con las que se descifran los .p12 de firma y los correos del buzón
# (backend/app/core/crypto.py). Dentro de la base esos datos están cifrados; si
# metiéramos el .env en el mismo archivo, el respaldo pasaría a contener el
# candado y la llave juntos. Se guarda aparte, en el gestor de contraseñas, y
# restaurar.sh lo exige. Quien prefiera asumir el riesgo: INCLUIR_ENV=true.
#
# SALIDA
# ------
# Pensado para cron cada 6 horas: en silencio si todo va bien, y solo escribe en
# stdout/stderr cuando algo falla (así cron avisa por correo únicamente cuando
# hay que mirar). El detalle completo siempre va al fichero de registro.
#
# LÍNEA DE CRONTAB QUE HAY QUE INSTALAR
# -------------------------------------
# En el crontab de ROOT (`sudo crontab -e`). Podría ir en el del usuario de
# operación, pero solo si estuviera en el grupo `docker`, y instalar-servidor.sh
# NO lo mete ahí a propósito: pertenecer a ese grupo equivale a root sin
# contraseña. Se opera con sudo, y el respaldo también.
# 05 y no 00 para no coincidir con el minuto en el que todo
# el mundo lanza sus tareas. El VPS va en UTC y Ecuador es UTC-5, así que las
# 06:00 UTC son la 01:00 de acá: la hora más tranquila, y por eso HORA_DIARIA_UTC
# vale 06 (esa es la copia que se retiene 30 días).
#
# Antes de instalarla, dos cosas que no hace instalar-servidor.sh:
#   sudo apt install age
#   sudo install -d -m 700 -o factuchat -g factuchat /var/backups/factuchat/copias /var/log/factuchat
#
#   MAILTO=<correo del administrador>
#   5 0,6,12,18 * * * /opt/factuchat/deploy/scripts/respaldo.sh
#
# Y una vez al mes, el recordatorio de la prueba de restauración (control A.8.13
# y continuidad A.5.30): la prueba se hace a mano y se documenta.
#
#   0 9 1 * * echo "Toca la prueba mensual de restauración de Factuchat: deploy/scripts/restaurar.sh"
#
# USO
# ---
#   ./respaldo.sh                  respaldo normal
#   ./respaldo.sh --dry-run        comprueba todo y no escribe nada
#   ./respaldo.sh --verboso        además del registro, escribe en pantalla
#   ./respaldo.sh --ayuda
#
set -euo pipefail

# rclone y la CLI de AWS suelen instalarse en /usr/local/bin, que no está en el
# PATH mínimo de cron. Sin esto el envío al destino externo falla solo de noche.
PATH="${PATH}:/usr/local/bin"

# Nadie más que el dueño debe poder leer respaldos, manifiestos ni registros.
umask 077

# =============================================================================
# Parámetros (todos por variable de entorno; los valores de abajo son el defecto)
# =============================================================================

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-$(cd "${AQUI}/.." && pwd)}"
COMPOSE_ARCHIVO="${COMPOSE_ARCHIVO:-docker-compose.prod.yml}"
ENV_ARCHIVO="${ENV_ARCHIVO:-${DEPLOY_DIR}/.env}"

# `name: factuchat` en el compose: los volúmenes reales se llaman factuchat_<nombre>
PROYECTO="${PROYECTO:-factuchat}"
# `comprobantes` son los documentos con valor tributario. `nginx-logs` entra
# porque es un volumen de Docker y la regla de logrotate del paso 9 apunta a
# /var/log/factuchat, así que nunca lo alcanza: sin esto, los registros de
# acceso —la evidencia del control A.8.15— no se rotan ni se respaldan.
VOLUMENES_FICHEROS="${VOLUMENES_FICHEROS:-comprobantes nginx-logs}"

# Subcarpeta propia dentro de /var/backups/factuchat: ahí mismo deja
# instalar-servidor.sh las copias .bak de los ficheros de sistema que toca
# (sshd_config y compañía). Mezclarlas con los respaldos cifrados haría que la
# poda de este script tuviera que distinguir entre unas y otras, y basta con
# aflojar un patrón para borrar lo que no se debe.
RESPALDO_DIR="${RESPALDO_DIR:-/var/backups/factuchat/copias}"
LOG_ARCHIVO="${LOG_ARCHIVO:-/var/log/factuchat/respaldo.log}"
TRABAJO_DIR="${TRABAJO_DIR:-${RESPALDO_DIR}/.tmp}"

# Destinatario age: la clave PÚBLICA (age1... o una clave pública SSH).
AGE_DESTINATARIO="${AGE_DESTINATARIO:-}"
AGE_DESTINATARIOS_ARCHIVO="${AGE_DESTINATARIOS_ARCHIVO:-}"
# Solo para la verificación manual fuera de cron. JAMÁS en el .env del VPS.
AGE_IDENTIDAD_PRUEBA="${AGE_IDENTIDAD_PRUEBA:-}"

# Destino externo: ninguno | rsync | rclone | s3
DESTINO_TIPO="${DESTINO_TIPO:-ninguno}"
DESTINO_RSYNC="${DESTINO_RSYNC:-}"          # usuario@host:/ruta/factuchat
RSYNC_SSH_KEY="${RSYNC_SSH_KEY:-}"
DESTINO_RCLONE="${DESTINO_RCLONE:-}"        # remoto:bucket/factuchat
DESTINO_S3="${DESTINO_S3:-}"                # s3://bucket/factuchat

# Retención. Cada 6 h son 4 copias diarias: no tiene sentido guardar 120 copias
# intradía de un mes. Se conservan 7 días de copias cada 6 h (28 copias) para
# recuperar de un error reciente, y 30 días de la copia marcada como diaria.
# Los 7 días son los que fija docs/procedimiento-respaldo-restauracion.md: el
# script y el procedimiento tienen que decir lo mismo o la evidencia no vale.
RETENCION_INTRADIA_DIAS="${RETENCION_INTRADIA_DIAS:-7}"
RETENCION_DIARIA_DIAS="${RETENCION_DIARIA_DIAS:-30}"
HORA_DIARIA_UTC="${HORA_DIARIA_UTC:-06}"
# Red de seguridad: la poda nunca puede dejar el servidor sin copias.
MIN_COPIAS="${MIN_COPIAS:-4}"

INCLUIR_ENV="${INCLUIR_ENV:-false}"

# Tamaños mínimos creíbles. Un pg_dump de 200 bytes es un fallo silencioso.
MIN_BYTES_BD="${MIN_BYTES_BD:-4096}"
MIN_BYTES_FICHEROS="${MIN_BYTES_FICHEROS:-100}"

# Gancho opcional de alerta. Hoy no hay alertas activas (SECURITY.md, A09, lo
# reconoce como pendiente); esta es la única vía para conectar una.
ALERTA_CMD="${ALERTA_CMD:-}"

DRY_RUN=false
VERBOSO=false

# =============================================================================
# Utilidades
# =============================================================================

ROJO=""; RESET=""
[[ -t 2 ]] && { ROJO=$'\033[31m'; RESET=$'\033[0m'; }

registrar() {
  local linea
  linea="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  printf '%s\n' "$linea" >>"$LOG_ARCHIVO" 2>/dev/null || true
  [[ "$VERBOSO" == true ]] && printf '%s\n' "$linea"
  return 0
}

fallar() {
  local msg="$*"
  registrar "ERROR: $msg"
  # A stderr para que cron lo mande por correo, y a syslog para que quede en el
  # registro del sistema aunque el correo no salga.
  printf '%s[respaldo.sh] ERROR: %s%s\n' "$ROJO" "$msg" "$RESET" >&2
  printf 'Registro completo en: %s\n' "$LOG_ARCHIVO" >&2
  command -v logger >/dev/null 2>&1 && logger -t factuchat-respaldo -p daemon.err "$msg"
  if [[ -n "$ALERTA_CMD" ]]; then
    "$ALERTA_CMD" "Factuchat: falló el respaldo — $msg" || true
  fi
  exit 1
}

# Lee una clave del .env sin ejecutarlo. Sourcear un .env con `set -u` activo o
# con valores que traen $ o comillas raras rompe el script o, peor, ejecuta algo.
valor_env() {
  local clave="$1" linea valor
  [[ -f "$ENV_ARCHIVO" ]] || return 1
  linea="$(grep -E "^[[:space:]]*${clave}=" "$ENV_ARCHIVO" | tail -n1 || true)"
  [[ -n "$linea" ]] || return 1
  valor="${linea#*=}"
  valor="${valor%$'\r'}"          # el .env pudo editarse desde Windows
  valor="${valor%\"}"; valor="${valor#\"}"
  valor="${valor%\'}"; valor="${valor#\'}"
  [[ -n "$valor" ]] || return 1
  printf '%s' "$valor"
}

dc() { docker compose -f "${DEPLOY_DIR}/${COMPOSE_ARCHIVO}" --project-directory "$DEPLOY_DIR" "$@"; }

# Se pregunta por el contenedor y no por `docker compose ps --status`, porque
# las banderas de `ps` han cambiado entre versiones de Compose y este script
# tiene que funcionar dentro de tres años sin que nadie lo mire.
servicio_corriendo() {
  local cid
  # Sin `| head -1`: con `pipefail`, head cierra la tubería antes de tiempo y el
  # productor muere con SIGPIPE. Se corta la primera línea con expansión de bash.
  cid="$(dc ps -q "$1" 2>/dev/null || true)"
  cid="${cid%%$'\n'*}"
  [[ -n "$cid" ]] || return 1
  [[ "$(docker inspect --format '{{.State.Running}}' "$cid" 2>/dev/null)" == "true" ]]
}

bytes_de() { stat -c %s "$1" 2>/dev/null || echo 0; }

# =============================================================================
# Argumentos
# =============================================================================

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; VERBOSO=true ;;
    --verboso|-v) VERBOSO=true ;;
    --ayuda|-h|--help)
      sed -n '2,96p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) printf 'Opción desconocida: %s (usa --ayuda)\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

# =============================================================================
# Comprobaciones previas — todas antes de tocar nada
# =============================================================================

mkdir -p "$(dirname "$LOG_ARCHIVO")" 2>/dev/null || true
mkdir -p "$RESPALDO_DIR" "$TRABAJO_DIR"
chmod 700 "$RESPALDO_DIR" "$TRABAJO_DIR"

registrar "=== inicio (dry-run=${DRY_RUN}) ==="

# Un solo respaldo a la vez. Si el de las 00:00 todavía está subiendo cuando
# entra el de las 06:00, dos tar sobre el mismo volumen compiten por disco y por
# E/S, y el segundo puede quedarse sin espacio a medio escribir.
CANDADO="${TRABAJO_DIR}/respaldo.lock"
exec 9>"$CANDADO"
if ! flock -n 9; then
  registrar "AVISO: ya hay un respaldo en curso; esta corrida se salta"
  exit 0
fi

# `age` NO lo instala deploy/scripts/instalar-servidor.sh (ese cubre los pasos
# 1, 2, 8 y 9); hay que instalarlo a mano antes de programar el cron. El resto
# viene de serie en Ubuntu 24, salvo docker, que sí instala ese script.
#
# El nombre del binario NO es el del paquete: decirle a alguien «sudo apt
# install sha256sum» a las tres de la mañana solo le da un error más.
declare -A PAQUETE_DE=(
  [docker]="docker-ce (lo instala deploy/scripts/instalar-servidor.sh)"
  [age]="age"
  [tar]="tar"
  [gzip]="gzip"
  [sha256sum]="coreutils"
  [flock]="util-linux"
)
for prog in docker age tar gzip sha256sum flock; do
  command -v "$prog" >/dev/null 2>&1     || fallar "falta el programa '${prog}'. Viene en: ${PAQUETE_DE[$prog]}"
done

[[ -f "${DEPLOY_DIR}/${COMPOSE_ARCHIVO}" ]] || fallar "no encuentro ${DEPLOY_DIR}/${COMPOSE_ARCHIVO}"
[[ -f "$ENV_ARCHIVO" ]] || fallar "no encuentro el .env en ${ENV_ARCHIVO}"

# --- destinatario age ---------------------------------------------------------
AGE_ARGS=()
if [[ -n "$AGE_DESTINATARIOS_ARCHIVO" ]]; then
  [[ -f "$AGE_DESTINATARIOS_ARCHIVO" ]] || fallar "AGE_DESTINATARIOS_ARCHIVO no existe: ${AGE_DESTINATARIOS_ARCHIVO}"
  grep -q 'AGE-SECRET-KEY-' "$AGE_DESTINATARIOS_ARCHIVO" && \
    fallar "el fichero de destinatarios contiene una clave PRIVADA (AGE-SECRET-KEY-). La privada no puede vivir en el VPS: quien tome el servidor se llevaría también los respaldos"
  AGE_ARGS+=(-R "$AGE_DESTINATARIOS_ARCHIVO")
  registrar "destinatarios desde ${AGE_DESTINATARIOS_ARCHIVO}"
elif [[ -n "$AGE_DESTINATARIO" ]]; then
  case "$AGE_DESTINATARIO" in
    AGE-SECRET-KEY-*) fallar "AGE_DESTINATARIO trae una clave PRIVADA. Se cifra con la PÚBLICA (age1...); la privada se queda fuera del servidor" ;;
    age1*|ssh-ed25519*|ssh-rsa*) : ;;
    *) fallar "AGE_DESTINATARIO no parece una clave pública válida (esperaba age1..., ssh-ed25519... o ssh-rsa...)" ;;
  esac
  AGE_ARGS+=(-r "$AGE_DESTINATARIO")
else
  fallar "falta AGE_DESTINATARIO (clave pública age). Generar el par FUERA del VPS con: age-keygen -o factuchat-respaldos.key ; la línea 'public key:' es lo único que se copia al servidor"
fi

# --- la identidad de prueba no puede quedarse en el servidor ------------------
if [[ -n "$AGE_IDENTIDAD_PRUEBA" ]]; then
  [[ -f "$AGE_IDENTIDAD_PRUEBA" ]] || fallar "AGE_IDENTIDAD_PRUEBA no existe: ${AGE_IDENTIDAD_PRUEBA}"
  case "$(readlink -f "$AGE_IDENTIDAD_PRUEBA")" in
    "${DEPLOY_DIR}"/*|"${RESPALDO_DIR}"/*)
      fallar "la clave privada está dentro del despliegue (${AGE_IDENTIDAD_PRUEBA}). Eso anula el motivo de cifrar: sácala del VPS" ;;
  esac
  registrar "AVISO: verificación con clave privada activada. Esto solo debe pasar en una corrida MANUAL, nunca desde cron"
fi

# --- postgres arriba ----------------------------------------------------------
PGUSER_="$(valor_env POSTGRES_USER || echo factuchat)"
PGDB_="$(valor_env POSTGRES_DB || echo factuchat)"
servicio_corriendo postgres || \
  fallar "el servicio postgres no está corriendo; sin él no hay pg_dump"

# --- volúmenes existentes -----------------------------------------------------
for vol in $VOLUMENES_FICHEROS; do
  docker volume inspect "${PROYECTO}_${vol}" >/dev/null 2>&1 || \
    fallar "no existe el volumen ${PROYECTO}_${vol}. Revisa PROYECTO/VOLUMENES_FICHEROS: respaldar 'nada' sin avisar es peor que no respaldar"
done

# Imagen para hacer el tar del volumen. Se usa la misma de postgres porque ya
# está descargada (hoy fijada por ETIQUETA en POSTGRES_IMAGE; el digest es
# pendiente del paso 2): así el respaldo no depende de
# bajar una imagen nueva justo cuando el servidor tiene problemas.
IMAGEN_TAR="${IMAGEN_TAR:-$(valor_env POSTGRES_IMAGE || echo postgres:16)}"

# --- espacio en disco ---------------------------------------------------------
# Si alguna de estas consultas devolviera texto en vez de un número, la
# aritmética de más abajo reventaría con un mensaje incomprensible a las 3 de la
# mañana. Se normaliza a 0 y se sigue: el respaldo importa más que la estimación.
solo_numero() { [[ "$1" =~ ^[0-9]+$ ]] && printf '%s' "$1" || printf '0'; }

TAM_BD="$(solo_numero "$(dc exec -T postgres psql -qtAX -U "$PGUSER_" -d "$PGDB_" \
  -c "SELECT pg_database_size('${PGDB_}')" 2>/dev/null | tr -d '[:space:]')")"
TAM_FICHEROS=0
declare -A N_FICHEROS
for vol in $VOLUMENES_FICHEROS; do
  n="$(solo_numero "$(docker run --rm --network none -v "${PROYECTO}_${vol}:/datos:ro" "$IMAGEN_TAR" \
       du -sb /datos 2>/dev/null | cut -f1 | tr -d '[:space:]')")"
  TAM_FICHEROS=$(( TAM_FICHEROS + n ))
  # Cuántos ficheros hay: el manifiesto lo anota y restaurar.sh lo compara, para
  # que un tar que se copió a medias no pase por bueno.
  N_FICHEROS["$vol"]="$(solo_numero "$(docker run --rm --network none -v "${PROYECTO}_${vol}:/datos:ro" "$IMAGEN_TAR" \
       sh -c 'find /datos -type f | wc -l' 2>/dev/null | tr -d '[:space:]')")"
done
NECESARIO=$(( (TAM_BD + TAM_FICHEROS) / 2 + 268435456 ))   # comprimido + holgura
LIBRE="$(solo_numero "$(df -B1 --output=avail "$RESPALDO_DIR" | tail -1 | tr -d ' ')")"
registrar "tamaño bd=${TAM_BD}B ficheros=${TAM_FICHEROS}B; libre en ${RESPALDO_DIR}=${LIBRE}B; estimado necesario=${NECESARIO}B"
[[ "$LIBRE" -gt "$NECESARIO" ]] || \
  fallar "espacio insuficiente en ${RESPALDO_DIR}: libres ${LIBRE}B, hacen falta ~${NECESARIO}B"

# --- destino externo ----------------------------------------------------------
case "$DESTINO_TIPO" in
  ninguno)
    registrar "AVISO: DESTINO_TIPO=ninguno. El respaldo se queda en el MISMO servidor, así que no cumple A.8.13: un disco perdido o un cifrado por ransomware se lleva original y copia. Configura rsync, rclone o s3" ;;
  rsync)
    command -v rsync >/dev/null 2>&1 || fallar "falta rsync"
    [[ -n "$DESTINO_RSYNC" ]] || fallar "falta DESTINO_RSYNC (usuario@host:/ruta)" ;;
  rclone)
    command -v rclone >/dev/null 2>&1 || fallar "falta rclone"
    [[ -n "$DESTINO_RCLONE" ]] || fallar "falta DESTINO_RCLONE (remoto:bucket/ruta)" ;;
  s3)
    command -v aws >/dev/null 2>&1 || fallar "falta la CLI de AWS"
    [[ -n "$DESTINO_S3" ]] || fallar "falta DESTINO_S3 (s3://bucket/prefijo)" ;;
  *) fallar "DESTINO_TIPO no válido: ${DESTINO_TIPO} (ninguno|rsync|rclone|s3)" ;;
esac

# =============================================================================
# Nombre de la corrida
# =============================================================================

MARCA="$(date -u +%Y%m%dT%H%M%SZ)"
HORA_ACTUAL="$(date -u +%H)"
ES_DIARIO=false
[[ "$HORA_ACTUAL" == "$HORA_DIARIA_UTC" ]] && ES_DIARIO=true
NOMBRE="$MARCA"; [[ "$ES_DIARIO" == true ]] && NOMBRE="${MARCA}-diario"
DESTINO_LOCAL="${RESPALDO_DIR}/${NOMBRE}"

if [[ "$DRY_RUN" == true ]]; then
  registrar "--- SIMULACIÓN: no se escribe nada ---"
  registrar "carpeta que se crearía: ${DESTINO_LOCAL}"
  registrar "  bd.dump.age        (pg_dump -Fc de ${PGDB_} como ${PGUSER_}, cifrado con age)"
  for vol in $VOLUMENES_FICHEROS; do
    registrar "  ${vol}.tar.gz.age   (volumen ${PROYECTO}_${vol})"
  done
  [[ "$INCLUIR_ENV" == true ]] && registrar "  env.age            (INCLUIR_ENV=true)"
  registrar "  manifiesto.txt     (sha256, tamaños, filas, alembic, tablas con FORCE RLS)"
  registrar "marcada como diaria: ${ES_DIARIO} (hora UTC ${HORA_ACTUAL}, diaria a las ${HORA_DIARIA_UTC})"
  registrar "envío a destino externo: ${DESTINO_TIPO}"
  registrar "poda: intradía > ${RETENCION_INTRADIA_DIAS} días, diarias > ${RETENCION_DIARIA_DIAS} días, mínimo ${MIN_COPIAS} copias"
  registrar "--- todas las comprobaciones previas pasaron ---"
  exit 0
fi

mkdir -p "$DESTINO_LOCAL"
chmod 700 "$DESTINO_LOCAL"
PARCIAL="${DESTINO_LOCAL}/.en-curso"
touch "$PARCIAL"

# Si algo revienta a media escritura, la carpeta queda marcada como incompleta y
# la poda futura no la confundirá con un respaldo bueno.
limpiar() {
  local code=$?
  if [[ $code -ne 0 && -d "$DESTINO_LOCAL" ]]; then
    mv "$DESTINO_LOCAL" "${DESTINO_LOCAL}.FALLIDO" 2>/dev/null || true
    registrar "respaldo incompleto renombrado a ${DESTINO_LOCAL}.FALLIDO"
  fi
  rm -f "${TRABAJO_DIR}/fifo."* 2>/dev/null || true
}
trap limpiar EXIT

MANIFIESTO="${DESTINO_LOCAL}/manifiesto.txt"

# =============================================================================
# Cifrado en flujo, con SHA-256 del contenido EN CLARO
# =============================================================================
#
# El volcado nunca toca el disco sin cifrar. Escribir primero un .dump en claro
# y cifrarlo después deja, durante minutos, una copia legible de todos los datos
# de todos los inquilinos en el mismo servidor que queremos proteger.
#
# El SHA-256 del contenido en claro se calcula al vuelo con una tubería con
# nombre (fifo). Sirve para que restaurar.sh compruebe, tras descifrar, que el
# volcado es byte a byte el que salió de aquí. Se usa fifo y no `tee >(...)`
# porque de la sustitución de procesos no se recoge el código de salida.
cifrar_flujo() {
  local salida="$1" archivo_sha="$2"; shift 2
  local fifo="${TRABAJO_DIR}/fifo.$$.$RANDOM"
  mkfifo "$fifo"

  ( sha256sum < "$fifo" | cut -d' ' -f1 > "$archivo_sha" ) &
  local pid_sha=$!

  # La tubería va dentro de un `if` a propósito: así `set -e` no aborta el
  # script cuando algún eslabón falla y podemos leer PIPESTATUS entero. Con
  # `set +e`/`set -e` dentro de la función se pisaría el estado del que llama.
  local estados
  if "$@" | tee "$fifo" | age "${AGE_ARGS[@]}" > "$salida"; then
    estados=("${PIPESTATUS[@]}")
  else
    estados=("${PIPESTATUS[@]}")
  fi

  wait "$pid_sha" || { rm -f "$fifo"; return 90; }
  rm -f "$fifo"

  # estados[0]=productor, [1]=tee, [2]=age
  [[ "${estados[2]}" -eq 0 ]] || return 93
  [[ "${estados[1]}" -eq 0 ]] || return 92
  return "${estados[0]}"
}

# Comprueba lo único que se puede comprobar aquí sin la clave privada.
verificar_age() {
  local f="$1" minimo="$2" tam cabecera
  tam="$(bytes_de "$f")"
  [[ "$tam" -ge "$minimo" ]] || fallar "$(basename "$f") pesa ${tam}B, por debajo del mínimo creíble de ${minimo}B: el volcado salió vacío o truncado"
  cabecera="$(head -c 21 "$f")"
  [[ "$cabecera" == "age-encryption.org/v1" ]] || fallar "$(basename "$f") no tiene cabecera age válida"
  # Sustitución de proceso y no `head | grep`: con `pipefail`, grep -q termina en
  # cuanto encuentra la línea, head recibe SIGPIPE y la tubería devolvería error
  # aunque el fichero esté perfecto. Un respaldo bueno marcado como fallido a las
  # tres de la mañana es exactamente el tipo de aviso que la gente aprende a ignorar.
  grep -qE '^-> (X25519|ssh-ed25519|ssh-rsa|scrypt) ' < <(head -c 4096 "$f") || \
    fallar "$(basename "$f") no lleva ninguna estrofa de destinatario: nadie podría descifrarlo"
  registrar "verificado ${f} (${tam}B, contenedor age con destinatario)"
}

# =============================================================================
# 1. Base de datos
# =============================================================================
#
# --format=custom permite restaurar tabla por tabla y ya viene comprimido.
# NO se usa --no-owner: las tablas son de `factuchat` (las crea Alembic con
# DATABASE_URL_ADMIN) y esa propiedad importa. Si al restaurar acabaran siendo
# de `factuchat_app`, ese rol pasaría a ser dueño de las tablas y, sin FORCE ROW
# LEVEL SECURITY, un dueño se salta sus propias políticas: fuga entre inquilinos
# sin un solo error visible. Por eso el dueño se conserva y restaurar.sh lo
# comprueba al final.
registrar "volcando base de datos ${PGDB_}"
cifrar_flujo "${DESTINO_LOCAL}/bd.dump.age" "${TRABAJO_DIR}/bd.sha" \
  dc exec -T postgres pg_dump -U "$PGUSER_" -d "$PGDB_" --format=custom --compress=6 \
  || fallar "pg_dump falló (código $?)"
verificar_age "${DESTINO_LOCAL}/bd.dump.age" "$MIN_BYTES_BD"
SHA_BD="$(cat "${TRABAJO_DIR}/bd.sha")"
[[ -n "$SHA_BD" ]] || fallar "no se pudo calcular el SHA-256 del volcado"

# =============================================================================
# 2. Volúmenes de ficheros
# =============================================================================
#
# `--network none`: el contenedor que empaqueta solo necesita leer un volumen,
# no tiene por qué poder hablar con nada.
#
# tar puede devolver 1 con «file changed as we read it» si el worker escribe un
# XML justo mientras copiamos. No es un respaldo roto: los XML firmados y los
# RIDE se escriben una vez y no se vuelven a tocar, así que como mucho el
# fichero más nuevo queda a medias y llegará entero en la copia de dentro de 6
# horas. Un código 2 sí es un error de verdad.
declare -A SHA_VOL
for vol in $VOLUMENES_FICHEROS; do
  registrar "empaquetando volumen ${PROYECTO}_${vol}"
  cod=0
  cifrar_flujo "${DESTINO_LOCAL}/${vol}.tar.gz.age" "${TRABAJO_DIR}/${vol}.sha" \
    docker run --rm --network none -v "${PROYECTO}_${vol}:/datos:ro" "$IMAGEN_TAR" \
    tar -C /datos --warning=no-file-changed -czf - . || cod=$?
  case "$cod" in
    0) : ;;
    1) registrar "AVISO: tar avisó de ficheros que cambiaron durante la copia en ${vol}; se acepta (los XML y RIDE no se reescriben)" ;;
    *) fallar "falló el empaquetado del volumen ${vol} (código ${cod})" ;;
  esac
  verificar_age "${DESTINO_LOCAL}/${vol}.tar.gz.age" "$MIN_BYTES_FICHEROS"
  SHA_VOL["$vol"]="$(cat "${TRABAJO_DIR}/${vol}.sha")"
  [[ -n "${SHA_VOL[$vol]}" ]] || fallar "no se pudo calcular el SHA-256 de ${vol}"
done

# =============================================================================
# 3. .env (solo si se pidió expresamente)
# =============================================================================
SHA_ENV=""
if [[ "$INCLUIR_ENV" == true ]]; then
  registrar "AVISO: INCLUIR_ENV=true. Este respaldo lleva dentro CERT_ENC_KEY, BUZON_ENC_KEY y TOTP_ENC_KEY: quien tenga el fichero y la clave age tiene los certificados de firma de todos los inquilinos"
  cifrar_flujo "${DESTINO_LOCAL}/env.age" "${TRABAJO_DIR}/env.sha" cat "$ENV_ARCHIVO" \
    || fallar "no se pudo cifrar el .env"
  verificar_age "${DESTINO_LOCAL}/env.age" 64
  SHA_ENV="$(cat "${TRABAJO_DIR}/env.sha")"
fi

# =============================================================================
# 4. Manifiesto
# =============================================================================
#
# En claro a propósito: son hashes, tamaños y cuentas, ningún dato personal ni
# secreto. Tiene que poder leerse SIN la clave privada, para saber qué hay en
# una copia y comprobar que llegó entera al destino externo.
#
# Las cuentas de filas y el número de tablas con FORCE ROW LEVEL SECURITY son
# los testigos que restaurar.sh compara al terminar: una restauración que deja
# `comprobantes` vacío, o una tabla sin FORCE, se detecta ahí y no seis meses
# después.
consulta_sql() {
  dc exec -T postgres psql -qtAX -U "$PGUSER_" -d "$PGDB_" -c "$1" 2>/dev/null | tr -d '[:space:]'
}

FORCE_RLS="$(consulta_sql "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity AND c.relforcerowsecurity")"
SIN_FORCE="$(consulta_sql "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname<>'alembic_version' AND NOT (c.relrowsecurity AND c.relforcerowsecurity)")"
ALEMBIC="$(consulta_sql "SELECT version_num FROM alembic_version LIMIT 1")"
PGVER="$(consulta_sql "SHOW server_version")"
F_TENANTS="$(consulta_sql "SELECT count(*) FROM tenants")"
F_USERS="$(consulta_sql "SELECT count(*) FROM users")"
F_COMPROBANTES="$(consulta_sql "SELECT count(*) FROM comprobantes")"
F_AUDIT="$(consulta_sql "SELECT count(*) FROM audit_log")"

# Si en el origen ya hay una tabla sin FORCE, el problema es de ahora, no de la
# restauración: hay que verlo hoy.
if [[ "${SIN_FORCE:-0}" != "0" ]]; then
  registrar "AVISO GRAVE: ${SIN_FORCE} tabla(s) de public SIN FORCE ROW LEVEL SECURITY en la base VIVA. El aislamiento entre inquilinos está comprometido AHORA MISMO"
  if [[ -n "$ALERTA_CMD" ]]; then
    "$ALERTA_CMD" "Factuchat: ${SIN_FORCE} tabla(s) sin FORCE RLS en producción" || true
  fi
fi

{
  echo "# Manifiesto de respaldo de Factuchat — control A.8.13"
  echo "# Sin datos personales ni secretos: se guarda en claro para poder"
  echo "# comprobar la copia sin tener la clave privada delante."
  echo "version_manifiesto=1"
  echo "marca_utc=${MARCA}"
  echo "diario=${ES_DIARIO}"
  echo "host=$(hostname -f 2>/dev/null || hostname)"
  echo "proyecto_compose=${PROYECTO}"
  echo "postgres_version=${PGVER}"
  echo "postgres_usuario=${PGUSER_}"
  echo "postgres_bd=${PGDB_}"
  echo "alembic_version=${ALEMBIC}"
  echo "tablas_force_rls=${FORCE_RLS}"
  echo "tablas_sin_force_rls=${SIN_FORCE}"
  echo "filas_tenants=${F_TENANTS}"
  echo "filas_users=${F_USERS}"
  echo "filas_comprobantes=${F_COMPROBANTES}"
  echo "filas_audit_log=${F_AUDIT}"
  echo "volumenes=${VOLUMENES_FICHEROS}"
  for vol in $VOLUMENES_FICHEROS; do echo "ficheros_${vol}=${N_FICHEROS[$vol]}"; done
  echo "incluye_env=${INCLUIR_ENV}"
  echo "# --- SHA-256 del contenido EN CLARO (para verificar tras descifrar) ---"
  echo "sha256_claro_bd=${SHA_BD}"
  for vol in $VOLUMENES_FICHEROS; do echo "sha256_claro_${vol}=${SHA_VOL[$vol]}"; done
  [[ -n "$SHA_ENV" ]] && echo "sha256_claro_env=${SHA_ENV}"
  echo "# --- SHA-256 del fichero CIFRADO (para verificar el traslado) ---"
} > "$MANIFIESTO"

for f in "${DESTINO_LOCAL}"/*.age; do
  echo "sha256_cifrado_$(basename "$f")=$(sha256sum "$f" | cut -d' ' -f1)" >> "$MANIFIESTO"
  echo "bytes_$(basename "$f")=$(bytes_de "$f")" >> "$MANIFIESTO"
done
chmod 600 "$MANIFIESTO"

# =============================================================================
# 5. Verificación con clave privada (solo corridas manuales)
# =============================================================================
if [[ -n "$AGE_IDENTIDAD_PRUEBA" ]]; then
  registrar "descifrando de verdad para comprobar el volcado"
  tmpv="$(mktemp -d "${TRABAJO_DIR}/verif.XXXXXX")"
  age -d -i "$AGE_IDENTIDAD_PRUEBA" "${DESTINO_LOCAL}/bd.dump.age" > "${tmpv}/bd.dump" \
    || fallar "el respaldo NO se descifra con esa clave"
  sha_ok="$(sha256sum "${tmpv}/bd.dump" | cut -d' ' -f1)"
  [[ "$sha_ok" == "$SHA_BD" ]] || fallar "el SHA-256 tras descifrar no coincide con el del volcado"
  pg_restore --list "${tmpv}/bd.dump" > /dev/null 2>&1 \
    || fallar "el fichero descifrado no es un volcado de PostgreSQL legible"
  rm -rf "$tmpv"
  registrar "descifrado y pg_restore --list correctos"
fi

rm -f "$PARCIAL"
rm -f "${TRABAJO_DIR}"/*.sha

# =============================================================================
# 6. Copia al destino externo
# =============================================================================
#
# NUNCA con borrado remoto (--delete, `sync`). Si el VPS cae en manos ajenas,
# un espejo con borrado convierte «me entraron al servidor» en «además me
# borraron todos los respaldos». Aquí solo se AÑADE. La retención en el destino
# la impone el proveedor: versionado y bloqueo de objetos en S3, o una tarea que
# TIRE de los ficheros desde el otro extremo. El servidor no debe poder destruir
# lo que ya envió.
subir() {
  local origen="$1" nombre; nombre="$(basename "$origen")"
  case "$DESTINO_TIPO" in
    ninguno) return 0 ;;
    rsync)
      local ssh_opts="ssh -o StrictHostKeyChecking=yes -o BatchMode=yes"
      [[ -n "$RSYNC_SSH_KEY" ]] && ssh_opts="${ssh_opts} -i ${RSYNC_SSH_KEY}"
      rsync -a --partial --chmod=D700,F600 -e "$ssh_opts" \
        "${origen}/" "${DESTINO_RSYNC%/}/${nombre}/" || return 1
      # Verificación real: una segunda pasada con checksum no debe encontrar
      # nada que transferir. Confiar solo en el código de salida deja pasar
      # copias truncadas por un disco lleno en el otro extremo.
      local pendiente
      pendiente="$(rsync -a --checksum --dry-run --out-format='%n' -e "$ssh_opts" \
        "${origen}/" "${DESTINO_RSYNC%/}/${nombre}/" | grep -v '/$' || true)"
      [[ -z "$pendiente" ]] || { registrar "rsync dejó diferencias: ${pendiente}"; return 1; }
      ;;
    rclone)
      rclone copy --checksum "$origen" "${DESTINO_RCLONE%/}/${nombre}" || return 1
      rclone check --one-way "$origen" "${DESTINO_RCLONE%/}/${nombre}" || return 1
      ;;
    s3)
      aws s3 cp --recursive --only-show-errors "$origen" "${DESTINO_S3%/}/${nombre}/" || return 1
      local n_local n_remoto
      n_local="$(find "$origen" -type f | wc -l)"
      n_remoto="$(aws s3 ls --recursive "${DESTINO_S3%/}/${nombre}/" | wc -l)"
      [[ "$n_local" -eq "$n_remoto" ]] || { registrar "en S3 hay ${n_remoto} ficheros y en local ${n_local}"; return 1; }
      ;;
  esac
  return 0
}

if [[ "$DESTINO_TIPO" != "ninguno" ]]; then
  registrar "enviando ${NOMBRE} a destino externo (${DESTINO_TIPO})"
  subir "$DESTINO_LOCAL" || fallar "no se pudo copiar el respaldo al destino externo. La copia local existe (${DESTINO_LOCAL}) pero un respaldo que solo vive en el mismo servidor no protege de nada"
  registrar "envío verificado"
fi

# =============================================================================
# 7. Poda
# =============================================================================
#
# Por NOMBRE (marca de tiempo UTC en la carpeta), no por fecha de modificación:
# el mtime cambia si alguien toca la carpeta y la retención dejaría de ser la
# que dice el procedimiento. Las carpetas .FALLIDO se podan igual, y antes.
CORTE_INTRADIA="$(date -u -d "-${RETENCION_INTRADIA_DIAS} days" +%Y%m%dT%H%M%SZ)"
CORTE_DIARIO="$(date -u -d "-${RETENCION_DIARIA_DIAS} days" +%Y%m%dT%H%M%SZ)"

mapfile -t COPIAS < <(find "$RESPALDO_DIR" -mindepth 1 -maxdepth 1 -type d \
  -name '20*' ! -name '*.FALLIDO' -printf '%f\n' | sort)
TOTAL="${#COPIAS[@]}"
registrar "poda: ${TOTAL} copias, corte intradía ${CORTE_INTRADIA}, corte diario ${CORTE_DIARIO}"

BORRADAS=0
for copia in "${COPIAS[@]}"; do
  restantes=$(( TOTAL - BORRADAS ))
  if [[ "$restantes" -le "$MIN_COPIAS" ]]; then
    registrar "poda detenida: quedan ${restantes} copias y el mínimo es ${MIN_COPIAS}"
    break
  fi
  marca="${copia%-diario}"
  if [[ "$copia" == *-diario ]]; then
    [[ "$marca" < "$CORTE_DIARIO" ]] || continue
  else
    [[ "$marca" < "$CORTE_INTRADIA" ]] || continue
  fi
  rm -rf "${RESPALDO_DIR:?}/${copia}"
  BORRADAS=$(( BORRADAS + 1 ))
  registrar "podada la copia local ${copia}"
done

# Las incompletas no cuentan como copias válidas y se limpian aparte.
find "$RESPALDO_DIR" -mindepth 1 -maxdepth 1 -type d -name '*.FALLIDO' -mtime +2 \
  -exec rm -rf {} + 2>/dev/null || true

# =============================================================================
# 8. Cierre
# =============================================================================
TAM_TOTAL="$(du -sh "$DESTINO_LOCAL" | cut -f1)"
registrar "OK ${NOMBRE} (${TAM_TOTAL}) — diario=${ES_DIARIO}, podadas=${BORRADAS}, destino=${DESTINO_TIPO}"
registrar "=== fin ==="

# Ni una línea en stdout cuando todo va bien: cron solo debe escribir cuando hay
# algo que mirar. Con --verboso se ve todo.
exit 0
