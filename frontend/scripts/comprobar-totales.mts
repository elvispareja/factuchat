/** Comprobación de los totales de la factura (`src/util/totales.ts`).
 *
 *  Sin marco de pruebas ni dependencias: son asertos y `node` a secas, que
 *  desde la v22 ejecuta TypeScript quitando los tipos.
 *      node scripts/comprobar-totales.mts
 *
 *  Lo que fija: el redondeo de medio centavo, que el IVA sale de la base
 *  AGRUPADA por tarifa y no de sumar los IVA de cada línea, y que el descuento
 *  se resta ANTES de redondear. Si alguien "simplifica" cualquiera de las tres,
 *  el panel empieza a discrepar del XML por un centavo y el SRI rechaza el
 *  comprobante.
 */

import assert from "node:assert/strict";
import { baseSinIva, cent, descuentoExcede, num, totalizar } from "../src/util/totales.ts";

const linea = (
  cantidad: string,
  precio: string,
  codigoIva = "4",
  porcentaje = 15,
  descuento = "0",
) => ({
  cantidad,
  precio,
  descuento,
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
  descuento: 0,
  iva: 3,
  total: 23,
  porTarifa: [{ codigoIva: "4", tarifa: 15, base: 20, iva: 3 }],
});

// Tarifas distintas se agrupan por separado: 100.00 al 15% y 50.00 al 0%. El
// desglose que pinta la revisión sale de estos mismos grupos —una fila por
// tarifa, como el RIDE—, no de recorrer las líneas por segunda vez.
assert.deepEqual(totalizar([linea("2", "50"), linea("1", "50", "0", 0)]), {
  subtotal: 15000,
  descuento: 0,
  iva: 1500,
  total: 16500,
  porTarifa: [
    { codigoIva: "4", tarifa: 15, base: 10000, iva: 1500 },
    { codigoIva: "0", tarifa: 0, base: 5000, iva: 0 },
  ],
});

// Sin líneas no hay factura, pero tampoco NaN en pantalla.
assert.deepEqual(totalizar([]), {
  subtotal: 0,
  descuento: 0,
  iva: 0,
  total: 0,
  porTarifa: [],
});

// Una cantidad a medias (aún sin teclear el precio) no rompe el total.
assert.deepEqual(totalizar([linea("3", "")]), {
  subtotal: 0,
  descuento: 0,
  iva: 0,
  total: 0,
  porTarifa: [{ codigoIva: "4", tarifa: 15, base: 0, iva: 0 }],
});

/* --- Descuento por línea ---------------------------------------------------
 *
 * El servidor (`emision.calcular_items`) hace, en este orden:
 *     bruto = cantidad × precio            (exacto, sin redondear)
 *     base  = _d2(bruto − descuento)       (UN redondeo, ya restado)
 *     iva   = _d2(base_del_GRUPO × tarifa / 100)
 * y acumula `total_descuento` como la suma de `_d2(descuento)` de cada línea.
 * Estos asertos fijan ese orden, no el resultado de «una cuenta equivalente».
 */

// El caso de todos los días: $100 con $20 de rebaja tributan sobre $80.
assert.deepEqual(totalizar([linea("1", "100", "4", 15, "20")]), {
  subtotal: 8000,
  descuento: 2000,
  iva: 1200,
  total: 9200,
  porTarifa: [{ codigoIva: "4", tarifa: 15, base: 8000, iva: 1200 }],
});

// EL ORDEN, que es lo que este aserto existe para proteger. 3 × 0.335 = 1.005
// exactos; restarle 0.001 deja 1.004, que redondea a 1.00. Quien redondee
// primero el bruto obtiene 1.01 y luego le resta 0.00: un centavo de más en la
// base, en el IVA del grupo y en el total del comprobante.
assert.deepEqual(totalizar([linea("3", "0.335", "4", 15, "0.001")]), {
  subtotal: 100,
  descuento: 0,
  iva: 15,
  total: 115,
  porTarifa: [{ codigoIva: "4", tarifa: 15, base: 100, iva: 15 }],
});

// Y el descuento se redondea POR LÍNEA para el rótulo «Descuento» de la
// pantalla: dos de 0.005 son 0.01 + 0.01 = 0.02, no _d2(0.01) = 0.01. Es el
// `totalDescuento` que va impreso, y tiene que ser el mismo número.
assert.deepEqual(totalizar([linea("1", "10", "4", 15, "0.005"), linea("1", "10", "4", 15, "0.005")]), {
  subtotal: 2000,
  descuento: 2,
  iva: 300,
  total: 2300,
  porTarifa: [{ codigoIva: "4", tarifa: 15, base: 2000, iva: 300 }],
});

// Con dos tarifas, el descuento baja la base de SU grupo y nada más: el 0% no
// puede quedarse con parte de la rebaja del 15%.
assert.deepEqual(totalizar([linea("1", "100", "4", 15, "50"), linea("1", "100", "0", 0, "10")]), {
  subtotal: 14000,
  descuento: 6000,
  iva: 750,
  total: 14750,
  porTarifa: [
    { codigoIva: "4", tarifa: 15, base: 5000, iva: 750 },
    { codigoIva: "0", tarifa: 0, base: 9000, iva: 0 },
  ],
});

// Descuento igual al subtotal: la línea queda en cero y el servidor la acepta
// (rechaza el descuento MAYOR, no el igual). Sin NaN ni un total negativo.
assert.deepEqual(totalizar([linea("2", "25", "4", 15, "50")]), {
  subtotal: 0,
  descuento: 5000,
  iva: 0,
  total: 0,
  porTarifa: [{ codigoIva: "4", tarifa: 15, base: 0, iva: 0 }],
});

/* LA RESTA EN COMA FLOTANTE, que es como se coló el centavo de verdad.
 *
 * Estos tres se midieron contra `calcular_items` y fallaban: la resta de dos
 * números parecidos se come los dígitos buenos ANTES de que `cent()` pueda
 * limpiarlos, y el saneado de `toPrecision(15)` ya no tiene nada que salvar.
 * Media libra de queso a $1,13 con $0,50 de rebaja daba 6 centavos en pantalla
 * y 7 en el XML firmado. Quien vuelva a hacer la cuenta con `number` en vez de
 * con enteros exactos, revienta aquí. */
assert.equal(totalizar([linea("0.5", "1.13", "4", 15, "0.50")]).subtotal, 7);
assert.equal(totalizar([linea("426", "3.5875", "4", 15, "1444.21")]).subtotal, 8407);
assert.equal(totalizar([linea("426", "3.5875", "4", 15, "1444.21")]).total, 9668);
assert.equal(totalizar([linea("2.365", "1.5", "4", 15, "0.01")]).subtotal, 354);

/* El tope del descuento se compara EXACTO, como en el servidor, no en centavos
 * ya redondeados: 1,5 m de cable a $3,33 son 4,995, que la pantalla enseña como
 * $5,00. Redondeando, teclear $5,00 de rebaja parecía válido y el servidor lo
 * rechazaba con un 422 pidiendo un importe que el campo, de centavo en centavo,
 * no deja escribir. */
assert.equal(descuentoExcede(linea("1.5", "3.33", "4", 15, "5.00")), true);
assert.equal(descuentoExcede(linea("1.5", "3.33", "4", 15, "4.99")), false);
assert.equal(descuentoExcede(linea("2", "25", "4", 15, "50")), false); // igual, no excede

// Un descuento a medio teclear («0,», «-3», vacío) no puede subir ni bajar el
// total: `num()` lo trata como 0, igual que un precio a medias.
for (const escrito of ["", "0", "0,", "-3", "hola"]) {
  assert.deepEqual(totalizar([linea("1", "100", "4", 15, escrito)]).total, 11500);
}

// La coma decimal del teclado del móvil también descuenta.
assert.equal(totalizar([linea("1", "100", "4", 15, "2,50")]).descuento, 250);

// El recargo de la nota de débito se teclea CON IVA y se desglosa al revés que
// una línea de factura. Es la cuenta del servidor (`crear_nota_debito`) y tiene
// que dar lo mismo al céntimo: 20.00 → 17.39 + 2.61.
const recargo = (conIva: number) => totalizar([linea("1", String(baseSinIva(conIva, 15) / 100))]);

assert.deepEqual(recargo(20), {
  subtotal: 1739,
  descuento: 0,
  iva: 261,
  total: 2000,
  porTarifa: [{ codigoIva: "4", tarifa: 15, base: 1739, iva: 261 }],
});
assert.equal(recargo(115).total, 11500);
assert.equal(recargo(500).total, 50000);

// Y el centavo que NO se puede evitar, fijado a propósito para que nadie lo
// "arregle": 10.00 con IVA dentro no existe, sale 8.70 + 1.31. El panel lo
// avisa antes de emitir en vez de enseñar un total que luego cambia.
assert.equal(recargo(10).total, 1001);
assert.equal(recargo(1000).total, 100001);

console.log("totales: bien");
