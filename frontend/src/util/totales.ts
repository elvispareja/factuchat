/** Totales de una factura, para ENSEÑARLOS mientras se arma.
 *
 *  Lo que vale es lo que calcula el servidor al emitir
 *  (`emision.calcular_items`); esto solo tiene que decir lo mismo, así que
 *  replica su orden al pie de la letra: base por ítem redondeada a centavos, e
 *  IVA sobre la base AGRUPADA por tarifa — no la suma de los IVA ya
 *  redondeados de cada línea, que se desvía un centavo y el SRI rechaza el
 *  comprobante si no cuadra.
 *
 *  Todo se lleva en CENTAVOS ENTEROS: sumar flotantes acaba enseñando
 *  747.4999999999 en pantalla. Se divide entre 100 solo al pintar.
 */

/** Centavos, medio arriba, como el `_d2` del servidor.
 *
 *  El problema: 0.335 × 3 × 100 vale 100.49999999999999 en coma flotante, y un
 *  Math.round pelado da 100 donde el servidor —que usa Decimal exacto— da 101.
 *  Un centavo de diferencia entre lo que el usuario ve y lo que firma.
 *
 *  Sumar un sesgo fijo (1e-9) lo tapa solo en importes pequeños: el error
 *  propio del double crece con la magnitud, y pasados los ~65.000 dólares ya es
 *  mayor que el sesgo, así que el fallo vuelve. `toPrecision(15)` no tiene ese
 *  techo: recorta el ruido en los dígitos que un double ya no puede garantizar
 *  —tiene entre 15 y 17 significativos— y deja el valor que se pretendía
 *  escribir, sin empujar en ninguna dirección. */
export const cent = (v: number) => Math.round(Number((v * 100).toPrecision(15)));

/** Lo tecleado en un campo numérico. Acepta la coma decimal y trata cualquier
 *  cosa rara (vacío, texto, negativo) como 0: el campo se valida aparte. */
export const num = (s: string) => {
  const n = Number(s.replace(",", "."));
  return Number.isFinite(n) && n > 0 ? n : 0;
};

/** Tope del consumidor final, en centavos (emision.LIMITE_CONSUMIDOR_FINAL).
 *  Se comprueba en el panel solo para no mandar un viaje que va a rebotar:
 *  quien manda es el servidor. */
export const TOPE_CONSUMIDOR_FINAL = 20000;

export interface LineaCalculable {
  cantidad: string;
  precio: string;
  codigoIva: string;
  /** Tarifa del `codigoIva`, tal como la trae el producto (`porcentaje_iva`,
   *  que el servidor saca de la misma tabla TARIFAS_IVA). */
  porcentaje: number;
}

export function totalizar(lineas: LineaCalculable[]): {
  subtotal: number;
  iva: number;
  total: number;
} {
  const grupos = new Map<string, { base: number; tarifa: number }>();
  let subtotal = 0;
  for (const l of lineas) {
    const base = cent(num(l.cantidad) * num(l.precio));
    subtotal += base;
    const g = grupos.get(l.codigoIva) ?? { base: 0, tarifa: l.porcentaje };
    g.base += base;
    grupos.set(l.codigoIva, g);
  }
  let iva = 0;
  for (const g of grupos.values()) iva += Math.round((g.base * g.tarifa) / 100 + 1e-9);
  return { subtotal, iva, total: subtotal + iva };
}
