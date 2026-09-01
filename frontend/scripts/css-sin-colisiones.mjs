/** Ninguna clase puede estar definida a la vez en la hoja del panel INTERNO y
 *  en las del panel de cliente.
 *
 *  Por qué existe este chequeo: `PanelInterno` se importa en App.tsx sin carga
 *  diferida, así que `interno.css` acaba en el MISMO archivo CSS que
 *  `design/componentes.css` y, al ir después, gana en la cascada. Una clase
 *  repetida no da error en ninguna parte: simplemente se aplica también donde
 *  no toca. Así estuvo `.fc-modal__panel`, cuyo `overflow: hidden` (pensado
 *  para el modal interno, que desplaza solo su cuerpo) recortaba los modales
 *  del panel de cliente y dejaba sus botones fuera de alcance.
 *
 *  Ejecutar: node scripts/css-sin-colisiones.mjs
 */

import { readFileSync } from "node:fs";

const INTERNO = "src/interno/interno.css";
const CLIENTE = [
  "src/design/componentes.css",
  "src/design/patron-factuchat.css",
  "src/shell/shell.css",
];

/** Selectores de clase declarados al principio de línea (`.fc-x {`, `.fc-x,`).
 *  Los acotados (`.fc-sa-shell .fc-modal`) no colisionan: cuentan por su raíz. */
const clases = (ruta) =>
  new Set(
    readFileSync(new URL(`../${ruta}`, import.meta.url), "utf8")
      .split("\n")
      .map((linea) => /^(\.[A-Za-z0-9_-]+)\s*[,{ ]/.exec(linea)?.[1])
      .filter(Boolean),
  );

const delInterno = clases(INTERNO);
const colisiones = CLIENTE.flatMap((ruta) => [...clases(ruta)].filter((c) => delInterno.has(c)));

if (colisiones.length > 0) {
  console.error(
    `Clases definidas en ${INTERNO} y también en las hojas del panel de cliente:\n` +
      colisiones.map((c) => `  ${c}`).join("\n") +
      "\n\nAcota la de interno.css con `.fc-sa-shell ` delante, o renómbrala.",
  );
  process.exit(1);
}
console.log(`Sin colisiones: ${delInterno.size} clases en ${INTERNO}.`);
