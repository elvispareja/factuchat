/** Formato de moneda y fechas para Ecuador (USD, es-EC). */

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

export const ETIQUETA_TIPO: Record<string, string> = {
  FACTURA: "Factura",
  NOTA_CREDITO: "Nota de crédito",
  NOTA_DEBITO: "Nota de débito",
  RETENCION: "Retención",
  GUIA_REMISION: "Guía de remisión",
  LIQUIDACION_COMPRA: "Liquidación de compra",
};
