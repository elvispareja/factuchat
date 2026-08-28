# Registro de tratamiento de datos personales — Factuchat

Versión 1.0 · Fases 1–7 · Actualizar al añadir cada finalidad nueva, cada encargado nuevo
o cada versión nueva del documento de términos.

Este documento cumple dos funciones: es el **registro de actividades de tratamiento** que
exige la LOPDP y es la **constancia de cómo se prueba el consentimiento**. Todo lo que
afirma está tomado del código de este repositorio y se cita el archivo. Donde un control
no existe todavía, se dice explícitamente en la sección 8; un registro que promete lo que
el sistema no hace no sirve como evidencia.

El mapeo técnico de seguridad vive en [SECURITY.md](../SECURITY.md); quién puede ver qué,
en [matriz-roles-accesos.md](matriz-roles-accesos.md).

---

## 1. En calidad de qué trata Factuchat cada conjunto de datos

Factuchat no tiene el mismo papel sobre todos los datos que pasan por el sistema, y la
diferencia no es una declaración de intenciones: está construida en la base de datos.

| Conjunto de datos | Quién decide para qué se usan | Papel de Factuchat | Cómo se sostiene técnicamente |
|---|---|---|---|
| Contribuyente inquilino y su equipo (`tenants`, `users`) | Factuchat, al prestar el servicio | **Responsable** | Alta por `app/cli.py` o por el wizard de `app/api/routes/superadmin.py`, auditada |
| Clientes finales del inquilino (`clientes_finales`, `comprobantes`) | El inquilino: él decide a quién factura y qué datos carga | **Encargado** | RLS `FORCE` por `tenant_id`; el rol de la app es `NOBYPASSRLS` (`deploy/postgres/init/01-roles.sh`, migración `0002`) |
| Documentos de terceros del buzón (`buzon_correos`, `retenciones_recibidas`) | El inquilino, al publicar su dirección de buzón | **Encargado** | Cifrado AES-256-GCM con clave propia + RLS (migración `0009`) |
| Interesados de la landing (`solicitudes_contacto`, `aceptaciones_terminos`) | Factuchat | **Responsable** | Checkout público, `app/api/routes/publico.py` |

Lo que hace verificable el papel de **encargado** es que ni el personal interno de
Factuchat puede leer los datos de un inquilino con una consulta normal: la política RLS
solo abre por `tenant_id`, y el acceso interno pasa por funciones `sa_*` de
`factuchat_security` que exigen motivo escrito y dejan fila en `audit_log`. Un encargado
que puede leerlo todo sin dejar rastro es un encargado de nombre.

---

## 2. Registro de actividades de tratamiento

Una fila por finalidad. El detalle de tablas y columnas de cada una está en la sección 3.

| # | Finalidad | Categorías de titulares | Categorías de datos | Base legal | Plazo de conservación | Destinatarios y transferencias |
|---|---|---|---|---|---|---|
| A1 | Prestación del servicio de facturación (alta, acceso y gestión de la cuenta) | Contribuyente inquilino y las personas de su equipo con usuario | Identificación (RUC, cédula), razón social, nombre, correo, teléfono, dirección de matriz y establecimientos; credenciales (hash Argon2id), secreto TOTP cifrado, IP y user agent de cada sesión | Ejecución del contrato + consentimiento registrado (bandera `DATOS_PERSONALES`) | Mientras la cuenta esté activa y el tiempo que la ley exija después (sección 7 del documento de términos). **Declarado, no automatizado** | Ninguno fuera de Factuchat. Trazas de error a Sentry, sin variables locales ni cuerpos de petición (`app/core/observabilidad.py`) |
| A2 | Emisión y firma de comprobantes electrónicos a los clientes finales del inquilino | Clientes finales del inquilino (personas naturales y jurídicas) | Tipo y número de identificación, razón social o nombres, correo, teléfono, dirección; detalle de la compra, montos y clave de acceso | Cumplimiento de obligación legal tributaria del inquilino (el comprobante es obligatorio) + ejecución del contrato. Factuchat actúa como encargado | 7 años, conforme a la normativa y a la sección 7 del documento. **Declarado, no automatizado** | **SRI** (`RecepcionComprobantesOffline` y `AutorizacionComprobantesOffline`, `app/sri/client.py`) y **el propio cliente final**, que recibe RIDE en PDF y XML por SMTP (`app/tasks/emision.py`). Sin transferencia internacional |
| A3 | Atención y emisión por WhatsApp | Inquilino y números adicionales que él autoriza | Número de teléfono, dirección y categoría del mensaje, texto del mensaje recortado a 1000 caracteres, identificador de mensaje de Meta, costo imputado | Ejecución del contrato + consentimiento | `whatsapp_msgs`: **sin plazo de purga implementado**. El estado de la conversación en Redis caduca a los 30 minutos (`TTL_ESTADO_S`, `app/whatsapp/conversacion.py`) | **Meta Platforms** (WhatsApp Cloud API, único destino permitido `graph.facebook.com` en `app/whatsapp/cliente.py`). **Transferencia internacional**: los mensajes atraviesan infraestructura de Meta fuera de Ecuador |
| A4 | Cobro y facturación del propio servicio | Contribuyente inquilino / contratante | Plan contratado, precio congelado, monto, método de pago, referencia, imagen del comprobante de transferencia, uso de códigos promocionales | Ejecución del contrato + obligación legal (Factuchat debe emitir su propio comprobante) | Plazos tributarios aplicables a Factuchat. **Declarado, no automatizado** | Entidad bancaria del titular receptor, fuera del sistema (las cuentas están en `COBRO_CUENTAS`). Payphone figura como método pero **no está integrado**: la vía de tarjeta registra el pedido y no redirige a ninguna pasarela |
| A5 | Soporte, operación interna e impersonación | Inquilino; de forma incidental, sus clientes finales visibles en la ficha | Ficha del inquilino (RUC, razón social, correo, teléfono, estado, plan, conteos, vencimiento del certificado), notas internas, motivo del acceso, IP y user agent del operador, valores antes/después de cada escritura | Interés legítimo en operar y dar soporte, acotado por el deber de trazabilidad. El acceso a la ficha exige **motivo escrito** | `audit_log` **no se purga, no se puede borrar ni reescribir**: es inmutable por diseño (sin GRANT ni política de UPDATE/DELETE, más el trigger `trg_audit_log_inmutable`, migración `0002`). `impersonaciones` (migración `0005`) tampoco se purga y no admite DELETE, pero **sí tiene GRANT de UPDATE** porque el cierre de sesión escribe `terminada_at`, y ningún trigger impide reescribir motivo, actor o fechas (pendiente 15 de la sección 8) | Solo personal interno con rol `LECTURA`, `SOPORTE` o `SUPERADMIN`. Trazas de error a Sentry, filtradas |
| A6 | Buzón de documentos recibidos del SRI | Agentes de retención y proveedores del inquilino (terceros), y el propio inquilino | Remitente, asunto y cuerpo del correo; RUC y razón social del agente de retención, base imponible, retención de renta e IVA, clave de acceso, período fiscal | Cumplimiento de obligación legal tributaria del inquilino (crédito tributario). Factuchat actúa como encargado | Custodia de siete años del XML y del RIDE (`app/db/models/admin.py`, `RetencionRecibida`). **Declarado, no automatizado** | **SRI**, para verificar que la retención está realmente autorizada (`app/buzon/verificacion.py`). El proveedor de correo entrante será un encargado adicional: **todavía no está contratado** |
| A7 | Captación desde la landing (checkout y contacto) | Interesados que aún no son clientes | Nombres y apellidos, identificación, correo, teléfono, país, provincia, ciudad, plan de interés, método de pago, día y hora de agenda, mensaje libre, código promocional, imagen del comprobante de transferencia; y la constancia de aceptación con IP y user agent | **Consentimiento**, obtenido con acto afirmativo (casilla que nace desmarcada, `app/schemas/tienda.py`), más medidas precontractuales | **Sin plazo de purga implementado**. Las constancias de `aceptaciones_terminos` se conservan de forma indefinida a propósito: son la prueba del consentimiento | El correo de ventas del propio equipo, por SMTP (`app/tasks/notificaciones.py`). Ningún tercero comercial |

---

## 3. Dónde vive cada dato personal y cómo está protegido

| Tabla o almacén | Datos personales que contiene | Protección aplicada |
|---|---|---|
| `tenants` | RUC, razón social, nombre comercial, correo, teléfono, dirección de matriz | RLS `FORCE`; cerrada incluso al contexto interno: se consulta por `sa_tenant_basico`, `sa_ficha_cliente`, `sys_tenant_por_buzon` y `sys_tenant_por_telefono` |
| `users` | Correo, nombre, rol, últimos accesos | RLS por `tenant_id`; contraseña en Argon2id (m=64 MiB, t=3, p=4) y secreto TOTP cifrado AES-256-GCM con `TOTP_ENC_KEY` |
| `user_sessions` | IP, user agent, hash SHA-256 del refresh token | Nunca se guarda el token en claro; rotación con detección de reúso |
| `clientes_finales` | Tipo y número de identificación, razón social, correo, teléfono, dirección | RLS `FORCE` por `tenant_id`, verificada con el rol de la app en `tests/test_rls.py` |
| `comprobantes` | `payload` JSONB con los datos del comprador y el detalle de la venta | RLS; el XML autorizado es inmutable (hash SHA-256 + trigger, migración `0003`) |
| `certificados` | El `.p12` del inquilino y su contraseña, que son su identidad electrónica | AES-256-GCM con `CERT_ENC_KEY`, cifrados **por separado y con AAD distinto**; descifrado solo en memoria del worker al firmar (`app/sri/firma.py`) |
| `whatsapp_msgs` | Número de teléfono y texto del mensaje (máx. 1000 caracteres) | RLS por `tenant_id`; firma HMAC-SHA256 obligatoria en el webhook (`app/whatsapp/firma.py`) |
| `pagos`, `recargas` | Monto, referencia y ruta de la imagen del comprobante de transferencia | RLS; la subida pública valida tipo MIME y 5 MB y el nombre del archivo lo pone el servidor |
| `buzon_correos` | Remitente, asunto y el correo completo del tercero | El cuerpo **no vive en ninguna columna**: se guarda cifrado en disco con `BUZON_ENC_KEY` y AAD `factuchat/buzon/correo`, y se descifra bajo demanda. `asunto` y `motivo_error` van enmascarados en la bitácora |
| `retenciones_recibidas` | RUC y razón social del agente de retención, montos, clave de acceso | RLS verificada con el rol de la app (`tests/test_buzon.py::test_postgres_impide_ver_la_retencion_de_otro`) |
| `solicitudes_contacto` | Datos completos del interesado de la landing | RLS: quien envía el formulario **puede insertar pero no leer**; completar su propio pedido pasa por `publico_adjuntar_comprobante` (SECURITY DEFINER, no devuelve datos). Rate limit de 5 envíos / 15 min por IP |
| `aceptaciones_terminos` | Correo, nombre, identificación, IP y user agent de quien aceptó | RLS con INSERT abierto y SELECT solo para personal interno o el propio tenant; sin GRANT de UPDATE/DELETE y con trigger de inmutabilidad |
| `impersonaciones` | Operador, inquilino, motivo, IP y user agent, inicio y fin | Solo personal interno; el token dura 30 minutos y no se renueva |
| `audit_log` | Actor, tenant, IP, user agent y el **valor antes/después de cada columna escrita** | Inmutable: sin GRANT ni política de UPDATE/DELETE, más trigger `trg_audit_log_inmutable`. Enmascara `password_hash`, `totp_secret_enc`, `token_hash`, `p12_data_enc`, `p12_password_enc`, `motivo_error` y `asunto` |
| Volumen `comprobantes` (disco) | XML firmados, RIDE en PDF, correos del buzón cifrados | Volumen compartido solo entre `api` y `worker`, en contenedores de solo lectura salvo ese punto de montaje |
| Redis | Estado de conversación de WhatsApp, contadores de rate limit, candados | Red interna de Docker sin salida a internet, con contraseña; el estado caduca a los 30 minutos |
| Logs de nginx | IP, URI, user agent | Formato JSON (`deploy/nginx/nginx.conf`), rotación en el driver de Docker; la retención de 12 meses se fija en el despliegue |

**Consecuencia que conviene tener presente:** el listener de auditoría de
`app/core/audit.py` vuelca **todas** las columnas escritas a `audit_log`, salvo las siete
enmascaradas. Eso significa que la identificación, el correo y el teléfono de un cliente
final quedan replicados en una tabla que, por diseño, nadie puede editar ni borrar. Es una
decisión deliberada —la trazabilidad no sirve si se puede reescribir—, pero tiene un
efecto directo sobre el derecho de supresión que se explica en la sección 6.

---

## 4. El documento de términos y su versionado

El documento vive en `backend/app/services/terminos.py`, no en la base ni en el bundle del
frontend, y se publica en `GET /api/v1/publico/terminos`.

| Dato | Valor | Dónde |
|---|---|---|
| Título | Términos de uso y tratamiento de datos | `TITULO` |
| Versión vigente | **2026.08** | `VERSION` |
| Última actualización | agosto de 2026 | `ACTUALIZADO` |
| Pie fijado | Última actualización: agosto de 2026 · Factuchat, Quito, Ecuador | `PIE` |
| Secciones | 9: las 1 a 4 son los términos de uso, las 5 a 9 el aviso de tratamiento de datos | `SECCIONES` |
| Huella | SHA-256 del texto exacto (título + las 9 secciones + pie) | `Documento.sha256` |

Las secciones 5 a 9 son las que cumplen el deber de información: **5. Qué datos
recogemos**, **6. Para qué los usamos**, **7. Cuánto tiempo los guardamos**, **8. Tus
derechos** y **9. Cambios**. La sección 6 declara además que no se venden ni ceden datos
con fines comerciales, y que solo se comparten con la administración tributaria, con el
procesador de pagos cuando se paga con tarjeta y con los proveedores tecnológicos
necesarios para operar. La tabla de la sección 2 de este registro es la versión detallada
de esa misma frase.

### Dos consentimientos, una casilla

Legalmente son dos cosas distintas: aceptar las condiciones de uso de un servicio no es
autorizar el tratamiento de datos personales. En pantalla se piden juntos —una sola
casilla, como en la maqueta— pero en la base se registran **por separado**, con una fila
por cada uno:

| Bandera | Constante | Qué cubre |
|---|---|---|
| `TERMINOS` | `terminos.CONDICIONES` | Secciones 1 a 4: qué es el servicio, la firma, planes y uso correcto |
| `DATOS_PERSONALES` | `terminos.DATOS` | Secciones 5 a 9: el aviso de tratamiento |

`terminos.registrar()` exige **ambos**: si falta cualquiera de los dos lanza
`TerminosError` y el checkout devuelve 422. No es una formalidad —sin la autorización de
tratamiento no hay base legal para procesar ni los datos del contribuyente ni los de sus
clientes finales—, y por eso la aceptación se registra **antes** de crear la solicitud:
si fallara, no quedaría un pedido huérfano cuyos datos ya se estarían tratando sin base.
Está verificado en `tests/test_tienda.py::test_sin_aceptar_no_hay_checkout`, que comprueba
que no queda ni la solicitud ni media constancia.

La casilla nace desmarcada por contrato del esquema (`AceptacionIn`, con ambos campos en
`False` por defecto). Un valor marcado por omisión no es un acto afirmativo.

### Por qué se guarda la versión y el hash, y no un booleano

Un `acepto = true` no prueba nada. Dentro de un año, con el texto ya actualizado, sería
imposible saber qué leyó esa persona cuando pulsó el botón; y la carga de la prueba es
del responsable del tratamiento, no del titular. Por eso cada constancia guarda:

| Columna | Para qué sirve en una reclamación |
|---|---|
| `version` | Identifica qué edición del documento se mostró |
| `sha256` | Fija el **texto exacto**. Si alguien edita el documento sin subir la versión, el hash deja de coincidir y queda a la vista |
| `aceptado_at` | El momento del acto |
| `ip`, `user_agent` | Circunstancias del acto |
| `origen` | Por qué vía se dio: `CHECKOUT`, o `RETIRADO:{canal}` en un retiro |
| `email`, `nombre`, `identificacion` | Quién lo dio, cuando todavía no hay tenant ni usuario |

`historial()` devuelve además un campo calculado, `sobre_version_vigente`, que compara el
hash guardado con el del documento actual: dice de un vistazo si esa persona aceptó el
texto que hoy está publicado o uno anterior.

Que el hash cumple su función está comprobado en
`tests/test_tienda.py::test_si_el_texto_cambia_el_hash_lo_delata`: con la **misma** versión
y otro texto, el hash cambia.

### La tabla es append-only

`aceptaciones_terminos` no se edita nunca. Cada aceptación, cada versión nueva y cada
retiro son filas propias. Tres capas lo sostienen, y hacen falta las tres:

1. El rol de la aplicación tiene `GRANT SELECT, INSERT` y nada más (migración `0007`).
2. No existe política RLS de UPDATE ni de DELETE, así que quedan cerradas incluso para
   quien tuviera el permiso.
3. El trigger `trg_aceptacion_inmutable` aborta cualquier UPDATE o DELETE con el mensaje
   «la aceptación de términos es inmutable». Verificado en
   `tests/test_tienda.py::test_la_constancia_es_inmutable`, que lo intenta con el rol
   propietario y falla.

Un detalle deliberado: la clave foránea de `tenant_id` es `ON DELETE SET NULL`, no
`CASCADE`. Si algún día se da de baja un inquilino, la constancia de su consentimiento
**sobrevive** con el correo intacto. Borrarla destruiría precisamente lo que hay que poder
demostrar.

### Discrepancia conocida en el texto de la casilla

El backend publica en `texto_casilla` la frase «Acepto los términos y condiciones de uso y
el tratamiento de mis datos para emitir mis comprobantes y activar mi cuenta», pero el
checkout (`frontend/src/landing/Checkout.tsx`) muestra una etiqueta propia, escrita a mano:
«Acepto los términos de uso y el tratamiento de mis datos personales». La prueba que se
almacena es la versión y el hash del **documento**, que sí es el mismo que se muestra en el
modal, así que la constancia no se ve afectada; pero las dos frases deberían salir del
mismo sitio. Queda anotado en la sección 8.

---

## 5. Cómo se cambia de versión

El procedimiento no está automatizado y conviene que quede escrito, porque el hash lo hace
inflexible a propósito:

1. Se edita `SECCIONES` en `app/services/terminos.py` y **se sube `VERSION` y
   `ACTUALIZADO`**. Cambiar el texto sin subir la versión no rompe nada de inmediato, pero
   deja constancias antiguas con `sobre_version_vigente = false` sin explicación.
2. `Documento.sha256` se recalcula solo: es una propiedad, no un valor guardado.
3. La sección 9 del propio documento compromete a avisar por el mismo chat **antes** de
   que la versión nueva entre en vigor. Ese aviso es manual hoy: no hay tarea que lo
   dispare.
4. Quien acepte a partir de ese momento genera constancias con la versión nueva. Las
   anteriores no se tocan.

---

## 6. Derechos del titular y cómo se atienden hoy

La sección 8 del documento promete acceso, rectificación, eliminación, portabilidad y
retiro de la autorización, por WhatsApp o por el correo de contacto. Esto es lo que existe
hoy para cumplirlo, sin adornos.

| Derecho | Qué hay implementado | Cómo se atiende en la práctica | Estado |
|---|---|---|---|
| **Acceso** | El inquilino ve sus datos, sus clientes y sus comprobantes en el panel (`/clientes`, `/comprobantes`, `/panel/estado`). El historial de consentimiento se obtiene con `terminos.historial(db, email)` | Lo del panel es autoservicio. El historial de consentimiento hay que ejecutarlo a mano contra la base | Parcial |
| **Rectificación** | `PUT /api/v1/clientes/{id}` para los datos de un cliente final. Para los datos del propio inquilino **no hay nada**: ninguna función `sa_*` corrige RUC, razón social, correo, teléfono ni dirección —las únicas que escriben sobre `tenants` son `sa_crear_tenant` y `sa_cambiar_estado_tenant`—, y tampoco hay endpoint PUT/PATCH de tenant ni comando de CLI | Autoservicio para los clientes finales; para el inquilino, SQL manual con el rol propietario | **Parcial** |
| **Rectificación de un comprobante autorizado** | No se puede, y es correcto que no se pueda: el XML autorizado es inmutable por trigger y hash | La vía es la nota de crédito, por normativa. La sección 4 del documento lo advierte | Cubierto por diseño |
| **Eliminación / supresión** | **Nada automatizado.** No existe ningún endpoint DELETE sobre `clientes_finales`, `users` ni `tenants`. El único DELETE de la API es el de productos, y es baja lógica (`activo = false`) | Hoy exige una intervención manual en la base con el rol propietario | **Pendiente** |
| **Portabilidad** | Cada comprobante se descarga en XML y en RIDE PDF (`/comprobantes/{id}/xml`, `/ride`), y el resumen fiscal se consulta en `/reportes/resumen` | Se puede recomponer la información, comprobante por comprobante | Parcial: no hay exportación única de «todo lo mío» |
| **Retiro de la autorización** | `terminos.registrar_retiro(db, email, canal)` escribe **dos filas nuevas** (una por bandera) con `aceptado = false` y `origen = "RETIRADO:{canal}"`. No borra nada. `consentimiento_vigente()` pasa a devolver `false` | Se ejecuta a mano: no hay endpoint ni comando de CLI que lo invoque | **Parcial** |
| **Oposición** | Mismo canal y mismo registro que el retiro | Manual | Parcial |

### Por qué el retiro añade en vez de borrar

Si el retiro borrara la aceptación previa, se destruiría la prueba de que en su momento sí
hubo consentimiento —justamente lo que hay que poder demostrar si alguien reclama por lo
que se trató **antes** del retiro—. Por eso el histórico queda entero y el estado se
calcula: `consentimiento_vigente()` mira la última fila de cada bandera y exige que esté
aceptada **y** que su hash coincida con el del documento vigente. Un retiro posterior
invalida la aceptación previa aunque esta siga en la tabla; y una aceptación sobre un texto
antiguo tampoco cuenta como vigente. Comprobado en
`tests/test_tienda.py::test_consentimiento_vigente_y_retiro`: tras un checkout y un retiro
quedan cuatro filas y el consentimiento pasa a `false`.

### Dos límites honestos del derecho de supresión

**Primero**, buena parte de estos datos no se puede borrar aunque el titular lo pida,
porque hay una obligación de conservación tributaria de siete años sobre los comprobantes
—y el documento lo dice en su sección 7—. La sección 8 advierte además que retirar la
autorización puede impedir que se sigan emitiendo comprobantes, porque esos datos son
indispensables para el servicio.

**Segundo**, y esto es más incómodo: aunque se borrara una fila de `clientes_finales`, sus
valores seguirían en `audit_log`, que es inmutable por decisión de arquitectura y no
enmascara la identificación, el correo ni el teléfono. Cualquier procedimiento de supresión
que se escriba tiene que decidir explícitamente qué hace con eso —anonimizar no es una
opción sobre una tabla que no admite UPDATE— y no se puede resolver improvisando el día
que llegue la primera solicitud.

---

## 7. Trazabilidad de los accesos internos a datos personales

Mirar la ficha de un cliente **es** un acceso a datos personales y se trata como tal.

- **Abrir una ficha** exige motivo escrito y deja fila `SA_FICHA` en `audit_log` con el
  actor real, su rol, el tenant y el motivo. Está dentro de la propia función
  `sa_ficha_cliente()` (migración `0005`): el registro no depende de que el código de la
  API se acuerde de escribirlo. Evidencia:
  `tests/test_superadmin.py::test_abrir_ficha_queda_auditado`.
- **La impersonación** —entrar al panel como si se fuera el inquilino— exige motivo de al
  menos 10 caracteres y queda registrada **dos veces**:
  1. La **sesión** en `impersonaciones`, con operador, inquilino, motivo, IP, user agent,
     inicio y fin. Es una sesión y no un evento suelto porque sin el cierre no se sabe
     cuánto duró el acceso a datos ajenos.
  2. **Cada acción** realizada durante esa sesión, en `audit_log`, con el rol **real** del
     operador y un bloque `_impersonacion` que enlaza a la sesión
     (`app/core/audit.py::_make_entry`). Sin ese segundo rastro, lo que hizo soporte
     quedaría registrado como si lo hubiera hecho el propio inquilino, que es
     exactamente lo que no puede pasar en un registro de accesos.
- El token de impersonación dura 30 minutos, no se renueva y concede rol `CLIENTE` sobre
  ese tenant, nunca rol interno. El rol `LECTURA` no puede impersonar.
- Nadie escribe en `audit_log` a mano: no existe endpoint que lo permita
  (`app/api/routes/superadmin.py`, `/auditoria` es solo lectura por diseño).

---

## 8. Lo que falta

Nada de esto está implementado hoy. Se lista aquí para que el registro sea utilizable como
plan de trabajo y no solo como declaración.

| # | Pendiente | Por qué importa |
|---|---|---|
| 1 | **No hay procedimiento automatizado de supresión.** Ningún endpoint, ningún comando de CLI, ninguna tarea. La baja de un titular hoy es SQL manual con el rol propietario | Es el derecho ARCO peor cubierto. Además choca con `audit_log`, que es inmutable: hay que decidir qué se hace con la copia que queda ahí antes de recibir la primera solicitud |
| 2 | **No hay purga por plazo de conservación.** Los dos únicos trabajos periódicos son `barrer-comprobantes-atascados` (cada 10 min) y `barrer-buzones-callados` (diario); ninguno borra nada. Los plazos de la sección 7 del documento están **declarados, no automatizados** | Prometer «siete años» y conservar indefinidamente es una promesa incumplida en la dirección contraria a la habitual, pero incumplida |
| 3 | **El retiro del consentimiento no se puede pedir desde ningún lado.** `registrar_retiro` existe y funciona, pero solo se invoca desde una sesión de Python | El documento promete atender el retiro «por WhatsApp o por correo»; hoy depende de que alguien del equipo ejecute la función a mano |
| 4 | **`consentimiento_vigente()` no se consulta en ningún flujo.** Solo aparece en las pruebas | Un retiro queda registrado pero **no bloquea nada por sí solo**. Conviene decidir dónde se comprueba: al menos al reactivar una cuenta y antes de una campaña de avisos |
| 5 | **No hay pantalla ni endpoint para consultar las constancias.** La política RLS permite al personal interno leer `aceptaciones_terminos`, pero el panel interno no la muestra y ninguna ruta la expone | La prueba existe pero solo se alcanza por SQL. Ante un requerimiento, eso es lento y propenso a error |
| 6 | **El texto de la casilla está duplicado** entre `terminos.TEXTO_CASILLA` y la etiqueta escrita a mano en `Checkout.tsx` | Dos frases que deberían ser una. No afecta a la constancia, que versiona el documento, pero es una divergencia que crece sola |
| 7 | **El aviso de cambio de versión (sección 9) es manual** | El documento compromete a avisar por el mismo chat antes de que la versión nueva entre en vigor. No hay tarea que lo dispare |
| 8 | **Dominio definitivo sin confirmar** (`APP_DOMAIN` vacío; las maquetas usan tres distintos) | El dominio aparece en el aviso de tratamiento, en los correos y en la dirección del buzón de cada inquilino. En producción es un error de arranque, así que no llegará a desplegarse en blanco, pero bloquea la publicación del aviso |
| 9 | **No hay certificado `.p12` real todavía** | Sin él no se ha probado la actividad A2 de punta a punta contra el ambiente de producción del SRI |
| 10 | **Faltan las credenciales de Meta** (`WA_APP_SECRET`, `WA_ACCESS_TOKEN`, `WA_PHONE_NUMBER_ID`) | Sin ellas la actividad A3 no opera. Cuando operen, Meta pasa a ser encargado con transferencia internacional y debe quedar reflejado en el aviso de tratamiento |
| 11 | **Falta contratar el proveedor de correo entrante del buzón** | Será encargado del tratamiento sobre documentos fiscales de terceros. La guía de puesta en marcha está en `deploy/scripts/buzon-sri-puesta-en-marcha.md`; la decisión de proveedor y el contrato, no |
| 12 | **El análisis de documentos con IA no tiene proveedor conectado.** `analisis_ia` cuenta consumos y `registrar_analisis_ia` descuenta cupo, pero el único origen que hoy escribe filas es el buzón, y lo hace exento (`consume=false`). No hay ninguna llamada saliente a un servicio de IA en el código | Cuando se conecte, aparece un encargado nuevo, probablemente con transferencia internacional, y una finalidad nueva en esta tabla. Hoy declararla sería falso |
| 13 | **El despliegue en el VPS no se ha hecho.** Con él llegan TLS, HSTS, la retención de 12 meses de los logs y los respaldos cifrados | Varias medidas de seguridad del tratamiento están escritas en `deploy/` pero no en funcionamiento |
| 14 | **No hay vía para rectificar los datos del propio inquilino.** Ni endpoint, ni función `sa_*`, ni comando de CLI: hoy es SQL manual con el rol propietario, igual que la supresión | El derecho de rectificación se promete en la sección 8 del documento de términos y solo está cubierto para los clientes finales del inquilino |
| 15 | **`impersonaciones` no es inmutable.** El rol de la aplicación tiene `GRANT SELECT, INSERT, UPDATE` (migración `0005`) porque el cierre de sesión escribe `terminada_at`, y no hay trigger que acote qué columnas se pueden tocar | Es el registro de los accesos a datos de un inquilino hecho por personal interno. Que el motivo, el actor o las fechas se puedan reescribir debilita justo la evidencia que sostiene la sección 7. La opción razonable es un trigger que permita únicamente pasar `terminada_at` de nulo a una fecha |

---

## 9. Mantenimiento de este registro

Este documento se revisa y se vuelve a fechar cuando ocurra cualquiera de estas cosas:

- Se añade una finalidad nueva o se amplía una existente.
- Se conecta un encargado nuevo (Meta, proveedor de correo entrante, pasarela de pago,
  proveedor de IA) o cambia el país donde trata los datos.
- Sube la versión del documento de términos: la sección 4 debe reflejar la versión vigente.
- Se cierra cualquiera de los quince pendientes de la sección 8.

Referencias cruzadas: [SECURITY.md](../SECURITY.md) para el mapeo OWASP,
[matriz-roles-accesos.md](matriz-roles-accesos.md) para quién accede a qué, y el
[procedimiento de gestión de incidentes](procedimiento-gestion-incidentes.md) (documento 5)
para la notificación de brechas que exige la LOPDP.
