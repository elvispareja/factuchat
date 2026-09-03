/** Totales de una factura, para ENSEÑARLOS mientras se arma.
 *
 *  Lo que vale es lo que calcula el servidor al emitir
 *  (`emision.calcular_items`); esto solo tiene que decir lo mismo, así que
 *  replica su orden al pie de la letra: base por ítem —descuento restado ANTES
 *  de redondear— y IVA sobre la base AGRUPADA por tarifa; no la suma de los IVA
 *  ya redondeados de cada línea, que se desvía un centavo y el SRI rechaza el
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

/** Quita el IVA de un importe que ya lo lleva dentro, en centavos.
 *
 *  Para el recargo de la nota de débito, que se teclea CON impuestos incluidos
 *  («cóbrale 20 dólares de mora») al revés que el precio de una línea de
 *  factura. Es la misma cuenta del servidor —`_d2(valor × 100 / (100+tarifa))`
 *  en `crear_nota_debito`— y por eso sale aquí y no dentro de la pantalla: quien
 *  la cambie tiene delante el aserto que la fija.
 *
 *  OJO: la vuelta NO siempre da el importe de partida. El IVA se redondea al
 *  céntimo y el SRI recalcula base×tarifa, así que 10.00 → 8.70 + 1.31 = 10.01.
 *  No es un fallo que arreglar: es que ese importe no es expresable con IVA
 *  dentro, y el panel lo avisa antes de emitir. */
export const baseSinIva = (conIva: number, tarifa: number) =>
  cent((conIva * 100) / (100 + tarifa));

export interface LineaCalculable {
  cantidad: string;
  precio: string;
  /** Rebaja EN DÓLARES sobre esta línea, antes del IVA («Descuento $» del
   *  formulario). Cadena vacía = ninguna, igual que un precio a medio teclear:
   *  `num()` lo trata como 0. */
  descuento: string;
  codigoIva: string;
  /** Tarifa del `codigoIva`, tal como la trae el producto (`porcentaje_iva`,
   *  que el servidor saca de la misma tabla TARIFAS_IVA). */
  porcentaje: number;
}

/** Un decimal TECLEADO, en aritmética exacta: mantisa entera y cuántos
 *  decimales tenía. `"3.5875"` → `{ m: 35875n, e: 4 }`.
 *
 *  Hace falta porque `cent()` NO basta en cuanto hay una resta de por medio. Ese
 *  truco repara el ruido de una MULTIPLICACIÓN —los dígitos malos quedan al
 *  final y `toPrecision(15)` los recorta—, pero al restar dos números parecidos
 *  el error sube a los dígitos significativos y ya no hay nada que recuperar
 *  (cancelación catastrófica). Medido: media libra de queso a $1,13 con $0,50 de
 *  rebaja da 0.06499999999999995 en coma flotante, o sea 6 centavos, y el
 *  servidor —Decimal exacto— dice 7. El usuario aprobaba en pantalla un centavo
 *  menos del que se firmaba.
 *
 *  Con BigInt no hay coma flotante en ninguna parte del camino, así que la
 *  cuenta es la MISMA que la del servidor y no una que se le parece.
 *
 *  Lo que no sea un decimal positivo y sencillo vale 0, como en `num()`: el
 *  campo a medio teclear y la basura pegada se validan aparte. */
const exacto = (s: string): { m: bigint; e: number } => {
  const t = String(s).replace(",", ".").trim();
  if (!/^\d+(\.\d*)?$|^\.\d+$/.test(t)) return { m: 0n, e: 0 };
  const [entera, decimales = ""] = t.split(".");
  return { m: BigInt((entera || "0") + decimales), e: decimales.length };
};

/** `m / 10^e` redondeado a CENTAVOS, medio ARRIBA: el `_d2` del servidor
 *  (`ROUND_HALF_UP`, que en un empate se aleja del cero). */
const aCentavos = (m: bigint, e: number): number => {
  if (e <= 2) return Number(m * 10n ** BigInt(2 - e));
  const divisor = 10n ** BigInt(e - 2);
  const negativo = m < 0n;
  const abs = negativo ? -m : m;
  const entero = abs / divisor;
  const resto = abs % divisor;
  const redondeado = resto * 2n >= divisor ? entero + 1n : entero;
  return Number(negativo ? -redondeado : redondeado);
};

/** Bruto y descuento de una línea llevados a una escala común, para poder
 *  compararlos y restarlos SIN redondear ninguno antes de tiempo. */
const partes = (l: LineaCalculable) => {
  const c = exacto(l.cantidad);
  const p = exacto(l.precio);
  const d = exacto(l.descuento);
  const eProducto = c.e + p.e;
  const e = Math.max(eProducto, d.e);
  return {
    e,
    bruto: c.m * p.m * 10n ** BigInt(e - eProducto),
    descuento: d.m * 10n ** BigInt(e - d.e),
  };
};

/** El importe de UNA línea en centavos, que es su base imponible.
 *
 *  Se exporta porque la pantalla lo pinta línea a línea —en el formulario y en
 *  la tabla de la revisión— y tiene que ser exactamente el número que `totalizar`
 *  suma: dos expresiones parecidas en tres sitios es como se cuela el centavo. */
export const importeLinea = (l: LineaCalculable) => {
  const { e, bruto, descuento } = partes(l);
  return aCentavos(bruto - descuento, e);
};

/** ¿La rebaja se pasa del bruto de la línea?
 *
 *  Comparación EXACTA, como la del servidor (`if descuento > bruto` en
 *  `calcular_items`), no en centavos redondeados. Comparar redondeado dejaba un
 *  callejón sin salida: 1,5 m de cable a $3,33 son 4,995, que la pantalla
 *  enseña como $5,00; teclear $5,00 de rebaja parecía válido, el servidor lo
 *  rechazaba con un 422, y el importe exacto —4,995— no se podía escribir
 *  porque el campo va de centavo en centavo. */
export const descuentoExcede = (l: LineaCalculable) => {
  const { bruto, descuento } = partes(l);
  return descuento > bruto;
};

/** Una tarifa de IVA con su base imponible y su cuota, en centavos. Es como lo
 *  desglosa el RIDE («Subtotal 15%», «Subtotal 0%»), y es la agrupación con la
 *  que ya se calculaba el IVA: se devuelve para poder PINTARLA, no se recalcula
 *  nada aparte. */
export interface GrupoIva {
  codigoIva: string;
  tarifa: number;
  base: number;
  iva: number;
}

export function totalizar(lineas: LineaCalculable[]): {
  /** SIN impuestos y YA descontado, como el `totalSinImpuestos` del XML. */
  subtotal: number;
  /** Lo rebajado entre todas las líneas (`totalDescuento` del XML). Se enseña
   *  aparte porque el RIDE lo imprime, no porque haga falta para el total. */
  descuento: number;
  iva: number;
  total: number;
  porTarifa: GrupoIva[];
} {
  const grupos = new Map<string, { base: number; tarifa: number }>();
  let subtotal = 0;
  let descuento = 0;
  for (const l of lineas) {
    // UN solo redondeo, y DESPUÉS de restar: el servidor hace
    // `_d2(cantidad × precio − descuento)` (emision.calcular_items). Redondear
    // el bruto por un lado y el descuento por otro da «lo mismo» casi siempre y
    // se desvía un centavo justo donde duele: 3 × 0.335 = 1.005 menos 0.001 es
    // 1.00, pero redondeando antes sale 1.01 y el SRI rechaza el comprobante.
    const base = importeLinea(l);
    subtotal += base;
    // El servidor acumula `_d2(descuento)` línea a línea, no la suma cruda.
    const d = exacto(l.descuento);
    descuento += aCentavos(d.m, d.e);
    const g = grupos.get(l.codigoIva) ?? { base: 0, tarifa: l.porcentaje };
    g.base += base;
    grupos.set(l.codigoIva, g);
  }
  let iva = 0;
  const porTarifa: GrupoIva[] = [];
  for (const [codigoIva, g] of grupos) {
    // También exacto, y por la misma razón: `_d2(base × tarifa / 100)` sobre la
    // base YA agrupada. El `+ 1e-9` que había aquí tapaba el empate de 130.5
    // por casualidad; con enteros no hay empate que tapar.
    const cuota = aCentavos(BigInt(g.base) * BigInt(Math.round(g.tarifa * 100)), 6);
    iva += cuota;
    porTarifa.push({ codigoIva, tarifa: g.tarifa, base: g.base, iva: cuota });
  }
  return { subtotal, descuento, iva, total: subtotal + iva, porTarifa };
}
