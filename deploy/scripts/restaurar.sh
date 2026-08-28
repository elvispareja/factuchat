#!/usr/bin/env bash
#
# restaurar.sh — Restauración guiada de Factuchat (paso 6 y 10 de PLAN.md,
# controles A.8.13 respaldo y A.5.30 continuidad)
# =============================================================================
#
# QUÉ HACE, EN ORDEN
# ------------------
#   1. Lee el manifiesto de la copia y comprueba el SHA-256 de cada fichero
#      cifrado ANTES de tocar nada.
#   2. Enseña qué se va a restaurar y qué se va a destruir, y exige que lo
#      confirmes escribiendo una frase completa. No hay «pulse s/n».
#   3. Para api, worker y beat. Restaurar con el worker escribiendo encima es
#      la forma más rápida de acabar con una base de un momento y unos ficheros
#      de otro.
#   4. Recrea los DOS roles que pg_dump no guarda (factuchat_app y
#      factuchat_security). Sin ellos la aplicación no conecta. El propietario
#      lo crea el entrypoint de la imagen a partir de POSTGRES_USER:
#      `pg_dump` NO guarda roles (son del clúster, no de la base), así que un
#      volcado restaurado sobre un clúster nuevo trae GRANTs que apuntan a roles
#      que no existen y la restauración se cae, o peor, entra a medias.
#   5. Restaura la base y los ficheros de los volúmenes.
#   6. VERIFICA. Esta parte es la razón de ser del script: una restauración
#      puede terminar «sin errores» y dejar el sistema con el aislamiento entre
#      inquilinos roto. Ver el bloque de verificación más abajo.
#
# POR QUÉ SE RESTAURA COMO SUPERUSUARIO Y NO COMO factuchat_app
# -------------------------------------------------------------
# Las tablas son de `factuchat` (Alembic corre con DATABASE_URL_ADMIN). Si se
# restauraran conectado como `factuchat_app`, ese rol pasaría a ser DUEÑO de las
# tablas. Y en PostgreSQL el dueño de una tabla NO está sujeto a sus propias
# políticas RLS salvo que la tabla tenga FORCE ROW LEVEL SECURITY. Es decir:
# la aplicación entera dejaría de estar aislada por inquilino, sin un error,
# sin una excepción, sin nada raro en los registros. Cada cliente vería las
# facturas de los demás y nadie se enteraría hasta que alguien lo denunciara.
# Por eso: se restaura como `factuchat` (POSTGRES_USER) y al final se comprueba,
# tabla por tabla, que FORCE sigue puesto.
#
# LO QUE ESTE SCRIPT NO PUEDE DEVOLVERTE
# -------------------------------------
# El .env. Por omisión no entra en el respaldo (ver respaldo.sh, INCLUIR_ENV):
# guarda CERT_ENC_KEY, BUZON_ENC_KEY y TOTP_ENC_KEY, las claves maestras de
# AES-256-GCM con las que se descifran los .p12 de firma y los correos del
# buzón (backend/app/core/crypto.py). Si se hubieran guardado junto al volcado,
# el respaldo llevaría el candado y la llave en el mismo sobre.
# Consecuencia práctica: sin el .env original, los certificados restaurados son
# bytes ilegibles y ningún inquilino podrá firmar. Recupéralo del gestor de
# contraseñas ANTES de empezar. El script comprueba que exista y que traiga las
# tres claves.
#
# CLAVE PRIVADA
# -------------
# Hace falta la identidad `age` (AGE_IDENTIDAD). No vive en el VPS a propósito:
# quien tome el servidor no debe llevarse también el histórico de respaldos.
# Tráela en el momento de restaurar y llévatela cuando termines.
#
# USO
# ---
#   AGE_IDENTIDAD=/media/usb/factuchat-respaldos.key \
#     ./restaurar.sh /var/backups/factuchat/copias/20260825T060000Z-diario
#
#   ./restaurar.sh --solo-verificar        no restaura: solo pasa las
#                                          comprobaciones contra el sistema vivo
#                                          (sirve de evidencia mensual)
#   ./restaurar.sh --sobrescribir-ficheros <copia>
#                                          VACÍA los volúmenes antes de extraer.
#                                          Es la única opción que borra ficheros.
#   ./restaurar.sh --ayuda
#
set -euo pipefail
PATH="${PATH}:/usr/local/bin"
umask 077

# =============================================================================
# Parámetros
# =============================================================================

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-$(cd "${AQUI}/.." && pwd)}"
COMPOSE_ARCHIVO="${COMPOSE_ARCHIVO:-docker-compose.prod.yml}"
ENV_ARCHIVO="${ENV_ARCHIVO:-${DEPLOY_DIR}/.env}"
PROYECTO="${PROYECTO:-factuchat}"

AGE_IDENTIDAD="${AGE_IDENTIDAD:-}"
TRABAJO_DIR="${TRABAJO_DIR:-/var/tmp/factuchat-restauracion}"
LOG_ARCHIVO="${LOG_ARCHIVO:-/var/log/factuchat/restauracion.log}"

# Si el volumen de ficheros ya tiene contenido, el script se niega a mezclar
# salvo que se le diga expresamente. Mezclar ficheros de dos momentos distintos
# deja XML huérfanos que nadie sabe de qué comprobante son.
SOBRESCRIBIR_FICHEROS="${SOBRESCRIBIR_FICHEROS:-false}"

# Confirmación no interactiva (solo para la prueba mensual automatizada).
CONFIRMO="${CONFIRMO:-}"

SOLO_VERIFICAR=false
COPIA=""

# =============================================================================
# Utilidades
# =============================================================================

ROJO=""; VERDE=""; AMARILLO=""; RESET=""
if [[ -t 1 ]]; then
  ROJO=$'\033[31m'; VERDE=$'\033[32m'; AMARILLO=$'\033[33m'; RESET=$'\033[0m'
fi

# decir() escribe SOLO en el registro. Lo que se ve en pantalla lo imprime cada
# función de abajo: si decir() también imprimiera, cada línea saldría dos veces.
decir() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG_ARCHIVO" 2>/dev/null || true; }
titulo() { printf '\n%s== %s ==%s\n' "$AMARILLO" "$*" "$RESET"; decir "== $* =="; }
ok()     { printf '  %s[ok]%s   %s\n' "$VERDE" "$RESET" "$*"; decir "[ok] $*"; }
mal()    { printf '  %s[MAL]%s  %s\n' "$ROJO" "$RESET" "$*"; decir "[MAL] $*"; }
fallar() { printf '\n%s[restaurar.sh] ERROR: %s%s\n' "$ROJO" "$*" "$RESET" >&2; decir "ERROR: $*"; exit 1; }

valor_env() {
  local clave="$1" linea valor
  [[ -f "$ENV_ARCHIVO" ]] || return 1
  linea="$(grep -E "^[[:space:]]*${clave}=" "$ENV_ARCHIVO" | tail -n1 || true)"
  [[ -n "$linea" ]] || return 1
  valor="${linea#*=}"
  valor="${valor%$'\r'}"
  valor="${valor%\"}"; valor="${valor#\"}"
  valor="${valor%\'}"; valor="${valor#\'}"
  [[ -n "$valor" ]] || return 1
  printf '%s' "$valor"
}

valor_manifiesto() {
  local clave="$1"
  grep -E "^${clave}=" "${COPIA}/manifiesto.txt" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

dc() { docker compose -f "${DEPLOY_DIR}/${COMPOSE_ARCHIVO}" --project-directory "$DEPLOY_DIR" "$@"; }

# Por contenedor y no por `docker compose ps --status`: las banderas de `ps`
# han ido cambiando entre versiones de Compose.
servicio_corriendo() {
  local cid
  # Sin `| head -1`: con `pipefail`, head cierra la tubería antes de tiempo y el
  # productor muere con SIGPIPE. Se corta la primera línea con expansión de bash.
  cid="$(dc ps -q "$1" 2>/dev/null || true)"
  cid="${cid%%$'\n'*}"
  [[ -n "$cid" ]] || return 1
  [[ "$(docker inspect --format '{{.State.Running}}' "$cid" 2>/dev/null)" == "true" ]]
}
salud_servicio() {
  local cid
  cid="$(dc ps -q "$1" 2>/dev/null || true)"
  cid="${cid%%$'\n'*}"
  [[ -n "$cid" ]] || { printf 'sin-contenedor'; return; }
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}sin-healthcheck{{end}}' \
    "$cid" 2>/dev/null || printf 'desconocido'
}

# psql como superusuario, por el socket local del contenedor.
psql_admin() { dc exec -T postgres psql -v ON_ERROR_STOP=1 -qtAX -U "$PGUSER_" -d "${1:-$PGDB_}" ; }
consulta()   { dc exec -T postgres psql -qtAX -U "$PGUSER_" -d "$PGDB_" -c "$1" 2>/dev/null | tr -d '\r'; }

# psql con el ROL de la aplicación (factuchat_app), que es lo que hace falta
# para probar la RLS. OJO: conecta por 127.0.0.1 DENTRO del contenedor de
# postgres, y el pg_hba de la imagen oficial trae `host all all 127.0.0.1/32
# trust` antes de la regla scram, así que por esa vía la contraseña NO se
# comprueba. La prueba de aislamiento es válida —conecta como factuchat_app—,
# pero esto NO verifica que APP_DB_PASSWORD sea correcta: eso lo demuestra que
# la API arranque y conecte al host `postgres` desde su propia red.
# La contraseña viaja por la entrada estándar y no por la línea de órdenes, que
# sería visible en `ps` para cualquier usuario del servidor.
consulta_app() {
  local sql="$1"
  printf '%s\n' "$APP_PASS_" | dc exec -T postgres sh -c '
    read -r pass
    export PGPASSWORD="$pass"
    psql -qtAX -h 127.0.0.1 -U factuchat_app -d "$1" -c "$2" 2>&1
  ' _ "$PGDB_" "$sql"
}

# =============================================================================
# Argumentos
# =============================================================================

while [[ $# -gt 0 ]]; do
  case "$1" in
    --solo-verificar) SOLO_VERIFICAR=true ;;
    --sobrescribir-ficheros) SOBRESCRIBIR_FICHEROS=true ;;
    --ayuda|-h|--help)
      sed -n '2,70p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    -*) fallar "opción desconocida: $1 (usa --ayuda)" ;;
    *) COPIA="${1%/}" ;;
  esac
  shift
done

mkdir -p "$(dirname "$LOG_ARCHIVO")" 2>/dev/null || true
decir "=== restaurar.sh inicio (solo-verificar=${SOLO_VERIFICAR}) ==="

for prog in docker; do
  command -v "$prog" >/dev/null 2>&1 || fallar "falta el programa '${prog}'"
done
[[ -f "${DEPLOY_DIR}/${COMPOSE_ARCHIVO}" ]] || fallar "no encuentro ${DEPLOY_DIR}/${COMPOSE_ARCHIVO}"
[[ -f "$ENV_ARCHIVO" ]] || fallar "no encuentro el .env en ${ENV_ARCHIVO}. Sin él no arranca nada: recupéralo del gestor de contraseñas antes de seguir"

PGUSER_="$(valor_env POSTGRES_USER || echo factuchat)"
PGDB_="$(valor_env POSTGRES_DB || echo factuchat)"
APP_PASS_="$(valor_env APP_DB_PASSWORD || true)"
IMAGEN_TAR="${IMAGEN_TAR:-$(valor_env POSTGRES_IMAGE || echo postgres:16)}"

# =============================================================================
# Comprobación del .env (lo que el respaldo NO trae)
# =============================================================================

comprobar_env() {
  titulo "El .env y las claves maestras"
  local faltan=()
  for clave in POSTGRES_USER POSTGRES_DB APP_DB_PASSWORD SECRET_KEY CERT_ENC_KEY TOTP_ENC_KEY; do
    valor_env "$clave" >/dev/null || faltan+=("$clave")
  done
  if [[ ${#faltan[@]} -gt 0 ]]; then
    mal "faltan en ${ENV_ARCHIVO}: ${faltan[*]}"
    fallar "sin esas variables el sistema no arranca. CERT_ENC_KEY es la que descifra los .p12: si se perdió, los certificados guardados son ilegibles y cada inquilino tendrá que volver a subir el suyo"
  fi
  ok ".env presente con las claves maestras"
  # BUZON_ENC_KEY solo hace falta si el módulo está encendido; que falte no es
  # un fallo, pero sí un aviso: los correos guardados no se podrán leer.
  if ! valor_env BUZON_ENC_KEY >/dev/null; then
    printf '  %s[aviso]%s BUZON_ENC_KEY no está definida: si el buzón SRI estaba encendido, los correos restaurados no se podrán descifrar\n' "$AMARILLO" "$RESET"
  fi
}

# =============================================================================
# VERIFICACIÓN — el bloque que justifica todo el script
# =============================================================================
#
# Una restauración mala no suele fallar con estruendo: falla en silencio. Las
# cuatro formas de que eso pase aquí son:
#
#   a) Los roles no se recrean o se recrean con atributos distintos. Si
#      factuchat_app acabara con BYPASSRLS, se saltaría TODA la RLS y cada
#      inquilino vería los datos de los demás. Si factuchat_security se quedara
#      sin BYPASSRLS, el login dejaría de funcionar (las funciones auth_* son
#      SECURITY DEFINER suyas).
#   b) Alguna tabla queda con RLS activada pero SIN FORCE. FORCE es lo que
#      somete también al DUEÑO de la tabla. Sin él, basta con que el dueño y el
#      rol de la aplicación coincidan para que las políticas dejen de aplicarse.
#   c) Los GRANTs no se restauran (pasa si el volcado se hizo con -x/--no-acl).
#      Eso sí se nota: la aplicación no puede leer nada.
#   d) audit_log deja de ser inmutable, porque el trigger no se restauró.
#      La bitácora que sostiene A09 y la trazabilidad LOPDP dejaría de servir
#      como evidencia: si se puede editar, no prueba nada.
#
# Todo eso se comprueba abajo, y además se ejecuta la prueba de verdad: conectar
# como la aplicación, sin contexto de inquilino, y confirmar que no se ve ni una
# fila. Es el mismo criterio que backend/tests/test_rls.py::TestAislamientoPostgres.
FALLOS=0
verificar() {
  titulo "Verificación posterior a la restauración"

  # --- 1. los tres roles ------------------------------------------------------
  local fila
  fila="$(consulta "SELECT rolcanlogin||'|'||rolsuper||'|'||rolbypassrls FROM pg_roles WHERE rolname='${PGUSER_}'")"
  if [[ "$fila" == "t|t|"* ]]; then
    ok "rol ${PGUSER_}: LOGIN y superusuario (solo migraciones y CLI, nunca la API)"
  else
    mal "rol ${PGUSER_} con atributos inesperados: ${fila:-no existe}"
    FALLOS=$((FALLOS+1))
  fi

  fila="$(consulta "SELECT rolcanlogin||'|'||rolsuper||'|'||rolbypassrls FROM pg_roles WHERE rolname='factuchat_app'")"
  if [[ "$fila" == "t|f|f" ]]; then
    ok "rol factuchat_app: LOGIN, NOSUPERUSER, NOBYPASSRLS (sujeto a RLS siempre)"
  else
    mal "rol factuchat_app mal: '${fila:-no existe}' (se esperaba t|f|f). Con BYPASSRLS o superusuario, la RLS deja de aislar a los inquilinos"
    FALLOS=$((FALLOS+1))
  fi

  fila="$(consulta "SELECT rolcanlogin||'|'||rolsuper||'|'||rolbypassrls FROM pg_roles WHERE rolname='factuchat_security'")"
  if [[ "$fila" == "f|f|t" ]]; then
    ok "rol factuchat_security: NOLOGIN, NOSUPERUSER, BYPASSRLS (solo actúa por las funciones auth_*/sa_*/sys_*)"
  else
    mal "rol factuchat_security mal: '${fila:-no existe}' (se esperaba f|f|t). Con LOGIN sería una puerta que se salta la RLS; sin BYPASSRLS, el login deja de funcionar"
    FALLOS=$((FALLOS+1))
  fi

  # --- 2. FORCE ROW LEVEL SECURITY en todas las tablas ------------------------
  # alembic_version es la única tabla de public sin RLS, y no debe tenerla: solo
  # guarda el número de revisión y no pertenece a ningún inquilino.
  local sin_force
  sin_force="$(consulta "SELECT string_agg(c.relname, ', ' ORDER BY c.relname)
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind='r' AND c.relname<>'alembic_version'
      AND NOT (c.relrowsecurity AND c.relforcerowsecurity)")"
  if [[ -z "$sin_force" ]]; then
    ok "todas las tablas de negocio tienen ENABLE + FORCE ROW LEVEL SECURITY"
  else
    mal "tablas SIN FORCE ROW LEVEL SECURITY: ${sin_force}"
    mal "esto NO da error en la aplicación: simplemente deja de aislar. Arreglar antes de dar servicio: ALTER TABLE <tabla> ENABLE ROW LEVEL SECURITY; ALTER TABLE <tabla> FORCE ROW LEVEL SECURITY;"
    FALLOS=$((FALLOS+1))
  fi

  local n_force
  n_force="$(consulta "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity AND c.relforcerowsecurity")"
  if [[ -n "$COPIA" && -f "${COPIA}/manifiesto.txt" ]]; then
    local esperadas; esperadas="$(valor_manifiesto tablas_force_rls)"
    if [[ -n "$esperadas" && "$n_force" != "$esperadas" ]]; then
      mal "hay ${n_force} tablas con FORCE y el respaldo tenía ${esperadas}: la restauración quedó incompleta"
      FALLOS=$((FALLOS+1))
    else
      ok "${n_force} tablas con FORCE, las mismas que en el respaldo"
    fi
  else
    ok "${n_force} tablas con FORCE"
  fi

  # --- 3. las políticas siguen ahí --------------------------------------------
  local n_pol
  n_pol="$(consulta "SELECT count(*) FROM pg_policies WHERE schemaname='public'")"
  if [[ "${n_pol:-0}" -gt 0 ]]; then
    ok "${n_pol} políticas RLS presentes"
  else
    mal "no hay ni una política RLS: con FORCE y sin políticas nadie ve nada, y sin FORCE lo ven todo"
    FALLOS=$((FALLOS+1))
  fi

  # --- 4. permisos de la aplicación -------------------------------------------
  local n_grants
  n_grants="$(consulta "SELECT count(*) FROM information_schema.role_table_grants WHERE grantee='factuchat_app' AND table_schema='public'")"
  if [[ "${n_grants:-0}" -gt 0 ]]; then
    ok "${n_grants} permisos de tabla para factuchat_app"
  else
    mal "factuchat_app no tiene ningún permiso: el volcado se hizo con -x/--no-acl o los GRANTs no se restauraron"
    FALLOS=$((FALLOS+1))
  fi

  # audit_log: nadie actualiza ni borra (permisos + trigger). Es la base de A09.
  local grants_audit
  grants_audit="$(consulta "SELECT string_agg(DISTINCT privilege_type, ',') FROM information_schema.role_table_grants WHERE grantee='factuchat_app' AND table_name='audit_log'")"
  if [[ "$grants_audit" == *UPDATE* || "$grants_audit" == *DELETE* ]]; then
    mal "factuchat_app tiene ${grants_audit} sobre audit_log: la bitácora debe ser inmutable (solo SELECT/INSERT)"
    FALLOS=$((FALLOS+1))
  else
    ok "audit_log sin permisos de UPDATE/DELETE para la aplicación (${grants_audit:-sin permisos})"
  fi

  local trig
  trig="$(consulta "SELECT count(*) FROM pg_trigger WHERE tgname='trg_audit_log_inmutable' AND NOT tgisinternal")"
  if [[ "${trig:-0}" == "1" ]]; then
    ok "trigger trg_audit_log_inmutable restaurado"
  else
    mal "falta el trigger trg_audit_log_inmutable: sin él la bitácora se puede editar y deja de valer como evidencia"
    FALLOS=$((FALLOS+1))
  fi

  # --- 5. las funciones seguras y su dueño ------------------------------------
  local n_fn mal_dueno
  n_fn="$(consulta "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prosecdef AND (p.proname LIKE 'auth\\_%' OR p.proname LIKE 'sa\\_%' OR p.proname LIKE 'sys\\_%' OR p.proname LIKE 'publico\\_%')")"
  mal_dueno="$(consulta "SELECT string_agg(p.proname, ', ') FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_roles r ON r.oid=p.proowner WHERE n.nspname='public' AND p.prosecdef AND (p.proname LIKE 'auth\\_%' OR p.proname LIKE 'sa\\_%' OR p.proname LIKE 'sys\\_%' OR p.proname LIKE 'publico\\_%') AND r.rolname<>'factuchat_security'")"
  if [[ "${n_fn:-0}" -gt 0 && -z "$mal_dueno" ]]; then
    ok "${n_fn} funciones SECURITY DEFINER, todas de factuchat_security"
  else
    mal "funciones SECURITY DEFINER: ${n_fn:-0} encontradas; con dueño incorrecto: ${mal_dueno:-ninguna}"
    mal "si el dueño fuera un superusuario, cualquiera que las ejecute correría con permisos de superusuario"
    FALLOS=$((FALLOS+1))
  fi

  # --- 6. la prueba de verdad: conectarse como la aplicación -------------------
  local r
  r="$(consulta_app "SELECT count(*) FROM clientes_finales")"
  if [[ "$r" == "0" ]]; then
    ok "sin contexto de inquilino, factuchat_app no ve ni una fila de clientes_finales (deny by default)"
  elif [[ "$r" =~ ^[0-9]+$ ]]; then
    mal "factuchat_app ve ${r} filas de clientes_finales SIN fijar app.tenant_id: el aislamiento entre inquilinos está roto"
    FALLOS=$((FALLOS+1))
  else
    mal "no se pudo conectar como factuchat_app: ${r}"
    mal "revisa que el rol factuchat_app exista y tenga permisos: los roles se recrean con la contraseña de ahí, y si no coincide la API no levanta"
    FALLOS=$((FALLOS+1))
  fi

  r="$(consulta_app "SET row_security = off; SELECT count(*) FROM clientes_finales")"
  if [[ "$r" =~ ^[0-9]+$ ]]; then
    mal "factuchat_app pudo apagar row_security y leer ${r} filas: solo un rol con BYPASSRLS puede hacer eso"
    FALLOS=$((FALLOS+1))
  else
    ok "factuchat_app no puede apagar row_security"
  fi

  # La prueba va DENTRO de una transacción que nunca confirma. `verificar()` se
  # invoca también con --solo-verificar, que corre contra el sistema VIVO y sin
  # pedir confirmación: un UPDATE suelto sobre la bitácora sería exactamente la
  # alteración que este control existe para impedir. Hoy lo frenan el GRANT y el
  # trigger, pero la prueba no puede depender de que la defensa aguante.
  r="$(consulta_app "BEGIN; UPDATE audit_log SET accion='alterado' WHERE true; ROLLBACK;")"
  if [[ "$r" == *"denied"* || "$r" == *"denegado"* || "$r" == *"inmutable"* || "$r" == *ERROR* ]]; then
    ok "audit_log rechaza el UPDATE de la aplicación (bitácora inmutable)"
  else
    mal "la aplicación pudo escribir sobre audit_log: '${r}'"
    FALLOS=$((FALLOS+1))
  fi

  # --- 7. contenido: que no se haya restaurado una base vacía ------------------
  local esperado real
  for tabla in tenants users comprobantes audit_log; do
    real="$(consulta "SELECT count(*) FROM ${tabla}")"
    if [[ -n "$COPIA" && -f "${COPIA}/manifiesto.txt" ]]; then
      esperado="$(valor_manifiesto "filas_${tabla}")"
      # Las cuentas del manifiesto se toman justo antes del volcado, así que
      # pueden diferir en unas pocas filas escritas mientras se respaldaba. Lo
      # que no es tolerable es que el respaldo tuviera filas y aquí no haya
      # ninguna: eso es una restauración que no restauró.
      if [[ -n "$esperado" && "${esperado:-0}" -gt 0 && "${real:-0}" -eq 0 ]]; then
        mal "${tabla}: el respaldo tenía ${esperado} filas y la base restaurada tiene 0"
        FALLOS=$((FALLOS+1))
      else
        ok "${tabla}: ${real} filas (el respaldo anotó ${esperado:-?})"
      fi
    else
      ok "${tabla}: ${real} filas"
    fi
  done

  # --- 8. la versión de esquema coincide --------------------------------------
  local alembic_real alembic_esp
  alembic_real="$(consulta "SELECT version_num FROM alembic_version LIMIT 1")"
  if [[ -n "$COPIA" && -f "${COPIA}/manifiesto.txt" ]]; then
    alembic_esp="$(valor_manifiesto alembic_version)"
    if [[ -n "$alembic_esp" && "$alembic_real" != "$alembic_esp" ]]; then
      mal "revisión de Alembic ${alembic_real}, el respaldo era ${alembic_esp}"
      FALLOS=$((FALLOS+1))
    else
      ok "revisión de Alembic ${alembic_real}"
    fi
  else
    ok "revisión de Alembic ${alembic_real}"
  fi

  # --- 9. los ficheros están donde la base dice --------------------------------
  # Una fila de `comprobantes` con estado AUTORIZADO cuyo XML no exista en disco
  # no sirve de nada: el XML firmado es el documento con valor tributario.
  local n_ficheros
  n_ficheros="$(docker run --rm --network none -v "${PROYECTO}_comprobantes:/datos:ro" "$IMAGEN_TAR" \
    sh -c 'find /datos -type f 2>/dev/null | wc -l' || echo 0)"
  n_ficheros="$(printf '%s' "$n_ficheros" | tr -d '[:space:]')"
  local aut
  aut="$(consulta "SELECT count(*) FROM comprobantes WHERE estado='AUTORIZADO'")"
  if [[ "${aut:-0}" -gt 0 && "${n_ficheros:-0}" -eq 0 ]]; then
    mal "hay ${aut} comprobantes AUTORIZADOS en la base y el volumen de ficheros está vacío: faltan los XML firmados y los RIDE"
    FALLOS=$((FALLOS+1))
  else
    ok "volumen ${PROYECTO}_comprobantes con ${n_ficheros} ficheros (XML, RIDE, buzón y comprobantes de pago)"
  fi
}

# =============================================================================
# Modo solo verificar
# =============================================================================

if [[ "$SOLO_VERIFICAR" == true ]]; then
  servicio_corriendo postgres || fallar "postgres no está corriendo"
  [[ -n "$APP_PASS_" ]] || fallar "falta APP_DB_PASSWORD en el .env"
  comprobar_env
  verificar
  echo
  if [[ "$FALLOS" -eq 0 ]]; then
    printf '%sTodas las comprobaciones en verde.%s Guarda esta salida como evidencia (control A.8.13).\n' "$VERDE" "$RESET"
    decir "solo-verificar: 0 fallos"
    exit 0
  fi
  printf '%s%d comprobación(es) fallidas.%s\n' "$ROJO" "$FALLOS" "$RESET"
  decir "solo-verificar: ${FALLOS} fallos"
  exit 1
fi

# =============================================================================
# Restauración: comprobaciones previas
# =============================================================================

[[ -n "$COPIA" ]] || fallar "falta la ruta de la copia. Ejemplo: ./restaurar.sh /var/backups/factuchat/copias/20260825T060000Z-diario"
[[ -d "$COPIA" ]] || fallar "no existe la carpeta ${COPIA}"
[[ -f "${COPIA}/manifiesto.txt" ]] || fallar "${COPIA} no tiene manifiesto.txt: no es un respaldo de este sistema o quedó a medias"
[[ -f "${COPIA}/.en-curso" ]] && fallar "esa copia está marcada como incompleta (.en-curso): el respaldo se cortó a medias. Usa otra"
[[ -f "${COPIA}/bd.dump.age" ]] || fallar "falta ${COPIA}/bd.dump.age"

command -v age >/dev/null 2>&1 || fallar "falta el programa 'age'. En Ubuntu 24: sudo apt install age"
[[ -n "$AGE_IDENTIDAD" ]] || fallar "falta AGE_IDENTIDAD (la clave privada del respaldo). No está en el VPS a propósito: tráela ahora y llévatela al terminar"
[[ -f "$AGE_IDENTIDAD" ]] || fallar "no existe la identidad ${AGE_IDENTIDAD}"
[[ -n "$APP_PASS_" ]] || fallar "falta APP_DB_PASSWORD en el .env: es la contraseña con la que se recrea factuchat_app y con la que conecta la API"

comprobar_env

titulo "Integridad de la copia"
# Antes de destruir nada, comprobar que lo que vamos a poner en su sitio llegó
# entero. Si el fichero cifrado está corrupto, mejor saberlo con la base vieja
# todavía en pie.
while IFS='=' read -r clave esperado; do
  [[ "$clave" == sha256_cifrado_* ]] || continue
  fichero="${COPIA}/${clave#sha256_cifrado_}"
  [[ -f "$fichero" ]] || fallar "el manifiesto menciona $(basename "$fichero") y no está en la carpeta"
  real="$(sha256sum "$fichero" | cut -d' ' -f1)"
  [[ "$real" == "$esperado" ]] || fallar "$(basename "$fichero") no coincide con su SHA-256: la copia llegó corrupta. No sigas: usa otra copia"
  ok "$(basename "$fichero") íntegro"
done < "${COPIA}/manifiesto.txt"

MARCA_COPIA="$(valor_manifiesto marca_utc)"
VOLS_COPIA="$(valor_manifiesto volumenes)"
VOLS_COPIA="${VOLS_COPIA:-comprobantes}"

# -----------------------------------------------------------------------------
# ¿Hay ficheros que estorben? Se pregunta AQUÍ, antes de la confirmación y muy
# antes del DROP DATABASE.
#
# Comprobarlo en el paso 5 dejaba el sistema a medias: se destruía la base, se
# restauraba el volcado y solo entonces el script abortaba por los ficheros, con
# api, worker y beat parados y una base de hace horas conviviendo con ficheros
# actuales. Una comprobación que puede abortar tiene que correr antes de lo
# irreversible, no después.
# -----------------------------------------------------------------------------
for vol in $VOLS_COPIA; do
  destino_previo="${PROYECTO}_${vol}"
  docker volume inspect "$destino_previo" >/dev/null 2>&1 || continue
  ocupados_previo="$(docker run --rm --network none -v "${destino_previo}:/datos:ro" \
    "$IMAGEN_TAR" sh -c 'ls -A /datos 2>/dev/null | wc -l' | tr -d '[:space:]')"
  if [[ "${ocupados_previo:-0}" -gt 0 && "$SOBRESCRIBIR_FICHEROS" != true ]]; then
    fallar "el volumen ${destino_previo} ya tiene ${ocupados_previo} entradas y NO se ha tocado nada todavía. Mezclar ficheros de dos momentos distintos deja XML huérfanos que no corresponden a ninguna fila. Repite con --sobrescribir-ficheros, que lo vacía antes de extraer."
  fi
done

# =============================================================================
# Confirmación explícita
# =============================================================================

titulo "Esto es lo que va a pasar"
cat <<RESUMEN
  Copia            : ${COPIA}
  Tomada el (UTC)  : ${MARCA_COPIA:-desconocido}
  Revisión Alembic : $(valor_manifiesto alembic_version)
  Filas de origen  : tenants=$(valor_manifiesto filas_tenants), users=$(valor_manifiesto filas_users), comprobantes=$(valor_manifiesto filas_comprobantes)

  SE VA A DESTRUIR:
    - La base de datos '${PGDB_}' COMPLETA (DROP DATABASE). Todo lo emitido,
      cobrado y auditado después de ${MARCA_COPIA:-esa fecha} se pierde.
    - Los volúmenes ${VOLS_COPIA} (XML firmados, RIDE, correos del buzón
      y comprobantes de pago): si ya tienen contenido, la restauración se
      DETIENE salvo que pases --sobrescribir-ficheros, y con ese flag se
      VACÍAN por completo antes de extraer el respaldo$( [[ "$SOBRESCRIBIR_FICHEROS" == true ]] && echo " [--sobrescribir-ficheros]" )

  SE VAN A PARAR: api, worker, beat (mientras dure la restauración).
  NO se toca: el .env, los certificados TLS, ni las imágenes.

  Antes de confirmar, comprueba que ${MARCA_COPIA:-la fecha de la copia} es la
  que quieres. Restaurar una copia más vieja de lo necesario borra comprobantes
  ya autorizados por el SRI, y esos no se pueden volver a emitir con la misma
  clave de acceso.
RESUMEN

FRASE="RESTAURAR ${PGDB_}"
if [[ -n "$CONFIRMO" ]]; then
  [[ "$CONFIRMO" == "$FRASE" ]] || fallar "CONFIRMO no coincide. Debe ser exactamente: ${FRASE}"
  decir "confirmado por variable de entorno"
else
  [[ -t 0 ]] || fallar "no hay terminal y no se pasó CONFIRMO='${FRASE}'. Este script NO debe correr desatendido por accidente"
  printf '\n%sEscribe exactamente%s  %s  %spara continuar (cualquier otra cosa cancela):%s\n> ' \
    "$ROJO" "$RESET" "$FRASE" "$ROJO" "$RESET"
  read -r respuesta
  [[ "$respuesta" == "$FRASE" ]] || { decir "cancelado por el operador"; fallar "cancelado. No se tocó nada"; }
fi

# =============================================================================
# Manos a la obra
# =============================================================================

mkdir -p "$TRABAJO_DIR"; chmod 700 "$TRABAJO_DIR"
TMP="$(mktemp -d "${TRABAJO_DIR}/rest.XXXXXX")"
# Aquí se escribe el volcado DESCIFRADO. Es el único momento en que los datos de
# todos los inquilinos están en claro en disco; se borra pase lo que pase.
limpiar() { rm -rf "$TMP"; }
trap limpiar EXIT

titulo "1. Parando los servicios que escriben"
dc stop api worker beat >/dev/null 2>&1 || true
ok "api, worker y beat parados"
if ! servicio_corriendo postgres; then
  dc up -d postgres >/dev/null 2>&1 || true
  sleep 5
fi
servicio_corriendo postgres || fallar "postgres no arranca"
ok "postgres en pie"

titulo "2. Descifrando"
age -d -i "$AGE_IDENTIDAD" "${COPIA}/bd.dump.age" > "${TMP}/bd.dump" \
  || fallar "no se pudo descifrar bd.dump.age. ¿Es la clave privada que corresponde a la pública con la que se cifró?"
sha_esperado="$(valor_manifiesto sha256_claro_bd)"
sha_real="$(sha256sum "${TMP}/bd.dump" | cut -d' ' -f1)"
if [[ -n "$sha_esperado" && "$sha_real" != "$sha_esperado" ]]; then
  fallar "el volcado descifrado no coincide con el SHA-256 que anotó el respaldo: está alterado o corrupto"
fi
ok "volcado descifrado y verificado byte a byte"

for vol in $VOLS_COPIA; do
  [[ -f "${COPIA}/${vol}.tar.gz.age" ]] || fallar "falta ${vol}.tar.gz.age en la copia"
  age -d -i "$AGE_IDENTIDAD" "${COPIA}/${vol}.tar.gz.age" > "${TMP}/${vol}.tar.gz" \
    || fallar "no se pudo descifrar ${vol}.tar.gz.age"
  sha_esperado="$(valor_manifiesto "sha256_claro_${vol}")"
  sha_real="$(sha256sum "${TMP}/${vol}.tar.gz" | cut -d' ' -f1)"
  if [[ -n "$sha_esperado" && "$sha_real" != "$sha_esperado" ]]; then
    fallar "${vol}.tar.gz no coincide con su SHA-256"
  fi
  ok "volumen ${vol} descifrado y verificado"
done

titulo "3. Recreando los roles que pg_dump no guarda"
# pg_dump no guarda roles: son del clúster, no de la base. En un VPS nuevo los
# crea deploy/postgres/init/01-roles.sh, pero SOLO la primera vez que se
# inicializa el clúster; si el volumen pgdata ya existe, ese script no vuelve a
# correr nunca. Por eso se recrean aquí, con los mismos atributos exactos:
#   factuchat_app      LOGIN, NOSUPERUSER, NOBYPASSRLS  -> siempre sujeto a RLS
#   factuchat_security NOLOGIN, BYPASSRLS               -> solo por sus funciones
# La contraseña se manda por la entrada estándar de psql, nunca en la línea de
# órdenes: los argumentos de un proceso los ve cualquier usuario del servidor
# con `ps`, y el .env está en 600 justamente para que eso no pase.
APP_PASS_SQL="${APP_PASS_//\'/\'\'}"   # duplicar comillas simples para SQL
{
  cat <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'factuchat_security') THEN
    CREATE ROLE factuchat_security NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
  ELSE
    ALTER ROLE factuchat_security NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'factuchat_app') THEN
    CREATE ROLE factuchat_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  ELSE
    ALTER ROLE factuchat_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;
SQL
  printf "ALTER ROLE factuchat_app PASSWORD '%s';\n" "$APP_PASS_SQL"
} | psql_admin postgres >/dev/null || fallar "no se pudieron recrear los roles"
ok "factuchat_app y factuchat_security recreados con sus atributos"

titulo "4. Restaurando la base de datos"
# Cortar las conexiones abiertas: DROP DATABASE falla si queda una sola sesión,
# y con api/worker parados solo suelen quedar sesiones colgadas.
psql_admin postgres >/dev/null <<SQL || true
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = '${PGDB_}' AND pid <> pg_backend_pid();
SQL
psql_admin postgres >/dev/null <<SQL || fallar "no se pudo recrear la base ${PGDB_}"
DROP DATABASE IF EXISTS "${PGDB_}";
-- TEMPLATE template0: partir de una plantilla limpia evita arrastrar objetos o
-- ajustes de la base anterior que el volcado no espera encontrar.
CREATE DATABASE "${PGDB_}" OWNER "${PGUSER_}" TEMPLATE template0 ENCODING 'UTF8';
SQL
ok "base ${PGDB_} recreada, vacía y propiedad de ${PGUSER_}"

# --single-transaction: o entra todo o no entra nada. Una restauración a medias
# es el peor resultado posible, porque parece que funciona.
# Sin --no-owner: se conserva el dueño original de cada tabla (${PGUSER_}). Si
# las tablas acabaran siendo de factuchat_app, ese rol sería dueño y, en cuanto
# faltara FORCE en alguna, se saltaría sus propias políticas.
if ! dc exec -T postgres pg_restore -U "$PGUSER_" -d "$PGDB_" \
      --single-transaction --exit-on-error < "${TMP}/bd.dump"; then
  fallar "pg_restore falló. La base quedó vacía (la transacción se revirtió entera). Revisa el registro en ${LOG_ARCHIVO} y prueba con otra copia"
fi
ok "volcado restaurado"

titulo "5. Restaurando los ficheros"
for vol in $VOLS_COPIA; do
  destino="${PROYECTO}_${vol}"
  docker volume inspect "$destino" >/dev/null 2>&1 || {
    docker volume create "$destino" >/dev/null
    ok "volumen ${destino} creado"
  }
  ocupados="$(docker run --rm --network none -v "${destino}:/datos:ro" "$IMAGEN_TAR" \
    sh -c 'ls -A /datos 2>/dev/null | wc -l' | tr -d '[:space:]')"
  if [[ "${ocupados:-0}" -gt 0 && "$SOBRESCRIBIR_FICHEROS" != true ]]; then
    fallar "el volumen ${destino} ya tiene ${ocupados} entradas. Mezclar ficheros de dos momentos distintos deja XML huérfanos que no corresponden a ninguna fila. Vacíalo a conciencia o repite con --sobrescribir-ficheros"
  fi
  if [[ "${ocupados:-0}" -gt 0 ]]; then
    # --sobrescribir-ficheros tiene que VACIAR de verdad. Extraer encima solo
    # pisa los ficheros del mismo nombre y deja intactos los demás: quedarían
    # mezclados XML posteriores al respaldo con los restaurados, y el conteo de
    # más abajo —que solo detecta si faltan— daría el visto bueno igualmente.
    decir "vaciando ${destino} (${ocupados} entradas) antes de extraer"
    docker run --rm --network none -v "${destino}:/datos" "$IMAGEN_TAR" \
      find /datos -mindepth 1 -delete \
      || fallar "no se pudo vaciar ${destino}"
  fi
  # El contenedor extrae como root para conservar el usuario y el grupo con los
  # que el worker escribió cada fichero; si no, la API podría no poder leerlos.
  gzip -dc "${TMP}/${vol}.tar.gz" | docker run --rm -i --network none \
    -v "${destino}:/datos" "$IMAGEN_TAR" tar -C /datos --same-owner -xf - \
    || fallar "no se pudieron extraer los ficheros en ${destino}"
  n="$(docker run --rm --network none -v "${destino}:/datos:ro" "$IMAGEN_TAR" \
    sh -c 'find /datos -type f | wc -l' | tr -d '[:space:]')"
  esperados="$(valor_manifiesto "ficheros_${vol}")"
  if [[ -n "$esperados" && "${n:-0}" -lt "${esperados:-0}" ]]; then
    # El respaldo cuenta los ficheros justo antes de empaquetar, así que puede
    # haber alguno MÁS (el worker siguió emitiendo). Menos, no: eso es un tar
    # incompleto y significa que hay XML firmados que no volvieron.
    mal "${destino}: ${n} ficheros restaurados y el respaldo anotó ${esperados}. Faltan documentos"
    FALLOS=$((FALLOS+1))
  else
    ok "${destino}: ${n} ficheros restaurados (el respaldo anotó ${esperados:-?})"
  fi
done

titulo "6. Levantando los servicios"
dc up -d >/dev/null 2>&1 || fallar "no se pudieron levantar los servicios"
ok "api, worker y beat arriba"

# La API tarda en pasar su healthcheck (start_period 40s en el compose).
estado=""
for _ in $(seq 1 24); do
  estado="$(salud_servicio api)"
  [[ "$estado" == "healthy" ]] && break
  sleep 5
done
if [[ "$estado" == "healthy" ]]; then
  ok "la API responde sana"
else
  printf '  %s[aviso]%s la API no reporta healthy (estado: %s); revisa: docker compose logs api\n' \
    "$AMARILLO" "$RESET" "$estado"
fi

# =============================================================================
# 7. Verificación
# =============================================================================
verificar

echo
if [[ "$FALLOS" -eq 0 ]]; then
  printf '%sRestauración completada y verificada.%s\n' "$VERDE" "$RESET"
  cat <<'CIERRE'

Queda por hacer a mano:
  1. Guardar esta salida completa como evidencia de la prueba (control A.8.13
     pide prueba de restauración mensual documentada, y A.5.30 continuidad).
  2. Llevarte la clave privada age del servidor. Si se queda aquí, cifrar los
     respaldos deja de servir para nada.
  3. Emitir un comprobante de prueba contra el ambiente PRUEBAS del SRI
     (deploy/scripts/emision-prueba-sri.md): es lo único que confirma que el
     .p12 restaurado se descifra de verdad con la CERT_ENC_KEY del .env.
  4. Revisar la cola: los comprobantes que quedaron a medio camino los recoge
     el barrido de `barrer_atascados` (cada 10 minutos), pero conviene mirarlo.
CIERRE
  decir "restauración OK, 0 fallos"
  exit 0
fi

printf '%sLa restauración terminó con %d comprobación(es) fallidas.%s\n' "$ROJO" "$FALLOS" "$RESET"
printf 'NO des servicio hasta resolverlas: varias de ellas (FORCE RLS, atributos de los roles)\n'
printf 'no producen ningún error visible y sin embargo rompen el aislamiento entre inquilinos.\n'
decir "restauración con ${FALLOS} fallos"
exit 1
