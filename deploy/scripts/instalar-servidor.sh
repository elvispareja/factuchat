#!/usr/bin/env bash
# =============================================================================
# instalar-servidor.sh — Endurecimiento del VPS de Factuchat
# =============================================================================
# Cubre los pasos 1, 2, 8 y 9 de la lista de despliegue de PLAN.md:
#
#   1. Ubuntu 24 limpio: usuario no-root con sudo, SSH solo con llave, puerto
#      SSH no estándar, fail2ban, ufw con solo 80/443 y el puerto SSH.
#   2. Docker + Compose (la parte del servidor; el endurecimiento de los
#      contenedores vive en deploy/docker-compose.prod.yml).
#   8. unattended-upgrades para el sistema operativo.
#   9. Registro y trazabilidad (ISO 27001 A.8.15): logrotate a 12 meses para
#      los logs de nginx, api y worker + retención del journal.
#
# NO cubre —y se dice al final, en el resumen— los pasos 3 (TLS), 4 (Postgres y
# Redis), 5 (secretos), 6 (respaldos), 7 (monitoreo) ni 10 (continuidad).
#
# CÓMO SE USA
# -----------
#   sudo ./instalar-servidor.sh --dry-run     # enseña todo lo que haría
#   sudo ./instalar-servidor.sh               # aplica, dejando el 22 abierto
#   # ...abrir una sesión NUEVA en el puerto nuevo y comprobar que entra...
#   sudo -E ./instalar-servidor.sh --confirmar-ssh  # recién ahí cierra el 22
#   # (-E conserva SSH_CONNECTION, que sudo borra por defecto)
#
# EL PASO EN DOS TIEMPOS NO ES UN CAPRICHO: cambiar el puerto de SSH y cerrar el
# 22 en la misma pasada es la forma clásica de quedarse fuera del propio
# servidor. Aquí el 22 sigue abierto hasta que TÚ vuelvas a entrar por el puerto
# nuevo y lo confirmes. --confirmar-ssh comprueba, ANTES de tocar el cortafuegos,
# que la sesión desde la que lo invocas llegó por el puerto nuevo; si no, aborta
# sin haber cambiado nada.
#
# Es idempotente: correrlo dos veces no rompe nada ni reabre lo ya cerrado.
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Parámetros. Todos por variable de entorno, con valores por defecto sensatos.
# -----------------------------------------------------------------------------

# Usuario de operación. PLAN.md paso 1: nadie opera como root.
USUARIO="${FC_USUARIO:-factuchat}"

# Puerto SSH no estándar. No es seguridad por oscuridad: es higiene de registro.
# El 22 recibe miles de intentos automatizados al día y esos intentos ahogan el
# journal, que es justamente donde vive la evidencia de accesos (A.8.15) y de
# donde lee fail2ban. Mover el puerto deja el registro legible.
# 2222 es el "puerto alternativo" más escaneado del mundo; por eso el defecto no
# es ese. Cámbialo si quieres, cualquier valor por encima de 1024 sirve.
PUERTO_SSH="${FC_PUERTO_SSH:-52222}"

# Llave pública autorizada. Si se deja vacío, se busca en el authorized_keys de
# quien invoca (SUDO_USER) y luego en el de root: en un VPS recién entregado la
# llave con la que entraste está ahí. Se valida con ssh-keygen antes de usarla.
LLAVE_ORIGEN="${FC_LLAVE_PUBLICA:-}"

# Quién puede entrar por SSH (directiva AllowUsers). Si tienes más cuentas
# legítimas en la máquina, pásalas separadas por espacios o vaciarás su acceso.
ALLOW_USERS="${FC_ALLOW_USERS:-$USUARIO}"

# Dónde vivirá el repositorio en el VPS (solo se usa para el resumen final).
DIR_APP="${FC_DIR:-/opt/factuchat}"

# Directorio de logs de la aplicación en el HOST, el que rota logrotate.
DIR_LOGS="${FC_LOGS:-/var/log/factuchat}"

# Retención de registros en meses. PLAN.md paso 9 e ISO 27001 A.8.15: 12 meses.
RETENCION_MESES="${FC_RETENCION_MESES:-12}"

# fail2ban: 5 intentos en 15 minutos, veto de 1 hora. Coincide a propósito con
# el rate limit de la aplicación (LOGIN_MAX_ATTEMPTS=5 / LOGIN_WINDOW_SECONDS=900
# en backend/.env.example): dos capas con el mismo criterio, una en la red y
# otra en la aplicación.
F2B_MAXRETRY="${FC_F2B_MAXRETRY:-5}"
F2B_FINDTIME="${FC_F2B_FINDTIME:-15m}"
F2B_BANTIME="${FC_F2B_BANTIME:-1h}"

# Meter al usuario en el grupo docker es equivalente a darle root sin contraseña
# (puede montar / dentro de un contenedor). Por eso el defecto es NO hacerlo: se
# opera con `sudo docker compose ...`. Poner "si" solo si sabes lo que implica.
USUARIO_EN_DOCKER="${FC_USUARIO_EN_DOCKER:-no}"

# Tope de los logs de stdout de los contenedores (api, worker, beat, nginx).
# Es un tope de TAMAÑO, no la retención de 12 meses: ver la sección del paso 9.
DOCKER_LOG_MAX="${FC_DOCKER_LOG_MAX:-50m}"
DOCKER_LOG_FICHEROS="${FC_DOCKER_LOG_FICHEROS:-10}"

# Escapes de emergencia, todos apagados por defecto.
IGNORAR_VERSION="${FC_IGNORAR_VERSION:-no}"   # correr en algo que no es Ubuntu 24
SIN_SESION_SSH="${FC_SIN_SESION_SSH:-no}"     # confirmar desde consola web del proveedor

# Estado interno.
DRY_RUN=no
CONFIRMAR_SSH=no
MARCA_DIR="/etc/factuchat"
MARCA_SSH="$MARCA_DIR/ssh-confirmado"
RESPALDOS="/var/backups/factuchat"
ARCHIVO_CAMBIADO=no
AVISOS=()

# -----------------------------------------------------------------------------
# Utilidades de presentación y de escritura idempotente
# -----------------------------------------------------------------------------

if [[ -t 1 ]]; then
    C_TIT=$'\033[1;36m'; C_OK=$'\033[0;32m'; C_AV=$'\033[0;33m'
    C_ERR=$'\033[0;31m'; C_DIM=$'\033[2m'; C_FIN=$'\033[0m'
else
    C_TIT=""; C_OK=""; C_AV=""; C_ERR=""; C_DIM=""; C_FIN=""
fi

titulo()  { printf '\n%s== %s ==%s\n' "$C_TIT" "$*" "$C_FIN"; }
ok()      { printf '   %s✓%s %s\n' "$C_OK" "$C_FIN" "$*"; }
detalle() { printf '   %s· %s%s\n' "$C_DIM" "$*" "$C_FIN"; }
aviso()   { printf '   %s! %s%s\n' "$C_AV" "$*" "$C_FIN"; AVISOS+=("$*"); }
fatal()   { printf '\n%sABORTADO: %s%s\n\n' "$C_ERR" "$*" "$C_FIN" >&2; exit 1; }

# Ejecuta un comando, o lo enseña si estamos en --dry-run.
correr() {
    if [[ "$DRY_RUN" == "si" ]]; then
        printf '   %s[dry-run]%s %s\n' "$C_DIM" "$C_FIN" "$*"
    else
        "$@"
    fi
}

# escribir_archivo RUTA MODO [COMANDO_DE_VALIDACIÓN]
# El contenido llega por stdin. Solo escribe si el contenido cambió, así que
# correr el script dos veces no toca marcas de tiempo ni dispara reinicios.
# Si se pasa un comando de validación, se le da el archivo TEMPORAL: si no pasa,
# el destino real no se toca (nunca se instala un sshd_config o un sudoers roto).
#
# SIEMPRE se invoca con  < <( ... )  y NUNCA con una tubería: el lado derecho de
# una tubería corre en una subshell y ARCHIVO_CAMBIADO no volvería. De eso
# depende que se reinicie sshd cuando toca, así que no es un detalle de estilo.
escribir_archivo() {
    local ruta="$1" modo="$2" validador="${3:-}" tmp
    ARCHIVO_CAMBIADO=no
    tmp="$(mktemp)"
    cat >"$tmp"

    if [[ -n "$validador" ]]; then
        if ! $validador "$tmp" >/dev/null 2>&1; then
            rm -f "$tmp"
            fatal "el contenido generado para $ruta no pasó la validación ($validador). No se tocó nada."
        fi
    fi

    if [[ -f "$ruta" ]] && cmp -s "$tmp" "$ruta"; then
        rm -f "$tmp"
        detalle "sin cambios: $ruta"
        return 0
    fi

    if [[ "$DRY_RUN" == "si" ]]; then
        printf '   %s[dry-run]%s escribiría %s (modo %s):\n' "$C_DIM" "$C_FIN" "$ruta" "$modo"
        sed 's/^/        | /' "$tmp"
        rm -f "$tmp"
        ARCHIVO_CAMBIADO=si
        return 0
    fi

    # Respaldo del anterior: si algo sale mal se sabe qué había antes.
    if [[ -f "$ruta" ]]; then
        mkdir -p "$RESPALDOS"
        cp -a "$ruta" "$RESPALDOS/$(basename "$ruta").$(date +%Y%m%d%H%M%S).bak"
    fi

    mkdir -p "$(dirname "$ruta")"
    install -m "$modo" "$tmp" "$ruta"
    rm -f "$tmp"
    ok "escrito $ruta"
    ARCHIVO_CAMBIADO=si
}

# Instala paquetes solo si falta alguno (apt es idempotente pero lento y ruidoso).
instalar_paquetes() {
    local faltan=()
    for p in "$@"; do
        dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "ok installed" || faltan+=("$p")
    done
    if [[ ${#faltan[@]} -eq 0 ]]; then
        detalle "ya instalados: $*"
        return 0
    fi
    detalle "faltan: ${faltan[*]}"
    correr env DEBIAN_FRONTEND=noninteractive apt-get install -y "${faltan[@]}"
}

uso() {
    cat <<'AYUDA'
Uso: sudo ./instalar-servidor.sh [--dry-run] [--confirmar-ssh]

  --dry-run         Enseña cada archivo que escribiría y cada comando que
                    correría, sin tocar el servidor. No requiere confirmar nada.
  --confirmar-ssh   Segunda pasada: cierra el puerto 22 en sshd y en ufw.
                    Solo funciona si la sesión desde la que se invoca entró por
                    el puerto SSH nuevo (o con FC_SIN_SESION_SSH=si desde la
                    consola web del proveedor).
  -h, --ayuda       Esta ayuda.

Variables de entorno principales (valor por defecto entre paréntesis):
  FC_USUARIO (factuchat)        FC_PUERTO_SSH (52222)
  FC_LLAVE_PUBLICA (autodetect) FC_ALLOW_USERS (= FC_USUARIO)
  FC_DIR (/opt/factuchat)       FC_LOGS (/var/log/factuchat)
  FC_RETENCION_MESES (12)       FC_USUARIO_EN_DOCKER (no)
  FC_F2B_MAXRETRY (5)           FC_F2B_FINDTIME (15m)   FC_F2B_BANTIME (1h)
AYUDA
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)       DRY_RUN=si ;;
        --confirmar-ssh) CONFIRMAR_SSH=si ;;
        -h|--ayuda|--help) uso; exit 0 ;;
        *) printf 'Opción desconocida: %s\n\n' "$1" >&2; uso >&2; exit 2 ;;
    esac
    shift
done

printf '%s\n' "============================================================"
printf '%s\n' " Factuchat — endurecimiento del VPS (PLAN.md pasos 1, 2, 8, 9)"
[[ "$DRY_RUN" == "si" ]] && printf '%s MODO --dry-run: no se modifica NADA %s\n' "$C_AV" "$C_FIN"
printf '%s\n' "============================================================"

# =============================================================================
# COMPROBACIONES PREVIAS
# Control: no se empieza a endurecer una máquina que no es la esperada. Un
# script de este tipo a medio aplicar es peor que no haberlo corrido.
# =============================================================================
titulo "Comprobaciones previas"

# --- Que se corra con privilegios ---------------------------------------------
[[ "$(id -u)" -eq 0 ]] || fatal "hay que correrlo con sudo (toca sshd, ufw, apt y systemd)."
ok "ejecutando como root${SUDO_USER:+ (vía sudo, invocado por $SUDO_USER)}"

# --- Que sea Ubuntu 24 --------------------------------------------------------
# Importa de verdad: Ubuntu 24.04 trae dos cambios que rompen recetas viejas y
# que este script maneja explícitamente más abajo — SSH activado por socket
# (systemd) y la desaparición de /var/log/auth.log (todo va al journal).
if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
else
    fatal "no existe /etc/os-release: no puedo confirmar la distribución."
fi
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != 24.* ]]; then
    if [[ "$IGNORAR_VERSION" == "si" ]]; then
        aviso "no es Ubuntu 24 (${PRETTY_NAME:-desconocido}) y se continúa por FC_IGNORAR_VERSION=si"
    else
        fatal "esto está escrito y probado para Ubuntu 24 y aquí hay '${PRETTY_NAME:-desconocido}'. Con FC_IGNORAR_VERSION=si se salta esta comprobación bajo tu responsabilidad."
    fi
else
    ok "sistema: ${PRETTY_NAME}"
    [[ "${VERSION_ID}" == "24.04" ]] || aviso "${VERSION_ID} no es LTS; PLAN.md asume 24.04 LTS"
fi

# --- Que el puerto SSH sea usable --------------------------------------------
[[ "$PUERTO_SSH" =~ ^[0-9]+$ ]] && (( PUERTO_SSH >= 1 && PUERTO_SSH <= 65535 )) \
    || fatal "FC_PUERTO_SSH='$PUERTO_SSH' no es un puerto válido."
if [[ "$PUERTO_SSH" == "22" ]]; then
    aviso "el puerto sigue siendo el 22; PLAN.md paso 1 pide uno no estándar"
elif (( PUERTO_SSH < 1024 )); then
    aviso "puerto $PUERTO_SSH por debajo de 1024: válido, pero revísalo"
fi
if [[ "$PUERTO_SSH" == "80" || "$PUERTO_SSH" == "443" ]]; then
    fatal "el puerto SSH no puede ser $PUERTO_SSH: ahí escucha nginx (deploy/docker-compose.prod.yml)."
fi
ok "puerto SSH objetivo: $PUERTO_SSH"

# --- Localizar la llave pública ANTES de tocar nada ---------------------------
# Sin llave válida no se avanza: todo lo que viene después (PasswordAuthentication
# no, PermitRootLogin no, AllowUsers) deja la máquina accesible ÚNICAMENTE por
# llave. Descubrir aquí que no hay llave es un mensaje de error; descubrirlo
# después de reiniciar sshd es una reinstalación del VPS.
if [[ -z "$LLAVE_ORIGEN" ]]; then
    for candidato in \
        "${SUDO_USER:+/home/$SUDO_USER/.ssh/authorized_keys}" \
        "/root/.ssh/authorized_keys" \
        "/home/$USUARIO/.ssh/authorized_keys"
    do
        [[ -n "$candidato" && -s "$candidato" ]] && { LLAVE_ORIGEN="$candidato"; break; }
    done
fi
[[ -n "$LLAVE_ORIGEN" ]] || fatal "no encontré ninguna llave pública. Indica el archivo con FC_LLAVE_PUBLICA=/ruta/a/id_ed25519.pub"
[[ -s "$LLAVE_ORIGEN" ]] || fatal "el archivo de llave '$LLAVE_ORIGEN' no existe o está vacío."

# Validar cada línea con ssh-keygen: un archivo con basura pasa un `test -s` pero
# sshd lo ignora, y ahí es donde aparece el candado sin llave.
llave_valida() {
    local tmp; tmp="$(mktemp)"
    printf '%s\n' "$1" >"$tmp"
    if ssh-keygen -l -f "$tmp" >/dev/null 2>&1; then rm -f "$tmp"; return 0; fi
    rm -f "$tmp"; return 1
}
LLAVES_OK=()
while IFS= read -r linea; do
    [[ -z "${linea// }" || "$linea" == \#* ]] && continue
    if llave_valida "$linea"; then
        LLAVES_OK+=("$linea")
        detalle "llave válida: $(printf '%s\n' "$linea" | awk '{print $1, substr($2,1,16)"…", $3}')"
    else
        aviso "línea ignorada en $LLAVE_ORIGEN (no es una llave pública válida)"
    fi
done <"$LLAVE_ORIGEN"
[[ ${#LLAVES_OK[@]} -gt 0 ]] || fatal "'$LLAVE_ORIGEN' no contiene ninguna llave pública válida según ssh-keygen."
ok "${#LLAVES_OK[@]} llave(s) pública(s) válida(s) en $LLAVE_ORIGEN"

correr mkdir -p "$MARCA_DIR" "$RESPALDOS"
correr chmod 0755 "$MARCA_DIR"

# =============================================================================
# PASO 1.a — USUARIO NO-ROOT CON SUDO
# Control: nadie opera como root. Si una credencial se pierde, lo que se pierde
# es una cuenta con sudo trazable en el journal, no la máquina entera. Además
# habilita AllowUsers/PermitRootLogin no, que es lo que apaga el objetivo #1 de
# todo bot de internet: root por contraseña.
# =============================================================================
titulo "Paso 1.a — Usuario de operación '$USUARIO' con sudo"

if id -u "$USUARIO" >/dev/null 2>&1; then
    ok "el usuario '$USUARIO' ya existe"
else
    # --disabled-password: nace SIN contraseña. El acceso será por llave.
    correr adduser --disabled-password --gecos "" "$USUARIO"
    ok "usuario '$USUARIO' creado sin contraseña (acceso por llave)"
fi

if id -nG "$USUARIO" 2>/dev/null | tr ' ' '\n' | grep -qx sudo; then
    ok "'$USUARIO' ya está en el grupo sudo"
else
    correr usermod -aG sudo "$USUARIO"
    ok "'$USUARIO' añadido al grupo sudo"
fi

# Un usuario sin contraseña no puede usar sudo (sudo se la pediría y no existe),
# así que sin esto la cuenta quedaría inservible para administrar. La contraseña
# de sudo es el segundo factor si algún día roban la llave privada; por eso, si
# el usuario YA tiene contraseña, se respeta y no se concede NOPASSWD.
ESTADO_PASS="$(passwd -S "$USUARIO" 2>/dev/null | awk '{print $2}' || echo "?")"
if [[ "$ESTADO_PASS" == "P" ]]; then
    ok "'$USUARIO' tiene contraseña: sudo la pedirá (mejor, es un segundo factor)"
    if [[ -f /etc/sudoers.d/90-factuchat ]]; then
        correr rm -f /etc/sudoers.d/90-factuchat
        aviso "retirado el NOPASSWD anterior: ahora hay contraseña y sudo debe exigirla"
    fi
else
    # visudo -cf valida el archivo TEMPORAL antes de instalarlo. Un sudoers roto
    # deja la máquina sin escalada de privilegios para nadie.
    escribir_archivo /etc/sudoers.d/90-factuchat 0440 "visudo -cf" < <(
        printf '# Factuchat — %s no tiene contraseña, así que sudo no puede pedirla.\n# Ponle contraseña (sudo passwd %s) y vuelve a correr el script: se retira\n# este archivo solo y sudo pasa a exigirla.\n%s ALL=(ALL) NOPASSWD:ALL\n' \
            "$USUARIO" "$USUARIO" "$USUARIO"
    )
    aviso "'$USUARIO' opera con sudo SIN contraseña. Ponle una con 'sudo passwd $USUARIO' y vuelve a correr el script."
fi

# =============================================================================
# PASO 1.b — LLAVE PÚBLICA INSTALADA Y VERIFICADA
# Control: acceso solo con llave. Esta es la verificación que hace imposible el
# error clásico: la llave se instala y se COMPRUEBA aquí; si algo de esto falla,
# el script muere antes de tocar sshd, y la máquina se queda como estaba.
# =============================================================================
titulo "Paso 1.b — Llave pública de '$USUARIO'"

HOME_USR="$(getent passwd "$USUARIO" | cut -d: -f6)"
[[ -n "$HOME_USR" ]] || HOME_USR="/home/$USUARIO"
DIR_SSH="$HOME_USR/.ssh"
AUTH_KEYS="$DIR_SSH/authorized_keys"

if [[ "$DRY_RUN" == "si" ]]; then
    detalle "[dry-run] instalaría ${#LLAVES_OK[@]} llave(s) en $AUTH_KEYS"
else
    mkdir -p "$DIR_SSH"
    touch "$AUTH_KEYS"
    nuevas=0
    for k in "${LLAVES_OK[@]}"; do
        if grep -qxF "$k" "$AUTH_KEYS"; then
            detalle "ya estaba: $(printf '%s\n' "$k" | awk '{print substr($2,1,16)"…"}')"
        else
            printf '%s\n' "$k" >>"$AUTH_KEYS"
            nuevas=$((nuevas + 1))
        fi
    done
    # sshd aplica StrictModes: si el home, el .ssh o el authorized_keys son
    # escribibles por el grupo o por otros, IGNORA las llaves en silencio. Ese
    # silencio es exactamente el que deja a la gente fuera.
    chown -R "$USUARIO:$USUARIO" "$DIR_SSH"
    chmod 700 "$DIR_SSH"
    chmod 600 "$AUTH_KEYS"
    chmod g-w,o-w "$HOME_USR"
    ok "$nuevas llave(s) nueva(s); permisos 700/600 y propietario $USUARIO aplicados"
fi

# Verificación dura: se vuelve a LEER lo instalado y se valida con ssh-keygen.
# No se confía en que los comandos de arriba hayan funcionado, se comprueba.
verificar_llave_instalada() {
    [[ "$DRY_RUN" == "si" ]] && { detalle "[dry-run] no se verifica la llave instalada"; return 0; }
    [[ -s "$AUTH_KEYS" ]] || fatal "$AUTH_KEYS quedó vacío o no existe. NO se toca sshd."
    ssh-keygen -l -f "$AUTH_KEYS" >/dev/null 2>&1 \
        || fatal "$AUTH_KEYS no contiene ninguna llave que ssh-keygen reconozca. NO se toca sshd."
    [[ "$(stat -c '%U' "$AUTH_KEYS")" == "$USUARIO" ]] \
        || fatal "$AUTH_KEYS no pertenece a $USUARIO. sshd lo rechazaría. NO se toca sshd."
    local perm_dir perm_key
    perm_dir="$(stat -c '%a' "$DIR_SSH")"; perm_key="$(stat -c '%a' "$AUTH_KEYS")"
    [[ "$perm_dir" == "700" ]] || fatal "$DIR_SSH tiene permisos $perm_dir (deben ser 700). NO se toca sshd."
    [[ "$perm_key" == "600" ]] || fatal "$AUTH_KEYS tiene permisos $perm_key (deben ser 600). NO se toca sshd."
    ok "verificado: $(grep -cvE '^\s*(#|$)' "$AUTH_KEYS") llave(s) legible(s) por sshd para '$USUARIO'"
}
verificar_llave_instalada

# =============================================================================
# PASO 1.c — CORTAFUEGOS ufw
# Control: solo 80/443 (nginx, el único servicio publicado en
# deploy/docker-compose.prod.yml) y el puerto SSH. Todo lo demás, denegado.
# ORDEN DELIBERADO: el cortafuegos se configura y se VERIFICA ANTES de tocar
# sshd. Cambiar el puerto de SSH con el nuevo puerto cerrado en ufw es la otra
# mitad del error clásico.
# =============================================================================
titulo "Paso 1.c — Cortafuegos ufw (80, 443 y $PUERTO_SSH)"

correr apt-get update -qq
instalar_paquetes ufw

# -----------------------------------------------------------------------------
# VERIFICACIÓN DE LA SESIÓN — tiene que ocurrir AQUÍ, antes de tocar nada.
#
# Comprobarlo al final del script no sirve de nada: para entonces el 22 ya se
# retiró de ufw y de sshd, así que un `fatal` llegaría cuando el operador ya
# está fuera. La barrera contra el error clásico solo es barrera si se levanta
# ANTES de cerrar la puerta.
# -----------------------------------------------------------------------------

# Puerto por el que entró la sesión actual.
#
# SSH_CONNECTION es lo directo, pero `sudo` en Ubuntu trae `Defaults env_reset`
# y no la conserva: dentro del script llega SIEMPRE vacía. Si dependiéramos solo
# de ella, la única salida sería FC_SIN_SESION_SSH=si, que desactiva justo la
# barrera que este script existe para dar. Así que se busca por otras vías:
#   1. SSH_CONNECTION, por si se invocó con `sudo -E`.
#   2. El puerto local del socket de la sesión, subiendo por los procesos padre
#      hasta encontrar el sshd que la atiende.
puerto_de_la_sesion() {
    if [[ -n "${SSH_CONNECTION:-}" ]]; then
        printf '%s\n' "$SSH_CONNECTION" | awk '{print $4}'
        return 0
    fi
    command -v ss >/dev/null 2>&1 || return 1

    local pid="$PPID" intentos=0 puerto=""
    while [[ -n "$pid" && "$pid" != "1" && "$intentos" -lt 12 ]]; do
        puerto="$(ss -tnpH state established 2>/dev/null \
            | grep -F "pid=${pid}," \
            | awk '{print $3}' | awk -F: '{print $NF}' | head -n1)"
        [[ -n "$puerto" ]] && { printf '%s\n' "$puerto"; return 0; }
        pid="$(awk '{print $4}' "/proc/${pid}/stat" 2>/dev/null || true)"
        intentos=$((intentos + 1))
    done
    return 1
}

verificar_sesion_ssh() {
    [[ "$CONFIRMAR_SSH" == "si" && "$PUERTO_SSH" != "22" ]] || return 0

    local puerto_sesion
    if puerto_sesion="$(puerto_de_la_sesion)" && [[ -n "$puerto_sesion" ]]; then
        if [[ "$puerto_sesion" == "$PUERTO_SSH" ]]; then
            ok "esta sesión entró por el puerto $puerto_sesion: el puerto nuevo está demostrado"
            return 0
        fi
        fatal "esta sesión entró por el puerto $puerto_sesion, no por el $PUERTO_SSH. Abre una sesión nueva en el $PUERTO_SSH y confirma desde ahí; el 22 se queda abierto y NO se ha tocado nada."
    fi

    if [[ "$SIN_SESION_SSH" == "si" ]]; then
        aviso "sin sesión SSH (consola del proveedor) y se continúa por FC_SIN_SESION_SSH=si: comprueba TÚ que entras por el $PUERTO_SSH"
        return 0
    fi
    fatal "no pude averiguar por qué puerto entró esta sesión. Reintenta con: sudo -E $0 --confirmar-ssh (sudo -E conserva SSH_CONNECTION), o usa FC_SIN_SESION_SSH=si si estás en la consola web del proveedor y ya comprobaste a mano que entras por el $PUERTO_SSH."
}
verificar_sesion_ssh

# ¿Ya se confirmó el cambio de puerto en una pasada anterior? Entonces el 22 no
# se vuelve a abrir aunque se corra el script otra vez (idempotencia real).
YA_CONFIRMADO=no
[[ -f "$MARCA_SSH" ]] && YA_CONFIRMADO=si

CERRAR_22=no
if [[ "$PUERTO_SSH" == "22" ]]; then
    CERRAR_22=no
elif [[ "$CONFIRMAR_SSH" == "si" || "$YA_CONFIRMADO" == "si" ]]; then
    CERRAR_22=si
fi

correr ufw default deny incoming
correr ufw default allow outgoing

# 'limit' en vez de 'allow' para SSH: ufw veta la IP que abre más de 6
# conexiones en 30 segundos. Es la primera línea, barata y sin estado de
# aplicación; fail2ban es la segunda, que sí lee los intentos fallidos.
correr ufw limit "$PUERTO_SSH/tcp" comment "SSH Factuchat"
correr ufw allow 80/tcp  comment "HTTP (redirige a HTTPS)"
correr ufw allow 443/tcp comment "HTTPS nginx"

if [[ "$CERRAR_22" == "si" ]]; then
    # `ufw delete` falla si la regla no existe; con `|| true` el script sigue.
    if [[ "$DRY_RUN" == "si" ]]; then
        detalle "[dry-run] borraría las reglas del puerto 22"
    else
        ufw delete limit 22/tcp >/dev/null 2>&1 || true
        ufw delete allow 22/tcp >/dev/null 2>&1 || true
        ok "puerto 22 retirado de ufw"
    fi
else
    correr ufw limit 22/tcp comment "SSH temporal - cerrar con --confirmar-ssh"
    detalle "el 22 queda abierto a propósito hasta que confirmes el puerto nuevo"
fi

if ufw status | grep -q "Status: active"; then
    ok "ufw ya estaba activo"
else
    correr ufw --force enable
    ok "ufw activado"
fi

# Verificación dura: el puerto SSH nuevo TIENE que estar permitido. Si esta
# comprobación no pasa, no se sigue: lo siguiente es cambiar el puerto de sshd.
verificar_ufw() {
    [[ "$DRY_RUN" == "si" ]] && { detalle "[dry-run] no se verifica ufw"; return 0; }
    ufw status | grep -qE "^${PUERTO_SSH}/tcp[[:space:]]+(ALLOW|LIMIT)" \
        || fatal "ufw NO tiene abierto el puerto $PUERTO_SSH. NO se toca sshd: cambiarlo ahora te dejaría fuera."
    ufw status | grep -qE "^80/tcp[[:space:]]+(ALLOW|LIMIT)"  || aviso "el puerto 80 no aparece permitido en ufw"
    ufw status | grep -qE "^443/tcp[[:space:]]+(ALLOW|LIMIT)" || aviso "el puerto 443 no aparece permitido en ufw"
    ok "verificado en ufw: $PUERTO_SSH abierto, 80 y 443 abiertos, el resto denegado"
}
verificar_ufw

# ADVERTENCIA REAL, no de plantilla: Docker publica puertos escribiendo reglas
# en la cadena DOCKER de nat, que se evalúa ANTES que las de ufw. Un puerto
# publicado con `ports:` queda expuesto a internet aunque ufw diga "deny".
# Hoy no es un problema porque en deploy/docker-compose.prod.yml solo nginx
# publica (80 y 443) y postgres y redis no tienen `ports:`. Pero si alguien
# añade `ports:` a postgres "un momentito para depurar", ufw no lo va a tapar.
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    publicados="$(docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null \
        | grep -E '0\.0\.0\.0:|:::' | grep -vE ':(80|443)->' || true)"
    if [[ -n "$publicados" ]]; then
        aviso "hay contenedores publicando puertos distintos de 80/443, y ufw NO los filtra:"
        printf '%s\n' "$publicados" | sed 's/^/        /'
    else
        ok "ningún contenedor publica puertos fuera de 80/443"
    fi
fi

# =============================================================================
# PASO 1.d — SSH: SOLO LLAVE, PUERTO NO ESTÁNDAR, SIN ROOT
# Control: elimina de un golpe la contraseña adivinable y el usuario root como
# blanco. Con AuthenticationMethods publickey, un atacante sin la llave privada
# no tiene NADA que probar.
#
# Dos trampas de Ubuntu 24 que este bloque maneja y que rompen las recetas de
# internet:
#  1) SSH viene activado por SOCKET (ssh.socket). Con socket activation, la
#     directiva `Port` de sshd_config SE IGNORA: el puerto lo decide el
#     ListenStream del socket de systemd. Quien solo edita sshd_config cree que
#     cambió el puerto, cierra el 22 y se queda fuera.
#  2) sshd se queda con el PRIMER valor de cada palabra clave, y las imágenes
#     de nube traen /etc/ssh/sshd_config.d/50-cloud-init.conf con
#     PasswordAuthentication yes. Por eso este archivo se llama 01-: para ganar.
# =============================================================================
titulo "Paso 1.d — Endurecimiento de SSH"

# ¿Existe el Include de drop-ins? Si no, hay que editar el archivo principal y
# eso ya no es este script.
if ! grep -qE '^\s*Include\s+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config; then
    fatal "/etc/ssh/sshd_config no incluye /etc/ssh/sshd_config.d/*.conf. Este sshd no es el estándar de Ubuntu 24 y no voy a editar el archivo principal a ciegas."
fi
ok "sshd lee los drop-ins de /etc/ssh/sshd_config.d/"

# Detectar activación por socket.
SSH_POR_SOCKET=no
if systemctl is-active --quiet ssh.socket 2>/dev/null \
   || [[ "$(systemctl is-enabled ssh.socket 2>/dev/null || true)" == "enabled" ]]; then
    SSH_POR_SOCKET=si
    ok "SSH activado por socket (ssh.socket): el puerto se fija en el socket, no en sshd_config"
else
    ok "SSH como servicio clásico (ssh.service): el puerto se fija con 'Port' en sshd_config"
fi

# Puertos a escuchar durante esta pasada.
if [[ "$CERRAR_22" == "si" || "$PUERTO_SSH" == "22" ]]; then
    PUERTOS_SSH=("$PUERTO_SSH")
else
    PUERTOS_SSH=(22 "$PUERTO_SSH")
fi
detalle "sshd escuchará en: ${PUERTOS_SSH[*]}"

# Delatar cualquier otro drop-in que pelee por las mismas directivas.
for otro in /etc/ssh/sshd_config.d/*.conf; do
    [[ -e "$otro" ]] || continue
    [[ "$(basename "$otro")" == "01-factuchat.conf" ]] && continue
    if grep -qiE '^\s*(PasswordAuthentication|PermitRootLogin|Port|AuthenticationMethods)\b' "$otro"; then
        detalle "$(basename "$otro") también fija directivas de acceso; 01-factuchat.conf se lee antes y gana"
    fi
done

# --- Foto previa, para poder deshacer -----------------------------------------
# Deshacer NO es "borrar los archivos": si esta máquina ya tenía el puerto
# confirmado y el 22 cerrado en ufw, borrar la configuración devolvería sshd al
# puerto 22... que ya no está abierto. Eso es precisamente el candado sin llave
# que este script existe para evitar. Se guarda el estado ANTERIOR y se restaura
# tal cual, incluida la posibilidad de que el archivo no existiera.
SSH_ARCHIVOS=(
    /etc/ssh/sshd_config.d/01-factuchat.conf
    /etc/systemd/system/ssh.socket.d/10-factuchat-puerto.conf
)
FOTO_SSH=""
if [[ "$DRY_RUN" != "si" ]]; then
    FOTO_SSH="$(mktemp -d)"
    for f in "${SSH_ARCHIVOS[@]}"; do
        if [[ -f "$f" ]]; then
            cp -a "$f" "$FOTO_SSH/$(basename "$f")"
        else
            : >"$FOTO_SSH/$(basename "$f").ausente"
        fi
    done
    detalle "estado previo de SSH guardado en $FOTO_SSH"
fi

# --- Construir el drop-in ------------------------------------------------------
escribir_archivo /etc/ssh/sshd_config.d/01-factuchat.conf 0644 < <(
    cat <<FIN
# Factuchat — endurecimiento de SSH (PLAN.md paso 1). Generado por
# deploy/scripts/instalar-servidor.sh. No editar a mano: se regenera.
#
# Se llama 01- a propósito: sshd conserva el PRIMER valor de cada palabra clave,
# así que 50-cloud-init.conf no puede volver a encender la contraseña.
FIN

    if [[ "$SSH_POR_SOCKET" == "si" ]]; then
        cat <<FIN

# El puerto NO va aquí: con ssh.socket activo esta directiva se ignora. Vive en
# /etc/systemd/system/ssh.socket.d/10-factuchat-puerto.conf (ListenStream).
FIN
    else
        printf '\n'
        for p in "${PUERTOS_SSH[@]}"; do printf 'Port %s\n' "$p"; done
    fi

    cat <<FIN

# Solo llave. Sin contraseña que adivinar no hay fuerza bruta posible: un bot
# sin la llave privada no tiene nada que enviar.
PubkeyAuthentication yes
AuthenticationMethods publickey
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no

# root no entra por SSH. Se entra como $USUARIO y se escala con sudo, que deja
# rastro con nombre y hora en el journal (ISO 27001 A.8.15).
PermitRootLogin no
AllowUsers $ALLOW_USERS

# Superficie mínima y sesiones que no se quedan colgadas.
MaxAuthTries 3
MaxSessions 5
LoginGraceTime 30
X11Forwarding no
AllowAgentForwarding no
ClientAliveInterval 300
ClientAliveCountMax 2

# AllowTcpForwarding se queda en 'yes' A PROPÓSITO: PostgreSQL y Redis no se
# publican nunca (paso 4 de PLAN.md), así que el túnel SSH es la ÚNICA forma
# correcta de que un administrador llegue a la base. Apagarlo empujaría a
# publicar el puerto, que es justo lo que no se quiere.
AllowTcpForwarding yes
FIN
)
DROPIN_CAMBIO="$ARCHIVO_CAMBIADO"

# --- Socket de systemd, si aplica ---------------------------------------------
SOCKET_CAMBIO=no
if [[ "$SSH_POR_SOCKET" == "si" ]]; then
    escribir_archivo /etc/systemd/system/ssh.socket.d/10-factuchat-puerto.conf 0644 < <(
        cat <<FIN
# Factuchat — puerto de escucha de SSH (PLAN.md paso 1).
# El ListenStream vacío BORRA la lista heredada (el 22 de la unidad original);
# sin esa línea, systemd añadiría los puertos nuevos y seguiría oyendo el 22.
[Socket]
ListenStream=
FIN
        for p in "${PUERTOS_SSH[@]}"; do printf 'ListenStream=%s\n' "$p"; done
    )
    SOCKET_CAMBIO="$ARCHIVO_CAMBIADO"
fi

# --- Validar, aplicar y COMPROBAR que quedó escuchando -------------------------
# Restaura el estado EXACTO que había antes de esta ejecución y reinicia SSH.
revertir_ssh() {
    printf '%s   Revirtiendo el cambio de SSH al estado anterior…%s\n' "$C_AV" "$C_FIN" >&2
    local base
    for f in "${SSH_ARCHIVOS[@]}"; do
        base="$FOTO_SSH/$(basename "$f")"
        if [[ -f "$base" ]]; then
            install -m 0644 "$base" "$f"          # había uno: se repone tal cual
            printf '     repuesto %s\n' "$f" >&2
        elif [[ -f "$base.ausente" ]]; then
            rm -f "$f"                            # no había: se quita el nuevo
            printf '     retirado %s (no existía antes)\n' "$f" >&2
        fi
    done
    systemctl daemon-reload >/dev/null 2>&1 || true
    if [[ "$SSH_POR_SOCKET" == "si" ]]; then
        systemctl restart ssh.socket >/dev/null 2>&1 || true
    else
        systemctl restart ssh >/dev/null 2>&1 || true
    fi
    # Si el rollback deja SSH en un puerto que ufw no tiene abierto, decirlo a
    # gritos: el operador todavía tiene su sesión actual viva para arreglarlo.
    if ! ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.](${PUERTO_SSH}|22)$"; then
        printf '%s   ATENCIÓN: SSH no escucha ni en %s ni en el 22. NO cierres esta sesión.%s\n' \
            "$C_ERR" "$PUERTO_SSH" "$C_FIN" >&2
    fi
}

if [[ "$DRY_RUN" == "si" ]]; then
    detalle "[dry-run] validaría con 'sshd -t' y reiniciaría SSH, comprobando que escucha en ${PUERTOS_SSH[*]}"
elif [[ "$DROPIN_CAMBIO" == "si" || "$SOCKET_CAMBIO" == "si" ]]; then
    # 'sshd -t' antes de reiniciar. Un sshd_config inválido + restart = sshd que
    # no arranca = servidor inalcanzable.
    if ! sshd -t 2>/tmp/factuchat-sshd-t.err; then
        printf '%s\n' "$(cat /tmp/factuchat-sshd-t.err)" >&2
        revertir_ssh
        fatal "la configuración de sshd no es válida. Se revirtió y NO se reinició nada."
    fi
    ok "configuración de sshd válida (sshd -t)"

    if [[ "$SSH_POR_SOCKET" == "si" ]]; then
        systemctl daemon-reload
        systemctl restart ssh.socket
    else
        systemctl restart ssh
    fi

    # La comprobación que salva: ¿está sshd realmente escuchando en el puerto
    # nuevo? Es la que caza la trampa del socket. Si falla, se revierte.
    escuchando=no
    for _ in $(seq 1 20); do
        if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${PUERTO_SSH}$"; then
            escuchando=si; break
        fi
        sleep 0.5
    done
    if [[ "$escuchando" != "si" ]]; then
        revertir_ssh
        fatal "SSH NO quedó escuchando en el puerto $PUERTO_SSH. Se revirtió todo y el acceso sigue como estaba."
    fi
    ok "verificado: SSH escuchando en el puerto $PUERTO_SSH"

    if [[ "$CERRAR_22" != "si" && "$PUERTO_SSH" != "22" ]]; then
        ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE '[:.]22$' \
            && ok "el 22 sigue escuchando (red de seguridad hasta que confirmes)" \
            || aviso "el 22 ya no escucha; comprueba el acceso por $PUERTO_SSH antes de cerrar esta sesión"
    fi
else
    ok "la configuración de SSH ya estaba aplicada; no hace falta reiniciar"
fi

# =============================================================================
# PASO 1.e — fail2ban
# Control: veta la IP que insiste. Con el acceso solo por llave el riesgo de
# adivinar la contraseña es cero, pero fail2ban sigue valiendo por dos motivos
# concretos: corta el ruido que ahoga el registro de accesos (A.8.15) y frena el
# consumo de CPU de miles de negociaciones SSH por hora.
# =============================================================================
titulo "Paso 1.e — fail2ban"

instalar_paquetes fail2ban

# DOS DETALLES QUE HACEN QUE ESTO FUNCIONE DE VERDAD EN UBUNTU 24:
#  1) backend = systemd. Ubuntu 24.04 ya no trae rsyslog: /var/log/auth.log NO
#     existe. El backend de archivo por defecto no encuentra nada que leer y el
#     jail se queda "activo" sin vetar jamás a nadie: un control que parece
#     puesto y no lo está.
#  2) banaction = ufw. Sin esto fail2ban escribe en iptables por su cuenta,
#     conviviendo con ufw. Con esto, los vetos se ven en 'ufw status' y hay un
#     solo lugar donde mirar quién está bloqueado.
escribir_archivo /etc/fail2ban/jail.d/factuchat.local 0644 < <(
    cat <<FIN
# Factuchat — fail2ban (PLAN.md paso 1). Generado por instalar-servidor.sh.
[DEFAULT]
# Ubuntu 24.04 no instala rsyslog y /var/log/auth.log no existe: sin este
# backend el jail no lee nada y no veta a nadie.
backend   = systemd
banaction = ufw
bantime   = $F2B_BANTIME
findtime  = $F2B_FINDTIME
maxretry  = $F2B_MAXRETRY
ignoreip  = 127.0.0.1/8 ::1

[sshd]
enabled = true
port    = $(IFS=,; echo "${PUERTOS_SSH[*]}")
FIN
)

if [[ "$DRY_RUN" == "si" ]]; then
    detalle "[dry-run] activaría y reiniciaría fail2ban, y comprobaría el jail sshd"
else
    correr systemctl enable --quiet fail2ban
    systemctl restart fail2ban
    # Verificar que el jail existe DE VERDAD. Un fail2ban arrancado con un jail
    # roto no es protección, es una casilla marcada en falso.
    listo=no
    for _ in $(seq 1 20); do
        if fail2ban-client status sshd >/dev/null 2>&1; then listo=si; break; fi
        sleep 0.5
    done
    if [[ "$listo" == "si" ]]; then
        ok "jail 'sshd' activo — $F2B_MAXRETRY intentos / $F2B_FINDTIME, veto $F2B_BANTIME, vía ufw"
    else
        aviso "fail2ban arrancó pero el jail 'sshd' no responde. Revisa: journalctl -u fail2ban -n 50"
    fi
fi

# =============================================================================
# PASO 2 — DOCKER Y COMPOSE
# Control: desde el repositorio oficial de Docker con su llave GPG, no desde el
# script conveniente de internet ni desde snap. Es OWASP A03 (cadena de
# suministro) aplicado a la propia máquina: paquetes firmados y verificables.
# Ojo con el alcance: aquí se instala el MOTOR. El endurecimiento de los
# contenedores (usuario no-root, read_only, límites de CPU/memoria, digests
# fijados, trivy) es cosa de deploy/docker-compose.prod.yml, no de este script.
# =============================================================================
titulo "Paso 2 — Docker Engine y Compose"

instalar_paquetes ca-certificates curl gnupg

if [[ -f /etc/apt/keyrings/docker.asc ]]; then
    ok "llave GPG de Docker ya presente"
else
    correr install -m 0755 -d /etc/apt/keyrings
    if [[ "$DRY_RUN" == "si" ]]; then
        detalle "[dry-run] descargaría https://download.docker.com/linux/ubuntu/gpg a /etc/apt/keyrings/docker.asc"
    else
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
        ok "llave GPG de Docker instalada"
    fi
fi

ARCH="$(dpkg --print-architecture)"
CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-noble}}"
escribir_archivo /etc/apt/sources.list.d/docker.list 0644 < <(
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
        "$ARCH" "$CODENAME"
)
[[ "$ARCHIVO_CAMBIADO" == "si" ]] && correr apt-get update -qq

instalar_paquetes docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

if [[ "$DRY_RUN" != "si" ]]; then
    systemctl enable --quiet docker 2>/dev/null || true
    systemctl start docker 2>/dev/null || true
    if docker compose version >/dev/null 2>&1; then
        ok "$(docker --version) · $(docker compose version)"
    else
        aviso "el plugin 'docker compose' no responde; revisa: docker compose version"
    fi
fi

# --- Tope de tamaño de los logs de contenedor ---------------------------------
# api, worker, beat y nginx escriben a stdout y Docker los guarda como JSON en
# /var/lib/docker/containers/. Sin tope, un worker con un fallo en bucle llena
# el disco y tumba PostgreSQL, que es el peor final posible para un sistema de
# facturación. ESTO ES UN TOPE DE TAMAÑO, NO LA RETENCIÓN DE 12 MESES: eso se
# resuelve en el paso 9, más abajo, y hoy está incompleto.
#
# OJO CON EL ALCANCE: esto es el DEFECTO del demonio y no manda sobre Factuchat.
# Los servicios de deploy/docker-compose.prod.yml declaran su propio `logging`
# (ancla x-registro: max-size 20m, max-file 5) y la opción por servicio gana
# siempre sobre la del demonio. Este daemon.json cubre a cualquier contenedor
# que NO fije el suyo, que es donde suele aparecer el disco lleno.
escribir_archivo /etc/docker/daemon.json 0644 < <(
    cat <<FIN
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "$DOCKER_LOG_MAX",
    "max-file": "$DOCKER_LOG_FICHEROS",
    "compress": "true"
  },
  "live-restore": true
}
FIN
)

if [[ "$ARCHIVO_CAMBIADO" == "si" && "$DRY_RUN" != "si" ]]; then
    # Reiniciar el demonio detiene los contenedores. Si Factuchat ya está
    # corriendo, no se reinicia por las buenas: se deja para la ventana semanal
    # de mantenimiento (PLAN.md paso 8).
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^factuchat-'; then
        aviso "daemon.json actualizado pero Factuchat está corriendo: NO se reinició Docker. Hazlo en la ventana de mantenimiento con 'sudo systemctl restart docker'."
    else
        systemctl restart docker
        ok "Docker reiniciado con los límites de log aplicados"
    fi
fi

if [[ "$USUARIO_EN_DOCKER" == "si" ]]; then
    correr usermod -aG docker "$USUARIO"
    aviso "'$USUARIO' está en el grupo docker: eso equivale a root sin contraseña en esta máquina"
else
    ok "'$USUARIO' NO está en el grupo docker (se opera con 'sudo docker compose'); pertenecer a ese grupo equivale a root"
fi

# =============================================================================
# PASO 8 — ACTUALIZACIONES AUTOMÁTICAS DEL SISTEMA OPERATIVO
# Control: los parches de seguridad del SO se aplican solos. La mayoría de las
# intrusiones no usan un fallo nuevo, usan uno viejo sin parchar. Esto cubre el
# SO ÚNICAMENTE: las imágenes de Docker se actualizan en la ventana semanal tras
# pasar trivy (PLAN.md paso 8), y eso todavía no está automatizado.
# =============================================================================
titulo "Paso 8 — unattended-upgrades (solo el sistema operativo)"

instalar_paquetes unattended-upgrades apt-listchanges

escribir_archivo /etc/apt/apt.conf.d/20auto-upgrades 0644 < <(
    printf '%s\n' \
        'APT::Periodic::Update-Package-Lists "1";' \
        'APT::Periodic::Unattended-Upgrade "1";' \
        'APT::Periodic::AutocleanInterval "7";'
)

escribir_archivo /etc/apt/apt.conf.d/52factuchat-seguridad 0644 < <(
cat <<'FIN'
// Factuchat (PLAN.md paso 8). Generado por instalar-servidor.sh.

// Solo orígenes de SEGURIDAD. Actualizar todo automáticamente en un servidor de
// facturación cambia versiones de paquetes sin que nadie lo pruebe.
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};

// Docker fuera del automático A PROPÓSITO: actualizar docker-ce reinicia el
// demonio y se llevaría por delante api, worker, beat, postgres, redis y nginx,
// eventualmente en mitad de una firma de comprobante. Docker se actualiza en la
// ventana semanal de mantenimiento, después de pasar trivy.
Unattended-Upgrade::Package-Blacklist {
    "docker-ce";
    "docker-ce-cli";
    "containerd.io";
};

Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";

// Sin reinicio automático: un reinicio a las 3 de la mañana con el worker
// firmando facturas es peor que un kernel con el parche pendiente unas horas.
// El reinicio va en la ventana semanal; el resumen de este script avisa cuando
// hay uno pendiente (/var/run/reboot-required).
Unattended-Upgrade::Automatic-Reboot "false";

Unattended-Upgrade::SyslogEnable "true";
FIN
)

if [[ "$DRY_RUN" != "si" ]]; then
    correr systemctl enable --quiet unattended-upgrades
    if unattended-upgrade --dry-run --debug >/dev/null 2>&1; then
        ok "unattended-upgrades activo y con configuración válida"
    else
        aviso "unattended-upgrades no valida su configuración; revisa: sudo unattended-upgrade --dry-run --debug"
    fi
fi

# =============================================================================
# PASO 9 — REGISTRO Y TRAZABILIDAD (ISO 27001 A.8.15, OWASP A09)
# Control: 12 meses de registros. No es burocracia: cuando aparece un acceso
# indebido, la pregunta del auditor y la del cliente es "desde cuándo y quién",
# y sin registros no hay respuesta. Son tres piezas distintas y conviene no
# confundirlas:
#   - audit_log en PostgreSQL: la bitácora de NEGOCIO, inmutable, ya construida
#     (migración 0002, backend/app/core/audit.py). No la toca este script.
#   - journal de systemd: sshd, sudo y fail2ban. La evidencia de ACCESO a la
#     máquina. En Ubuntu 24 es el único sitio donde vive: no hay auth.log.
#   - logs de nginx, api y worker: los del servicio. Aquí es donde hay un hueco
#     que se declara abajo sin adornos.
# =============================================================================
titulo "Paso 9 — Retención de registros ($RETENCION_MESES meses)"

# --- Journal de systemd: la evidencia de acceso -------------------------------
correr mkdir -p /var/log/journal
escribir_archivo /etc/systemd/journald.conf.d/factuchat.conf 0644 < <(
    cat <<FIN
# Factuchat (PLAN.md paso 9 / ISO 27001 A.8.15).
# En Ubuntu 24 no hay rsyslog: los intentos de SSH, los sudo y los vetos de
# fail2ban SOLO viven aquí. Sin retención explícita, el journal se recicla por
# tamaño en semanas y la evidencia de acceso desaparece.
[Journal]
Storage=persistent
Compress=yes
MaxRetentionSec=${RETENCION_MESES}month
SystemMaxUse=2G
SystemKeepFree=1G
FIN
)
if [[ "$ARCHIVO_CAMBIADO" == "si" && "$DRY_RUN" != "si" ]]; then
    systemctl restart systemd-journald
    ok "journald con retención de $RETENCION_MESES meses (tope 2 GB: manda el que llegue primero)"
fi

# --- Directorio de logs de la aplicación en el host ---------------------------
correr mkdir -p "$DIR_LOGS/nginx" "$DIR_LOGS/api" "$DIR_LOGS/worker"
correr chmod 0755 "$DIR_LOGS"
ok "directorio de logs: $DIR_LOGS/{nginx,api,worker}"

# --- Regla de logrotate --------------------------------------------------------
# copytruncate y no 'create' + postrotate, por dos razones concretas de este
# despliegue: (1) nginx corre DENTRO de un contenedor con su propio uid, y un
# archivo nuevo creado por root en el host puede quedar sin permiso de escritura
# para él, cortando el log en silencio; (2) un postrotate que llame a docker
# falla si el contenedor está parado, y entonces nginx sigue escribiendo en el
# archivo ya rotado. copytruncate puede perder las líneas del instante exacto de
# la rotación; a cambio, no deja nunca de registrar.
escribir_archivo /etc/logrotate.d/factuchat 0644 < <(
    cat <<FIN
# Factuchat — retención de $RETENCION_MESES meses (PLAN.md paso 9, ISO 27001 A.8.15).
# Generado por deploy/scripts/instalar-servidor.sh. No editar a mano.
$DIR_LOGS/*.log
$DIR_LOGS/*/*.log
{
    monthly
    rotate $RETENCION_MESES
    dateext
    dateformat -%Y%m
    missingok
    notifempty
    compress
    copytruncate
    su root adm
    create 0640 root adm
}
FIN
)

if [[ "$DRY_RUN" != "si" ]]; then
    if logrotate -d /etc/logrotate.d/factuchat >/dev/null 2>&1; then
        ok "regla de logrotate válida: rota cada mes y guarda $RETENCION_MESES"
    else
        aviso "logrotate no valida la regla; revisa: sudo logrotate -d /etc/logrotate.d/factuchat"
    fi
fi

# --- El hueco, dicho con todas las letras -------------------------------------
# La regla de arriba es correcta y está puesta, pero HOY NO ROTA NADA, porque
# nada escribe en $DIR_LOGS:
#   - nginx escribe en /var/log/nginx DENTRO del contenedor (deploy/nginx/nginx.conf
#     líneas 9 y 24). deploy/docker-compose.prod.yml SÍ monta algo ahí: el
#     volumen Docker `nginx-logs:/var/log/nginx`, así que los logs NO se pierden
#     al recrear el contenedor y deploy/scripts/respaldo.sh los copia. Pero
#     viven bajo /var/lib/docker/volumes/factuchat_nginx-logs/_data, que esta
#     regla —que solo mira $DIR_LOGS— no alcanza.
#   - api, worker y beat escriben a stdout y los recoge Docker, que rota por
#     TAMAÑO (el ancla x-registro del compose), no por tiempo.
# El arreglo no es de este script sino del compose. Se repite en el resumen
# final para que no se pierda.
if ! grep -q "$DIR_LOGS" "$DIR_APP/deploy/docker-compose.prod.yml" 2>/dev/null; then
    aviso "logrotate está puesto pero los logs no pasan por $DIR_LOGS: nginx escribe en el volumen nginx-logs y api/worker en el driver de Docker (ver el resumen)"
fi

# =============================================================================
# CIERRE DEL PUERTO 22 — segunda pasada, con verificación de sesión
# Control: esta es la barrera que impide el error clásico. El 22 solo se cierra
# cuando se demuestra que el puerto nuevo funciona, y la demostración es que la
# sesión desde la que corres esto llegó por él.
# =============================================================================
if [[ "$CONFIRMAR_SSH" == "si" && "$PUERTO_SSH" != "22" ]]; then
    titulo "Confirmación — cerrando el puerto 22"
    # La sesión ya se verificó al principio, en `verificar_sesion_ssh`, antes de
    # tocar el cortafuegos. Aquí solo queda dejar la marca.

    if [[ "$DRY_RUN" == "si" ]]; then
        detalle "[dry-run] dejaría la marca $MARCA_SSH y volvería a aplicar sin el 22"
    elif [[ -f "$MARCA_SSH" ]]; then
        ok "el 22 ya estaba cerrado en una pasada anterior (marca en $MARCA_SSH)"
    else
        printf 'Puerto SSH %s confirmado el %s por %s\n' \
            "$PUERTO_SSH" "$(date -Is)" "${SUDO_USER:-root}" >"$MARCA_SSH"
        chmod 0644 "$MARCA_SSH"
        ok "marca escrita: a partir de ahora el script no vuelve a abrir el 22"
        ok "el 22 ya quedó cerrado en esta misma pasada: fuera de ufw, fuera de sshd y fuera del jail de fail2ban. No hace falta otra ejecución."
    fi
elif [[ "$PUERTO_SSH" != "22" && "$YA_CONFIRMADO" != "si" ]]; then
    titulo "Pendiente: confirmar el puerto SSH"
    printf '   %sEl puerto 22 sigue abierto a propósito. Haz esto AHORA, sin cerrar\n' "$C_AV"
    printf '   esta sesión:%s\n\n' "$C_FIN"
    printf '     1. Desde tu equipo, en OTRA terminal:\n'
    printf '        ssh -p %s %s@<IP-del-servidor>\n\n' "$PUERTO_SSH" "$USUARIO"
    printf '     2. Si entra, desde ESA sesión nueva:\n'
    printf '        sudo %s --confirmar-ssh\n\n' "$DIR_APP/deploy/scripts/$(basename "$0")"
    printf '        Esa única pasada comprueba que llegaste por el %s y, recién\n' "$PUERTO_SSH"
    printf '        entonces, retira el 22 de ufw, de sshd y del jail de\n'
    printf '        fail2ban. No hace falta ninguna ejecución adicional.\n\n'
    printf '   %sSi no entra, no cierres esta sesión: revisa el problema desde aquí.%s\n' "$C_DIM" "$C_FIN"
fi

# =============================================================================
# RESUMEN
# =============================================================================
titulo "Resumen de lo aplicado"

cat <<FIN
   Usuario de operación .... $USUARIO (sudo; sin contraseña SSH)
   Puerto SSH .............. $PUERTO_SSH  $( [[ "$CERRAR_22" == "si" ]] && echo "(22 cerrado)" || echo "(22 abierto hasta confirmar)" )
   Acceso SSH .............. solo llave · sin root · AllowUsers: $ALLOW_USERS
   Activación de SSH ....... $( [[ "$SSH_POR_SOCKET" == "si" ]] && echo "por socket (puerto en ssh.socket.d)" || echo "servicio clásico (Port en sshd_config.d)" )
   Cortafuegos ............. ufw: 80, 443 y $PUERTO_SSH; el resto denegado
   fail2ban ................ jail sshd, backend systemd, vetos vía ufw
   Docker .................. repositorio oficial + compose plugin
   Tope de logs ............ demonio: $DOCKER_LOG_MAX × $DOCKER_LOG_FICHEROS · servicios de Factuchat: 20m × 5 (el del compose manda)
   Actualizaciones ......... unattended-upgrades solo de seguridad, sin reinicio automático
   Registros ............... journald $RETENCION_MESES meses · logrotate $RETENCION_MESES meses en $DIR_LOGS
FIN

if [[ ${#AVISOS[@]} -gt 0 ]]; then
    titulo "Avisos de esta ejecución (${#AVISOS[@]})"
    for a in "${AVISOS[@]}"; do printf '   %s!%s %s\n' "$C_AV" "$C_FIN" "$a"; done
fi

titulo "Lo que queda por hacer A MANO"

cat <<FIN
   Este script hace los pasos 1, 2, 8 y 9 de PLAN.md. Lo de abajo NO está hecho
   y el servidor todavía no puede recibir tráfico de producción.

   1. DNS — bloqueante, y antes que el TLS
      El dominio definitivo NO está decidido. APP_DOMAIN está vacío en
      backend/.env.example y las maquetas usan tres dominios distintos
      (factuchat.ec, factuchat.com y factuchat.ai). backend/app/core/config.py
      usa factuchat.ec como respaldo de desarrollo y en producción se NIEGA a
      arrancar sin APP_DOMAIN (sin_valores_inseguros_en_produccion).
      Hay que fijarlo antes de pedir el certificado, porque el dominio también
      forma las direcciones del buzón ({ruc}@dominio) y los enlaces de los
      correos. Luego: registro A (y AAAA si hay IPv6) apuntando a este VPS, y
      esperar a que propague.

   2. TLS — paso 3 de PLAN.md, no cubierto aquí
      La configuración de nginx YA está escrita y sin comentar. NO hay que
      escribir ningún bloque más: duplicar el 443 deja a nginx sin arrancar.
      · deploy/nginx/nginx.conf no tiene ningún 'server'; lo que trae es el
        bloque TLS global: solo TLS 1.2 y 1.3, cifrados, stapling y sesiones.
      · deploy/nginx/templates/factuchat.conf.template trae los dos 'server':
        el del 80, con el desafío ACME y la redirección 301 a HTTPS, y el de
        443 completo, con HSTS de dos años ACTIVO. El dominio entra por
        envsubst desde FACTUCHAT_DOMINIO al arrancar el contenedor.
      El cliente ACME también está: el servicio 'certbot' del compose, en el
      perfil 'certbot', que renueva cada 12 horas por webroot.
      Lo que falta de verdad es el certificado. El volumen 'certs' está VACÍO y
      sin /etc/letsencrypt/live/<dominio>/fullchain.pem nginx NO arranca, así
      que la primera emisión va en dos tiempos y con --standalone; los comandos
      exactos están en la cabecera del servicio certbot de
      deploy/docker-compose.prod.yml.
      Faltan entonces: fijar FACTUCHAT_DOMINIO y CERTBOT_EMAIL en el .env,
      emitir el certificado y comprobar que la renovación automática corre. El
      puerto 80 ya está abierto en ufw, que es lo que necesita el desafío
      HTTP-01.

   3. Resto de pasos de despliegue de PLAN.md
      · Paso 2 (lo que falta): fijar las imágenes base por DIGEST y pasarles
        trivy antes de subirlas. deploy/.env.example todavía las trae por
        ETIQUETA (nginx:1.27-alpine, postgres:16, redis:7-alpine), y una
        etiqueta cambia de contenido sin avisar. Del endurecimiento del
        compose ya está hecho: no-new-privileges en todos los servicios menos
        certbot; cap_drop ALL en nginx, api, worker, beat y redis (postgres NO
        lo lleva: su entrypoint necesita CHOWN, SETUID y SETGID para bajar de
        privilegios al arrancar el clúster); read_only con tmpfs en nginx, api,
        worker y beat; y límites de CPU y memoria en todos menos certbot.
      · Paso 4: contraseñas fuertes de PostgreSQL y pg_hba restringido.
        Postgres y Redis ya están sin publicar en el compose; que siga así.
      · Paso 5: subir el .env a $DIR_APP/deploy/.env con permisos 600 y
        propietario root, y documentar la rotación semestral.
      · Paso 6: los scripts deploy/scripts/respaldo.sh y restaurar.sh ya existen,
        pero este script NO les programa la ejecución. Falta crear el temporizador
        (cron o systemd) cada 6 horas, dar de alta el destino externo al VPS y
        hacer la primera prueba de restauración con su evidencia.
      · Paso 7: monitoreo externo y alertas al administrador.
      · Paso 9 (lo que falta): hacer que los logs pasen por $DIR_LOGS, que es
        lo único que rota logrotate. Hoy el servicio nginx del compose monta
        'nginx-logs:/var/log/nginx': es un volumen Docker, así que los logs
        sobreviven al recrear el contenedor y respaldo.sh los copia, pero viven
        en /var/lib/docker/volumes/ y logrotate no los ve nunca. Hay que
        SUSTITUIR ese montaje —no añadir otro, o el compose aborta con
        'Duplicate mount point'— por:
              - $DIR_LOGS/nginx:/var/log/nginx
        y en api y worker, redirigir la salida a $DIR_LOGS/api y
        $DIR_LOGS/worker o mandarla a un recolector; hoy solo tienen el tope de
        tamaño del ancla x-registro del compose (20m × 5 por contenedor).
      · Paso 10: probar el levantamiento en un VPS nuevo desde respaldo.

   4. Bloqueos que no son de servidor pero impiden facturar
      · No hay certificado .p12 real: la emisión de punta a punta contra el
        ambiente PRUEBAS del SRI sigue sin hacerse
        (deploy/scripts/emision-prueba-sri.md).
      · Faltan las credenciales de Meta (WA_APP_SECRET, WA_ACCESS_TOKEN): sin
        ellas el canal de WhatsApp no opera.
      · Falta contratar el proveedor de correo entrante del buzón:
        BUZON_ACTIVO nace apagado y así se queda.
FIN

if [[ -f /var/run/reboot-required ]]; then
    titulo "Reinicio pendiente"
    printf '   %sHay un reinicio pendiente por actualizaciones del sistema.%s\n' "$C_AV" "$C_FIN"
    printf '   No se reinicia solo (a propósito). Hazlo en la ventana de mantenimiento.\n'
    [[ -f /var/run/reboot-required.pkgs ]] && sed 's/^/     · /' /var/run/reboot-required.pkgs
fi

printf '\n'
if [[ "$DRY_RUN" == "si" ]]; then
    printf '%s--dry-run: no se modificó nada. Quita la opción para aplicar.%s\n\n' "$C_AV" "$C_FIN"
else
    printf '%sListo.%s Verificación rápida:\n' "$C_OK" "$C_FIN"
    printf '   sudo ufw status verbose\n'
    printf '   sudo fail2ban-client status sshd\n'
    printf '   sudo ss -ltnp | grep sshd\n'
    printf '   journalctl -u ssh --since today\n\n'
fi
