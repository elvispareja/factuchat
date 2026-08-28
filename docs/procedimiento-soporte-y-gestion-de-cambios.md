# Procedimiento de soporte y gestión de cambios — Factuchat

Versión 1.0 · Fases 1–7 · Documento 7 de 7 · Evidencia ISO 9001.
Actualizar al cerrar cada fase y al aprobar los tiempos de respuesta.

Este documento describe **lo que el repositorio hace hoy**. Donde algo todavía no
existe, se dice que no existe y por qué importa. Un procedimiento que promete
controles inexistentes no sirve como evidencia: sirve como hallazgo en contra.

---

# Parte 1 — Soporte

## 1.1 Planes vigentes

Los cupos y precios salen de `backend/app/services/planes.py`
(`LIMITES_POR_PLAN`), que es la **semilla** con la que se siembran los planes en
la base. Una vez sembrados, el superadmin los edita con vigencia futura, así que
la tabla de abajo es el punto de partida, no un valor inmutable.

| Plan | Precio/mes | Comprobantes | Análisis IA | Clientes | Productos | Números WhatsApp | Acumula |
|---|---|---|---|---|---|---|---|
| Inicial | $2.99 | 10 | 0 | 20 | 10 | 1 | No |
| Independiente | $5.99 | 30 | 20 | 100 | 100 | 1 | No |
| Emprendedor | $9.99 | 80 | 40 | 200 | 200 | 1 | Sí |
| Empresario | $24.99 | 250 | 100 | Ilimitados | Ilimitados | 2 | Sí |

Funciones por plan (mismas banderas del código):

| Función | Inicial | Independiente | Emprendedor | Empresario |
|---|---|---|---|---|
| Bandeja de retenciones (`archivos`) | No | Sí | Sí | Sí |
| Control de inventario (`stock`) | No | No | Sí | Sí |
| Tienda interna (`tienda`) | No | No | No | Sí |
| Carga masiva (`masivo`) | No | No | No | Sí |
| Mensajes de voz (`voz`) | No | No | No | Sí |

Estos cupos **no son decorativos**: se aplican en el servidor. `exigir_funcion`,
`exigir_cupo_clientes`, `exigir_cupo_productos` y `exigir_cupo_comprobantes`
lanzan `LimitePlanError` con el mensaje que ve el usuario, y el panel solo pinta
el estado que la API le devuelve. Está probado en
`tests/test_planes.py::TestGatingEnServidor`. Esto importa para soporte porque
**un cliente que reporta "no me deja guardar un producto" casi siempre está
topando su plan, no ante una falla**: el primer paso del diagnóstico es mirar
`/api/v1/panel/estado` —que es lo que devuelve `resumen_para_frontend`: cupos,
usados, restantes, topes de clientes y productos y las banderas de función— y
comparar contra esta tabla.

## 1.2 Qué promete la landing y qué respalda el sistema

La maqueta de la landing (`diseno/Facturas IA.dc.html`, líneas 1497 y 1498)
ofrece dos cosas **solo en el plan Empresario**:

- "Asesoría por videollamada incluida"
- "Soporte prioritario"

Y el resumen del plan en `docs/spec-landing.json` (línea 184) repite:
*"Facturación masiva, 3 usuarios y soporte prioritario."*

**Pendiente, y hay que decirlo claro:** `LIMITES_POR_PLAN` no tiene ninguna
bandera de soporte prioritario ni de videollamada, y la tupla `FUNCIONES` del
mismo archivo solo enumera `stock`, `tienda`, `voz`, `masivo` y `archivos`. Es
decir: **la prioridad del plan tope hoy la sostienen las personas del equipo, no
el sistema.** No hay un campo que la cola de soporte pueda leer, ni una prueba
que la verifique, ni forma de auditar después si se cumplió.

Mientras eso siga así, este procedimiento es el único lugar donde la prioridad
está escrita, y por eso la tabla de tiempos de la sección 1.5 es de cumplimiento
manual. El trabajo concreto que lo volvería verificable es añadir la bandera al
plan (junto a `tienda` o `masivo`), exponerla en `resumen_para_frontend` y
cubrirla con un test igual que el resto del gating.

Hay además una diferencia que conviene resolver antes de publicar nada: la
landing dice "3 usuarios para tu equipo" en el plan Empresario, mientras que la
semilla define `nums: 2`. No son lo mismo —`nums` es la cantidad de números de
WhatsApp, no de usuarios— y hoy no existe en el código ningún cupo de usuarios
por tenant. Conviene aclararlo con el dueño del producto antes de que un cliente
lo reclame.

## 1.3 Canales y horario

**Horario de atención.** La fuente es `contacto_horario` en
`backend/app/core/config.py` (línea 62), con el valor
**"Lunes a sábado, de 07:00 a 21:00."**. Se sirve al público por
`GET /api/v1/publico/config` (`backend/app/api/routes/publico.py`, campo
`horario`).

Que viva en la configuración y no en el bundle del frontend es deliberado: las
maquetas se contradecían —la agenda del checkout decía L–S 07:00–21:00 y la
pantalla de confirmación decía L–D 09:00–19:00 (`docs/spec-landing.json`, línea
539)—. El comentario del propio `config.py` deja constancia de que manda la
agenda, porque es la que salta los domingos. Con el horario en configuración,
cambiarlo es editar el `.env`, no recompilar y volver a desplegar el frontend.

**Con una salvedad que hoy rompe la fuente única:** `frontend/src/landing/Checkout.tsx`
(línea 544) lleva el mismo texto escrito a mano como valor de respaldo
—`{config?.horario ?? "Lunes a sábado, de 07:00 a 21:00."}`—. Si se cambia el
horario en el `.env` y la llamada a `/publico/config` falla o llega vacía, el
checkout sigue mostrando el horario viejo compilado en el bundle. Eliminar ese
literal es parte de lo que hay que cerrar.

Nota menor pero real: la sección de contacto de `frontend/src/landing/Landing.tsx`
pinta correo, teléfono y ubicación, pero **no muestra el horario** aunque la API
lo devuelva. Publicarlo es parte de lo que hay que aprobar.

**Zona horaria.** El worker de Celery corre en `America/Guayaquil`
(`backend/app/worker.py`). Todos los tiempos de este documento se cuentan en esa
zona.

| Canal | Dónde está | Estado |
|---|---|---|
| WhatsApp | `contacto_telefono` = 099 337 1891 · `contacto_telefono_e164` = +593993371891 (`config.py`) | Configurado. Falta el número productivo de Meta. |
| Correo | `email_info` → `info@{dominio}` · `email_ventas` → `ventas@{dominio}` (propiedades de `Settings`) | Direcciones **derivadas del dominio, que aún no está confirmado**. |
| Formulario web | `POST /api/v1/publico/contacto` | Funciona y está probado. |
| Asistente de WhatsApp | Opción "Hablar con un asesor" del `MENU_PRINCIPAL` | **Ofrecida pero sin implementar.** Ver abajo. |

**El formulario web es el canal más sólido que hay hoy**, y conviene entender
por qué. `POST /publico/contacto` guarda la consulta en `solicitudes_contacto`,
devuelve un enlace de WhatsApp con el mensaje ya redactado, y encola
`aviso_solicitud` (`backend/app/tasks/notificaciones.py`), que envía un correo a
`email_ventas`. Ese aviso vive en un task aparte a propósito: quien está en el
formulario no debe esperar al SMTP ni ver un error si el correo falla —su
consulta ya está guardada—, y el aviso se reintenta solo hasta ocho veces con
backoff hasta 30 minutos. La marca `avisado_at` se escribe **después** del envío,
de modo que un reintento posterior a un correo que sí salió no manda un segundo
aviso. El formulario tiene rate limit de 5 envíos por IP cada 15 minutos
(`_limitar`), probado en `tests/test_tienda.py::test_rate_limit_del_formulario_publico`.

**Pendiente en el asistente de WhatsApp.** El menú principal
(`backend/app/whatsapp/conversacion.py`, línea 115) ofrece
`("asesor", "Hablar con un asesor", "Una persona del equipo te atiende")`, pero
el despachador `_por_accion` de `backend/app/whatsapp/asistente.py` no tiene
ninguna rama para `"asesor"`: la acción cae al `return [conv.MENU_PRINCIPAL]`
final. En la práctica, **el cliente que pide hablar con una persona recibe otra
vez el menú**. Es el hueco de soporte más visible del producto y hay que
cerrarlo antes de abrir el canal a clientes reales.

## 1.4 Severidades

Las severidades se definen por **el daño al cliente**, no por lo difícil que sea
arreglarlo. Los ejemplos son situaciones reales de este producto, con el archivo
donde vive el mecanismo.

| Sev | Definición | Ejemplos concretos de Factuchat |
|---|---|---|
| **S1 — Crítica** | Nadie puede facturar, o hay riesgo fiscal o de datos. | El circuit breaker hacia el SRI quedó abierto y la cola de emisión está en pausa (`backend/app/sri/client.py`). La API no responde. Sospecha de acceso indebido a datos de un inquilino. Un `.p12` comprometido. |
| **S2 — Alta** | Un inquilino no puede emitir, o un número fiscal sale mal. | Certificado caducado o de otro RUC, que `backend/app/services/certificados.py` rechaza al subirlo. Un comprobante atascado que el barrido de `barrer_atascados` no destrabó. Una retención verificada que no está bajando el IVA a pagar. Cupo de plan mal contado. |
| **S3 — Media** | Molesta pero hay cómo seguir trabajando. | El RIDE no le llegó al comprador por correo (el reintento propio de `correo_enviado_at` suele resolverlo). Un cliente final guardado con la cédula mal escrita. Un XML del buzón que llegó y no se pudo parsear. |
| **S4 — Baja** | Consulta, configuración o mejora. | Cómo configurar el reenvío del SRI hacia la dirección del buzón. Cómo se usa la carga masiva. Cambio de plan. Dudas de facturación de su suscripción. |

Regla de clasificación: **ante la duda entre dos niveles, sube.** Bajar la
severidad de un caso que resultó ser grave cuesta mucho más que atender de más
uno que no lo era.

Regla adicional: **todo lo que huela a incidente de seguridad o de datos
personales entra como S1 y sale de este procedimiento.** Se atiende por el
[procedimiento de gestión de incidentes](procedimiento-gestion-incidentes.md)
(documento 5), incluida la notificación LOPDP.

## 1.5 Tiempos de respuesta y resolución

> **ESTOS TIEMPOS SON UN COMPROMISO A APROBAR.** Salvo la excepción que se
> señala abajo, **no están publicados en ninguna parte del producto** ni pactados
> con ningún cliente. Ninguno se cumple ni se mide automáticamente: no hay
> panel de soporte, no hay reloj y no hay bandera de plan que los distinga.
> Requieren la aprobación explícita del dueño del producto antes de publicarse,
> y una vez publicados dejan de ser una intención y pasan a ser una obligación
> contractual.

**Lo único ya publicado.** La landing dice, textualmente, *"¿Qué podemos hacer
por ti? Escríbenos y te respondemos el mismo día."*
(`frontend/src/landing/Landing.tsx`, línea 692, y `docs/spec-landing.json`, línea
2055). Ese "el mismo día" **ya está prometido a todo el que entre a la web, sin
distinción de plan**, y aplica al formulario de contacto. Cualquier tabla que se
apruebe tiene que ser compatible con esa frase o hay que cambiar la frase.

**Primera respuesta** (una persona contesta y confirma que está en ello). Se
cuenta dentro del horario de atención:

| Sev | Inicial | Independiente | Emprendedor | Empresario |
|---|---|---|---|---|
| S1 | 4 h | 4 h | 2 h | 1 h |
| S2 | 8 h | 8 h | 4 h | 2 h |
| S3 | 1 día hábil | 1 día hábil | 1 día hábil | 4 h |
| S4 | 2 días hábiles | 2 días hábiles | 1 día hábil | 1 día hábil |

**Resolución objetivo** (el cliente puede volver a trabajar; puede ser un rodeo
temporal mientras la corrección definitiva sale por la Parte 2):

| Sev | Inicial | Independiente | Emprendedor | Empresario |
|---|---|---|---|---|
| S1 | 8 h | 8 h | 6 h | 4 h |
| S2 | 2 días hábiles | 2 días hábiles | 1 día hábil | 8 h |
| S3 | 5 días hábiles | 5 días hábiles | 3 días hábiles | 2 días hábiles |
| S4 | Siguiente versión | Siguiente versión | Siguiente versión | Siguiente versión |

Dos aclaraciones honestas sobre esta tabla:

1. **Las S1 no se diferencian de verdad por plan.** Si el SRI no responde o la
   API está caída, están caídos todos los inquilinos a la vez y se arregla para
   todos al mismo tiempo. La columna del plan Empresario refleja a quién se le
   avisa primero, no a quién se le arregla primero.
2. **El reloj se detiene mientras el caso espera al cliente** (falta su `.p12`,
   falta que confirme un dato, falta que configure el reenvío del SRI) y
   mientras dependa de un tercero fuera de nuestro control —el SRI o Meta—. Esa
   pausa debe quedar anotada en el caso, o el tiempo medido no significa nada.

## 1.6 Escalamiento

| Paso | Quién | Cuándo | Qué puede hacer |
|---|---|---|---|
| 1 | Rol `LECTURA` | Entrada de todos los casos | Ver el panel interno, buscar el inquilino, leer auditoría. **No actúa**: por diseño, mira. |
| 2 | Rol `SOPORTE` | S3–S4, y S2 que se resuelvan mirando | Dar de alta clientes, suspender o reactivar inquilinos, abrir la ficha con motivo, impersonar. |
| 3 | Rol `SUPERADMIN` | S1, y todo lo que toque configuración o dinero | Todo lo anterior más precios de planes, tarifas, códigos promocionales y el flag `BUZON_ACTIVO`. 2FA TOTP obligatorio. |
| 4 | Cambio de código | Cuando no hay arreglo operativo | Entra a la Parte 2. Ningún arreglo llega a producción saltándose la puerta de calidad, ni siquiera en una S1. |

Esta escalera no es una convención de equipo: **está aplicada en el servidor**.
`backend/app/api/routes/superadmin.py` define `SOLO_LECTURA` y `PUEDE_ACTUAR`
con `require_roles`, y `sa_verificar_rol()` comprueba el rol **real en la base de
datos**, no el que venga en el token. Está probado en
`tests/test_superadmin.py::TestRolesYAuditoria`,
`::test_lectura_no_puede_actuar` y `::test_solo_superadmin_cambia_precios`.

El detalle de qué puede cada rol está en el documento 3,
[matriz-roles-accesos.md](matriz-roles-accesos.md), y no se duplica aquí para que
no se desincronicen.

## 1.7 Caso especial: entrar en la cuenta de un cliente (impersonación)

Es la herramienta más potente de soporte y la más peligrosa: permite ver los
datos fiscales y los clientes finales de un negocio ajeno. Por eso tiene reglas
propias, y todas están en el código —`backend/app/services/impersonacion.py`—,
no en la buena voluntad del operador.

| Regla | Cómo se aplica | Por qué |
|---|---|---|
| Solo `SOPORTE` y `SUPERADMIN` | `ROLES_PERMITIDOS`; `LECTURA` queda fuera | Quien solo mira no necesita entrar. Probado en `::test_lectura_no_puede_impersonar`. |
| Motivo obligatorio, mínimo 10 caracteres | Validación en `iniciar()` | Un motivo vacío convierte la auditoría en ruido. Probado en `::test_motivo_obligatorio`. |
| Dura 30 minutos | `MINUTOS_IMPERSONACION = 30` | Soporte entra, mira lo que necesita y sale. |
| **No se renueva** | El token es de tipo `impersonacion` y el flujo de refresh no lo acepta | Si pudiera renovarse, "30 minutos" no significaría nada. |
| Da rol `CLIENTE`, nunca rol interno | `rol=Rol.CLIENTE.value` en `create_access_token` | Entrar a una cuenta no es llevarse los permisos internos. Probado en `::test_el_token_no_da_acceso_al_panel_interno`. |
| **Doble rastro** | (1) fila en `impersonaciones` con actor, tenant, motivo, inicio y fin; (2) cada acción auditada con el **actor real** | Sin el segundo rastro, lo que hizo el operador quedaría registrado como si lo hubiera hecho el propio inquilino. Probado en `::test_doble_rastro`. |
| Aviso visible mientras dura | La API devuelve `aviso`: "Estás viendo la cuenta de {razón social} como soporte · toda acción queda en auditoría" | El operador tiene que saber en todo momento que no está en su propia sesión. |
| Una sola sesión abierta por operador | `iniciar()` cierra las que quedaron abiertas antes de abrir otra | Ninguna sesión queda eterna por olvido. |
| Las caducadas sin cerrar se listan | `caducadas_sin_cerrar()` | El panel las muestra para que quede claro que ya no están abiertas de verdad. |

Salir es idempotente: `terminar()` llamado dos veces no es un error, y solo el
operador dueño de la sesión puede cerrarla.

**Regla de procedimiento que complementa al código:** el motivo escrito debe
citar el caso de soporte que lo justifica. La auditoría prueba *que* alguien
entró; solo el motivo explica *por qué*, y es lo único que un auditor —o la
autoridad de protección de datos— puede leer después.

Abrir la ficha de un cliente sin impersonar también exige motivo y también se
audita (`sa_ficha_cliente()`, migración `0005`, probado en
`::test_abrir_ficha_queda_auditado`): es un acceso a datos personales y la LOPDP
no distingue entre mirar y actuar.

## 1.8 Lo que falta para operar soporte de verdad

| Falta | Evidencia | Consecuencia |
|---|---|---|
| La sección **Soporte** del panel interno no está construida | `frontend/src/interno/PanelInterno.tsx`: `{(seccion === "pagos" \|\| seccion === "soporte") && <EnConstruccion .../>}` | No hay cola de casos, ni estados, ni "señales de abandono" (lo pedía PLAN.md 4.1). Hoy los casos se llevarían fuera del sistema. |
| La opción "Hablar con un asesor" no está implementada | `asistente.py`, sin rama para `"asesor"` en `_por_accion` | El cliente que la elige recibe otra vez el menú. |
| No hay bandera de soporte prioritario por plan | `planes.py`, `LIMITES_POR_PLAN` y `FUNCIONES` | La promesa del plan Empresario no es verificable ni auditable. |
| Nadie recibe alertas activas | `SECURITY.md`, A09: presupuesto de WhatsApp y rechazos del SRI en ráfaga marcados ⚠️ | Soporte se entera de un problema masivo cuando llama el primer cliente, no antes. |
| Las direcciones de correo no son definitivas | `config.py`, `dominio_publico` cae a `factuchat.ec` mientras `APP_DOMAIN` esté vacío | `info@` y `ventas@` cambiarán cuando se confirme el dominio. |

---

# Parte 2 — Gestión de cambios

## 2.1 Punto de partida: el control de versiones

Antes de describir cómo se aprueba una versión hay que decir en qué estado está
el control de versiones, porque **todo lo demás depende de esto**.

El repositorio tiene **un solo commit** (`214b4c8 "primer cambio antes del
codigo"`) con **seis archivos** (`git ls-tree -r HEAD`): `PLAN.md`, las tres
maquetas de `diseno/` y dos logotipos. `git ls-files` devuelve **siete**, porque
`deploy/scripts/instalar-servidor.sh` ya está añadido al índice sin commitear
—`git status` lo muestra como `AM`, no como `??`—. Todo lo demás —`backend/`,
`frontend/`, el resto de `deploy/`, `docs/`, `SECURITY.md`,
`.pre-commit-config.yaml`— figura como **no rastreado** en `git status`.

Esto tiene tres consecuencias que un auditor va a encontrar de inmediato:

1. **No existe "la versión aprobada".** Sin commits no hay nada que aprobar, ni
   forma de decir qué código está en producción.
2. **La afirmación de `SECURITY.md` (A08) "Despliegue solo desde el
   repositorio" no se puede cumplir todavía**, porque en el repositorio no está
   el código que habría que desplegar.
3. **La marcha atrás de la sección 2.7 no funciona.** Se apoya en reconstruir
   una versión anterior; sin historia, no hay versión anterior a la que volver.

El gancho de pre-commit **sí está instalado** (`.git/hooks/pre-commit`, generado
por `pre-commit`), así que la puerta de calidad se disparará en cuanto haya
commits. **El primer cambio de este procedimiento, y el que habilita todos los
demás, es versionar el código.**

## 2.2 La puerta de calidad

Es la misma en los tres sitios donde se invoca —`deploy/scripts/check.sh`,
`deploy/scripts/check.ps1` y `.pre-commit-config.yaml`— y corre **dentro del
contenedor `api`**, sobre el Python 3.12 de producción. No sobre el Python del
equipo de quien programa: una prueba que pasa en una versión distinta de la que
se despliega no prueba lo que hace falta.

| # | Paso | Comando exacto | Qué defiende |
|---|---|---|---|
| 1 | Lint | `ruff check app tests` | Errores, imports, bugbear, pyupgrade, nombres, comprehensions, `print` sueltos y **la regla de seguridad `S` (bandit)** — es lo que sostiene la casilla A05 de `SECURITY.md`. |
| 2 | Formato | `ruff format --check app tests` | Formato único (línea de 100). `--check` no reescribe: falla, para que el arreglo entre como cambio y no en silencio. |
| 3 | Tipos | `mypy app` | `check_untyped_defs`, `no_implicit_optional`, `warn_unused_ignores`, `warn_redundant_casts`. Excluye `alembic/`. |
| 4 | Pruebas | `pytest` | 271 pruebas contra PostgreSQL real con RLS. Ver 2.3. |
| 5 | Dependencias Python | `pip-audit -r requirements.txt --disable-pip --no-deps` | Vulnerabilidades conocidas en lo que se instala en producción (A03). |
| 6 | Dependencias frontend | `npm --prefix frontend audit --audit-level=high` | Igual, del lado del panel. |
| 7 | Secretos | Hook `no-env-files` (`language: fail`) | Bloquea cualquier `.env` que no sea `.env.example`. No analiza: rechaza. Es la defensa de A02 contra el error más caro y más común. |

Los pasos 1 a 6 corren también en `check.sh` / `check.ps1`, que además levantan
el entorno (`docker compose up -d --build postgres redis api`) y terminan con
`TODO VERDE`. Ambos scripts abortan al primer fallo (`set -euo pipefail` en bash,
comprobación de `$LASTEXITCODE` en PowerShell): **no hay forma de que un paso
rojo pase inadvertido porque el siguiente salió verde**.

El hook 7 no está en los scripts porque solo tiene sentido sobre lo que se está
por commitear.

## 2.3 Las 271 pruebas

Contadas con `pytest --collect-only -q` dentro del contenedor y ejecutadas
completas al redactar este documento: **271 pruebas, las 271 en verde**
(`pytest -q`, código de salida 0).

| Archivo | Pruebas | Qué cubre |
|---|---|---|
| `test_buzon.py` | 56 | Buzón SRI: propiedad por dirección, XXE, deduplicación, cifrado, verificación ante el SRI |
| `test_whatsapp.py` | 38 | Webhook firmado, conversación, avisos, consumo |
| `test_tienda.py` | 28 | Tienda interna, landing pública, checkout, términos |
| `test_emision.py` | 23 | Emisión de punta a punta, idempotencia, fallos de canal |
| `test_superadmin.py` | 19 | Roles internos, impersonación, precios con vigencia |
| `test_reportes.py` | 18 | Reportes y resumen fiscal |
| `test_auth.py` | 14 | Login, 2FA, rate limit, bloqueo progresivo, rotación de refresh |
| `test_planes.py` | 13 | Gating por plan decidido en servidor |
| `test_rls.py` | 12 | Aislamiento entre inquilinos, por API y por SQL directo |
| `test_carga_masiva.py` | 9 | Carga masiva en dos pasos |
| `test_calculos.py` | 9 | Cálculo de impuestos y totales |
| `test_certificados.py` | 8 | Validación y cifrado del `.p12` |
| `test_xml_builder.py` | 7 | Construcción del XML del SRI |
| `test_clave_acceso.py` | 6 | Clave de acceso y dígito verificador |
| `test_audit.py` | 5 | Bitácora y enmascaramiento de secretos |
| `test_firma.py` | 4 | Firma XAdES-BES |
| `test_admin.py` | 2 | Funciones administrativas |
| **Total** | **271** | |

Lo que hace que estas pruebas valgan como evidencia no es el número, sino
**contra qué corren**. `backend/tests/conftest.py` deja constancia del criterio:
*"los tests corren DENTRO del contenedor api contra el postgres del compose de
desarrollo: así se prueba el RLS de verdad, no un sqlite de juguete."*

En cada sesión de pruebas, el fixture `database`:

1. Borra el esquema `public` completo y lo vuelve a crear.
2. Devuelve los `GRANT USAGE` a `factuchat_app` y `factuchat_security`.
3. Corre `command.upgrade(Config("alembic.ini"), "head")`.
4. Siembra tenants, usuarios y planes.

Esto tiene una consecuencia que conviene subrayar: **las migraciones hacia
adelante se ejercitan enteras en cada corrida del `check`**, desde base vacía
hasta `head`. Una migración que no aplica limpia no llega ni a discutirse.

Y como la conexión de las pruebas usa `factuchat_app` —el rol `NOBYPASSRLS`— las
pruebas de aislamiento comprueban el RLS que va a correr en producción, no una
simulación en la capa de aplicación.

## 2.4 Migraciones: ida y vuelta

Hay nueve migraciones, `0001_nucleo` a `0009_buzon_sri`, y **las nueve tienen un
`downgrade()` con contenido real**: ninguna es un `pass` de compromiso. Eso
importa porque una migración sin marcha atrás convierte cualquier despliegue
fallido en una restauración desde respaldo.

**La ida está automatizada; la vuelta no.** No hay ninguna prueba que invoque
`downgrade` —está verificado: `downgrade` no aparece en todo `backend/tests/`—,
así que la vuelta es un **paso manual obligatorio** de este procedimiento cuando
un cambio incluye migración:

```bash
# Con el entorno de desarrollo levantado, desde la raíz del repo
C="deploy/docker-compose.dev.yml"
docker compose -f $C exec -T api alembic upgrade head
docker compose -f $C exec -T api alembic downgrade -1
docker compose -f $C exec -T api alembic upgrade head
docker compose -f $C exec -T api pytest -q     # tiene que seguir en 271 verdes
```

Si el `downgrade -1` falla o deja el esquema en un estado del que `upgrade` ya
no sale, **la migración no está lista** y el cambio no pasa la puerta.

## 2.5 Qué NO cubre la puerta hoy

Decirlo es parte del control. Estos son huecos verificados, no hipótesis:

| Hueco | Evidencia | Riesgo |
|---|---|---|
| **El frontend no se compila en la puerta** | Ni `check.sh`, ni `check.ps1`, ni `.pre-commit-config.yaml` ejecutan `npm run build` ni `npm run lint`; solo `npm audit`. Ambos scripts existen en `frontend/package.json` (`build` = `tsc -b && vite build`, `lint` = `tsc -b --noEmit`). | Un error de TypeScript no lo detiene nadie hasta el despliegue. Cerrarlo es añadir un paso más a los tres archivos. |
| La marcha atrás de migraciones no está automatizada | Ver 2.4 | Depende de que quien despliega ejecute el paso manual. |
| No hay escaneo de imágenes ni digests fijados | `SECURITY.md` A03 marca trivy y digests como 🔜; `deploy/.env.example` (líneas 38-40) trae `nginx:1.27-alpine`, `postgres:16` y `redis:7-alpine` | El compose permite fijar la imagen por `.env`, pero hoy son **etiquetas**, no digests (`imagen@sha256:…`): una etiqueta cambia de contenido sin avisar. Faltan las dos cosas, fijar el digest y pasar trivy antes de subir. |
| No hay CI en servidor | La puerta corre en la máquina de quien programa | Depende de que el gancho de pre-commit esté instalado. Hoy lo está. |

## 2.6 Procedimiento de despliegue

Se apoya en `deploy/docker-compose.prod.yml`, que ya trae el endurecimiento del
paso 2 de PLAN.md: `no-new-privileges`, `cap_drop: ALL`, sistemas de archivos de
solo lectura con `tmpfs` para lo efímero, límites de CPU y memoria, rotación de
logs, y `postgres` y `redis` en una red marcada `internal: true` —que Docker deja
sin salida a internet y sin puertos publicables, de modo que ni un `ports:`
añadido por error los expondría—.

| # | Paso | Detalle |
|---|---|---|
| 1 | Puerta de calidad en verde | `deploy/scripts/check.sh` (o `.ps1`) hasta `TODO VERDE`. Sin esto no se sigue. |
| 2 | Ida y vuelta de migraciones | Solo si el cambio trae migración. Sección 2.4. |
| 3 | Compilar el frontend | `npm --prefix frontend run build`. **Paso manual**: no está en la puerta (2.5). |
| 4 | Fijar la versión | `FACTUCHAT_VERSION` en el `.env` de producción etiqueta la imagen `factuchat/backend:${FACTUCHAT_VERSION}`. Es la palanca de la marcha atrás: **una etiqueta nueva por despliegue, nunca `latest`**. |
| 5 | **Respaldo** | `deploy/scripts/respaldo.sh`. Sección 2.8. Antes de tocar la base, siempre. |
| 6 | Construir y levantar | `docker compose -f deploy/docker-compose.prod.yml up -d --build` |
| 7 | Migrar | `alembic upgrade head` con el rol **propietario** (`DATABASE_URL_ADMIN`), nunca con el de la aplicación. No corre solo: el `CMD` de la imagen de producción es únicamente `uvicorn`, así que migrar es una decisión explícita de quien despliega. |
| 8 | Verificar salud | El servicio `api` tiene healthcheck contra `/api/v1/health` (15 s, 5 reintentos, 40 s de gracia). nginx espera a que esté sano: sin eso, los primeros clientes verían errores contra una API que todavía migra. |
| 9 | Prueba de humo | Login, emitir un comprobante de prueba, ver que el RIDE se genera y que la bitácora registró la acción. |
| 10 | Anotar | Versión, fecha, quién desplegó, migraciones aplicadas y dónde quedó el respaldo del paso 5. |

**Pendiente de despliegue, verificado:** el volumen `static` está declarado y
montado de solo lectura en nginx —que sirve el panel desde `/srv/static` con
`try_files $uri /index.html`—, pero **ningún servicio del compose lo llena**: no
hay `frontend/Dockerfile` ni etapa de build del frontend. Publicar el resultado
del paso 3 en ese volumen es trabajo que falta escribir. El endurecimiento del
servidor (paso 1 de la lista de PLAN.md) sí está cubierto por
`deploy/scripts/instalar-servidor.sh`, pero no se ha corrido todavía en ninguna
máquina.

## 2.7 Marcha atrás

El orden importa: **primero el código, después la base, y solo si no queda otra.**

| Situación | Qué se hace |
|---|---|
| Falla sin migración | Poner `FACTUCHAT_VERSION` en la etiqueta anterior y `up -d`. Es el caso barato y el motivo por el que se etiqueta cada versión. |
| Falla con migración reversible | `alembic downgrade -1` con el rol propietario y luego volver a la etiqueta anterior. Solo si la ida y vuelta del paso 2.4 se probó de verdad. |
| Falla con pérdida o corrupción de datos | Restaurar desde el respaldo del paso 5. Es la vía cara y la última. |

Dos reglas que no se negocian:

- **Nunca se edita un XML autorizado para "arreglar" nada.** Son inmutables por
  hash SHA-256 y por un trigger de base de datos (migración `0003`, probado en
  `tests/test_emision.py::test_autorizado_inmutable_en_bd`). Un comprobante mal
  emitido se corrige por los mecanismos del SRI —nota de crédito, anulación—,
  jamás retrocediendo el sistema.
- **`audit_log` no se retrocede.** No tiene `GRANT` de UPDATE ni DELETE, ni
  política que los permita, y un trigger los bloquea (migración `0002`, probado
  en `tests/test_rls.py::test_audit_log_es_inmutable`). Una marcha atrás deja su
  propio rastro; no borra el anterior.

## 2.8 Ninguna migración sin respaldo previo

**Regla:** no se ejecuta `alembic upgrade` en producción sin un respaldo tomado
y **verificado** inmediatamente antes.

El porqué es directo: un `downgrade` que existe no es un `downgrade` que
funciona bajo presión y con datos reales, y hay migraciones —la `0009`, sin ir
más lejos, que reemplaza un UNIQUE global por uno por inquilino— cuya marcha
atrás no puede recuperar lo que la ida transformó. El respaldo es lo único que
convierte un despliegue fallido en un mal rato en lugar de una pérdida.

El respaldo tiene que cubrir dos cosas, no una:

1. La base de datos completa (`pg_dump`).
2. El volumen `comprobantes`, donde viven los XML firmados y los RIDE. El propio
   compose lo advierte: *"una fila de la base que apunte a un fichero que ya no
   existe no sirve de nada"*. Son documentos con valor tributario.

**Cómo se toma.** El script `deploy/scripts/respaldo.sh` cubre exactamente esas
dos cosas: `pg_dump --format=custom` de la base y un `tar` del volumen
`comprobantes` —que, conviene saberlo, es también donde viven los correos
cifrados del buzón (`${STORAGE_DIR}/buzon/…`) y los comprobantes de pago
subidos desde la landing—. Todo se cifra con `age` **en flujo**, sin que el
volcado en claro toque nunca el disco, y usando solo la clave **pública**: la
privada no vive en el VPS, así que el servidor puede crear respaldos pero no
leerlos.

Para el paso 5 de un despliegue basta con invocarlo a mano:

```bash
/opt/factuchat/deploy/scripts/respaldo.sh --verboso
```

Antes de escribir nada comprueba que postgres está corriendo, que el volumen
existe y que hay espacio en disco, y al terminar deja un `manifiesto.txt` en
claro con el SHA-256 del contenido descifrado, la revisión de Alembic y las
cuentas de filas de `tenants`, `users`, `comprobantes` y `audit_log`. **Ese
manifiesto es lo que hay que anotar en el registro del paso 10**: la revisión de
Alembic que figura ahí es la prueba de a qué punto exacto se puede volver.

Con `--dry-run` se comprueba toda la configuración sin escribir nada, que es lo
sensato la primera vez que se corre en un servidor nuevo.

**Pendientes reales de esta parte:** el `restaurar.sh` que el script de respaldo
referencia **sí existe** (`deploy/scripts/restaurar.sh`), pero **no se ha
ejecutado nunca en ninguna máquina**: no hay una sola restauración probada ni
documentada, y la verificación completa —descifrar de verdad y pasar
`pg_restore --list`— solo ocurre en corridas manuales con la clave privada fuera
del VPS. El detalle de la retención, el destino externo y la
prueba de restauración mensual es el contenido del documento 4,
[procedimiento-respaldo-restauracion.md](procedimiento-respaldo-restauracion.md).
Mientras `DESTINO_TIPO` sea `ninguno`, el respaldo se queda en el mismo servidor
y el propio script lo advierte en su registro.

## 2.9 Aprobación y registro

| Tipo de cambio | Quién aprueba | Requisito adicional |
|---|---|---|
| Corrección S3–S4, sin migración | Quien programa, con la puerta en verde | — |
| Cambio con migración | Dueño del producto | Ida y vuelta probada (2.4) + respaldo (2.8) |
| Cambio de precios o cupos de plan | Dueño del producto | Se hace **desde el panel, con vigencia futura**, no desplegando código. Un precio con fecha pasada se rechaza (`tests/test_superadmin.py::test_precio_retroactivo_se_rechaza`) y el cambio queda auditado con antes y después. |
| Encender o apagar `BUZON_ACTIVO` | Solo `SUPERADMIN` | Queda en la bitácora inmutable con antes y después (`tests/test_buzon.py::test_alternar_el_flag_queda_auditado`). |
| Corrección de seguridad S1 | Dueño del producto, avisado en el momento | La puerta de calidad **no se salta**. Una corrección apurada que rompe otra cosa deja peor al cliente que el fallo original. |

Los cambios que se aprueban desde el panel —precios, cupos, tarifas, el flag del
buzón— no son despliegues, y esa es exactamente la gracia: **cambiar un precio no
debería exigir tocar código**, y como pasan por funciones `sa_*` auditadas,
dejan mejor rastro que un commit.

---

## Pendientes que afectan a este procedimiento

Todos verificados en el repositorio al momento de escribir:

| Pendiente | Dónde se nota | Bloquea |
|---|---|---|
| **El código no está versionado** (1 commit con 6 archivos; `git ls-files` devuelve 7 porque `instalar-servidor.sh` ya está en el índice) | `git ls-tree -r HEAD` y `git ls-files` | Toda la Parte 2: aprobación de versiones, marcha atrás, "despliegue solo desde el repositorio" (A08). |
| **Dominio definitivo sin confirmar** | `app_domain` vacío en `config.py`; `dominio_publico` cae a `factuchat.ec`; el validador lo exige en producción; las maquetas usan tres dominios distintos | Correos de soporte (`info@`, `ventas@`), direcciones del buzón, enlaces al cliente. |
| **No hay certificado `.p12` real** | `deploy/scripts/emision-prueba-sri.md` lo pide como requisito | La prueba de emisión de punta a punta contra el SRI. |
| **Faltan credenciales de Meta** | `wa_app_secret`, `wa_access_token`, `wa_phone_number_id` vacíos en `config.py` | El canal de WhatsApp, que es el producto entero. |
| **Falta contratar el proveedor de correo entrante** | `buzon_webhook_secret` / `buzon_imap_host` vacíos; el validador exige uno de los dos si `BUZON_ACTIVO` | El buzón SRI, hoy apagado por defecto. |
| **El VPS no se ha desplegado** | `deploy/scripts/instalar-servidor.sh`, `respaldo.sh` y `restaurar.sh` existen y pasan shellcheck, sin correr en ninguna máquina | Todo lo de la sección 2.6 está escrito pero sin ejecutar ni una vez. |
| **Sección Soporte del panel sin construir** | `PanelInterno.tsx` → `EnConstruccion` | La operación de la Parte 1. |
| **Ninguna restauración probada** | `deploy/scripts/restaurar.sh` está escrito, pero nadie lo ha corrido ni queda evidencia de una restauración | La marcha atrás por restauración (2.7) está escrita y no verificada: no se sabe cuánto tarda ni si aguanta con datos reales. |
| **Frontend fuera de la puerta de calidad** | `check.sh`, `check.ps1`, `.pre-commit-config.yaml` | Errores de compilación llegan al despliegue. |

---

Documentos relacionados: [matriz-roles-accesos.md](matriz-roles-accesos.md)
(documento 3, quién puede qué), [procedimiento-respaldo-restauracion.md](procedimiento-respaldo-restauracion.md)
(documento 4, del que depende la regla 2.8), [SECURITY.md](../SECURITY.md)
(mapeo OWASP, el índice de qué controles existen y dónde) y
[README.md](README.md) (índice de los 7 documentos).

Un caso S1 de seguridad no se resuelve aquí: escala a `SUPERADMIN` y se sigue el
[documento 5](procedimiento-gestion-incidentes.md), gestión de incidentes con
notificación LOPDP, que ya está escrito. Lo que sigue pendiente es que
[README.md](README.md) lo marca todavía como «Pendiente»; hay que corregir ese
estado para que el índice no contradiga al documento.
