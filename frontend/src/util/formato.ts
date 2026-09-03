/** Formato de moneda y fechas para Ecuador (USD, es-EC). */

/** Quita los espacios de un teléfono.
 *
 *  Copiar el número desde WhatsApp trae separadores («+593 99 000 0000») y, a
 *  menudo, espacios duros invisibles. Se quedaban dentro del valor guardado, y
 *  además cuentan para el límite de 20 caracteres del servidor, así que un
 *  número perfectamente válido podía rebotar por largo. `\s` cubre también el
 *  espacio no separable, que es el que suele venir al pegar. */
export function telefonoLimpio(valor: string): string {
  return valor.replace(/\s+/g, "");
}

/** Ecuador está dolarizado y escribe el dinero como el dólar: coma para los
 *  miles y punto para los decimales ($1,208.50). La configuración regional
 *  «es-EC» de los navegadores hace lo contrario —$9,99— y dejaba la pantalla
 *  discrepando de la maqueta y de los XML del SRI, que usan punto. */
const MONEDA = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
});

export function dinero(valor: string | number): string {
  const numero = typeof valor === "string" ? Number(valor) : valor;
  return Number.isFinite(numero) ? MONEDA.format(numero) : "—";
}

const FECHA = new Intl.DateTimeFormat("es-EC", {
  day: "numeric",
  month: "long",
  year: "numeric",
});

export function fechaLarga(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : FECHA.format(d);
}

/** Hoy en Ecuador, en ISO (`2026-09-01`).
 *
 *  El servidor fecha los comprobantes con `America/Guayaquil`
 *  (emision.TZ_ECUADOR), así que la revisión tiene que enseñar ESA fecha: en un
 *  móvil configurado en otra zona —o en Madrid a las 3 de la mañana— la fecha
 *  local es otro día y la pantalla prometería una fecha de emisión falsa. */
const ISO_ECUADOR = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Guayaquil" });

export const hoyEnEcuador = (): string => ISO_ECUADOR.format(new Date());

const FECHA_CORTA = new Intl.DateTimeFormat("es-EC", { day: "2-digit", month: "2-digit", year: "numeric" });

export function fechaCorta(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : FECHA_CORTA.format(d);
}

/** Etiqueta y tono de cada estado del SRI, según la maqueta (~línea 3397). */
export function tonoEstado(estado: string): { label: string; clase: string } {
  switch (estado) {
    case "AUTORIZADO":
      return { label: "Autorizado", clase: "fc-estado--exito" };
    case "PENDIENTE":
    case "FIRMADO":
    case "ENVIADO_SRI":
      return { label: "En proceso", clase: "fc-estado--aviso" };
    case "DEVUELTO":
      return { label: "Devuelto", clase: "fc-estado--error" };
    case "RECHAZADO":
      return { label: "Rechazado", clase: "fc-estado--error" };
    default:
      return { label: estado, clase: "fc-estado--neutro" };
  }
}

/** Inicial para el avatar. `[...]` y no `[0]` porque una razón social puede
 *  empezar por un carácter fuera del plano básico y `[0]` partiría el par. */
export function inicial(nombre: string): string {
  return [...nombre.trim()][0]?.toUpperCase() ?? "?";
}

/** El tipo de identificación, legible. Lo usan la libreta de clientes y la
 *  columna CLIENTE del historial («RUC 0992745103001», «Cédula 0923737159»). */
export const ETIQUETA_ID: Record<string, string> = {
  RUC: "RUC",
  CEDULA: "Cédula",
  PASAPORTE: "Pasaporte",
  CONSUMIDOR_FINAL: "Consumidor final",
  ID_EXTERIOR: "Identificación del exterior",
};

export const ETIQUETA_TIPO: Record<string, string> = {
  FACTURA: "Factura",
  NOTA_CREDITO: "Nota de crédito",
  NOTA_DEBITO: "Nota de débito",
  RETENCION: "Retención",
  GUIA_REMISION: "Guía de remisión",
  LIQUIDACION_COMPRA: "Liquidación de compra",
};
