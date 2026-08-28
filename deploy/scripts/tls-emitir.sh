#!/usr/bin/env bash
#
# tls-emitir.sh — Primera emisión del certificado TLS (paso 3 del despliegue)
# =============================================================================
#
# EL PROBLEMA QUE RESUELVE
# ------------------------
# Hay un círculo: nginx no arranca si el bloque 443 apunta a un certificado que
# no existe, y Let's Encrypt no emite el certificado si nadie responde al
# desafío en el puerto 80. Los dos se esperan mutuamente y el despliegue se
# queda parado.
#
# Se rompe con un certificado AUTOFIRMADO temporal: sirve para que nginx
# arranque, nginx responde al desafío, certbot emite el de verdad y lo
# reemplaza. El autofirmado nunca llega a ver un navegador.
#
# Es idempotente: si ya hay un certificado real de Let's Encrypt, no lo toca.
#
# USO
# ---
#   sudo ./tls-emitir.sh                 # emite contra Let's Encrypt
#   sudo ./tls-emitir.sh --prueba        # usa el entorno de PRUEBAS de LE
#   sudo ./tls-emitir.sh --ayuda
#
# --prueba usa el «staging» de Let's Encrypt, que no cuenta contra el límite de
# 5 emisiones por dominio y semana. Conviene la primera vez: si el DNS o el
# cortafuegos están mal, gastar los intentos reales deja el dominio bloqueado
# una semana entera.
#
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-$(cd "${AQUI}/.." && pwd)}"
COMPOSE_ARCHIVO="${COMPOSE_ARCHIVO:-docker-compose.prod.yml}"
ENV_ARCHIVO="${ENV_ARCHIVO:-${DEPLOY_DIR}/.env}"

PRUEBA=no
for arg in "$@"; do
  case "$arg" in
    --prueba) PRUEBA=si ;;
    --ayuda|-h) sed -n '2,32p' "$0"; exit 0 ;;
    *) printf 'Opción desconocida: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

ROJO=""; VERDE=""; AMARILLO=""; RESET=""
if [[ -t 1 ]]; then
  ROJO=$'\033[31m'; VERDE=$'\033[32m'; AMARILLO=$'\033[33m'; RESET=$'\033[0m'
fi
titulo() { printf '\n%s== %s ==%s\n' "$AMARILLO" "$*" "$RESET"; }
ok()     { printf '  %s[ok]%s   %s\n' "$VERDE" "$RESET" "$*"; }
fallar() { printf '\n%sERROR: %s%s\n' "$ROJO" "$*" "$RESET" >&2; exit 1; }

dc() { docker compose -f "${DEPLOY_DIR}/${COMPOSE_ARCHIVO}" --project-directory "$DEPLOY_DIR" "$@"; }

# El dominio y el correo salen del .env, NO del entorno del administrador: si se
# leyeran del shell se expandirían vacíos y certbot abortaría sin decir por qué.
valor_env() {
  local clave="$1" linea valor
  [[ -f "$ENV_ARCHIVO" ]] || fallar "no encuentro $ENV_ARCHIVO"
  linea="$(grep -E "^[[:space:]]*${clave}=" "$ENV_ARCHIVO" | tail -n1 || true)"
  valor="${linea#*=}"; valor="${valor%$'\r'}"
  valor="${valor%\"}"; valor="${valor#\"}"
  printf '%s' "$valor"
}

DOMINIO="$(valor_env FACTUCHAT_DOMINIO)"
CORREO="$(valor_env CERTBOT_EMAIL)"
[[ -n "$DOMINIO" ]] || fallar "FACTUCHAT_DOMINIO está vacío en $ENV_ARCHIVO"
[[ -n "$CORREO"  ]] || fallar "CERTBOT_EMAIL está vacío en $ENV_ARCHIVO. Es el correo al que Let's Encrypt avisa antes de que caduque un certificado; sin él nadie se entera."

command -v docker >/dev/null 2>&1 || fallar "falta docker"

titulo "Comprobaciones previas"

# El DNS tiene que apuntar aquí ANTES de pedir nada: es el motivo más común de
# emisión fallida, y cada intento fallido consume cuota.
IP_PUBLICA="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)"
IP_DOMINIO="$(getent ahostsv4 "$DOMINIO" 2>/dev/null | awk '{print $1; exit}' || true)"
if [[ -n "$IP_PUBLICA" && -n "$IP_DOMINIO" ]]; then
  if [[ "$IP_PUBLICA" == "$IP_DOMINIO" ]]; then
    ok "$DOMINIO resuelve a $IP_DOMINIO, que es la IP de este servidor"
  else
    fallar "$DOMINIO resuelve a $IP_DOMINIO pero este servidor es $IP_PUBLICA. Corrige el DNS y espera a que propague; si emites ahora, fallará y gastarás uno de los 5 intentos semanales."
  fi
else
  printf '  %s[aviso]%s no pude comprobar el DNS. Confirma tú que %s apunta a este servidor.\n' \
    "$AMARILLO" "$RESET" "$DOMINIO"
fi

RUTA_LE="/etc/letsencrypt/live/${DOMINIO}"

titulo "1. Certificado temporal para que nginx pueda arrancar"

YA_REAL="$(docker run --rm -v factuchat_certs:/etc/letsencrypt alpine:3 \
  sh -c "[ -f ${RUTA_LE}/fullchain.pem ] && ! grep -q 'FACTUCHAT-TEMPORAL' ${RUTA_LE}/README 2>/dev/null && echo si || echo no" \
  2>/dev/null || echo no)"

if [[ "$YA_REAL" == "si" ]]; then
  ok "ya hay un certificado en $RUTA_LE; no se toca"
else
  docker run --rm -v factuchat_certs:/etc/letsencrypt alpine:3 sh -c "
    apk add --no-cache openssl >/dev/null 2>&1
    mkdir -p '${RUTA_LE}'
    openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
      -keyout '${RUTA_LE}/privkey.pem' -out '${RUTA_LE}/fullchain.pem' \
      -subj '/CN=${DOMINIO}' >/dev/null 2>&1
    cp '${RUTA_LE}/fullchain.pem' '${RUTA_LE}/chain.pem'
    echo FACTUCHAT-TEMPORAL > '${RUTA_LE}/README'
  " || fallar "no se pudo crear el certificado temporal"
  ok "certificado autofirmado temporal creado (dura 1 día y se reemplaza en un momento)"
fi

titulo "2. Levantando nginx para que responda al desafío"
dc up -d nginx || fallar "nginx no arrancó. Revisa: docker compose logs nginx"
sleep 3
dc exec -T nginx nginx -t >/dev/null 2>&1 || fallar "la configuración de nginx no valida"
ok "nginx en pie"

titulo "3. Pidiendo el certificado a Let's Encrypt"
ARGS_PRUEBA=()
[[ "$PRUEBA" == "si" ]] && ARGS_PRUEBA=(--staging) && \
  printf '  %s[aviso]%s modo PRUEBAS: el certificado NO será válido para navegadores.\n' "$AMARILLO" "$RESET"

# --force-renewal porque lo que hay es el autofirmado: sin él, certbot ve un
# fichero en su sitio y decide que no hace falta renovar nada.
dc run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/acme \
  -d "$DOMINIO" \
  --email "$CORREO" \
  --agree-tos --no-eff-email --non-interactive \
  --force-renewal \
  "${ARGS_PRUEBA[@]}" \
  || fallar "certbot no pudo emitir el certificado. Mira arriba el motivo; lo más común es que el puerto 80 no llegue desde fuera (cortafuegos del proveedor) o que el DNS no haya propagado."

ok "certificado emitido para $DOMINIO"

titulo "4. Recargando nginx con el certificado real"
dc exec -T nginx nginx -s reload || fallar "no se pudo recargar nginx"
ok "nginx sirviendo el certificado nuevo"

titulo "5. Levantando el resto y la renovación automática"
dc up -d
ok "todo arriba, incluido el servicio certbot que renueva cada 12 horas"

cat <<FIN

   Comprueba desde tu equipo:
     curl -I https://${DOMINIO}
     # debe responder 200 y traer la cabecera Strict-Transport-Security

   Renovación: el servicio 'certbot' la intenta cada 12 h y nginx se recarga
   solo cada 6 h para tomar el certificado nuevo. No hay que hacer nada más.

   Si usaste --prueba, repite SIN esa opción para emitir el certificado real.

FIN
