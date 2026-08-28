# SECURITY.md — Mapeo OWASP Top 10 (2025) → implementación

Documento vivo: se actualiza al cerrar cada fase. Estado actual: **Fases 1 a 7**.
✅ implementado y con evidencia (test o configuración) · ⚠️ parcial, con lo que
falta escrito · 🔜 llega en la fase indicada.

## A01 — Broken Access Control (incluye SSRF)

| Control | Implementación | Evidencia |
|---|---|---|
| ✅ RLS por tenant en PostgreSQL (FORCE, sin excepciones para el rol de la app) | `backend/alembic/versions/0002_rls_y_funciones.py` | `tests/test_rls.py::TestAislamientoPostgres` |
| ✅ Doble barrera: rol explícito en cada endpoint + RLS | `backend/app/api/deps.py` (`require_roles`, deny by default) | `tests/test_rls.py::test_sin_rol_no_hay_acceso` |
| ✅ IDs públicos UUID (sin enumeración) | `backend/app/db/base.py` (`UUIDPk`) | modelo de datos completo |
| ✅ Tests de acceso cruzado entre tenants y roles | — | `tests/test_rls.py` (API y SQL directo) |
| ✅ Superadmin solo vía funciones seguras auditadas | `sa_*` en migraciones 0002 y 0005 (verifican el rol REAL en BD, no el del token) | `tests/test_admin.py`, `tests/test_superadmin.py` |
| ✅ Matriz de roles internos aplicada en servidor: LECTURA mira, SOPORTE actúa sobre inquilinos, solo SUPERADMIN configura | `backend/app/api/routes/superadmin.py`, `sa_verificar_rol()` | `tests/test_superadmin.py::TestRolesYAuditoria` |
| ✅ Ni el personal interno puede leer `tenants` directamente: pasa por funciones seguras | migración 0005 (`sa_tenant_basico`, `sa_crear_tenant`, `sa_promo_usos`) | verificado al construir la fase 4 |
| ✅ SSRF: lista blanca de destinos salientes | `backend/app/sri/client.py` (`HOSTS_PERMITIDOS_SRI`), `backend/app/whatsapp/cliente.py` (`HOSTS_PERMITIDOS_META`: solo graph.facebook.com), SMTP por config; ninguna URL de usuario se visita | Payphone aún no está integrado: la vía de tarjeta registra el pedido, no redirige |
| ✅ La landing pública no lee ninguna tabla: escribe por política de INSERT y completa su pedido por función acotada | `backend/alembic/versions/0007_tienda_y_terminos.py` (`publico_adjuntar_comprobante`, SECURITY DEFINER de `factuchat_security`), políticas de `solicitudes_contacto` y `aceptaciones_terminos` | `tests/test_tienda.py::TestLandingPublica` (`test_el_comprobante_no_se_puede_reemplazar`, `test_comprobante_de_un_pedido_inexistente`) |
| ✅ La tienda interna solo la ve el rol CLIENTE del propio tenant, y solo con plan que la incluya | `backend/app/api/routes/tienda.py` (`SOLO_CLIENTE`, `_exigir_tienda`) | `tests/test_tienda.py::TestTiendaGatedPorPlan` |
| ✅ El dueño de un correo entrante lo decide la DIRECCIÓN de entrega, nunca el RUC escrito dentro del XML; si el documento retiene a otro, se archiva y no suma nada | `backend/app/buzon/correo.py` (`tenant_por_direccion`), `backend/app/buzon/ingesta.py` (`procesar`) | `tests/test_buzon.py::test_el_dueno_lo_decide_la_direccion_no_el_xml`, `::test_correo_a_direccion_desconocida_se_descarta` |
| ✅ El ingestor no abre `tenants`: resuelve por función segura y acotada que devuelve un solo identificador | migración `0009` (`sys_tenant_por_buzon`, SECURITY DEFINER de `factuchat_security`) | `tests/test_buzon.py::TestChecklistF7` |
| ✅ Corregido un fallo de la fase 5 con la misma raíz: `tenant_por_telefono` consultaba `tenants` desde una sesión de sistema y **nunca** resolvía, así que en producción todo mensaje legítimo se habría rechazado | `backend/app/whatsapp/asistente.py`, migración `0009` (`sys_tenant_por_telefono`) | `tests/test_whatsapp.py::test_un_numero_conocido_si_se_resuelve_desde_el_worker` |
| ✅ Un tercero no puede bloquear la recepción de otro inquilino: el `message_id` es único POR INQUILINO, no global | migración `0009` (`uq_buzon_correos_tenant_message`, reemplaza el UNIQUE global de `0001`) | `tests/test_buzon.py::test_un_message_id_ajeno_no_bloquea_el_correo_de_otro` |
| ✅ `To` y `Cc` NO deciden de quién es un correo: las escribe el remitente, igual que el RUC del XML. Manda el destinatario del sobre (`X-Buzon-Recipient`) o las cabeceras de entrega; con dos destinos válidos o ninguno, el correo se descarta en vez de adjudicarse a ciegas | `backend/app/buzon/correo.py` (`CABECERAS_DE_ENTREGA`, `tenant_por_direccion`) | `tests/test_buzon.py::test_el_to_del_remitente_no_decide_el_dueno`, `::test_sin_cabecera_de_entrega_no_se_adivina_el_dueno`, `::test_un_correo_a_dos_buzones_no_se_adjudica_a_ciegas` |
| ✅ Un correo cuyo candado esté tomado vuelve a la cola en vez de darse por hecho: tratarlo como éxito hacía que Celery lo confirmara y el mensaje se perdiera para siempre si el candado era de un worker muerto | `backend/app/tasks/buzon.py` (`CandadoOcupado`) | `tests/test_buzon.py::TestCandado` (2 casos) |
| ✅ RLS de PostgreSQL sobre `retenciones_recibidas` y `analisis_ia`, verificada con el rol de la app | migración `0009` | `tests/test_buzon.py::test_postgres_impide_ver_la_retencion_de_otro` |

## A02 — Security Misconfiguration

| Control | Implementación | Evidencia |
|---|---|---|
| ✅ `.env` fuera del repo; plantilla sin secretos | `backend/.env.example`, `.gitignore`, hook `no-env-files` | `.pre-commit-config.yaml` |
| ✅ Errores genéricos al usuario, detalle a Sentry | `backend/app/main.py` (exception handler, docs off en prod) | — |
| ✅ Validación dura de config en producción (sin defaults dev) | `backend/app/core/config.py` (`sin_valores_inseguros_en_produccion`) | — |
| ✅ Cabeceras nginx: X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, CSP sin inline | `deploy/nginx/nginx.conf` | HSTS se activa con TLS (fase despliegue) |
| ✅ CORS restringido a dominios propios | `backend/app/main.py` + `CORS_ORIGINS` | — |

## A03 — Software Supply Chain Failures

| Control | Implementación | Evidencia |
|---|---|---|
| ✅ Dependencias fijadas | `backend/requirements*.txt`, `frontend/package-lock.json` | — |
| ✅ pip-audit y npm audit en CI local | `.pre-commit-config.yaml`, `deploy/scripts/check.*` | ambas auditorías en verde al cierre de F1 |
| ✅ Sin CDNs externos | assets propios (`/static`), `deploy/nginx/nginx.conf` | CSP `default-src 'self'` |
| 🔜 Digests de imágenes Docker + trivy | fase de despliegue | — |

## A04 — Cryptographic Failures

| Control | Implementación | Evidencia |
|---|---|---|
| ✅ Argon2id (m=64MiB, t=3, p=4) para contraseñas | `backend/app/core/security.py` | tests de login |
| ✅ AES-256-GCM para secretos TOTP, clave maestra por entorno | `backend/app/core/security.py` (`encrypt_totp_secret`) | `tests/test_audit.py::TestEnmascaramiento` |
| ✅ Refresh tokens: solo hash SHA-256 en BD | `backend/app/core/security.py` (`new_refresh_token`) | migración 0002 (`user_sessions.token_hash`) |
| ✅ Secretos enmascarados en la bitácora | `backend/app/core/audit.py` (`SENSITIVE_FIELDS`) | `tests/test_audit.py::TestEnmascaramiento` |
| ✅ Sentry sin variables locales ni cuerpos de petición, con filtro de claves sensibles | `backend/app/core/observabilidad.py` (`include_local_variables=False`, `before_send`) | sin esto el .p12 descifrado y su clave salían del sistema en cualquier excepción de la firma |
| ✅ SMTP con verificación de certificado y hostname | `backend/app/core/mailer.py` (`ssl.create_default_context`) | — |
| ✅ El certificado debe pertenecer al RUC del negocio y estar vigente | `backend/app/services/certificados.py` | `tests/test_certificados.py::test_certificado_de_otro_ruc_rechazado`, `::test_certificado_caducado_rechazado` |
| ✅ AES-256-GCM para .p12 y su contraseña (cifrados por separado, AAD distinto; clave maestra CERT_ENC_KEY solo en el entorno; descifrado solo en memoria del worker) | `backend/app/core/crypto.py`, `backend/app/sri/firma.py`, `backend/app/services/certificados.py` | `tests/test_certificados.py::test_cifrado_en_reposo`; `tests/test_emision.py` verifica que el certificado jamás aparece en logs |
| ✅ El buzón se cifra en reposo con AES-256-GCM y su PROPIA clave (`BUZON_ENC_KEY`, AAD `factuchat/buzon/correo`): reusar `CERT_ENC_KEY` ampliaría a los documentos fiscales de terceros el radio de daño de la firma electrónica y obligaría a rotar las dos a la vez. En producción, encender el módulo sin clave es un error de arranque | `backend/app/buzon/ingesta.py`, `backend/app/core/crypto.py`, `config.py` (`sin_valores_inseguros_en_produccion`) | `tests/test_buzon.py::test_el_correo_se_guarda_cifrado` |
| ✅ El contenido del correo NO vive en ninguna columna: el listener de auditoría vuelca cada columna a `audit_log`, que es inmutable y la lee el personal interno, así que una columna con el XML anularía el cifrado en reposo. Se descifra bajo demanda, y `motivo_error` (que cita trozos del XML ajeno) y `asunto` van enmascarados en la bitácora | `backend/app/core/audit.py` (`SENSITIVE_FIELDS`), `backend/app/api/routes/buzon.py` (`xml_crudo`) | `tests/test_buzon.py::test_el_contenido_del_correo_no_llega_a_la_bitacora` |
| 🔜 TLS 1.2+ con Let's Encrypt | fase de despliegue | — |

## A05 — Injection

| Control | Implementación | Evidencia |
|---|---|---|
| ✅ SQLAlchemy con parámetros ligados siempre; regla de lint de seguridad (bandit `S`) | `backend/pyproject.toml` (ruff select `S`) | ruff en verde |
| ✅ Pydantic en todos los endpoints (tipos, longitudes, formato RUC/cédula) | `backend/app/schemas/` | `clientes.py` valida RUC 13 dígitos/001, cédula 10 |
| ✅ Escape por defecto de React; sin `dangerouslySetInnerHTML` en todo el panel | `frontend/src/` | verificado en la fase 3 |
| ✅ El CSV de carga masiva se lee como TEXTO: un valor que empieza por `=` nunca se evalúa | `backend/app/services/carga_masiva.py` | `tests/test_carga_masiva.py::test_formula_no_se_interpreta` |
| ✅ XXE y bombas de entidades: el XML del buzón lo escribe un desconocido y se lee con `resolve_entities=False`, `no_network=True`, `huge_tree=False`, rechazo explícito de DOCTYPE y tope de 4 MB — también al reabrir el contenido de un CDATA | `backend/app/buzon/parser.py` (`_parser`, `_sin_doctype`, `desenvolver`) | `tests/test_buzon.py::test_xxe_no_lee_ficheros_del_contenedor`, `::test_bomba_de_entidades_no_tumba_el_worker` |
| ✅ ZIP de un tercero: tope de miembros, de tamaño descomprimido y nombres reducidos a su base (zip slip) | `backend/app/buzon/correo.py` (`_xmls_del_zip`) | `tests/test_buzon.py::test_un_zip_con_el_xml_dentro_tambien_entra` |
| ✅ El nombre del fichero en disco sale del UUID de la fila, nunca del asunto, del Message-ID ni del nombre del adjunto (travesía de rutas) | `backend/app/buzon/ingesta.py` (`_ruta_payload`) | revisado en la construcción de la fase 7 |
| ✅ El recorrido del XML nunca es cuadrático y hay tope de líneas: un adjunto que cabía en todos los límites tenía al worker —el mismo que firma las facturas de todos— horas de CPU ocupado | `backend/app/buzon/parser.py` (`_leer_retencion`, `MAX_LINEAS_RETENCION`) | `tests/test_buzon.py::test_un_documento_con_muchas_lineas_no_cuelga_el_worker` |
| ✅ Valores numéricos no finitos rechazados: `NaN` e `Infinity` se construyen sin error en `Decimal` y PostgreSQL los acepta en una columna `numeric`, así que envenenarían todas las sumas de crédito | `backend/app/buzon/parser.py` (`_decimal`) | `tests/test_buzon.py::test_valores_no_finitos_no_se_guardan_como_credito` |
| ✅ Comentarios y processing instructions no revientan el parser: antes lanzaban `ValueError`, la transacción se revertía y el correo desaparecía sin dejar rastro | `backend/app/buzon/parser.py` (`_es_elemento`, `leer` traduce toda excepción a `BuzonParseError`) | `tests/test_buzon.py::test_un_comentario_no_revienta_el_parser` |
| ✅ Cada texto del XML se acota antes de llegar a columnas estrechas: un `<ruc>` de 500 caracteres hacía fallar el INSERT y perdía el registro del correo entero | `backend/app/buzon/parser.py` (`_texto`, `_solo_digitos`, `_periodo`) | `tests/test_buzon.py::test_un_ruc_kilometrico_no_tumba_el_registro_del_correo` |
| ✅ No se sigue ningún enlace que venga dentro de un correo (SSRF) | `backend/app/buzon/parser.py` (docstring y `no_network=True`) | — |

## A06 — Insecure Design

| Control | Implementación | Evidencia |
|---|---|---|
| ✅ Confirmación explícita antes de enviar al SRI: crear borrador ≠ emitir, también por WhatsApp («Nada se envía al SRI hasta que tú confirmes») | `backend/app/api/routes/comprobantes.py`, `backend/app/whatsapp/asistente.py` | `tests/test_emision.py::test_punta_a_punta`, `tests/test_whatsapp.py::test_flujo_de_punta_a_punta` |
| ✅ El asistente no responde a números no autorizados: contestar confirmaría que el número existe y abriría una conversación que se cobra | `backend/app/tasks/whatsapp.py` | `tests/test_whatsapp.py::test_numero_desconocido_no_recibe_respuesta` |
| ✅ Totales SIEMPRE calculados en servidor + consumidor final hasta $200 | `backend/app/services/emision.py` (`calcular_items`, `LIMITE_CONSUMIDOR_FINAL`) | `tests/test_emision.py::test_consumidor_final_maximo_200` |
| ✅ Cupos de plan decididos en SERVIDOR (comprobantes/mes, clientes, productos, funciones) — el panel solo refleja el estado que la API devuelve | `backend/app/services/planes.py`, `backend/app/api/routes/panel.py` | `tests/test_planes.py::TestGatingEnServidor` (13 casos, incl. que el inventario no se guarda sin el plan aunque el cliente lo mande) |
| ✅ Carga masiva en dos pasos: la vista previa no escribe nada | `backend/app/services/carga_masiva.py` | `tests/test_carga_masiva.py::test_no_guarda_nada` |
| ✅ El precio de un pedido de tienda sale del catálogo, nunca del cliente: aceptarlo dejaría cobrar lo que quisiera quien llame a la API | `backend/app/schemas/tienda.py` (`LineaPedidoIn` sin precio), `backend/app/services/tienda.py` | `tests/test_tienda.py::test_el_precio_no_viene_del_cliente` |
| ✅ El checkout público valida el plan y su precio contra la base; el navegador solo manda el CÓDIGO del plan | `backend/app/api/routes/publico.py` (`plan_vigente_por_codigo`) | `tests/test_tienda.py::TestChecklistTerminos` |
| ✅ La referencia del pedido la genera el servidor (la maqueta usaba `Date.now()`, colisionable) | `backend/app/api/routes/publico.py` | `tests/test_tienda.py::test_la_referencia_la_genera_el_servidor` |
| ✅ La subida pública de comprobantes valida tipo MIME y 5 MB, y el nombre del archivo lo pone el servidor (sin travesía de rutas) | `backend/app/api/routes/publico.py` (`TIPOS_COMPROBANTE`, `MAX_COMPROBANTE_BYTES`) | `tests/test_tienda.py::test_comprobante_solo_acepta_imagen_o_pdf` |
| ✅ Formularios públicos con rate limit por IP (5 / 15 min) | `backend/app/api/routes/publico.py` (`_limitar`) | `tests/test_tienda.py::test_rate_limit_del_formulario_publico` |
| ✅ Cupo de promoción contado en servidor: un código de un solo uso no se aplica dos veces | `backend/app/services/marketing.py` (`validar`, chequeo de `max_usos`) | `tests/test_superadmin.py::test_promo_agotada_se_rechaza` |
| ✅ Renta e IVA se mantienen SEPARADOS de punta a punta: solo la retención de IVA baja el IVA a pagar; sumarlas haría declarar de menos | `backend/app/services/retenciones.py`, `backend/app/services/reportes.py` (`resumen_fiscal`) | `tests/test_buzon.py::test_el_resumen_fiscal_descuenta_solo_el_iva` |
| ✅ El feature flag `BUZON_ACTIVO` se evalúa también donde se SUMA el saldo, no solo en el router: con el módulo apagado no se le cambia el IVA a pagar a nadie | `backend/app/services/retenciones.py` (`activo`, `saldo`, `listar`) | `tests/test_buzon.py::TestFeatureFlag` (4 casos) |
| ✅ Solo SUPERADMIN alterna el flag, y el cambio queda en la bitácora inmutable con antes/después | `backend/app/api/routes/buzon.py` (`alternar_flag`, `SOLO_SUPERADMIN`) | `tests/test_buzon.py::test_solo_el_superadmin_alterna_el_flag`, `::test_alternar_el_flag_queda_auditado` |
| ✅ La misma retención no se cuenta dos veces por más veces que llegue: índices únicos por inquilino sobre la clave de acceso y sobre (número, agente), candado en Redis por mensaje y comprobación previa de existencia | migración `0009`, `backend/app/tasks/buzon.py` (`_candado`), `backend/app/buzon/ingesta.py` (`_ya_registrada`) | `tests/test_buzon.py::TestDeduplicacion` (3 casos) |
| ✅ La exención de cupo de IA del buzón pasa por el MISMO punto donde se descuenta cualquier análisis, con constancia explícita (`consume=False`) — no por omisión | `backend/app/services/planes.py` (`registrar_analisis_ia`, `ORIGEN_IA_EXENTO`) | `tests/test_buzon.py::TestReglaSieteDos` (2 casos) |
| ✅ **Una retención solo cuenta como crédito cuando el SRI lo confirma.** Un XML lo escribe cualquiera, y el sobre `<autorizacion>` también; la dirección del buzón es el RUC del cliente, que es público. Sin esta comprobación, un tercero le bajaría el IVA que declara con un documento inventado | `backend/app/buzon/verificacion.py`, `backend/app/tasks/buzon.py` (`verificar_retencion`), `retenciones.saldo` filtra por `verificada` | `tests/test_buzon.py::test_una_retencion_inventada_no_baja_el_impuesto`, `::test_una_retencion_no_autorizada_no_suma` |
| ✅ Un SRI caído no se interpreta como permiso: se reintenta y la retención sigue sin contar mientras tanto | `backend/app/buzon/verificacion.py` (`VerificacionPendiente`) | `tests/test_buzon.py::test_mientras_el_sri_no_responde_la_retencion_no_cuenta` |
| ✅ La identificación del sujeto retenido es obligatoria y se compara con longitudes fijas: ni ausente ni un prefijo corto saltan el control de propiedad | `backend/app/buzon/ingesta.py` (`_por_que_no_es_suya`) | `tests/test_buzon.py::test_identificacion_del_retenido` (3 casos) |
| ✅ Una retención sin fecha utilizable no se persiste en silencio: quedaría fuera de todos los rangos y su clave bloquearía el reenvío | `backend/app/buzon/ingesta.py`, `parser.fecha_de_periodo` (respaldo por período fiscal) | `tests/test_buzon.py::TestDefensas` |

## A07 — Authentication Failures

| Control | Implementación | Evidencia |
|---|---|---|
| ✅ Sesiones JWT de 30 min + refresh con rotación y detección de reúso (revoca todo) | `backend/app/services/auth.py` | `tests/test_auth.py::TestRefreshRotacion` |
| ✅ 2FA TOTP obligatorio para SUPERADMIN | `backend/app/services/auth.py` (`TotpSetupRequired`) | `tests/test_auth.py::TestDosFactores` |
| ✅ Rate limiting 5 intentos/15 min por IP y por cuenta | `backend/app/core/ratelimit.py` (Redis) + nginx zone `login` | `tests/test_auth.py::TestRateLimit` |
| ✅ Bloqueo progresivo (15 min × 2ⁿ, tope 24 h) | `auth_login_failed()` en migración 0002 | `tests/test_auth.py::TestBloqueoProgresivo` |
| ✅ Mensajes genéricos (sin enumeración de cuentas) | `backend/app/api/routes/auth.py` | `tests/test_auth.py::test_email_inexistente_mismo_mensaje` |
| ✅ Sin credenciales por defecto: primer admin por CLI con contraseña fuerte | `backend/app/cli.py` (`create-superadmin`) | validación de fortaleza en CLI |

## A08 — Software or Data Integrity Failures

| Control | Implementación | Evidencia |
|---|---|---|
| ✅ XML autorizado inmutable: hash SHA-256 + trigger de BD que bloquea cualquier edición; un reintento genera documento nuevo (clave nueva) | migración `0003_motor_emision.py`, `backend/app/tasks/emision.py` | `tests/test_emision.py::test_autorizado_inmutable_en_bd`, `test_devuelta_con_motivo_y_reintento` |
| ✅ Parser defensivo de respuestas del SRI (sin entidades externas, sin red, estados validados) | `backend/app/sri/client.py` | XSD oficiales del SRI pendientes de vendorizar para validación estricta (mejora anotada) |
| ✅ Firma del webhook de Meta verificada SIEMPRE (HMAC-SHA256 del cuerpo crudo, comparación en tiempo constante); sin firma válida el cuerpo ni se parsea ni se encola | `backend/app/whatsapp/firma.py`, `backend/app/api/routes/whatsapp.py` | `tests/test_whatsapp.py::TestWebhookFirma` (6 casos: firma mala, sin firma, cuerpo alterado, token de suscripción) |
| ✅ Sin `WA_APP_SECRET` el webhook rechaza todo: nunca falla abierto | `backend/app/whatsapp/firma.py`, validación en `config.py` | — |
| ✅ El webhook de correo entrante va firmado con HMAC-SHA256 sobre el cuerpo CRUDO, comparado en tiempo constante; sin `BUZON_WEBHOOK_SECRET` rechaza todo con 403 mudo | `backend/app/api/routes/buzon.py` (`webhook_correo`) | `tests/test_buzon.py::TestWebhook` (3 casos) |
| ✅ Despliegue solo desde el repositorio | `deploy/` (compose + build) | — |

## A09 — Security Logging & Alerting Failures

| Control | Implementación | Evidencia |
|---|---|---|
| ✅ audit_log inmutable (sin GRANT ni política de UPDATE/DELETE + trigger) | migración 0002 | `tests/test_rls.py::test_audit_log_es_inmutable` |
| ✅ Toda escritura auditada: quién, qué, tenant, antes/después JSON, IP, UA, timestamp | `backend/app/core/audit.py` (listeners ORM) + funciones `auth_*`/`sa_*` | `tests/test_audit.py` |
| ✅ Logs nginx estructurados JSON | `deploy/nginx/nginx.conf` | retención 12 meses en fase de despliegue |
| ✅ Impersonación con DOBLE rastro: sesión con motivo, inicio y fin en `impersonaciones`, y cada acción auditada con el actor REAL (nunca como si fuera el inquilino) | `backend/app/services/impersonacion.py`, `backend/app/core/audit.py` | `tests/test_superadmin.py::TestChecklistImpersonacion` |
| ✅ Abrir la ficha de un cliente exige motivo y se audita: es un acceso a datos personales (LOPDP) | `sa_ficha_cliente()` en migración 0005 | `tests/test_superadmin.py::test_abrir_ficha_queda_auditado` |
| ✅ Cambios de precio y de estado de inquilino auditados con antes/después y motivo | `sa_cambiar_estado_tenant()`, `backend/app/services/configuracion.py` | `tests/test_superadmin.py` |
| ⚠️ Presupuesto de WhatsApp: la proyección del mes y el umbral de alerta se calculan en servidor y se muestran en el panel interno, pero NADIE es notificado activamente | `backend/app/api/routes/whatsapp.py` (`consumo_whatsapp`), `backend/app/services/consumo.py` | `tests/test_whatsapp.py` (proyección) — el envío de la alerta (correo/WhatsApp al equipo) queda pendiente |
| ⚠️ Rechazos del SRI en ráfaga: quedan en `audit_log` y en el estado de cada comprobante, sin regla de alerta que los agrupe | — | pendiente: es la única casilla de A09 sin implementar |

## A10 — Mishandling of Exceptional Conditions

| Control | Implementación | Evidencia |
|---|---|---|
| ✅ Handler global: mensaje claro al usuario, detalle a Sentry/logs | `backend/app/main.py` | — |
| ✅ Auditoría en la MISMA transacción que la escritura (sin estados intermedios) | `backend/app/core/audit.py` | — |
| ✅ Pipeline idempotente: estado bajo FOR UPDATE, candado por comprobante en Redis y marcas persistentes escritas ANTES de cada efecto externo | `backend/app/tasks/emision.py` | `tests/test_emision.py::TestNoDuplicarFacturas`, `::TestConcurrencia` |
| ✅ Nunca se duplica una factura: tras una caída se pregunta al SRI si ya la tiene antes de reenviar, y «clave ya registrada» no se trata como rechazo | `backend/app/tasks/emision.py` (`_sri_no_lo_tiene`), `backend/app/sri/client.py` (`ya_estaba_registrado`) | `tests/test_emision.py::test_caida_tras_enviar_no_reenvia`, `::test_caida_sin_llegar_al_sri_si_reenvia` |
| ✅ Los fallos de canal (403/404/429/HTML/SOAP truncado) se reintentan, jamás se interpretan como veredicto del SRI | `backend/app/sri/client.py` | `tests/test_emision.py::TestFallosDeCanal` |
| ✅ Solo se acepta la autorización que corresponde a la clave consultada | `backend/app/sri/client.py` | `tests/test_emision.py::test_autorizacion_de_otra_clave_se_rechaza` |
| ✅ Barrido periódico de comprobantes atascados a medio camino | `backend/app/tasks/emision.py` (`barrer_atascados`, cada 10 min por beat) | `tests/test_emision.py::TestBarridoAtascados` |
| ✅ El correo del RIDE se reintenta hasta lograrse (marca propia, independiente del RIDE) | `backend/app/tasks/emision.py` (`correo_enviado_at`) | migración `0004` |
| ✅ Timeouts, reintentos con backoff exponencial y circuit breaker hacia el SRI | `backend/app/sri/client.py` (breaker en Redis), task Celery con `retry_backoff` | cola en pausa mientras el circuito esté abierto; semáforo de salud en fase 4 |
| 🔜 Backoff/breaker hacia Meta | fase 5 | — |
