#!/bin/bash
# Crea los roles de base de datos al inicializar el cluster (solo primera vez):
#  - factuchat_app:      rol de la aplicación. LOGIN, sin BYPASSRLS → siempre sujeto a RLS.
#  - factuchat_security: dueño de las funciones SECURITY DEFINER de auth/superadmin.
#    NOLOGIN + BYPASSRLS: solo actúa a través de esas funciones auditadas.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE factuchat_app LOGIN PASSWORD '${APP_DB_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    CREATE ROLE factuchat_security NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
    GRANT USAGE ON SCHEMA public TO factuchat_app;
    GRANT USAGE ON SCHEMA public TO factuchat_security;
EOSQL
