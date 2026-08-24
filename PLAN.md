PROMPT MAESTRO PARA CLAUDE CODE — FACTUCHAT: DEL DISEÑO A PRODUCCIÓN
=====================================================================

CONTEXTO
--------
Tengo 5 maquetas HTML aprobadas (generadas en Claude Design) que definen el 100% de la interfaz:
1. "Facturas IA.dc.html"  → Landing pública + checkout + términos y tratamiento de datos.
2. "Dashboard.dc.html"    → Panel de clientes (multi-tenant): inicio, comprobantes, clientes, artículos/servicios con inventario, tienda, reportes, tutoriales, mi cuenta.
3. "Superadmin.dc.html"   → Panel interno con 11 secciones (dashboard, clientes, consumo y costos, pagos, comprobantes, WhatsApp, buzón SRI, soporte, marketing, configuración, auditoría).
4. DESCARTADAS: "Tienda.dc.html" y "Tienda Online.dc.html" NO se implementan. La única tienda del sistema es la que vive DENTRO del panel de clientes (Dashboard.dc.html, sección "Tienda en línea" con pestañas Pedidos / Mi tienda / Configuración): una vitrina interna donde el dueño o su equipo seleccionan productos del inventario, cierran la venta y el comprobante se emite al instante. Ignora por completo esos dos archivos.

Las maquetas son la ÚNICA fuente de verdad visual: mismos textos, mismos componentes, mismos estados. No inventes pantallas ni cambies el copy, salvo las correcciones listadas abajo.

CORRECCIONES DE COPY OBLIGATORIAS (aplicar al migrar):
- Reemplazar "Pacalina" por "Factuchat".
- Corregir "wathsapp" → "WhatsApp" y unificar la grafía "WhatsApp" en todo el sitio.
- Corregir "fué" → "fue".
- País Panamá: cambiar de "Disponible / en operación" a "Muy pronto". Solo Ecuador está en operación.
- Unificar dominio y correos: usar el dominio definitivo (confirmar conmigo: factuchat.ai o factuchat.ec) en correos, footer y enlaces.
- NO copiar la carpeta uploads/ del diseño al repositorio. Las imágenes de producción se optimizan y se sirven desde /static con nombres limpios.

STACK OBLIGATORIO
-----------------
- Backend: FastAPI (Python 3.12) + SQLAlchemy 2 + Alembic.
- Base de datos: PostgreSQL 16. Multi-tenant por tenant_id en todas las tablas de negocio + Row Level Security (RLS) activa.
- Colas: Celery + Redis (emisión de comprobantes, envíos WhatsApp, correos, parseo de buzón).
- Frontend: React 18 + Vite + TypeScript. Un solo design system extraído de las maquetas (colores, tipografía, componentes).
- PDF (RIDE): WeasyPrint en el backend.
- Infra: Docker Compose con servicios: api, worker, beat, redis, postgres, nginx. Todo tras nginx.
- Errores: Sentry SDK en api, worker y frontend.

=====================================================================
FASES DE CONSTRUCCIÓN (no avanzar de fase sin checklist verde)
=====================================================================

FASE 1 — FUNDACIONES Y SEGURIDAD BASE
-------------------------------------
1.1 Monorepo: /backend, /frontend, /deploy (compose, nginx, scripts), /docs.
1.2 Modelos y migraciones núcleo: tenants, users (con roles CLIENTE, SUPERADMIN, SOPORTE, LECTURA), planes, suscripciones, establecimientos, secuenciales, clientes_finales, productos, comprobantes (los 6 tipos SRI con estados PENDIENTE→FIRMADO→ENVIADO_SRI→AUTORIZADO/RECHAZADO/DEVUELTO), pagos, recargas, promo_codes, promo_uses, cost_rates (con vigencia), audit_log, notas_internas, whatsapp_msgs, buzon_correos.
1.3 Autenticación: sesiones JWT cortas (30 min) + refresh con rotación, hashing Argon2id, 2FA TOTP obligatorio para SUPERADMIN, rate limiting en login (5 intentos/15 min por IP y por cuenta), bloqueo progresivo.
1.4 RLS en PostgreSQL: política por tenant_id en cada tabla de negocio; el rol de conexión de la app NO puede saltarse RLS; el superadmin consulta vía funciones seguras que registran en audit_log.
1.5 Middleware de auditoría: toda escritura registra quién, qué, tenant, antes/después (JSON), IP, user agent, timestamp.
1.6 CI local: ruff + mypy + pytest + npm audit + pip-audit en pre-commit.
CHECKLIST F1: login con 2FA funciona; un usuario del tenant A no puede leer datos del tenant B ni manipulando IDs; audit_log registra todo; pip-audit y npm audit sin críticas.

FASE 2 — MOTOR DE EMISIÓN SRI (el corazón)
------------------------------------------
2.1 Generación de XML v2.31 para los 6 comprobantes con clave de acceso de 49 dígitos.
2.2 Firma XAdES-BES con el .p12 del cliente. Los .p12 se guardan cifrados con AES-256-GCM, clave maestra fuera de la BD (variable de entorno inyectada, nunca en el repo), y la contraseña del certificado cifrada por separado. Descifrado solo en memoria del worker al firmar.
2.3 Integración con los web services del SRI (RecepcionComprobantesOffline / AutorizacionComprobantesOffline), ambiente PRUEBAS y PRODUCCIÓN por inquilino, reintentos exponenciales, cola de rechazados con motivo legible.
2.4 RIDE en PDF con WeasyPrint + envío por correo al cliente final.
2.5 Todo el flujo corre en Celery, nunca en el request. El endpoint devuelve el id y el frontend consulta estado.
CHECKLIST F2: factura de prueba autorizada en ambiente PRUEBAS del SRI de punta a punta; certificado nunca aparece en logs; rechazo del SRI muestra motivo claro y permite reintento.

FASE 3 — PANEL DE CLIENTES (Dashboard.dc.html)
----------------------------------------------
3.1 Migrar las 8 secciones exactamente como la maqueta: Inicio (ventas, próxima declaración por noveno dígito, ranking, feed "Lo que hice por ti"), Comprobantes, Clientes (con carga masiva Excel y vista previa), Artículos/Servicios (inventario según plan), Tienda (pestañas pedidos/vitrina/config), Reportes (resumen fiscal, PDF/Excel), Tutoriales, Mi cuenta (establecimientos, firma, números autorizados, plan).
3.2 Gating por plan: cada función bloqueada muestra el estado "viene con un plan superior" tal como está diseñado.
3.3 Retenciones recibidas: bandeja con XML/PDF descargables y saldo del periodo.
CHECKLIST F3: un cliente Inicial ve los bloqueos correctos; uno Empresario ve todo; los números del resumen fiscal salen de comprobantes autorizados reales.

FASE 4 — SUPERADMIN (Superadmin.dc.html)
----------------------------------------
4.1 Migrar las 11 secciones con la lógica ya diseñada: clientes con ficha completa y acciones auditadas, impersonación con banner y doble registro, consumo y costos con tarifas por vigencia (alza Meta oct-2026 precargada), pagos con morosos y aviso previo de 48h, comprobantes global con cola en vivo, WhatsApp con presupuesto y alerta, buzón tras feature flag BUZON_ACTIVO, soporte con señales de abandono, marketing con códigos promo (LANZA99: primer mes $0.99, columna Retenido), configuración (planes editables con vigencia, textos de avisos, admins, parámetros SRI), auditoría de solo lectura.
4.2 Wizard "Nuevo cliente" con subida de .p12 igual a la maqueta.
CHECKLIST F4: crear código promo, alta de cliente con promo, verlo en usos con Retenido; impersonar deja doble rastro; cambiar precio con vigencia futura no afecta suscripciones actuales.

FASE 5 — WHATSAPP (API OFICIAL DE META)
---------------------------------------
5.1 Webhook verificado (token + firma X-Hub-Signature-256 validada SIEMPRE).
5.2 Conversación de emisión: intents (facturar, consultar, reenviar, reporte), confirmación previa al SRI, botones y listas como en la demo de la landing.
5.3 Plantillas de avisos (pre-declaración por noveno dígito, cupo agotado, pago vencido) con variables {nombre},{plan},{fecha},{digito},{enlace}.
5.4 Registro de conversaciones para el tablero de consumo (empresa vs usuario) y costo según cost_rates vigente.
CHECKLIST F5: emisión completa por chat en sandbox; webhook rechaza firmas inválidas; consumo aparece en superadmin.

FASE 6 — TIENDA INTERNA + LANDING + CHECKOUT
--------------------------------------------
6.1 Tienda: implementar SOLO la tienda interna del panel (pestañas Pedidos / Mi tienda / Configuración de Dashboard.dc.html). Es una vitrina de venta rápida para el equipo del inquilino: selecciona productos del inventario con sus precios sin IVA, el sistema calcula el impuesto al facturar, cobra por transferencia, WhatsApp o Payphone (si está conectado) y emite el comprobante al instante; si el comprador no da datos, sale a consumidor final hasta $200. Los pedidos caen en la pestaña Pedidos con sus estados (por revisar, transferencias por confirmar, por entregar, pagados). No existe tienda pública con carrito.
6.2 Landing con las correcciones de copy, formulario de contacto que abre WhatsApp, checkout con 3 vías (información/agenda, transferencia con subida de comprobante, Payphone) y aceptación explícita de términos y datos (guardar timestamp + versión del documento aceptado, exigencia LOPDP).
6.3 Consumidor final hasta $200 sin datos, tal como está diseñado.
CHECKLIST F6: pedido por transferencia crea registro y notifica; aceptación de términos queda auditada con versión.

FASE 7 — BUZÓN SRI (feature flag)
---------------------------------
7.1 Correo cedula@factuchat.[dominio] por inquilino, parser de XML firmados, deduplicación, cifrado en reposo, aislamiento por tenant, alerta de 30 días sin recepción.
7.2 Los XML del buzón no consumen análisis IA (regla de negocio ya publicada en la landing).
CHECKLIST F7: correo de prueba parseado y sumado al saldo de retenciones del tenant correcto y solo de ese tenant.

=====================================================================
SEGURIDAD — OWASP TOP 10 (edición 2025) MAPEADO A ESTE PROYECTO
=====================================================================
Implementar y dejar evidencia (tests o configuración) de cada control:

A01 Broken Access Control (incluye SSRF):
- RLS por tenant + verificación de pertenencia en cada endpoint (doble barrera).
- Deny by default: toda ruta exige rol explícito.
- IDs públicos no secuenciales (UUID) para evitar enumeración.
- Tests automáticos de acceso cruzado entre tenants y entre roles.
- SSRF: el backend solo hace requests salientes a la lista blanca (SRI, Meta, Payphone, SMTP); ninguna URL provista por el usuario se visita.

A02 Security Misconfiguration:
- Un solo archivo .env por entorno, nunca en el repo; plantilla .env.example sin secretos.
- DEBUG apagado en producción, errores genéricos al usuario, detalle solo en Sentry.
- Cabeceras en nginx: HSTS, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, CSP estricta (sin inline scripts; migrar los scripts de las maquetas a archivos).
- CORS restringido a los dominios propios.

A03 Software Supply Chain Failures:
- Dependencias fijadas (lockfiles), pip-audit y npm audit en CI, Dependabot o equivalente.
- Imágenes Docker oficiales con digest fijado, escaneo con trivy antes de desplegar.
- Sin CDNs externos en el panel: todo asset servido desde el propio dominio.

A04 Cryptographic Failures:
- TLS 1.2+ únicamente, certificados Let's Encrypt con renovación automática.
- Argon2id para contraseñas; AES-256-GCM para .p12 y claves de certificado; secretos rotables.
- Nada sensible en logs: filtro que enmascara contraseñas, tokens, claves de certificado y números de tarjeta.

A05 Injection:
- SQLAlchemy con parámetros ligados SIEMPRE; prohibido SQL por concatenación (regla de lint).
- Validación de entrada con Pydantic en todos los endpoints (tipos, longitudes, formatos RUC/cédula).
- Escape por defecto de React; sanitizar cualquier HTML dinámico; nada de dangerouslySetInnerHTML.

A06 Insecure Design:
- Confirmación explícita antes de enviar cualquier comprobante al SRI (ya diseñada).
- Límites de negocio en servidor: cupos de plan, montos consumidor final ($200), cupos de promo.
- Flujos de anulación solo por los mecanismos normativos.

A07 Authentication Failures:
- Ya cubierto en F1: Argon2id, 2FA para superadmin, rate limiting, bloqueo progresivo, sesiones cortas con rotación de refresh, cierre de sesión en cambio de contraseña.
- Sin credenciales por defecto; el seed de producción exige crear el primer admin por CLI con contraseña fuerte.

A08 Software or Data Integrity Failures:
- Verificación de firma del webhook de Meta y de las respuestas del SRI contra su XSD.
- Los XML autorizados son inmutables: hash SHA-256 almacenado; cualquier reintento genera documento nuevo, nunca edita el autorizado.
- Despliegues solo desde el repositorio (git pull + build), nunca archivos sueltos por FTP.

A09 Security Logging & Alerting Failures:
- audit_log inmutable (sin UPDATE/DELETE por permisos de BD).
- Alertas activas: logins fallidos repetidos, uso de impersonación, cambios de precios, rechazos SRI en ráfaga, proyección WhatsApp sobre presupuesto.
- Logs estructurados JSON con retención 12 meses, sin datos personales innecesarios.

A10 Mishandling of Exceptional Conditions:
- Toda excepción manejada: el usuario ve mensaje claro, el sistema no queda en estado intermedio (transacciones atómicas en emisión y pagos).
- Timeouts y reintentos con backoff en SRI/Meta; circuit breaker si el SRI no responde, con cola en pausa y aviso en el semáforo de salud.
- Fallos de Celery reencolan sin duplicar comprobantes (idempotencia por clave de acceso).

=====================================================================
DESPLIEGUE EN MI VPS — ALINEADO A CONTROLES ISO 27001
=====================================================================
Nota: ISO 27001 e ISO 9001 certifican a la ORGANIZACIÓN (gestión de seguridad y de calidad), no al código. Lo que haremos es implementar los controles técnicos del Anexo A de ISO 27001 y dejar la documentación que un auditor pediría, para que Factuchat pueda certificarse cuando toque.

Pasos de despliegue (generar script + guía en /deploy):
1. Servidor Ubuntu 24 limpio: usuario no-root con sudo, SSH solo con llave, puerto SSH no estándar, fail2ban, ufw con solo 80/443/SSH.
2. Docker + Compose; contenedores sin privilegios, usuario no-root dentro de cada imagen, read_only donde sea posible, límites de memoria/CPU.
3. nginx como único expuesto: TLS Let's Encrypt, HTTP→HTTPS, cabeceras de A02, rate limiting global y por ruta de login.
4. PostgreSQL y Redis SOLO en la red interna de Docker, jamás publicados; contraseñas fuertes generadas, pg_hba restringido.
5. Secretos: archivo .env con permisos 600 propiedad root, montado solo en los servicios que lo necesitan; rotación semestral documentada.
6. Respaldos (control A.8.13): pg_dump cifrado (age o gpg) cada 6 horas a almacenamiento externo al VPS + copia diaria retenida 30 días + prueba de restauración mensual documentada.
7. Monitoreo: healthchecks de compose, uptime externo, Sentry, alertas al WhatsApp/correo del administrador.
8. Actualizaciones: unattended-upgrades para el SO; ventana semanal para imágenes Docker tras pasar trivy.
9. Registro y trazabilidad (A.8.15): logs de nginx, api y worker centralizados en el VPS con logrotate 12 meses.
10. Continuidad (A.5.30): documento de recuperación: cómo levantar todo en un VPS nuevo desde respaldo en menos de 4 horas; probarlo una vez y guardar evidencia.

DOCUMENTACIÓN A GENERAR EN /docs (evidencia para ISO 27001/9001 y LOPDP):
- Política de seguridad de la información (1 página, práctica).
- Inventario de activos y flujos de datos (dónde viven los .p12, los XML, los datos personales).
- Matriz de roles y accesos.
- Procedimiento de respaldo y restauración con registro de pruebas.
- Procedimiento de gestión de incidentes (qué se hace ante una brecha, incluyendo notificación LOPDP).
- Registro de tratamiento de datos personales (LOPDP) y texto de términos versionado.
- Para ISO 9001: procedimiento de soporte (tiempos de respuesta por plan) y de gestión de cambios (cómo se prueba y aprueba cada versión antes de producción).

ENTREGABLES FINALES
-------------------
1. Código por fases con sus checklists en verde y tests.
2. /deploy con compose de producción, nginx.conf, script de instalación del servidor y script de respaldo.
3. /docs con los 7 documentos listados.
4. Un archivo SECURITY.md que mapee cada punto OWASP 2025 al lugar del código o configuración que lo implementa.

Empieza por la FASE 1 y no avances sin mostrarme el checklist cumplido.
