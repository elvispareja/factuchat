# Buzón SRI — puesta en marcha (fase 7)

Qué hace: cada inquilino recibe una dirección `{su RUC}@{dominio del buzón}`. Los
comprobantes que sus proveedores reenvían ahí se leen, se deduplican, se guardan
cifrados y —si son retenciones— se suman a su crédito tributario.

El módulo **nace apagado**. Con el flag apagado los correos igual se registran
para depurar, pero el cliente no ve nada y su IVA a pagar no cambia.

---

## 1. Decidir el dominio del buzón

Sigue **pendiente de confirmar** el dominio del producto. Recomendación: usar un
subdominio propio para el buzón (`buzon.factuchat.ec`) en lugar del dominio raíz.
Razones:

- El correo entrante y el saliente se configuran por separado, sin tocar los
  registros MX del dominio principal.
- Si algún día hay que cambiar de proveedor de correo, no se arrastra el resto.
- Un buzón atacado con spam no compromete la reputación del dominio de marca.

```
BUZON_DOMINIO=buzon.factuchat.ec
```

Vacío, se deriva de `APP_DOMAIN`.

## 2. Generar la clave de cifrado

Los documentos del buzón se guardan cifrados con **su propia clave**, distinta de
la del certificado de firma. No reutilizar `CERT_ENC_KEY`: ampliaría el radio de
daño de la firma electrónica a los documentos fiscales de todos los inquilinos, y
obligaría a rotar ambas cosas a la vez.

```bash
openssl rand -base64 32   # → BUZON_ENC_KEY
```

En producción, encender el módulo sin esta clave es un error de arranque.

## 3. Elegir cómo entra el correo

### Opción A — webhook del proveedor (recomendada)

Servicios como Mailgun, Postmark o SES entregan el mensaje MIME crudo por HTTP.

```
BUZON_WEBHOOK_SECRET=$(openssl rand -hex 32)
```

Configurar en el proveedor:

- **Destino**: `https://{dominio}/api/v1/buzon/webhook`
- **Método**: POST con el mensaje crudo en el cuerpo (`message/rfc822`)
- **Cabecera**: `X-Buzon-Signature: sha256={hmac_sha256(secreto, cuerpo_crudo)}`

La firma se verifica **antes de mirar el cuerpo**, con comparación en tiempo
constante. Sin secreto configurado el endpoint rechaza todo con 403: nunca falla
abierto, porque un buzón sin firma acepta documentos de cualquiera y esos
documentos cambian la declaración de impuestos de un cliente.

### Opción B — IMAP

Para despliegue propio con un buzón catch-all:

```
BUZON_IMAP_HOST=imap.tuproveedor.com
BUZON_IMAP_USER=buzon@…
BUZON_IMAP_PASSWORD=…
```

En ambos casos el correo debe llegar con `Delivered-To` o `X-Original-To`: es la
cabecera que dice a qué dirección se entregó **de verdad**, y es la que decide de
quién es el documento. El RUC escrito dentro del XML no decide nada; solo sirve
para verificar que coincide.

## 4. Registros DNS

Para el subdominio del buzón, con el proveedor elegido:

```
buzon.factuchat.ec.   MX    10 mxa.mailgun.org.
buzon.factuchat.ec.   MX    10 mxb.mailgun.org.
buzon.factuchat.ec.   TXT   "v=spf1 include:mailgun.org ~all"
```

Y una regla de reenvío **catch-all** de `*@buzon.factuchat.ec` al webhook: cada
inquilino tiene su dirección, pero no se crea un buzón por cliente.

## 5. Encender el módulo

Con el servicio desplegado, desde el panel interno → **Buzón SRI** → *Encender el
módulo*. Solo el rol SUPERADMIN puede hacerlo, y el cambio queda en la bitácora
inmutable como `Feature flag BUZON_ACTIVO → true`.

`BUZON_ACTIVO` en el `.env` es solo el valor inicial: lo que se pulse en el panel
manda a partir de ese momento.

## 6. Probar de punta a punta

```bash
# Dentro del contenedor de la API
docker compose -f deploy/docker-compose.dev.yml exec api python - <<'PY'
from tests.buzon_utils import correo, xml_retencion, envolver_autorizacion, clave_de_prueba
from app.tasks.buzon import ingerir
from app.buzon.correo import direccion_de_tenant

RUC = "1790012345001"   # el RUC del inquilino de prueba
xml = xml_retencion(ruc_retenido=RUC, clave_acceso=clave_de_prueba(1))
print(ingerir(correo(
    para=direccion_de_tenant(RUC),
    adjunto=envolver_autorizacion(xml),
    message_id="<prueba@proveedor.ec>",
)))
PY
```

Debe imprimir `parseado`. Después, en el panel del inquilino → Comprobantes →
Retenciones, aparece con su saldo.

## 7. Qué vigilar

- **Panel interno → Buzón SRI**: la columna «Parseo». Un `ERROR` trae su motivo y
  el visor de XML crudo (que descifra el mensaje bajo demanda).
- **Banda ámbar**: inquilinos que llevan días sin recibir nada. A los 30 días se
  les envía un recordatorio automático para que configuren el reenvío desde el
  portal del SRI. El aviso se manda una sola vez y el reloj se reinicia en cuanto
  llega cualquier correo.

## 8. Una retención solo cuenta cuando el SRI lo confirma

Un XML lo escribe cualquiera, y el sobre `<autorizacion><estado>AUTORIZADO`
también. La dirección del buzón de un inquilino es su RUC, que aparece en cada
factura que emite: cualquiera podría mandarle un comprobante inventado.

Por eso, cuando entra una retención:

1. Se guarda y el cliente la ve, marcada como **«Comprobando con el SRI»**.
2. Un trabajo aparte pregunta al SRI por su clave de acceso.
3. **Solo si el SRI responde AUTORIZADO** pasa a contar en el saldo y a
   descontar del IVA a pagar.

Si el SRI está caído, se reintenta con espera creciente y la retención sigue sin
contar: un problema de red no es un veredicto, pero tampoco un permiso. Si
responde que no está autorizada, queda archivada con el motivo a la vista y
nunca suma.

Consecuencia operativa: entre que llega un comprobante y que aparece en el saldo
pueden pasar unos minutos, o más si el SRI no responde. Es el precio de que el
número que el cliente declara sea real.

## 9. Lo que el módulo NO hace

- **No sigue enlaces** que vengan dentro de un correo. Si un proveedor manda el
  XML como URL en vez de adjunto, ese correo queda en `ERROR`. Es deliberado:
  seguir un enlace escrito por un desconocido convertiría al worker en un cliente
  HTTP dirigido por terceros.
- **No valida la firma XAdES del comprobante recibido.** La consulta al SRI es
  una garantía más fuerte —confirma que ese documento existe y está autorizado—,
  pero validar además la firma detectaría un XML alterado que reutiliza una clave
  de acceso ajena y legítima. Es la mejora pendiente del módulo. El XML original
  se custodia cifrado, así que la validación se puede aplicar retroactivamente.
- **No acepta `To` ni `Cc` para decidir de quién es un correo**: esas cabeceras
  las escribe el remitente. Hace falta que el proveedor entregue el destinatario
  del sobre (cabecera `X-Buzon-Recipient`) o una cabecera `Delivered-To`. Un
  correo cuyo destino real no se sepa se descarta sin adjudicárselo a nadie.
