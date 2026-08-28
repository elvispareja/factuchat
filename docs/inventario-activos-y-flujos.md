# Inventario de activos y flujos de datos — Factuchat

Versión 1.0 · Fases 1–7 · Actualizar cada vez que aparezca un activo nuevo, cambie
dónde se guarda algo o se sume un destino externo.

Este documento describe **lo que hace el código de este repositorio**, no una
instalación en marcha: el despliegue en el VPS todavía no se ha hecho, así que
todo lo que aquí se dice sobre volúmenes, respaldos y TLS describe la
configuración escrita en `deploy/`, no un servidor vivo. Lo que aún no existe
está marcado como pendiente, con el motivo.

Documento hermano: [matriz de roles y accesos](matriz-roles-accesos.md) (quién
puede hacer qué). El mapeo control-por-control de OWASP está en
[SECURITY.md](../SECURITY.md).

---

## 1. Dónde vive cada cosa

Cuatro lugares, y nada más. Todo lo que este sistema guarda cae en uno de ellos.

| Lugar | Qué guarda | Cómo está protegido | Definido en |
|---|---|---|---|
| PostgreSQL 16 | Todas las tablas: inquilinos, usuarios, clientes finales, comprobantes, certificados, buzón, bitácora | RLS `FORCE` por `tenant_id`, tres roles de Postgres, funciones `SECURITY DEFINER` para lo que cruza inquilinos. Solo red interna de Docker: el puerto nunca se publica | `deploy/docker-compose.prod.yml`, `deploy/postgres/init/01-roles.sh`, `alembic/versions/0002_rls_y_funciones.py` |
| Volumen `comprobantes` | XML firmados, RIDE en PDF, correos del buzón cifrados, XML de retenciones cifrados, comprobantes de pago del checkout | Montado en `/var/factuchat/storage` en **api** y **worker** (compartido a propósito: el worker escribe, la API sirve). Lo del buzón va cifrado; los XML y RIDE, en claro dentro del volumen | `deploy/docker-compose.prod.yml` (servicios `api`, `worker`, volumen `comprobantes`), `STORAGE_DIR` |
| Redis | Cola de Celery, candados de idempotencia, contadores de rate limit, cortacircuitos del SRI, estado de las conversaciones de WhatsApp | Solo red interna, sin puerto publicado y **sin volumen declarado**: al recrear el contenedor su contenido se pierde, que es lo correcto para candados y conversaciones a medias | `deploy/docker-compose.prod.yml`, `app/core/ratelimit.py`, `app/whatsapp/conversacion.py` |
| Archivo `.env` | Todos los secretos: claves maestras de cifrado, `SECRET_KEY`, credenciales de base, token de Meta, contraseña SMTP, secreto del webhook del buzón, DSN de Sentry | Un solo archivo por entorno, fuera del repositorio, montado con `env_file`. La plantilla sin secretos es `backend/.env.example`; el hook `no-env-files` impide que un `.env` entre al repo | `backend/app/core/config.py`, `.pre-commit-config.yaml` |

Rutas exactas dentro del volumen (todas derivadas del `tenant_id` y de un
identificador que genera el servidor, nunca de un nombre que escriba un usuario):

| Ruta | Contenido | Código |
|---|---|---|
| `{STORAGE_DIR}/{tenant_id}/{clave_acceso}.xml` | XML firmado del comprobante | `app/services/emision.py` (`ruta_almacen`) |
| `{STORAGE_DIR}/{tenant_id}/{clave_acceso}.pdf` | RIDE | `app/tasks/emision.py` (`_paso_ride_y_correo`) |
| `{STORAGE_DIR}/buzon/{tenant_id}/{correo_id}.eml.enc` | Correo entrante completo, cifrado | `app/buzon/ingesta.py` (`_ruta_payload`) |
| `{STORAGE_DIR}/buzon/{tenant_id}/{retencion_id}.xml.enc` | XML de la retención recibida, cifrado | `app/buzon/ingesta.py` (`_crear_retencion`) |
| `{STORAGE_DIR}/comprobantes-pago/{solicitud_id}.{ext}` | Foto o PDF de la transferencia del checkout | `app/api/routes/publico.py` (`subir_comprobante`) |
| `{EMAIL_OUTBOX_DIR}/*.eml` | Correos escritos a disco **solo cuando no hay SMTP** (desarrollo y tests) | `app/core/mailer.py` |

---

## 2. Activos de información

Para cada uno: dónde vive, cómo se protege, quién accede y qué pasa si se pierde
o si se filtra. Son dos preguntas distintas y las dos importan.

### 2.1 Certificado de firma electrónica (.p12) y su contraseña

Es el activo más delicado del sistema. Con él se firma a nombre del
contribuyente ante el SRI.

- **Dónde vive.** Tabla `certificados`, columnas `p12_data_enc` y
  `p12_password_enc` (`app/db/models/certificado.py`). Un certificado activo por
  inquilino (`tenant_id` con restricción `unique`). El archivo nunca se escribe
  en disco.
- **Cómo se protege.** AES-256-GCM, formato `base64(nonce(12) + ciphertext+tag)`
  (`app/core/crypto.py`). El archivo y la contraseña se cifran **por separado y
  con AAD distintos** —`factuchat:p12` y `factuchat:p12-password`
  (`app/sri/firma.py`)—, de modo que un blob no puede reutilizarse en el lugar
  del otro. La clave maestra `CERT_ENC_KEY` vive solo en el entorno y es
  obligatoria en producción (`config.py`, `sin_valores_inseguros_en_produccion`).
  El descifrado ocurre únicamente en memoria del worker, en el paso de firma, y
  el material se suelta explícitamente al terminar (`del p12, password` en
  `app/tasks/emision.py`). Ambas columnas están en `SENSITIVE_FIELDS`
  (`app/core/audit.py`), así que en la bitácora aparecen como `***`; y en Sentry
  no salen ni las variables locales de los frames ni ningún valor binario
  (`app/core/observabilidad.py`).
- **Quién accede.** El propio inquilino lo sube (rol `CLIENTE`, RLS del tenant,
  `app/api/routes/certificados.py`) y la API **nunca lo devuelve**: solo entrega
  metadatos (subject, emisor, vigencia). El worker lo descifra al firmar. El
  personal interno ve el subject y la fecha de vencimiento a través de
  `sa_ficha_cliente()`, que exige motivo y deja constancia en `audit_log`.
- **Validaciones al cargarlo** (`app/services/certificados.py`): máximo 100 KB,
  debe abrir con la contraseña dada, debe contener clave privada, debe estar
  vigente y su identificación incrustada debe corresponder al RUC del negocio.
  Firmar con el certificado de otro contribuyente es rechazo seguro del SRI y un
  problema legal, así que se corta antes de guardar.
- **Si se pierde.** El sistema no se queda colgado: sin certificado, o si el blob
  no descifra (clave rotada, dato corrupto), el comprobante pasa a `RECHAZADO`
  con un motivo legible —«No hay certificado de firma cargado», «No se pudo abrir
  el certificado de firma. Vuelva a cargarlo desde Mi cuenta»— en vez de quedarse
  en `PENDIENTE` para siempre. La recuperación es que el inquilino vuelva a
  subirlo: el original lo tiene él y lo emite su entidad certificadora, no
  nosotros.
- **Si se filtra.** Es el peor escenario del sistema, y solo se materializa si
  se filtran **a la vez** la base de datos y `CERT_ENC_KEY`. Por eso la clave no
  está en la base ni en el repositorio, y por eso Sentry se configuró con
  `include_local_variables=False`: sin eso, cualquier excepción durante la firma
  habría sacado el .p12 descifrado y su contraseña fuera del sistema.
- **Pendiente.** No existe todavía un comando de rotación de `CERT_ENC_KEY`
  (`app/cli.py` solo trae `create-superadmin`, `create-tenant` y `seed-planes`).
  Rotar la clave hoy exige recifrar los certificados guardados a mano, tal como
  advierte `backend/.env.example`.

### 2.2 XML firmados y RIDE en PDF

- **Dónde viven.** El archivo, en el volumen `comprobantes`
  (`{tenant_id}/{clave_acceso}.xml` y `.pdf`); la referencia y la huella, en la
  tabla `comprobantes` (`xml_path`, `ride_path`, `sha256_xml`).
- **Cómo se protegen.** El XML autorizado es **inmutable**: hash SHA-256 guardado
  al firmar más un trigger de base de datos que bloquea cualquier edición
  (migración `0003_motor_emision.py`). Un reintento no edita nada: genera
  documento nuevo con clave nueva y limpia las marcas de reanudación
  (`app/services/emision.py`, `reintentar`). El nombre del archivo sale de la
  clave de acceso de 49 dígitos que genera el servidor, así que ningún dato del
  usuario toca el sistema de archivos.
- **Quién accede.** Solo el rol `CLIENTE` del propio inquilino, por
  `GET /comprobantes/{id}/xml` y `/ride`. La barrera real es la fila: la ruta se
  lee del registro que RLS ya filtró por `tenant_id`, nunca de un parámetro de la
  petición (`app/api/routes/comprobantes.py`, `_descargar`). El cliente final
  recibe su copia por correo, adjunta al RIDE.
- **Si se pierde el volumen.** El comprobante sigue existiendo para el SRI y en
  la base (clave, autorización, totales, payload completo), pero **no hay rutina
  de reconstrucción automática**: el barrido periódico solo reencola los que
  quedaron en `FIRMADO` o `ENVIADO_SRI`, no los ya autorizados. Recuperar los
  archivos depende del respaldo del volumen `comprobantes`, que
  `deploy/scripts/respaldo.sh` ya cubre y `deploy/scripts/restaurar.sh` restaura
  verificando SHA-256 antes de tocar nada (procedimiento completo en el
  [documento 4](procedimiento-respaldo-restauracion.md)). Lo que todavía no existe es
  una ejecución real ni una prueba de restauración documentada, porque no hay
  servidor (ver sección 7).
- **Si se filtra.** Queda expuesta la facturación de los inquilinos y los datos de
  sus clientes finales. Es la razón por la que la descarga exige sesión con rol y
  pasa por RLS, y por la que nginx no sirve el volumen directamente.

### 2.3 Correos del buzón SRI y XML de retenciones recibidas

- **Dónde viven.** El contenido **no está en ninguna columna**: `buzon_correos`
  guarda solo las señas (message_id, remitente, asunto, estado, huella del XML,
  clave de acceso) y una ruta; el mensaje MIME completo va cifrado a
  `{STORAGE_DIR}/buzon/{tenant_id}/{correo_id}.eml.enc`, y el XML de cada
  retención a `{retencion_id}.xml.enc`.
- **Por qué no está en una columna.** El listener de auditoría vuelca cada
  columna escrita a `audit_log`, que es inmutable y la lee el personal interno.
  Una columna con el XML habría anulado el cifrado en reposo al replicarlo en
  claro dentro de una tabla que nadie puede borrar. Por lo mismo, `motivo_error`
  —que llega a citar trozos del XML ajeno— y `asunto` están enmascarados en la
  bitácora (`app/core/audit.py`).
- **Cómo se protege.** AES-256-GCM con **su propia clave**, `BUZON_ENC_KEY`, y
  AAD `factuchat/buzon/correo` (`app/buzon/ingesta.py`). No se reutiliza
  `CERT_ENC_KEY` a propósito: ampliaría a los documentos fiscales de terceros el
  radio de daño de la firma electrónica y obligaría a rotar las dos a la vez. En
  producción, encender el módulo sin esa clave es un error de arranque
  (`config.py`).
- **Quién accede.** El inquilino descarga el XML de sus retenciones, descifrado al
  vuelo, si su plan incluye la bandeja y el flag global está encendido
  (`GET /retenciones/{id}/xml`). El personal interno tiene el visor de «XML
  crudo» del panel (`GET /sa/buzon/{id}/crudo`), que descifra bajo demanda. El
  worker descifra al procesar.
- **Si se pierde.** El crédito ya registrado sigue en `retenciones_recibidas` con
  sus montos y su verificación, pero desaparece el respaldo documental que la
  norma obliga a custodiar. Es contenido que **no se puede regenerar**: lo mandó
  un tercero una sola vez.
- **Si se filtra.** Se exponen documentos fiscales de terceros —proveedores y
  agentes de retención— que no son clientes nuestros. De ahí que el nombre del
  archivo salga del UUID de la fila y nunca del asunto, del Message-ID o del
  nombre del adjunto, todos escritos por un desconocido.

### 2.4 Secreto TOTP del segundo factor

- **Dónde vive.** `users.totp_secret_enc`.
- **Cómo se protege.** AES-256-GCM con `TOTP_ENC_KEY`, clave propia y obligatoria
  en producción (`app/core/security.py`). A diferencia del .p12, este cifrado no
  usa AAD, porque hay un único dominio de uso para esa clave. La columna está
  enmascarada en la bitácora y el nombre figura en la lista de claves sensibles
  de Sentry.
- **Quién accede.** Solo las funciones seguras `auth_get_totp()` y
  `auth_set_totp()` de la migración `0002`, propiedad de `factuchat_security`.
- **Si se pierde.** El usuario no puede completar el segundo factor y hay que
  reinscribirlo. Como el 2FA es obligatorio para `SUPERADMIN`, perder la clave
  maestra deja al equipo fuera del panel interno hasta reinscribir los secretos.
- **Si se filtra.** Se cae el segundo factor: quedaría solo la contraseña.

### 2.5 Contraseñas y tokens de sesión

| Dato | Dónde | Protección |
|---|---|---|
| Contraseña de usuario | `users.password_hash` | Argon2id con parámetros OWASP (m=64 MiB, t=3, p=4). Nunca reversible; enmascarada en la bitácora |
| Refresh token | `user_sessions.token_hash` | Solo el SHA-256; el token en claro no toca la base. Rotación en cada uso y revocación de toda la familia si se detecta reúso |
| Access token (JWT) | No se guarda | HS256 firmado con `SECRET_KEY`, 30 minutos de vida |
| Access y refresh en el navegador | `localStorage` (`fc_access`, `fc_refresh`) | `frontend/src/api/cliente.ts`. Mitigado por CSP sin inline y por el escape por defecto de React, pero conviene inventariarlo: son credenciales alcanzables por JavaScript del propio origen |

Si se pierde la base: nadie recupera contraseñas (es lo correcto), y todas las
sesiones vivas mueren. Si se filtra: los hashes Argon2id no son directamente
utilizables, pero los refresh tokens sí lo serían si se guardaran en claro —por
eso solo está el hash.

### 2.6 Mensajes de WhatsApp

- **Dónde viven.** Tabla `whatsapp_msgs`: `wa_phone`, dirección, categoría, tipo,
  `wa_message_id`, `contenido` (JSONB con el texto recortado a 1000 caracteres) y
  el costo imputado. El estado de la conversación a medias vive en Redis con TTL
  de 30 minutos (`app/whatsapp/conversacion.py`).
- **Cómo se protege.** RLS por `tenant_id` más una política para el personal
  interno, que necesita el consumo global (migración `0006`). El webhook solo
  acepta cuerpos con firma HMAC-SHA256 válida de Meta.
- **Quién accede.** El inquilino a lo suyo; el personal interno al tablero de
  consumo y costos.
- **Anotación honesta.** `contenido` **no** está en `SENSITIVE_FIELDS`, así que
  el texto de los mensajes se copia a `audit_log` en cada inserción, donde es
  inmutable y lo lee el personal interno. Es la decisión contraria a la que se
  tomó con el buzón. No es un fallo de aislamiento entre inquilinos —la bitácora
  también respeta el ámbito— pero sí amplía dónde vive el contenido de las
  conversaciones. El [registro de tratamiento](registro-tratamiento-datos-personales.md)
  (documento 6) ya está escrito y **no recoge este punto**: sigue pendiente de
  decidir. Lo mismo aplica a `notas_internas.texto`, que es texto libre del equipo
  sobre un cliente.
- **Si se pierde.** Se pierde el histórico de conversaciones y la base del cálculo
  de consumo del mes. No afecta a comprobantes ya emitidos.

### 2.7 Bitácora `audit_log`

- **Qué guarda.** Toda escritura ORM (INSERT/UPDATE/DELETE) con actor, rol real,
  inquilino, tabla, registro, **antes y después en JSON**, IP, user agent,
  request id y timestamp (`app/core/audit.py`), dentro de la **misma transacción**
  que la escritura: si la operación se revierte, su rastro también. Las funciones
  `auth_*` y `sa_*` insertan su propia fila desde SQL.
- **Cómo se protege.** Nadie actualiza ni borra: no hay `GRANT` de UPDATE/DELETE,
  no hay política que los permita y además hay un trigger que lanza excepción
  (migración `0002`). El rol de la app puede insertar; leer, solo el contexto
  interno verificado.
- **Ojo con lo que implica.** Al guardar el «después» de cada fila, la bitácora es
  ella misma un almacén de datos personales: contiene copias del payload de
  comprobantes, de clientes finales, de solicitudes de la web. Lo enmascarado es
  únicamente lo declarado en `SENSITIVE_FIELDS`: `password_hash`,
  `totp_secret_enc`, `token_hash`, `p12_data_enc`, `p12_password_enc`,
  `motivo_error` y `asunto`.
- **Si se pierde.** Se pierde la trazabilidad, que es justo lo que un auditor
  viene a mirar. Y no se puede reconstruir.

### 2.8 Constancias de aceptación, solicitudes de la web y comprobantes de pago

| Activo | Dónde | Protección | Quién accede |
|---|---|---|---|
| Aceptación de términos y de tratamiento de datos | `aceptaciones_terminos` | Append-only reforzado con trigger (migración `0007`); guarda **versión, SHA-256 del texto exacto mostrado**, IP, user agent y timestamp. El checkout público puede insertar pero no leer (`eager_defaults: False` para no exigir `RETURNING`) | Personal interno y el propio inquilino |
| Solicitudes del checkout y del formulario de contacto | `solicitudes_contacto` | Política de INSERT abierta (es un formulario público), SELECT solo interno. El pedido se completa por `publico_adjuntar_comprobante()`, función acotada que impide reemplazar un comprobante ya subido o tocar el pedido de otro | Personal interno |
| Comprobante de la transferencia | `{STORAGE_DIR}/comprobantes-pago/{solicitud_id}.{ext}` | Tipo MIME validado (JPG, PNG, WEBP, PDF), tope de 5 MB, nombre puesto por el servidor, rate limit de 5 envíos por IP cada 15 minutos | Personal interno |

Si se pierde una constancia de aceptación, se pierde la prueba del
consentimiento, y la carga de esa prueba es del responsable del tratamiento, no
del titular: por eso la tabla nunca se edita y cada retiro es una fila nueva.

### 2.9 Secretos del entorno

Todos en el `.env`, ninguno en la base ni en el repositorio:
`SECRET_KEY`, `CERT_ENC_KEY`, `TOTP_ENC_KEY`, `BUZON_ENC_KEY`,
`BUZON_WEBHOOK_SECRET`, `WA_APP_SECRET`, `WA_ACCESS_TOKEN`, `WA_VERIFY_TOKEN`,
`SMTP_PASSWORD`, las contraseñas de los dos roles de Postgres y `SENTRY_DSN`.
En producción, arrancar con valores de desarrollo o con claves faltantes es un
error de arranque, no una advertencia (`config.py`,
`sin_valores_inseguros_en_produccion`).

---

## 3. Datos personales tratados

Dos papeles distintos, y conviene no mezclarlos:

- Sobre los datos del **inquilino** (su RUC, su correo, su teléfono, sus
  usuarios), Factuchat es **responsable del tratamiento**: los recoge para
  prestarle el servicio que contrató.
- Sobre los datos de los **clientes finales del inquilino** y de los documentos
  que recibe en su buzón, Factuchat es **encargado**: los trata por cuenta del
  inquilino, que es quien tiene la obligación tributaria de emitir el comprobante.
  Esta distinción está asumida en el diseño (RLS por inquilino, funciones `sa_*`
  con motivo y auditoría para que el personal interno mire una ficha), y el
  [registro de tratamiento](registro-tratamiento-datos-personales.md) (documento 6)
  la declara inquilino por inquilino. Lo que sigue **sin redactarse es el contrato
  de encargo de tratamiento** con cada inquilino.

| Tabla | Columnas con datos personales | ¿De quién? | Base legal invocada | Dónde se recogen |
|---|---|---|---|---|
| `tenants` | `ruc`, `razon_social`, `nombre_comercial`, `email`, `telefono`, `direccion_matriz` | Del inquilino (en Ecuador muchísimos RUC son de persona natural) | Ejecución del contrato de servicio | Alta desde el panel interno (`sa_crear_tenant`) o CLI |
| `users` | `email`, `nombre`, `password_hash`, `totp_secret_enc`, `last_login_at`, `failed_attempts`, `locked_until` | Del personal del inquilino y del equipo interno de Factuchat | Ejecución del contrato; los contadores de fallos y bloqueo, por seguridad de la información | Alta de cuenta y login |
| `user_sessions` | `ip`, `user_agent` | De quien inicia sesión | Seguridad y trazabilidad | Login |
| `clientes_finales` | `identificacion`, `razon_social`, `email`, `telefono`, `direccion` | De los clientes del inquilino (terceros) | Obligación legal tributaria del inquilino de emitir el comprobante. Factuchat actúa como encargado | Panel, carga masiva CSV/Excel, WhatsApp, tienda interna |
| `comprobantes` | `payload.comprador` (razón social, identificación, correo), ítems y montos | Del cliente final | Igual que arriba | Emisión |
| `solicitudes_contacto` | `nombre`, `email`, `telefono`, `identificacion`, `ciudad`, `provincia`, `pais`, `mensaje`, `comprobante_url` | De **visitantes de la web** que aún no son clientes | Consentimiento, registrado en `aceptaciones_terminos` en el mismo acto del checkout | `POST /publico/checkout` y `POST /publico/contacto` |
| `aceptaciones_terminos` | `email`, `nombre`, `identificacion`, `ip`, `user_agent` | Del visitante o del inquilino | Obligación legal: demostrar el consentimiento (la carga de la prueba es del responsable) | Checkout |
| `whatsapp_msgs` | `wa_phone`, `contenido` (el texto del mensaje, que puede citar nombres e identificaciones de clientes finales) | Del inquilino y de quien escriba desde un número autorizado suyo | Ejecución del contrato | Webhook de Meta y respuestas del asistente |
| `buzon_correos` | `remitente`, `asunto`, y el mensaje completo cifrado en disco | De terceros: proveedores y agentes de retención del inquilino | Obligación legal tributaria (crédito tributario del inquilino); Factuchat como encargado | Reenvío que el propio inquilino configura en el portal del SRI |
| `retenciones_recibidas` | `ruc_agente`, `razon_social_agente`, `concepto`, `detalle` | Del agente de retención (empresa o persona natural con RUC) | Igual que arriba | Buzón |
| `pedidos` | `comprador_nombre`, `comprador_telefono` | Del comprador en la tienda interna del inquilino | Ejecución de la venta; encargado | Tienda interna del panel |
| `pagos` | `comprobante_url` (foto de la transferencia) | Del inquilino | Ejecución del contrato | Panel interno |
| `notas_internas` | `texto` libre del equipo sobre un cliente | Del inquilino | Interés legítimo en la atención y el soporte | Panel interno |
| `impersonaciones` | `actor_user_id`, `motivo`, `ip`, `user_agent` | Del operador interno | Seguridad y rendición de cuentas | Panel interno |
| `analisis_ia` | `referencia` (clave de acceso o message-id) | Indirectamente, del inquilino | Control de cupos del plan | Ingesta del buzón |
| `audit_log` | Copia en JSON del antes y el después de todo lo anterior, salvo lo enmascarado | De todos | Obligación de trazabilidad y seguridad | Automático, en cada escritura |

**Hueco identificado.** `POST /publico/contacto` guarda nombre, correo, teléfono
y mensaje **sin registrar consentimiento**: `ContactoIn`
(`app/schemas/tienda.py`) no incluye las casillas que sí trae `CheckoutIn`
(`AceptacionIn`, que nace desmarcada porque la LOPDP exige un acto afirmativo).
Es un tratamiento sin constancia. Hay dos salidas razonables —pedir la casilla
también ahí, o apoyar ese caso en el interés legítimo de atender una consulta que
la propia persona inicia— y la decisión sigue sin tomarse: el
[registro de tratamiento](registro-tratamiento-datos-personales.md) (documento 6)
ya está escrito y agrupa checkout y contacto en una sola actividad, sin distinguir
este caso, así que el hueco sigue abierto y hay que dejarlo escrito aquí.

---

## 4. Flujos de datos

### 4.1 Emisión de un comprobante desde el panel

| # | Paso | Qué se mueve | Dónde ocurre |
|---|---|---|---|
| 1 | `POST /comprobantes/facturas` (rol `CLIENTE`) crea el **borrador** | Ítems y comprador entran; los totales y el IVA se calculan **en servidor**, se verifica el cupo del plan y el tope de $200 de consumidor final | `app/services/emision.py` (`crear_factura`, `calcular_items`) |
| 2 | Confirmación explícita: `emitir` | Se asigna secuencial con `FOR UPDATE` y se genera la clave de acceso de 49 dígitos. **Nada ha salido todavía al SRI** | `app/services/emision.py` (`emitir`, `asignar_secuencial`) |
| 3 | Se encola el pipeline **después del commit** | Solo viajan dos identificadores a Celery, nunca datos | `app/db/session.py` (`despues_del_commit`) |
| 4 | Firma | El worker toma un candado en Redis por comprobante, descifra el .p12 en memoria, construye el XML, lo firma XAdES-BES y lo escribe en el volumen con su SHA-256 | `app/tasks/emision.py` (`_paso_firmar`), `app/sri/firma.py` |
| 5 | Recepción | La marca `enviado_recepcion_at` se escribe **antes** del efecto externo. El XML firmado sale en base64 dentro de un SOAP hacia el host del SRI que corresponde al ambiente del inquilino | `app/sri/client.py` (`enviar_recepcion`) |
| 6 | Autorización | Se consulta por clave de acceso; solo se acepta la respuesta cuya `claveAccesoConsultada` coincide. `AUTORIZADO` fija número y fecha, y el trigger de base deja el documento inmutable | `app/sri/client.py` (`consultar_autorizacion`), migración `0003` |
| 7 | RIDE y correo | WeasyPrint genera el PDF en el volumen. Si el comprador dejó correo, salen **PDF y XML adjuntos** por SMTP y se marca `correo_enviado_at` (marca propia: si el correo falla, se reintenta sin rehacer el RIDE) | `app/sri/ride.py`, `app/core/mailer.py` |

Lo que sale del sistema en este flujo: el comprobante completo al SRI, y la
factura al correo del cliente final. Nada más.

Ante una caída: el pipeline es idempotente. Si el worker murió después del POST
de recepción, no se reenvía a ciegas ni se da por perdido: se le pregunta al SRI
si ya lo tiene (`_sri_no_lo_tiene`), y «clave ya registrada» no se trata como
rechazo. Un barrido cada 10 minutos rescata lo que quedó a medio camino.

### 4.2 Emisión por WhatsApp

1. Meta llama a `POST /whatsapp/webhook`. La firma `X-Hub-Signature-256` se
   verifica **sobre el cuerpo crudo, antes de parsearlo**, con comparación en
   tiempo constante; sin `WA_APP_SECRET` se rechaza todo (`app/whatsapp/firma.py`).
2. Se responde 200 al instante y el trabajo va a Celery: si tardáramos, Meta
   reintentaría y se procesaría dos veces el mismo mensaje.
3. El worker resuelve de quién es el número con `sys_tenant_por_telefono()`,
   función `SECURITY DEFINER` que devuelve **un solo identificador**. Un número
   desconocido no recibe respuesta: contestar confirmaría que existe y abriría una
   conversación que Meta cobra.
4. El mensaje entrante se registra en `whatsapp_msgs` con categoría `USUARIO` y el
   estado de la conversación va a Redis con TTL de 30 minutos. Ojo con el costo: la
   única categoría exenta **por construcción** es `SERVICIO`
   (`app/whatsapp/consumo.py`, `registrar`). `USUARIO` se valora a la tarifa del
   concepto «Conversación iniciada por el usuario» si esa tarifa está cargada en
   `cost_rates`, y solo se imputa una vez por ventana de 24 horas. El docstring del
   módulo dice que la conversación abierta por el usuario no se cobra, pero el código
   no lo garantiza: queda anotado para revisarlo.
5. El asistente pide cliente → detalle → monto y **exige confirmación explícita**:
   «Nada se envía al SRI hasta que tú confirmes». A partir de ahí entra al mismo
   pipeline de 4.1.
6. Cada respuesta sale hacia `graph.facebook.com` y se registra con su costo según
   la tarifa vigente en `cost_rates`.

### 4.3 Entrada de un correo al buzón SRI

1. El proveedor de correo entrega el mensaje MIME crudo a `POST /buzon/webhook`
   con `X-Buzon-Signature`. Se compara con HMAC-SHA256 en tiempo constante; sin
   `BUZON_WEBHOOK_SECRET` se responde 403 sin explicar nada; por encima de
   `BUZON_MAX_BYTES` (15 MB) se rechaza. **Es la única vía de entrada implementada**:
   la recolección por IMAP no existe en el código, solo están reservados sus ajustes
   de configuración (ver el punto 4 de la sección 7).
2. **De quién es el correo lo decide la dirección de entrega**: el `RCPT TO` del
   sobre (`X-Buzon-Recipient`) o las cabeceras que pone el servidor
   (`Delivered-To`, `X-Original-To`, `X-Envelope-To`, `X-Forwarded-To`). `To` y
   `Cc` no cuentan, porque los escribe el remitente. Con dos destinos válidos o
   ninguno, el correo se descarta en vez de adjudicarse a ciegas
   (`app/buzon/correo.py`, `tenant_por_direccion`).
3. Candado en Redis por `(tenant, message_id)`. Si está tomado, el correo vuelve a
   la cola: tratarlo como éxito haría que Celery lo confirmara y el mensaje se
   perdería si el candado era de un worker muerto.
4. Se registra la fila con las señas y se guarda el mensaje completo **cifrado**
   en disco. Los ficheros escritos se anotan en la sesión: si la transacción se
   revierte, se borran, para no dejar copias huérfanas de hasta 15 MB.
5. Se leen los XML —incluidos los que vienen dentro de un ZIP— con un parser
   endurecido: sin DOCTYPE, sin entidades externas, sin red, tope de 4 MB y tope
   de líneas.
6. Se comprueba que la retención sea **del inquilino**: la identificación del
   sujeto retenido es obligatoria y se compara con longitudes fijas (10 o 13
   dígitos). Se deduplica por clave de acceso y por (número, agente).
7. La retención se guarda con `verificada = false` y **no suma nada**. Un task
   pregunta al SRI por su clave de acceso; solo si responde `AUTORIZADO` empieza a
   contar como crédito. Un SRI caído se reintenta, nunca se interpreta como
   permiso.
8. Se registra un análisis de IA **exento** (`consume=False`) y se pone en cero el
   reloj del recordatorio de los 30 días sin recibir nada.

### 4.4 Checkout de la landing

1. La web pide `GET /publico/terminos` y `GET /publico/config`: el dominio, los
   datos de contacto y las cuentas de cobro salen del servidor, no del bundle,
   precisamente porque el dominio todavía no está confirmado.
2. `POST /publico/checkout`, con rate limit de 5 envíos por IP cada 15 minutos. El
   plan y su precio se validan **contra la base** por código: el navegador solo
   manda el código.
3. **Primero se registra la aceptación** —dos filas, `TERMINOS` y
   `DATOS_PERSONALES`, con versión, SHA-256 del texto mostrado, IP y user agent—
   y solo después se crea la solicitud. Si falla, no queda un pedido huérfano sin
   base legal para tratar sus datos. Sin ambas casillas marcadas, 422.
4. La referencia del pedido la genera el servidor (la maqueta usaba `Date.now()`,
   que colisiona). Se devuelve además el enlace de WhatsApp con el mensaje ya
   redactado.
5. El aviso al correo de ventas se encola **después del commit** y la marca
   `avisado_at` evita el segundo correo si el task se reintenta.
6. Si eligió transferencia, sube la foto o el PDF: tipo MIME validado, 5 MB, nombre
   puesto por el servidor, y la fila se completa por
   `publico_adjuntar_comprobante()`, que no deja reemplazar un comprobante ya
   subido ni tocar el pedido de otro.
7. **El checkout no activa ninguna cuenta.** La crea el equipo desde el panel
   interno. Payphone todavía no está integrado: la vía de tarjeta registra el
   pedido, no redirige.

### 4.5 Impersonación del personal interno

1. Solo `SOPORTE` y `SUPERADMIN`; `LECTURA` nunca. Se exige un motivo escrito de
   al menos 10 caracteres: un motivo vacío convierte la auditoría en ruido.
2. El nombre del inquilino se obtiene por `sa_tenant_basico()`, porque ni el
   personal interno lee `tenants` directamente.
3. Cualquier sesión anterior del mismo operador que quedara abierta se cierra
   antes de abrir la nueva, para que ninguna quede eterna.
4. **Doble rastro**: la fila en `impersonaciones` (actor, inquilino, motivo,
   inicio, fin, IP, user agent) y el evento `IMPERSONACION_INICIO` en la bitácora
   con el actor real.
5. El token dura 30 minutos, no se renueva y solo concede rol `CLIENTE` sobre ese
   inquilino, nunca rol interno sobre otro.
6. Cada escritura durante la sesión se audita con el **rol real** del operador y un
   bloque `_impersonacion` en el «después», nunca como si la hubiera hecho el
   inquilino (`app/core/audit.py`, `_make_entry`).
7. Al salir se registra `IMPERSONACION_FIN` con la duración. Las sesiones cuyo
   token ya caducó pero nadie cerró se listan aparte en el panel.

Fuera de la impersonación, abrir la ficha de un cliente ya es de por sí un acceso
a datos personales: `sa_ficha_cliente()` exige motivo y escribe `SA_FICHA` en la
bitácora antes de devolver una sola fila.

---

## 5. Destinos externos

Estos son **todos** los destinos a los que este código sale. La lista se puede
verificar en el repositorio: solo hay dos llamadas HTTP salientes
(`httpx.post` en `app/sri/client.py` y en `app/whatsapp/cliente.py`), más SMTP y
el SDK de Sentry.

| Destino | Qué sale hacia allá | Qué entra desde allá | Control | Código |
|---|---|---|---|---|
| SRI — `celcer.sri.gob.ec` (pruebas) y `cel.sri.gob.ec` (producción) | El XML firmado completo en base64: emisor, comprador, ítems, totales. Y la clave de acceso al consultar autorización o al verificar una retención recibida | Estado de recepción, autorización y mensajes de error | Lista blanca `HOSTS_PERMITIDOS_SRI`, verificada antes de cada POST. Timeout de 30 s, cortacircuitos en Redis, parser sin entidades externas ni red | `app/sri/client.py` |
| Meta — `graph.facebook.com` | Número de destino, texto de la respuesta, botones y listas; plantillas de aviso con sus variables | Webhooks con los mensajes del usuario | Lista blanca `HOSTS_PERMITIDOS_META` (un solo host). Firma HMAC verificada en todo webhook entrante. Ninguna URL provista por un usuario se visita | `app/whatsapp/cliente.py`, `app/whatsapp/firma.py` |
| SMTP (servidor configurado en `.env`) | RIDE en PDF y XML al correo del cliente final; aviso de pedidos y consultas al correo de ventas; recordatorio de buzón callado al inquilino | — | Contexto TLS con verificación de certificado y de hostname (`check_hostname`, `CERT_REQUIRED`): sin él, `starttls()` acepta cualquier certificado y las facturas quedan expuestas a un intermediario. Sin SMTP configurado, los correos se escriben como `.eml` en disco y no salen | `app/core/mailer.py` |
| Sentry (si hay `SENTRY_DSN`) | Trazas de error de api y worker | — | `send_default_pii=False`, `include_local_variables=False`, `max_request_body_size="never"` y un `before_send` que enmascara claves sensibles y descarta todo valor binario. Sin DSN, el SDK ni se inicializa | `app/core/observabilidad.py` |
| Proveedor de correo entrante del buzón | Nada sale: solo entra | El mensaje MIME crudo por webhook firmado (única vía implementada) | Firma HMAC obligatoria; sin secreto, 403 mudo | `app/api/routes/buzon.py` |

Lo que **no** existe como destino, y conviene decirlo porque un inventario que
promete integraciones inexistentes no sirve:

- **Payphone no está integrado.** El checkout y la tienda registran el método de
  pago, nada más (`app/api/routes/tienda.py`: `payphone_conectado = False`).
- **No hay proveedor de inteligencia artificial conectado.** La tabla
  `analisis_ia` lleva la cuenta de los análisis y aplica la exención del buzón,
  pero no hay ninguna llamada a un servicio de IA en el código.
- **No hay CDNs ni fuentes externas**: la CSP de nginx es `default-src 'self'` y
  los assets se sirven desde `/static`.
- El navegador del visitante puede abrir `wa.me` y Google Maps desde la landing,
  pero eso es un enlace que pulsa la persona, no una petición del servidor.

---

## 6. Retención de la información

| Activo | Plazo | Fundamento | Estado real hoy |
|---|---|---|---|
| Comprobantes emitidos: XML, RIDE y su fila | **Siete años** | Plazo de la normativa tributaria ecuatoriana, publicado además en la sección 7 del documento de términos que el cliente acepta (`app/services/terminos.py`) | Se cumple **por no borrar**: no existe rutina de eliminación ni de archivado al vencer el plazo |
| XML de retenciones recibidas y correos del buzón | Siete años, misma lógica: son documentos con valor tributario | Anotado en el modelo (`RetencionRecibida`) y en `app/buzon/ingesta.py` | Igual: se conservan cifrados, sin purga |
| Logs de nginx, api y worker | **12 meses** | Paso 9 del despliegue (A.8.15). El formato JSON estructurado ya está escrito en `deploy/nginx/nginx.conf` | Pendiente: `logrotate` con 12 meses se configura al desplegar; hoy no hay servidor |
| `audit_log` | Sin plazo definido | Es inmutable por diseño: no hay UPDATE ni DELETE para nadie | Crece sin purga. Cualquier política de retención futura tendrá que decidirse a la vez que se decide qué hacer con una tabla que, por definición, no se puede recortar desde la aplicación |
| Estado de conversación de WhatsApp (Redis) | 30 minutos | Una factura a medias no debe quedar colgada | Implementado (`TTL_ESTADO_S`) |
| Contadores de rate limit y candados (Redis) | 15 minutos los contadores, 5 minutos los candados | Ventana de los controles | Implementado |
| Datos de un titular que pide su eliminación | — | Sección 8 de los términos: acceso, rectificación, eliminación, portabilidad y retiro de la autorización | **Pendiente**: el retiro del consentimiento sí deja constancia (`registrar_retiro`), pero no hay procedimiento ni herramienta de borrado. El [documento 6](registro-tratamiento-datos-personales.md) ya dejó escrita la tensión —los comprobantes no se pueden borrar antes de los siete años aunque el titular lo pida, y lo que quede en `audit_log` no se puede ni borrar ni anonimizar— pero la deja listada como pendiente: no hay endpoint, ni comando de CLI, ni tarea |

---

## 7. Pendientes que afectan a este inventario

Ninguno de estos puntos es un descuido de redacción: son cosas que todavía no
existen, y un inventario que las diera por hechas sería falso.

1. **El dominio definitivo no está confirmado.** `APP_DOMAIN` está vacío y es
   obligatorio en producción; mientras tanto se usa `factuchat.ec` como respaldo
   para que la web y los correos no salgan en blanco. Las maquetas usan tres
   dominios distintos. Esto afecta a las direcciones del buzón
   (`{ruc}@{dominio}`), a los correos `info@` y `ventas@`, y a la CSP y CORS.
2. **No hay certificado .p12 real.** Todo el motor de firma está construido y
   probado con certificados de prueba; la emisión real contra el SRI espera el
   certificado del titular.
3. **Faltan las credenciales de Meta.** Sin `WA_APP_SECRET`, `WA_ACCESS_TOKEN` y
   `WA_PHONE_NUMBER_ID` el canal de WhatsApp no opera. El diseño ya decide que sin
   el secreto de la app el webhook rechaza todo: nunca falla abierto.
4. **Falta contratar el proveedor de correo entrante del buzón.** El webhook
   firmado está listo; el proveedor (Mailgun, Postmark, SES u otro) y los
   registros MX del subdominio, no. El runbook está en
   `deploy/scripts/buzon-sri-puesta-en-marcha.md`. Y la **recolección por IMAP no
   está implementada**: en el código solo existen las variables de configuración
   reservadas (`buzon_imap_host`, `buzon_imap_port`, `buzon_imap_user`,
   `buzon_imap_password`, `buzon_imap_carpeta` en `config.py`), sin cliente, sin
   tarea de Celery y sin pruebas. Mientras no se escriba, el webhook es el único
   camino de entrada. Cuidado con un detalle: `sin_valores_inseguros_en_produccion`
   acepta `BUZON_IMAP_HOST` como sustituto de `BUZON_WEBHOOK_SECRET`, así que un
   despliegue configurado solo con IMAP arrancaría sin protestar y no ingeriría
   nunca un correo.
5. **El despliegue en el VPS no se ha hecho.** El bloque TLS global está activo en
   `deploy/nginx/nginx.conf` (TLS 1.2 y 1.3, ciphers y stapling) y el `server` de
   443 con la redirección 301 y la cabecera HSTS está escrito y **sin comentar** en
   `deploy/nginx/templates/factuchat.conf.template`, que recibe el dominio por
   `envsubst`. El cliente ACME sí existe: el servicio `certbot` del compose renueva
   por webroot cada 12 horas y nginx se recarga solo cada 6 para tomar el
   certificado nuevo. Lo que falta es la PRIMERA emisión, que hace
   `deploy/scripts/tls-emitir.sh`: hasta que exista
   `/etc/letsencrypt/live/${FACTUCHAT_DOMINIO}/fullchain.pem` nginx no arranca, así
   que el script rompe ese círculo con un certificado autofirmado temporal.
   Siguen pendientes, además, fijar las imágenes por digest en vez de por etiqueta,
   el escaneo con trivy y la retención de logs de 12 meses.
6. **El respaldo está escrito, pero nunca se ha ejecutado.** `deploy/scripts/`
   contiene hoy los guiones de verificación (`check.sh`, `check.ps1`), dos runbooks
   y los tres scripts del despliegue: `instalar-servidor.sh`, `respaldo.sh` y
   `restaurar.sh`. Lo que no existe es un servidor donde correrlos, ni una sola
   copia tomada, ni evidencia de una restauración probada. Sigue siendo el punto
   más urgente de esta lista para el volumen `comprobantes`, porque los XML
   autorizados no se regeneran solos.
7. **Sin rotación asistida de claves maestras.** Rotar `CERT_ENC_KEY`,
   `TOTP_ENC_KEY` o `BUZON_ENC_KEY` exige hoy recifrar a mano lo ya guardado.
8. **Dos avisos activos siguen sin salir**: la alerta de presupuesto de WhatsApp
   se calcula y se muestra en el panel, pero nadie es notificado; y los rechazos
   del SRI en ráfaga quedan en la bitácora sin regla que los agrupe. Ambos
   figuran como parciales en A09 de SECURITY.md.
9. **El registro LOPDP ya está escrito** ([documento 6](registro-tratamiento-datos-personales.md)),
   pero no lo resolvió todo. Sigue sin redactarse el **contrato de encargo de
   tratamiento** con cada inquilino, y tres huecos de este inventario quedaron
   abiertos: el registro no aborda el consentimiento del formulario de contacto ni
   el destino del contenido de WhatsApp en la bitácora, y el procedimiento de
   eliminación a petición del titular figura en su sección 8 como pendiente, sin
   endpoint, sin comando de CLI y sin tarea.
