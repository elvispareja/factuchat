/** Comprobación de los totales de la factura (`src/util/totales.ts`).
 *
 *  Sin marco de pruebas ni dependencias: son asertos y `node` a secas, que
 *  desde la v22 ejecuta TypeScript quitando los tipos.
 *      node scripts/comprobar-totales.mts
 *
 *  Lo que fija: el redondeo de medio centavo y —lo importante— que el IVA sale
 *  de la base AGRUPADA por tarifa y no de sumar los IVA de cada línea. Si
 *  alguien "simplifica" eso, el panel empieza a discrepar del XML por un
 *  centavo y el SRI rechaza el comprobante.
 */

import assert from "node:assert/strict";
import { cent, num, totalizar } from "../src/util/totales.ts";

const linea = (cantidad: string, precio: string, codigoIva = "4", porcentaje = 15) => ({
  cantidad,
  precio,
  codigoIva,
  porcentaje,
});

// 0.335 × 3 vale 1.005 en decimal y 1.00499999… en binario: sin el sesgo esto
// daría 100 y el comprobante diría 1.01.
assert.equal(cent(3 * 0.335), 101);
assert.equal(cent(19.99), 1999);

assert.equal(num("1,5"), 1.5);
assert.equal(num(""), 0);
assert.equal(num("-3"), 0);
assert.equal(num("hola"), 0);

// Dos líneas de 0.10 al 15%: por línea el IVA se redondea a 2 centavos cada una
// (0.015 → 0.02) y sumaría 4. Agrupado son 0.20 × 15% = 0.03. Manda el grupo,
// que es lo que recalcula el SRI.
assert.deepEqual(totalizar([linea("1", "0.10"), linea("1", "0.10")]), {
  subtotal: 20,
  iva: 3,
  total: 23,
});

// Tarifas distintas se agrupan por separado: 100.00 al 15% y 50.00 al 0%.
assert.deepEqual(totalizar([linea("2", "50"), linea("1", "50", "0", 0)]), {
  subtotal: 15000,
  iva: 1500,
  total: 16500,
});

// Sin líneas no hay factura, pero tampoco NaN en pantalla.
assert.deepEqual(totalizar([]), { subtotal: 0, iva: 0, total: 0 });

// Una cantidad a medias (aún sin teclear el precio) no rompe el total.
assert.deepEqual(totalizar([linea("3", "")]), { subtotal: 0, iva: 0, total: 0 });

console.log("totales: bien");
