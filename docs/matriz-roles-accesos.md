# Matriz de roles y accesos — Factuchat

Versión 1.2 · Fases 1–4 · Actualizar al añadir cada módulo nuevo.

## Roles de aplicación

| Rol | Ámbito | Descripción |
|-----|--------|-------------|
| `CLIENTE` | Su tenant | Dueño o empleado del negocio inquilino. Panel de clientes. |
| `SUPERADMIN` | Global (auditado) | Equipo Factuchat. Panel interno completo. **2FA TOTP obligatorio.** |
| `SOPORTE` | Global (auditado) | Equipo Factuchat. Panel interno operativo, sin configuración crítica. |
| `LECTURA` | Global (auditado) | Solo consulta del panel interno. |

## Principios (OWASP A01)

1. **Deny by default**: toda ruta exige rol explícito con `require_roles(...)`; sin rol declarado no hay acceso.
2. **Doble barrera**: verificación de rol en la API **y** Row Level Security por `tenant_id` en PostgreSQL (FORCE).
3. El personal interno **no consulta datos de tenants directamente**: usa funciones `sa_*` (SECURITY DEFINER) que verifican el rol real en BD y registran actor + motivo en `audit_log`.
4. La impersonación exige motivo escrito, banner rojo visible mientras dura, y **doble
   registro**: la sesión en `impersonaciones` (con inicio, fin y motivo) y cada acción
   auditada con el rol REAL del operador, nunca como si la hubiera hecho el inquilino.
   El token dura 30 minutos, no se renueva y solo concede rol CLIENTE sobre ese tenant.

## Qué puede cada rol interno (fase 4)

| Acción | LECTURA | SOPORTE | SUPERADMIN |
|--------|---------|---------|------------|
| Ver dashboard, clientes, comprobantes, auditoría | ✅ | ✅ | ✅ |
| Abrir ficha de cliente (con motivo, auditado) | ✅ | ✅ | ✅ |
| Dar de alta un cliente | ✖ | ✅ | ✅ |
| Suspender o reactivar un inquilino | ✖ | ✅ | ✅ |
| Impersonar (entrar como cliente) | ✖ | ✅ | ✅ |
| Crear códigos promocionales | ✖ | ✖ | ✅ |
| Cambiar precios de planes y tarifas | ✖ | ✖ | ✅ |
| Escribir en auditoría | ✖ | ✖ | ✖ (nadie) |

## Roles de base de datos

| Rol Postgres | Login | BYPASSRLS | Uso |
|--------------|-------|-----------|-----|
| `factuchat` (propietario) | sí | superusuario | Solo migraciones (Alembic) y CLI administrativa. Nunca la API. |
| `factuchat_app` | sí | **no** | Conexión de la API. Sujeto a RLS siempre; no puede apagar `row_security`. |
| `factuchat_security` | no | sí | Dueño de las funciones `auth_*` / `sa_*`. Solo actúa a través de ellas. |

## Acceso por tabla (rol `factuchat_app` vía políticas RLS)

| Tabla | CLIENTE (tenant) | Interno (GUC verificado) | Notas |
|-------|------------------|--------------------------|-------|
| tenants | ve/edita solo el suyo | vía `sa_list_tenants()` auditada | sin INSERT/DELETE por API |
| users, user_sessions | solo su tenant | solo filas internas (tenant NULL) | login vía funciones `auth_*` |
| clientes_finales, productos, comprobantes, establecimientos, secuenciales, suscripciones, pagos, recargas, whatsapp_msgs, buzon_correos, **certificados** | solo su tenant (FOR ALL) | vía funciones `sa_*` (por fase) | aislamiento estricto; certificados además cifrados AES-256-GCM |
| planes | lectura | lectura + escritura | catálogo público interno |
| promo_uses | lectura de los suyos | todo | escritura solo interna |
| promo_codes, cost_rates, notas_internas | sin acceso | todo | solo panel interno |
| audit_log | solo INSERT | INSERT + SELECT | **nadie** actualiza ni borra (trigger + permisos) |
