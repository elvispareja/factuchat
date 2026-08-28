# Documentación de seguridad y calidad (evidencia ISO 27001/9001 y LOPDP)

Los siete documentos que pide PLAN.md están escritos. Todos describen el sistema
tal como está hoy: **construido y probado, pero todavía no desplegado en un
servidor**. Los procedimientos que dependen de que exista ese servidor —la
primera corrida del respaldo, la prueba de restauración, la emisión del
certificado— se señalan como pendientes dentro de cada documento, con su tabla
de registro vacía a la espera de la primera evidencia real.

| # | Documento | Estado |
|---|-----------|--------|
| 1 | [Política de seguridad de la información](politica-seguridad-informacion.md) | Escrito · v1.0 |
| 2 | [Inventario de activos y flujos de datos](inventario-activos-y-flujos.md) | Escrito · v1.0 |
| 3 | [Matriz de roles y accesos](matriz-roles-accesos.md) | Vigente desde fase 1 |
| 4 | [Procedimiento de respaldo y restauración](procedimiento-respaldo-restauracion.md) | Escrito · sin ejecutar todavía |
| 5 | [Procedimiento de gestión de incidentes](procedimiento-gestion-incidentes.md) | Escrito · incluye notificación LOPDP |
| 6 | [Registro de tratamiento de datos personales](registro-tratamiento-datos-personales.md) | Escrito · términos versión 2026.08 |
| 7 | [Procedimiento de soporte y gestión de cambios](procedimiento-soporte-y-gestion-de-cambios.md) | Escrito · tiempos de respuesta por aprobar |

Además, fuera de la lista de siete pero exigido por el paso 10 del despliegue
(control A.5.30):

| — | [Plan de continuidad y recuperación](plan-de-continuidad.md) | Escrito · prueba anual pendiente |

El mapeo técnico OWASP 2025 vive en [SECURITY.md](../SECURITY.md), en la raíz.

## Qué falta para que esta documentación sea evidencia completa

Un auditor no pide documentos: pide constancia de que los procedimientos se
ejecutan. Lo que hoy no se puede enseñar:

- **Ninguna corrida real del respaldo**, porque no hay servidor. Las tablas de
  registro de los documentos 4 y del plan de continuidad están vacías a
  propósito: se llenan con fechas reales, no antes.
- **Los tiempos de respuesta del documento 7 son una propuesta**, no un
  compromiso publicado. Los tiene que aprobar el dueño del producto.
- **El contrato de encargo de tratamiento** con cada inquilino (Factuchat trata
  datos de los clientes finales por cuenta del inquilino) no existe todavía.
  Es un vacío legal, no solo documental; lo señala el documento 6.
- **El nombre del responsable de seguridad** del documento 1 se tomó del titular
  de las cuentas de cobro, que es la única fuente que hay en el repositorio.
  Conviene una designación formal, con suplente.

## Scripts de despliegue

Están escritos y validados con `shellcheck`, pero **no se han ejecutado en
ninguna máquina**:

- [`instalar-servidor.sh`](../deploy/scripts/instalar-servidor.sh) — endurecimiento
  del VPS: usuario no-root, SSH solo con llave en puerto no estándar, fail2ban,
  ufw, Docker, actualizaciones automáticas y logrotate. Se corre en dos tiempos
  para que sea imposible quedarse fuera del propio servidor.
- [`respaldo.sh`](../deploy/scripts/respaldo.sh) — volcado de la base y de los
  volúmenes, cifrado con `age`, con manifiesto y poda por retención.
- [`restaurar.sh`](../deploy/scripts/restaurar.sh) — restauración guiada, que
  además **verifica que la RLS sigue activa**: una restauración puede terminar
  sin errores y dejar el aislamiento entre inquilinos roto.
- [`tls-emitir.sh`](../deploy/scripts/tls-emitir.sh) — primera emisión del
  certificado de Let's Encrypt. Rompe el círculo de que nginx no arranca sin
  certificado y el certificado no se emite sin nginx, y comprueba el DNS antes
  de gastar uno de los cinco intentos semanales que da Let's Encrypt.

## Runbooks de operación

- [emision-prueba-sri.md](../deploy/scripts/emision-prueba-sri.md) — prueba de
  emisión de punta a punta contra el ambiente PRUEBAS del SRI.
- [buzon-sri-puesta-en-marcha.md](../deploy/scripts/buzon-sri-puesta-en-marcha.md)
  — cómo encender el buzón: dominio, claves, proveedor de correo y DNS.

## Referencias de construcción

Especificaciones extraídas literalmente de las maquetas de `/diseno`. Sirven
para cambiar una pantalla sin volver a leer miles de líneas de HTML.

- [spec-dashboard.json](spec-dashboard.json) — panel del cliente: 861 textos,
  158 componentes, 180 estados y los 14 puntos de bloqueo por plan.
- [spec-superadmin.json](spec-superadmin.json) — panel interno: 585 textos, 124
  componentes, 149 estados y 93 acciones con su efecto y si deben auditarse.
- [spec-whatsapp.json](spec-whatsapp.json) — conversación de WhatsApp: 601
  textos, 183 pasos de flujo y las reglas de la confirmación previa al SRI.
- [spec-landing.json](spec-landing.json) — landing pública y checkout, con las
  correcciones de copy obligatorias y los dominios que hay que unificar.
- [spec-buzon.json](spec-buzon.json) — buzón SRI del panel interno y bandeja de
  retenciones del cliente.
