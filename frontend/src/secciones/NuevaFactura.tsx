/** Crear comprobante: el selector de tipo (1), el formulario (2), la revisión
 *  (3) y el desenlace del envío (4).
 *
 *  TRES DOCUMENTOS, UN FORMULARIO: la factura y las dos notas comparten el
 *  buscador de cliente, los totales, el pie, la revisión y todo el envío. Lo
 *  propio de las notas son tres campos —qué factura modifica, de qué fecha y por
 *  qué— y una regla: van SIEMPRE al mismo cliente de esa factura. Entre ellas
 *  cambia QUÉ importe se pide: la de crédito devuelve LÍNEAS de la factura (por
 *  eso trae el catálogo), la de débito cobra UN importe suelto y no vende nada,
 *  así que no tiene líneas que elegir y es el formulario más corto de los tres.
 *
 *  LA RETENCIÓN RECIBIDA YA NO ESTÁ EN EL SELECTOR. Era la cuarta tarjeta,
 *  apagada con un «Próximamente», como si fuera un documento que faltaba por
 *  construir. No lo es: el usuario de Factuchat no emite retenciones, se las
 *  hacen. Su cliente le retiene y le manda el comprobante, y ese papel se
 *  REGISTRA —hoy en Retenciones, que sí tiene su ruta— en vez de emitirse. Una
 *  cuarta tarjeta, aunque estuviera gris, seguía enseñando que «retención» es
 *  la cuarta cosa que uno crea desde aquí. Queda una nota al pie que lleva a
 *  donde de verdad va, que está a un clic (ver `PanelSelector`).
 *
 *  POR QUÉ HAY UNA REVISIÓN: emitir es irreversible —corregir una factura ya
 *  emitida obliga a una nota de crédito—, así que el formulario ya no emite:
 *  lleva a la revisión y allí se decide. Las cuatro pantallas son estados de
 *  ESTE componente, no rutas ni desmontajes: por eso «Volver a editar» devuelve
 *  el formulario con todo lo escrito intacto sin guardar ni restaurar nada.
 *
 *  El formulario y la revisión son paneles de TRES PARTES
 *  (`.fc-modal__panel--fijo`): solo el cuerpo desplaza y el pie —con el botón
 *  que emite— no se va nunca de la pantalla. El resto de modales del panel
 *  siguen siendo un div plano que desplaza entero; ver el comentario largo en
 *  design/componentes.css.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ErrorLimitePlan, api } from "../api/cliente";
import type {
  AtributoValor,
  ClienteFinal,
  Comprobante,
  EstadoComprobante,
  FacturaAcreditable,
  OpcionPago,
  Producto,
  ProductoVariante,
  SiguienteNumero,
} from "../api/tipos";
import type { Emisor } from "../plan/PlanContexto";
import { usePlan } from "../plan/PlanContexto";
import { ETIQUETA_TIPO, dinero, fechaCorta, fechaLarga, hoyEnEcuador, inicial } from "../util/formato";
import type { LineaCalculable } from "../util/totales";
import {
  TOPE_CONSUMIDOR_FINAL,
  baseSinIva,
  cent,
  descuentoExcede,
  importeLinea,
  num,
  totalizar,
} from "../util/totales";

/** Una línea de la factura: lo que hay que calcular más lo que hay que pintar. */
interface Linea extends LineaCalculable {
  clave: string;
  codigo: string;
  descripcion: string;
  /** El campo «Descuento $» está a la vista. Plegado por omisión: la mayoría de
   *  las facturas no rebajan nada y quien no lo usa no tiene por qué verlo. Es
   *  un estado de la LÍNEA y no un Set aparte para que muera con ella: quitar
   *  una línea no puede dejar rastro que reaparezca en la siguiente. */
  conDescuento?: boolean;
  /** Escrita a mano, no elegida del catálogo: aquí se teclean su descripción,
   *  su precio y su IVA, y el código se genera de lo escrito. */
  aMano?: boolean;
  /** «Guardar en mis productos», marcada por omisión. Solo en las de a mano:
   *  las del catálogo ya están guardadas. */
  guardar?: boolean;
}

/** Las tarifas de IVA que puede llevar algo que se vende HOY (tabla 17 del SRI,
 *  la misma `TARIFAS_IVA` del servidor). Las históricas —12% y 14%— se quedan
 *  en el catálogo, que sí tiene que poder corregir un artículo viejo; una línea
 *  que se está escribiendo ahora no las necesita, y tres opciones se eligen de
 *  un vistazo donde seis se leen. */
const IVA_A_MANO = [
  { codigo: "4", porcentaje: 15, etiqueta: "IVA 15%" },
  { codigo: "5", porcentaje: 5, etiqueta: "IVA 5%" },
  { codigo: "0", porcentaje: 0, etiqueta: "Sin IVA" },
] as const;

/** El código con el que la línea va IMPRESA y con el que se guardaría el
 *  artículo.
 *
 *  `ProductoIn.codigo` es obligatorio y único por negocio, pero quien factura
 *  desde el móvil no tiene SKUs en la cabeza: preguntárselo sería pedirle un
 *  dato que todavía no existe, y el que se invente al vuelo («1», «a») es el
 *  que chocará con el siguiente. Sale de lo que YA escribió —«Silla de madera»
 *  → SILLA-DE-MADERA—, que además es lo que querrá reconocer cuando busque ese
 *  artículo en el catálogo dentro de un mes.
 *
 *  `ocupados` son los códigos que ya están cogidos (el catálogo cargado, sus
 *  variantes y las demás líneas de esta factura): con ellos el sufijo evita el
 *  choque probable. NO lo garantiza —un artículo DESACTIVADO no sale en
 *  /productos y el índice único del servidor sí lo cuenta—, así que el guardado
 *  puede fallar igual; cuando pasa, la factura sale y se avisa (ver
 *  `guardarProductos`). Comprobarlo de verdad pediría una ruta que no existe. */
function codigoDe(descripcion: string, ocupados: Set<string>): string {
  const raiz =
    descripcion
      // NFD separa la tilde de la letra y la siguiente línea se la lleva:
      // «Camión rojo» → CAMION-ROJO. Borrarla APARTE y no dejar que caiga en el
      // filtro de símbolos de abajo, que la convertiría en separador y partiría
      // la palabra por la mitad (CAMIO-N-ROJO).
      .normalize("NFD")
      .replace(/\p{M}/gu, "")
      .toUpperCase()
      .replace(/[^A-Z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      // 22 y no 25: deja sitio para el «-99» del desempate sin pasarse del tope
      // de `ProductoIn.codigo` ni del de `ItemFacturaIn.codigo`.
      .slice(0, 22)
      .replace(/-+$/, "") || "ARTICULO";
  let codigo = raiz;
  for (let n = 2; ocupados.has(codigo); n++) codigo = `${raiz}-${n}`;
  return codigo;
}

/** Los tres documentos que este modal sabe crear. */
type Tipo = "FACTURA" | "NOTA_CREDITO" | "NOTA_DEBITO";

/** A dónde va cada uno. Las tres rutas crean BORRADOR; emitir es el segundo
 *  paso (`/comprobantes/{id}/emitir`), igual para los tres. */
const RUTA: Record<Tipo, string> = {
  FACTURA: "/comprobantes/facturas",
  NOTA_CREDITO: "/comprobantes/notas-credito",
  NOTA_DEBITO: "/comprobantes/notas-debito",
};

/** Cómo se llama cada uno en voz alta. Los tres son femeninos, así que los
 *  textos («Tu … está en proceso», «Ver …») no cambian de forma. */
const DOC: Record<Tipo, string> = {
  FACTURA: "factura",
  NOTA_CREDITO: "nota de crédito",
  NOTA_DEBITO: "nota de débito",
};

/** El IVA del recargo de una nota de débito. Es una CONSTANTE, no una elección:
 *  no hay línea de producto donde escogerla y el servidor tampoco la pregunta
 *  (`emision.CODIGO_IVA_RECARGO`). Aquí solo sirve para enseñar el desglose
 *  antes de emitir; quien lo calcula de verdad es él. */
const IVA_RECARGO = { codigo: "4", porcentaje: 15 };

/** A nombre de quién sale el comprobante, ya resuelto: de la libreta en la
 *  factura, y del SNAPSHOT de la factura de origen en la nota de crédito —que
 *  va siempre al mismo comprador que el SRI ya autorizó. */
interface Comprador {
  nombre: string;
  identificacion: string;
  direccion?: string | null;
  telefono?: string | null;
}

/** El número que el SRI exige citar: 001-001-000000123. */
const NUMERO_COMPROBANTE = /^\d{3}-\d{3}-\d{9}$/;

/** Mismo mínimo que el servidor (`_NotaSobreFactura.motivo_con_sentido`, que
 *  comparten las dos notas): va impreso
 *  en el comprobante, así que ni un carácter suelto ni una fila de puntos. Se
 *  comprueba aquí solo para no mandar un viaje que va a rebotar con un 422. */
const motivoValido = (v: string) => v.trim().length >= 5 && /\p{L}/u.test(v);

/* --- Iconos ---------------------------------------------------------------- */

const trazo = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

function Svg({ d, tamano = 17 }: { d: string; tamano?: number }) {
  return (
    <svg width={tamano} height={tamano} viewBox="0 0 24 24" aria-hidden="true" {...trazo}>
      <path d={d} />
    </svg>
  );
}

const ICONO_CERRAR = "M6 6l12 12M18 6L6 18";
const ICONO_CHEVRON = "m9 6 6 6-6 6";
const ICONO_DOC = "M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h4";
const ICONO_MENOS = "M6 3h8l4 4v14H6zM14 3v4h4M9 14h6";
const ICONO_MAS = "M6 3h8l4 4v14H6zM14 3v4h4M12 11v6M9 14h6";
const ICONO_PORCENTAJE = "M5 4h14v17l-2.3-1.6L14.4 21l-2.4-1.6L9.6 21l-2.3-1.6L5 21zM9 15l6-6M9.2 9.2h.01M14.8 14.8h.01";
const ICONO_LAPIZ = "M4 20h4l10-10-4-4L4 16zM14 6l4 4";
const ICONO_CHECK = "M4 12.5 9 17.5 20 6.5";
const ICONO_RELOJ = "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3.5 2";
const ICONO_AVISO = "M12 3 2.5 20h19zM12 10v4M12 17.5h.01";
const ICONO_SOBRE = "M3 6h18v12H3zM3 7l9 6 9-6";

/* --- Pantalla 1: elegir el tipo de documento -------------------------------- */

const TONOS = {
  verde: { fondo: "rgba(34,197,94,.12)", color: "var(--verde-medio)" },
  rojo: { fondo: "var(--error-bg)", color: "var(--error-texto)" },
  ambar: { fondo: "var(--aviso-bg)", color: "var(--aviso-texto)" },
  gris: { fondo: "var(--superficie-tenue)", color: "var(--texto-tenue)" },
} as const;

/** Lo que este modal SÍ crea: los tres que se emiten. Ni uno más — ver el
 *  encabezado del archivo sobre por qué la retención recibida no está. */
const TIPOS: Array<{
  id: Tipo;
  titulo: string;
  texto: string;
  tono: keyof typeof TONOS;
  icono: string;
}> = [
  {
    id: "FACTURA",
    titulo: "Factura",
    texto: "Le vendiste un producto o un servicio.",
    tono: "verde",
    icono: ICONO_DOC,
  },
  {
    id: "NOTA_CREDITO",
    titulo: "Nota de crédito",
    texto: "Anular o corregir una factura ya emitida.",
    tono: "rojo",
    icono: ICONO_MENOS,
  },
  {
    id: "NOTA_DEBITO",
    titulo: "Nota de débito",
    texto: "Cobrarle de más sobre una factura: intereses, un gasto.",
    tono: "ambar",
    icono: ICONO_MAS,
  },
];

function Cabecera({
  titulo,
  subtitulo,
  onCerrar,
  fijo,
}: {
  titulo: string;
  subtitulo: string;
  onCerrar: () => void;
  /** Cabecera de un panel de tres partes: el relleno lo pone la clase, no el
   *  panel, y se queda clavada mientras el cuerpo desplaza. */
  fijo?: boolean;
}) {
  return (
    <div
      className={fijo ? "fc-modal__cabecera" : undefined}
      style={
        fijo
          ? { alignItems: "flex-start" }
          : { display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 18 }
      }
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <h2 className="fc-titulo" style={{ fontSize: 20, margin: 0 }}>
          {titulo}
        </h2>
        <p style={{ fontSize: 13, color: "var(--texto-tenue)", margin: "5px 0 0" }}>{subtitulo}</p>
      </div>
      <button type="button" className="fc-btn-icono" aria-label="Cerrar" onClick={onCerrar}>
        <Svg d={ICONO_CERRAR} tamano={15} />
      </button>
    </div>
  );
}

function PanelSelector({
  onElegir,
  onRetenciones,
  onCerrar,
}: {
  onElegir: (tipo: Tipo) => void;
  /** Cierra este modal y abre la bandeja de retenciones recibidas, que está en
   *  la misma sección (Comprobantes → Retenciones). */
  onRetenciones: () => void;
  onCerrar: () => void;
}) {
  return (
    <div className="fc-modal__panel" style={{ maxWidth: 520 }}>
      <Cabecera
        titulo="Crear comprobante"
        subtitulo="Elige qué documento necesitas."
        onCerrar={onCerrar}
      />
      <div style={{ display: "grid", gap: 10 }}>
        {TIPOS.map((t) => {
          const tono = TONOS[t.tono];
          return (
            <button
              key={t.id}
              type="button"
              className="fc-tarjeta"
              onClick={() => onElegir(t.id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 13,
                padding: "13px 15px",
                textAlign: "left",
                font: "inherit",
                color: "inherit",
                background: "var(--superficie)",
                cursor: "pointer",
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  flex: "none",
                  width: 38,
                  height: 38,
                  borderRadius: 11,
                  display: "grid",
                  placeItems: "center",
                  background: tono.fondo,
                  color: tono.color,
                }}
              >
                <Svg d={t.icono} />
              </span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: "block", fontWeight: 600, fontSize: 14 }}>{t.titulo}</span>
                <span
                  style={{
                    display: "block",
                    fontSize: 12.5,
                    color: "var(--texto-tenue)",
                    marginTop: 2,
                  }}
                >
                  {t.texto}
                </span>
              </span>
              <span aria-hidden="true" style={{ color: "var(--texto-tenue)", display: "grid" }}>
                <Svg d={ICONO_CHEVRON} tamano={15} />
              </span>
            </button>
          );
        })}
      </div>

      {/* Nota al pie, no una cuarta tarjeta: quien abre «Crear comprobante»
          buscando su retención tiene que encontrar el camino, pero sin que
          parezca uno de los documentos que se emiten desde aquí. Se dice lo
          que la distingue —no se emite, se guarda— y se lleva a la bandeja,
          que está en esta misma sección. */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 11,
          marginTop: 16,
          paddingTop: 14,
          borderTop: "1px solid var(--borde)",
        }}
      >
        <span
          aria-hidden="true"
          style={{
            flex: "none",
            width: 28,
            height: 28,
            borderRadius: 9,
            display: "grid",
            placeItems: "center",
            background: TONOS.gris.fondo,
            color: TONOS.gris.color,
          }}
        >
          <Svg d={ICONO_PORCENTAJE} tamano={15} />
        </span>
        <p
          style={{
            margin: 0,
            fontSize: 12.5,
            lineHeight: 1.55,
            color: "var(--texto-tenue)",
            textWrap: "pretty",
          }}
        >
          ¿Te retuvieron a ti y tu cliente te mandó el comprobante? Eso no lo emites tú: se guarda.{" "}
          <button
            type="button"
            className="fc-btn fc-btn--texto"
            style={{ fontSize: 12.5 }}
            onClick={onRetenciones}
          >
            Súbelo en Retenciones
          </button>
        </p>
      </div>
    </div>
  );
}

/* --- Pantalla 2: nueva factura ---------------------------------------------- */

const etiquetaVariante = (v: ProductoVariante, nombres: Record<string, string>) =>
  v.valores
    .map((x) => nombres[x.atributo_valor_id])
    .filter(Boolean)
    .join(" / ") || v.codigo;

const filaElegible = {
  display: "flex",
  alignItems: "center",
  gap: 11,
  width: "100%",
  padding: "9px 12px",
  border: "1px solid var(--borde)",
  borderRadius: "var(--radio-campo)",
  background: "var(--superficie)",
  textAlign: "left",
  font: "inherit",
  color: "inherit",
  cursor: "pointer",
} as const;

/** Buscador de cliente. La lista se pide UNA vez y se filtra en memoria: una
 *  petición por pulsación sería un bombardeo por escribir un nombre. */
function BuscadorCliente({
  clientes,
  onElegir,
}: {
  clientes: ClienteFinal[] | null;
  onElegir: (c: ClienteFinal | "final") => void;
}) {
  const [texto, setTexto] = useState("");

  const encontrados = useMemo(() => {
    const t = texto.trim().toLowerCase();
    if (!t) return clientes ?? [];
    return (clientes ?? []).filter(
      (c) => c.razon_social.toLowerCase().includes(t) || c.identificacion.includes(t),
    );
  }, [clientes, texto]);

  const visibles = encontrados.slice(0, 6);

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <input
        className="fc-campo"
        type="search"
        aria-label="Buscar cliente"
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        placeholder="Busca por nombre, RUC o cédula"
      />

      {/* La venta sin cliente es una opción legítima y frecuente: va a la
          vista, no escondida detrás de «no encuentro a nadie». */}
      <button
        type="button"
        onClick={() => onElegir("final")}
        style={{ ...filaElegible, borderStyle: "dashed" }}
      >
        <span className="fc-avatar" aria-hidden="true" style={{ background: "var(--superficie-tenue)", color: "var(--texto-tenue)" }}>
          ?
        </span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: "block", fontWeight: 600, fontSize: 13.5 }}>
            Sin cliente · consumidor final
          </span>
          <span style={{ display: "block", fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 1 }}>
            Para ventas de hasta {dinero(TOPE_CONSUMIDOR_FINAL / 100)}, sin pedir datos.
          </span>
        </span>
      </button>

      {clientes === null && (
        <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0 }}>Cargando tu libreta…</p>
      )}
      {clientes !== null && encontrados.length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0 }}>
          {texto ? "Ningún cliente coincide con eso." : "Tu libreta está vacía."}
        </p>
      )}
      {/* Misma razón que en el catálogo: una libreta larga estiraba el modal. */}
      <div style={{ display: "grid", gap: 8, maxHeight: 280, overflowY: "auto" }}>
      {visibles.map((c) => (
        <button key={c.id} type="button" style={filaElegible} onClick={() => onElegir(c)}>
          <span className="fc-avatar" aria-hidden="true">
            {inicial(c.razon_social)}
          </span>
          <span style={{ flex: 1, minWidth: 0 }}>
            <span style={{ display: "block", fontWeight: 600, fontSize: 13.5 }}>{c.razon_social}</span>
            <span
              className="fc-mono"
              style={{ display: "block", fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 1 }}
            >
              {c.identificacion}
            </span>
          </span>
        </button>
      ))}
      </div>
      {encontrados.length > visibles.length && (
        <p style={{ fontSize: 11.5, color: "var(--texto-tenue)", margin: 0 }}>
          Y {encontrados.length - visibles.length} más. Escribe para acotar la búsqueda.
        </p>
      )}
    </div>
  );
}

/** Buscador de la factura que la nota —de crédito o de débito— modifica.
 *
 *  Mismo patrón que el de clientes —una petición y filtrado en memoria— y por la
 *  misma razón. Lo importante es que aquí SOLO salen las que el servidor da por
 *  buenas: autorizadas por el SRI, y con saldo si la nota es de crédito (la de
 *  débito pide la misma lista con `?solo_con_saldo=false`, porque un recargo no
 *  consume saldo). Elegir de esta lista es la única forma de que el número, la
 *  fecha y el cliente de la nota sean los que el SRI ya conoce; tecleados a mano
 *  no hay nada que comprobar. */
function SelectorFactura({
  facturas,
  recargo,
  onElegir,
}: {
  facturas: FacturaAcreditable[] | null;
  /** La lista es para una nota de DÉBITO: el saldo por acreditar no pinta nada
   *  aquí —no es lo que se va a cobrar— y decir «no tienes facturas que anular»
   *  sería contar otra historia. */
  recargo?: boolean;
  onElegir: (f: FacturaAcreditable) => void;
}) {
  const [texto, setTexto] = useState("");

  const encontradas = useMemo(() => {
    const t = texto.trim().toLowerCase();
    if (!t) return facturas ?? [];
    return (facturas ?? []).filter(
      (f) =>
        f.numero.includes(t) ||
        (f.cliente ?? "").toLowerCase().includes(t) ||
        (f.cliente_identificacion ?? "").includes(t),
    );
  }, [facturas, texto]);

  const visibles = encontradas.slice(0, 6);

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <input
        className="fc-campo"
        type="search"
        aria-label="Buscar la factura"
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        placeholder="Busca por número o por cliente"
      />

      {facturas === null && (
        <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0 }}>
          Buscando tus facturas…
        </p>
      )}
      {facturas !== null && encontradas.length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0 }}>
          {texto
            ? "Ninguna factura coincide con eso."
            : recargo
              ? "No tienes facturas a las que cobrarles un recargo. Solo se puede sobre una que el SRI ya autorizó."
              : "No tienes facturas que se puedan anular. Solo se puede sobre una que el SRI ya autorizó y a la que le quede importe."}
        </p>
      )}

      <div className="fc-scroll" style={{ display: "grid", gap: 8, maxHeight: 300, overflowY: "auto", paddingRight: 4 }}>
        {visibles.map((f) => {
          const parcial = !recargo && Number(f.acreditado) > 0;
          return (
            <button key={f.id} type="button" style={filaElegible} onClick={() => onElegir(f)}>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span className="fc-mono" style={{ display: "block", fontWeight: 600, fontSize: 13.5 }}>
                  {f.numero}
                </span>
                <span
                  style={{ display: "block", fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 1 }}
                >
                  {(f.cliente_final_id === null ? null : f.cliente) ?? "Consumidor final"} ·{" "}
                  {fechaCorta(f.fecha_emision)}
                </span>
              </span>
              <span style={{ textAlign: "right" }}>
                <span style={{ display: "block", fontWeight: 600, fontSize: 13 }}>
                  {dinero(f.total)}
                </span>
                {/* Ya lleva una nota encima: lo que importa no es su total, es
                    lo que todavía se le puede devolver. */}
                {parcial && (
                  <span style={{ display: "block", fontSize: 11, color: "var(--aviso-texto)", marginTop: 1 }}>
                    quedan {dinero(f.pendiente)}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>
      {encontradas.length > visibles.length && (
        <p style={{ fontSize: 11.5, color: "var(--texto-tenue)", margin: 0 }}>
          Y {encontradas.length - visibles.length} más. Escribe para acotar la búsqueda.
        </p>
      )}
    </div>
  );
}

/** Las líneas de la factura, tal cual, para que la nota arranque reflejándola.
 *
 *  EL DESCUENTO NO VIENE. `GET /comprobantes/acreditables` devuelve seis campos
 *  por línea (`CAMPOS_ITEM` en las rutas) y `descuento` no es uno de ellos; el
 *  snapshot del payload sí lo guarda, pero no sale por esa puerta. Consecuencia
 *  concreta, ahora que el formulario SÍ ofrece rebajar: una factura de $100 con
 *  $20 de descuento tiene un `pendiente` de $92, y estas líneas precargadas
 *  suman $115. La nota no se puede emitir hasta que cuadre.
 *
 *  Por eso el campo «Descuento $» también está en la nota de crédito, y no solo
 *  en la factura: es la forma de reponer esos $20 y devolver la factura ENTERA
 *  dejando la nota línea a línea igual que el original —mismo precio unitario,
 *  mismo descuento—, que es lo que compara quien pone los dos papeles juntos.
 *  Bajar el precio a $80 daría el mismo total y un documento que no se parece
 *  al que corrige. `excedePendiente` frena mientras no cuadre y el aviso dice
 *  que mire el descuento; ver también el comentario de ese aviso.
 *
 *  La nota de DÉBITO no entra en nada de esto: no tiene líneas. */
const lineasDe = (f: FacturaAcreditable): Linea[] =>
  f.items.map((i, n) => ({
    clave: `${f.id}-${n}`,
    codigo: i.codigo,
    descripcion: i.descripcion,
    cantidad: String(Number(i.cantidad)),
    precio: String(Number(i.precio_unitario)),
    // La rebaja que llevaba la línea EN LA FACTURA. Dejarla en blanco precargaba
    // la nota con el precio de tarifa y no con lo que el cliente pagó: una venta
    // rebajada no se podía ni anular, porque la nota nacía pasándose del
    // pendiente y el botón salía apagado.
    descuento: Number(i.descuento) > 0 ? String(Number(i.descuento)) : "",
    codigoIva: i.codigo_iva,
    porcentaje: Number(i.tarifa_iva),
  }));

/** Sin existencias. Solo aplica a lo que lleva conteo: un servicio o un artículo
 *  sin inventario nunca está agotado. Con variantes, lo está cuando NINGUNA
 *  combinación tiene unidades. */
const agotado = (p: Producto) => {
  if (!p.maneja_inventario) return false;
  const activas = p.variantes.filter((v) => v.activo);
  return activas.length > 0
    ? activas.every((v) => Number(v.stock) <= 0)
    : Number(p.stock) <= 0;
};

/** Catálogo real (/productos). Un producto CON variantes no se puede agregar
 *  tal cual: el código que va impreso en el comprobante es el de la variante y
 *  su precio puede ser propio, así que primero hay que elegir cuál. */
function SelectorProducto({
  productos,
  nombreValor,
  onElegir,
  onCerrar,
}: {
  productos: Producto[] | null;
  nombreValor: Record<string, string>;
  onElegir: (p: Producto, v: ProductoVariante | null) => void;
  onCerrar: () => void;
}) {
  const [texto, setTexto] = useState("");
  const [abierto, setAbierto] = useState<string | null>(null);

  const encontrados = useMemo(() => {
    const t = texto.trim().toLowerCase();
    return (productos ?? []).filter(
      (p) => !t || p.nombre.toLowerCase().includes(t) || p.codigo.toLowerCase().includes(t),
    );
  }, [productos, texto]);

  const visibles = encontrados.slice(0, 6);

  return (
    <div
      style={{
        display: "grid",
        gap: 8,
        padding: 12,
        border: "1px solid var(--borde)",
        borderRadius: "var(--radio-panel)",
        background: "var(--superficie-suave)",
      }}
    >
      <input
        className="fc-campo"
        type="search"
        aria-label="Buscar en el catálogo"
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        placeholder="Busca en tu catálogo por nombre o código"
      />
      {productos === null && (
        <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0 }}>Cargando el catálogo…</p>
      )}
      {productos !== null && encontrados.length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0 }}>
          {texto ? "Nada coincide con eso." : "Tu catálogo está vacío."}
        </p>
      )}
      {/* La lista desplaza por dentro y el buscador se queda fijo arriba: sin
          esto, un catálogo largo estiraba el modal hasta sacar de la pantalla
          los totales y el botón de emitir. `overflowY` explícito porque
          `maxHeight` a secas no recorta nada, solo limita la caja; y `fc-scroll`
          para que la barra sea la fina del panel y no la gruesa del sistema. */}
      <div
        className="fc-scroll"
        style={{ display: "grid", gap: 8, maxHeight: 300, overflowY: "auto", paddingRight: 4 }}
      >
      {visibles.map((p) => {
        const variantes = p.variantes.filter((v) => v.activo);
        const desplegado = abierto === p.id;
        return (
          <div key={p.id} style={{ display: "grid", gap: 7 }}>
            <button
              type="button"
              style={filaElegible}
              aria-expanded={variantes.length > 0 ? desplegado : undefined}
              onClick={() =>
                variantes.length > 0
                  ? setAbierto(desplegado ? null : p.id)
                  : onElegir(p, null)
              }
            >
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: "block", fontWeight: 600, fontSize: 13.5 }}>{p.nombre}</span>
                <span
                  style={{ display: "block", fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 1 }}
                >
                  <span className="fc-mono">{p.codigo}</span> · IVA {Number(p.porcentaje_iva)}%
                  {variantes.length > 0 && ` · ${variantes.length} combinaciones`}
                </span>
              </span>
              {/* Avisa ANTES de agregarlo, no al emitir. No lo bloquea: se
                  puede facturar sin existencias (un encargo, una reposición en
                  camino), pero quien vende tiene que verlo. */}
              {agotado(p) && (
                <span
                  className="fc-estado fc-estado--error"
                  style={{ fontSize: 11, padding: "3px 9px" }}
                >
                  Agotado
                </span>
              )}
              <span style={{ fontWeight: 600, fontSize: 13 }}>{dinero(p.precio_sin_iva)}</span>
            </button>
            {desplegado && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, paddingLeft: 12 }}>
                {variantes.map((v) => (
                  <button
                    key={v.id}
                    type="button"
                    className="fc-chip"
                    // Atenuada, no bloqueada: la talla 38 puede estar agotada y
                    // aun así facturarse, pero no de forma inadvertida.
                    style={{
                      padding: "6px 12px",
                      ...(p.maneja_inventario && Number(v.stock) <= 0
                        ? { opacity: 0.5 }
                        : undefined),
                    }}
                    title={
                      p.maneja_inventario && Number(v.stock) <= 0 ? "Sin existencias" : undefined
                    }
                    onClick={() => onElegir(p, v)}
                  >
                    {etiquetaVariante(v, nombreValor)} ·{" "}
                    {dinero(v.precio_sin_iva ?? p.precio_sin_iva)}
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}
      </div>
      <button
        type="button"
        className="fc-btn fc-btn--texto"
        style={{ justifySelf: "center", fontSize: 12.5 }}
        onClick={onCerrar}
      >
        Cerrar
      </button>
    </div>
  );
}

function Fila({
  etiqueta,
  valor,
  fuerte,
  grande,
}: {
  etiqueta: string;
  valor: ReactNode;
  fuerte?: boolean;
  /** El importe total de la revisión: es LA cifra del documento y se lee de un
   *  vistazo, sin buscarla entre las demás. */
  grande?: boolean;
}) {
  const destacada = fuerte || grande;
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 20,
        alignItems: "baseline",
        ...(grande ? { borderTop: "1px solid var(--borde)", paddingTop: 10, marginTop: 3 } : null),
      }}
    >
      <span
        style={{
          fontSize: destacada ? 14 : 13,
          fontWeight: grande ? 700 : undefined,
          color: destacada ? "var(--texto)" : "var(--texto-tenue)",
        }}
      >
        {etiqueta}
      </span>
      <span
        className={grande ? "fc-cifra" : undefined}
        style={{
          fontSize: grande ? 26 : fuerte ? 18 : 13,
          fontWeight: destacada ? 700 : 500,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {valor}
      </span>
    </div>
  );
}

/* --- Pantalla 3: revisa tu factura ------------------------------------------ */

const RASGO_TENUE = { fontSize: 12.5, color: "var(--texto-tenue)", margin: "2px 0 0" } as const;

function BloqueDocumento({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <div style={{ flex: "1 1 240px", minWidth: 0 }}>
      <p className="fc-kicker">{titulo}</p>
      {children}
    </div>
  );
}

/** «Revisa tu factura»: el documento que va a salir, no un formulario.
 *
 *  Todo lo que se pinta aquí es lo que el servidor va a firmar: los datos del
 *  emisor salen de /panel/estado (los mismos que imprime el RIDE), los totales
 *  de `totalizar` —que replica la aritmética del servidor al céntimo, incluido
 *  el IVA por tarifa— y el número es la PREVISIÓN de /siguiente-numero, que no
 *  reserva nada y por eso se rotula como tal.
 *
 *  Sirve igual para las dos notas: cambian el rótulo, el botón y un bloque con
 *  la factura de origen y el motivo —lo único que la nota lleva de más y que
 *  también va IMPRESO—. La de débito además NO lleva tabla de líneas: no vende
 *  nada, cobra un importe, y su desglose es el cuadro de totales. El resto del
 *  documento es el mismo, así que no hay una segunda pantalla que mantener. */
function Revision({
  emisor,
  tipo,
  numero,
  comprador,
  origen,
  formaPago,
  lineas,
  totales,
  correo,
  onCorreo,
  correoValido,
  error,
  aviso,
  congelado,
  onVolver,
  onEmitir,
  onCerrar,
}: {
  emisor: Emisor | null;
  tipo: Tipo;
  numero: string | null;
  comprador: Comprador;
  /** Solo la nota: la factura que modifica y por qué. Los dos van impresos.
   *  `tecleada` = el número se escribió a mano en vez de elegirlo del historial;
   *  entonces la fecha de aquí es la que puso el usuario y el servidor la
   *  sustituye por la real si esa factura resulta ser suya. */
  origen?: { numero: string; fecha: string; motivo: string; tecleada: boolean };
  formaPago: string | undefined;
  lineas: Linea[];
  totales: ReturnType<typeof totalizar>;
  correo: string;
  onCorreo: (v: string) => void;
  correoValido: boolean;
  error: string | null;
  /** Algo que salió mal PERO no impide emitir (hoy: un artículo que no se pudo
   *  guardar en el catálogo). Va aparte de `error` a propósito: pintarlo en rojo
   *  junto al que sí frena la emisión haría creer que la factura no salió. */
  aviso: string | null;
  congelado: boolean;
  onVolver: () => void;
  onEmitir: () => void;
  onCerrar: () => void;
}) {
  const [editandoCorreo, setEditandoCorreo] = useState(false);
  const esNota = tipo !== "FACTURA";
  const esDebito = tipo === "NOTA_DEBITO";
  const doc = DOC[tipo];
  const titulo = `Revisa tu ${doc}`;

  return (
    <div className="fc-modal" role="dialog" aria-modal="true" aria-label={titulo}>
      <div className="fc-modal__panel fc-modal__panel--fijo" style={{ maxWidth: 760 }}>
        <Cabecera
          fijo
          titulo={titulo}
          subtitulo={
            esNota
              ? "Así va a salir. Al emitirla ya no se puede corregir ni deshacer."
              : "Así va a salir. Al emitirla ya no se puede corregir: haría falta una nota de crédito."
          }
          onCerrar={onCerrar}
        />

        <div className="fc-modal__cuerpo fc-scroll" style={{ paddingTop: 16, display: "grid", gap: 16 }}>
          {/* Cabecera del documento: emisor, número previsto y fecha */}
          <div
            style={{
              display: "flex",
              gap: 18,
              flexWrap: "wrap",
              border: "1px solid var(--borde)",
              borderRadius: "var(--radio-panel)",
              background: "var(--superficie-suave)",
              padding: "16px 18px",
            }}
          >
            <BloqueDocumento titulo="Emisor">
              {emisor ? (
                <>
                  <p style={{ fontWeight: 700, fontSize: 15, margin: 0 }}>
                    {emisor.nombre_comercial ?? emisor.razon_social}
                  </p>
                  {emisor.nombre_comercial && <p style={RASGO_TENUE}>{emisor.razon_social}</p>}
                  <p className="fc-mono" style={RASGO_TENUE}>
                    RUC {emisor.ruc}
                  </p>
                  {/* Si el perfil no tiene dirección, el servidor manda null y
                      aquí no se pinta la línea: el «S/D» que exige el XML es
                      para el SRI, no para que lo lea una persona. */}
                  {emisor.direccion_matriz && <p style={RASGO_TENUE}>{emisor.direccion_matriz}</p>}
                  <p style={RASGO_TENUE}>
                    {emisor.obligado_contabilidad ? "Obligado" : "No obligado"} a llevar contabilidad
                  </p>
                </>
              ) : (
                <p style={RASGO_TENUE}>Cargando los datos de tu negocio…</p>
              )}
            </BloqueDocumento>

            <div style={{ flex: "1 1 200px", minWidth: 0, textAlign: "right" }}>
              <p className="fc-kicker">{ETIQUETA_TIPO[tipo]}</p>
              <p className="fc-mono" style={{ fontSize: 14, fontWeight: 700, margin: 0 }}>
                {numero ?? "—"}
              </p>
              {/* El servidor NO reserva el número al enseñarlo: si alguien emite
                  entre medias, el definitivo será otro. Prometerlo aquí sería
                  mentir sobre el único dato que el usuario luego busca. */}
              <p style={{ ...RASGO_TENUE, fontStyle: "italic" }}>Se asigna al emitir</p>
              <p style={{ ...RASGO_TENUE, marginTop: 8 }}>
                Fecha de emisión
                <br />
                <span style={{ color: "var(--texto)", fontWeight: 600 }}>
                  {fechaLarga(hoyEnEcuador())}
                </span>
              </p>
            </div>
          </div>

          <div
            style={{
              display: "flex",
              gap: 18,
              flexWrap: "wrap",
              border: "1px solid var(--borde)",
              borderRadius: "var(--radio-panel)",
              padding: "16px 18px",
            }}
          >
            <BloqueDocumento titulo="Comprador">
              <p style={{ fontWeight: 700, fontSize: 15, margin: 0 }}>{comprador.nombre}</p>
              <p className="fc-mono" style={RASGO_TENUE}>
                {comprador.identificacion}
              </p>
              {comprador.direccion && <p style={RASGO_TENUE}>{comprador.direccion}</p>}
              {comprador.telefono && <p style={RASGO_TENUE}>{comprador.telefono}</p>}
            </BloqueDocumento>
            {/* También va impreso en el comprobante, y es lo último que se elige
                en el formulario: verlo aquí evita emitir un «Efectivo» que en
                realidad se cobró por transferencia. */}
            {formaPago && (
              <div style={{ flex: "0 1 auto", textAlign: "right" }}>
                <p className="fc-kicker">Forma de pago</p>
                <p style={{ fontWeight: 600, fontSize: 13.5, margin: 0 }}>{formaPago}</p>
              </div>
            )}
          </div>

          {/* Lo que la nota lleva de más, y que va IMPRESO en el papel: a qué
              factura se refiere y por qué. Verlo aquí es la última oportunidad
              de cazar un motivo escrito de cualquier manera —lo va a leer el
              cliente, y el SRI lo guarda tal cual. */}
          {origen && (
            <div
              style={{
                display: "flex",
                gap: 18,
                flexWrap: "wrap",
                border: "1px solid var(--borde)",
                borderRadius: "var(--radio-panel)",
                padding: "16px 18px",
              }}
            >
              <BloqueDocumento titulo={esDebito ? "Recarga la factura" : "Modifica la factura"}>
                <p className="fc-mono" style={{ fontWeight: 700, fontSize: 15, margin: 0 }}>
                  {origen.numero}
                </p>
                <p style={RASGO_TENUE}>
                  Emitida el {fechaLarga(origen.fecha)}
                  {/* El número tecleado a mano puede ser de una factura que SÍ
                      está en el historial, y en ese caso manda la fecha real,
                      no la escrita: sin este aviso la pantalla enseñaría una
                      fecha y el documento saldría firmado con otra. */}
                  {origen.tecleada && " (si esa factura está en tu historial, se usa su fecha real)"}
                </p>
              </BloqueDocumento>
              <BloqueDocumento titulo={esDebito ? "Concepto del recargo" : "Motivo"}>
                <p style={{ fontSize: 13.5, margin: 0, lineHeight: 1.5, textWrap: "pretty" }}>
                  {origen.motivo}
                </p>
              </BloqueDocumento>
            </div>
          )}

          {/* Las líneas, como en el RIDE: código y descripción a la izquierda,
              las cifras alineadas a la derecha para poder repasarlas en columna.
              La nota de débito no tiene: su única «línea» es el recargo, que ya
              se lee arriba como concepto y abajo como importe. Una tabla de una
              fila con «RECARGO · 1 · 17,39» solo invitaría a buscarle sentido. */}
          {!esDebito && (
          <div style={{ overflowX: "auto", border: "1px solid var(--borde)", borderRadius: "var(--radio-panel)" }}>
            <table className="fc-tabla">
              <thead>
                <tr>
                  <th scope="col">Descripción</th>
                  <th scope="col" className="fc-num">Cant.</th>
                  <th scope="col" className="fc-num">P. unitario</th>
                  <th scope="col" className="fc-num">IVA</th>
                  <th scope="col" className="fc-num">Importe</th>
                </tr>
              </thead>
              <tbody>
                {lineas.map((l) => (
                  <tr key={l.clave}>
                    <td>
                      <span style={{ fontWeight: 600 }}>{l.descripcion}</span>
                      <span className="fc-mono" style={{ display: "block", color: "var(--texto-tenue)" }}>
                        {l.codigo}
                      </span>
                      {/* La rebaja, junto a la línea que rebaja y no en una sexta
                          columna: con cinco ya hay que desplazar de lado en el
                          móvil, y la columna estaría vacía en casi todas las
                          facturas. El importe de la derecha ya viene descontado,
                          así que sin esta línea el precio unitario × la cantidad
                          no cuadraría con él y parecería un error de la cuenta. */}
                      {num(l.descuento) > 0 && (
                        <span style={{ display: "block", color: "var(--texto-tenue)" }}>
                          menos {dinero(num(l.descuento))} de descuento
                        </span>
                      )}
                    </td>
                    <td className="fc-num">{num(l.cantidad)}</td>
                    <td className="fc-num">{dinero(num(l.precio))}</td>
                    <td className="fc-num">{l.porcentaje}%</td>
                    <td className="fc-num" style={{ fontWeight: 600 }}>
                      {dinero(importeLinea(l) / 100)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          )}

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <div
              style={{
                display: "grid",
                gap: 7,
                minWidth: 280,
                padding: "14px 16px",
                borderRadius: "var(--radio-panel)",
                background: "var(--superficie-tenue)",
              }}
            >
              {/* Una fila por TARIFA, que es como lo agrupa el servidor y como
                  sale impreso: una línea de «IVA» a secas mezclaría el 15% con
                  el 0% y no cuadraría con el comprobante. */}
              {totales.porTarifa.map((g) => (
                <Fila
                  key={`base-${g.codigoIva}`}
                  etiqueta={`Subtotal ${g.tarifa}%`}
                  valor={dinero(g.base / 100)}
                />
              ))}
              {/* Estos «Subtotal N%» ya vienen DESCONTADOS, y el descuento va
                  debajo como un dato: es el orden del RIDE (SUBTOTAL n%,
                  SUBTOTAL SIN IMPUESTOS, TOTAL DESCUENTO, IVA, TOTAL) y esta
                  pantalla enseña el documento, no la cuenta. La suma que se
                  sigue con el dedo está en el formulario, que es donde se está
                  decidiendo.

                  Sin descuento no se pinta la fila: antes salía un «$0.00» fijo
                  porque el formulario no sabía rebajar; ahora que sí, una fila a
                  cero solo sería ruido en la inmensa mayoría de las facturas. */}
              {totales.descuento > 0 && (
                <Fila etiqueta="Descuento" valor={dinero(totales.descuento / 100)} />
              )}
              {totales.porTarifa
                .filter((g) => g.tarifa > 0)
                .map((g) => (
                  <Fila key={`iva-${g.codigoIva}`} etiqueta={`IVA ${g.tarifa}%`} valor={dinero(g.iva / 100)} />
                ))}
              <Fila etiqueta="Importe total" valor={dinero(totales.total / 100)} grande />
            </div>
          </div>

          {/* La confusión que hay que evitar aquí: creer que este documento
              SUSTITUYE a la factura. No: se suma. Y el importe que se lee arriba
              es el definitivo —el que firma el servidor—, aunque en el
              formulario se tecleara un centavo menos. */}
          {esDebito && origen && (
            <p
              style={{
                margin: 0,
                padding: "12px 14px",
                borderRadius: "var(--radio-campo)",
                background: "var(--aviso-bg)",
                color: "var(--aviso-texto)",
                fontSize: 13,
                lineHeight: 1.55,
                textWrap: "pretty",
              }}
            >
              La factura {origen.numero} sigue en pie: esto no la reemplaza, se le
              suma. Tu cliente te deberá <strong>{dinero(totales.total / 100)}</strong> más.
            </p>
          )}

          {/* A dónde va la copia. Se edita aquí mismo porque es el momento en que
              se piensa en ello («que le llegue a mi contador»), y cambiarlo NO
              toca la ficha del cliente: vale solo para esta factura. */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 11,
              flexWrap: "wrap",
              padding: "12px 14px",
              borderRadius: "var(--radio-campo)",
              background: "var(--exito-bg)",
              border: "1px solid var(--exito-borde)",
            }}
          >
            <span aria-hidden="true" style={{ display: "grid", color: "var(--verde-medio)" }}>
              <Svg d={ICONO_SOBRE} tamano={16} />
            </span>
            {editandoCorreo ? (
              <input
                className="fc-campo"
                style={{ flex: "1 1 220px", padding: "8px 11px" }}
                type="email"
                autoFocus
                aria-label="Correo al que se enviará la factura"
                aria-invalid={!correoValido}
                placeholder="correo@cliente.com"
                value={correo}
                onChange={(e) => onCorreo(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && correoValido && setEditandoCorreo(false)}
              />
            ) : (
              <span style={{ flex: "1 1 200px", minWidth: 0, fontSize: 13.5 }}>
                {correo ? (
                  <>
                    Se enviará a: <strong>{correo}</strong>
                  </>
                ) : (
                  `Sin correo: la ${esNota ? "nota" : "factura"} se emite igual y queda en tu historial.`
                )}
              </span>
            )}
            <button
              type="button"
              className="fc-btn-icono"
              aria-label={editandoCorreo ? "Guardar el correo" : "Editar el correo"}
              aria-expanded={editandoCorreo}
              // Congelado: el borrador ya existe con su correo dentro, así que
              // editarlo aquí no cambiaría nada de lo que se va a enviar.
              disabled={congelado || (editandoCorreo && !correoValido)}
              onClick={() => setEditandoCorreo((v) => !v)}
            >
              <Svg d={editandoCorreo ? ICONO_CHECK : ICONO_LAPIZ} tamano={14} />
            </button>
          </div>
          {!correoValido && (
            <p className="fc-error" role="alert" style={{ margin: 0 }}>
              Ese correo no parece válido. Corrígelo o déjalo vacío para no enviar copia.
            </p>
          )}
        </div>

        <div className="fc-modal__pie" style={{ borderTop: "1px solid var(--borde)" }}>
          {error && (
            <p className="fc-error" role="alert" style={{ flexBasis: "100%", margin: 0 }}>
              {error}
            </p>
          )}
          {aviso && (
            <p
              role="status"
              style={{
                flexBasis: "100%",
                margin: 0,
                fontSize: 12.5,
                lineHeight: 1.5,
                color: "var(--aviso-texto)",
              }}
            >
              {aviso}
            </p>
          )}
          {/* Con el borrador ya creado, volver a editar no cambiaría nada de lo
              guardado: lo único que queda es reintentar el envío. */}
          <button type="button" className="fc-btn fc-btn--contorno" disabled={congelado} onClick={onVolver}>
            Volver a editar
          </button>
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            disabled={!correoValido}
            onClick={onEmitir}
          >
            {congelado ? "Reintentar el envío" : `Emitir ${doc}`}
          </button>
        </div>
      </div>
    </div>
  );
}

/* --- Pantalla 4: enviando y desenlace --------------------------------------- */

/** Los tres desenlaces posibles, que son los del comprobante y no los del
 *  formulario: el SRI ya dijo que sí, todavía no ha dicho nada, o dijo que no.
 *
 *  Ninguno es un error de la aplicación —tardar es normal en el SRI, que se cae
 *  a menudo—, y quien factura desde el móvil no puede quedarse con la duda de si
 *  salió. `doc` es cómo se llama el documento en voz alta («factura», «nota de
 *  crédito»): los tres son femeninos, así que el texto no cambia de forma.
 *
 *  Nada de «te avisamos»: el único correo que manda el servidor al autorizar va
 *  al COMPRADOR con su PDF adjunto (`app/tasks/emision.py::_paso_ride_y_correo`),
 *  no a quien emite. Prometerle un aviso que nadie le va a mandar es lo que le
 *  hace volver a mirar creyendo que se atascó. */
const DESENLACES = {
  autorizado: {
    icono: ICONO_CHECK,
    clase: "fc-estado--exito",
    titulo: (doc: string) => `El SRI autorizó tu ${doc}.`,
    texto: () => "Ya es válida y quedó en tu historial. Puedes descargar el PDF para tu cliente.",
  },
  // «En cola» y «en camino» no son lo mismo y no se pueden contar igual: en
  // PENDIENTE el documento NI se ha firmado NI ha salido, solo está encolado, y
  // decirle «ya salió» es la misma mentira que se vino a arreglar, un paso antes.
  cola: {
    icono: ICONO_RELOJ,
    clase: "fc-estado--aviso",
    titulo: (doc: string) => `Tu ${doc} está en cola.`,
    texto: () =>
      "Todavía no ha salido: espera turno. Se envía sola, y si se queda atrás la reintentamos nosotros.",
  },
  camino: {
    icono: ICONO_RELOJ,
    clase: "fc-estado--aviso",
    titulo: (doc: string) => `Tu ${doc} va en camino al SRI.`,
    texto: () =>
      "Ya salió y se autoriza sola: no tienes que hacer nada. El estado lo tienes en tu historial.",
  },
  devuelto: {
    icono: ICONO_AVISO,
    clase: "fc-estado--error",
    titulo: (doc: string) => `El SRI devolvió tu ${doc}.`,
    texto: () => "Está en tu historial con el motivo; desde ahí puedes reintentar el envío.",
  },
  // RECHAZADO no es «el SRI dijo que no»: el pipeline lo pone TAMBIÉN cuando el
  // envío no llegó a salir (sin certificado, caducado, el .p12 no se deja abrir).
  // Echarle la culpa al SRI de un problema propio manda al usuario a reintentar
  // algo que va a fallar igual hasta que arregle lo suyo; el motivo, que ya se
  // pinta debajo, es quien lo cuenta.
  fallido: {
    icono: ICONO_AVISO,
    clase: "fc-estado--error",
    titulo: (doc: string) => `No pudimos emitir tu ${doc}.`,
    texto: () => "Abajo tienes el motivo. Queda en tu historial y desde ahí puedes reintentarlo.",
  },
} as const;

type ClaveDesenlace = keyof typeof DESENLACES;

function PanelDesenlace({
  clave,
  doc,
  salida,
  vigilando,
  aviso,
  onVer,
  onOtra,
}: {
  clave: ClaveDesenlace;
  doc: string;
  /** Lo que no salió del todo bien pero no tiene que ver con el SRI: hoy, un
   *  artículo que no se pudo guardar en el catálogo. Aquí es donde el usuario
   *  aterriza tras emitir, así que aquí es donde se entera. */
  aviso: string | null;
  /** El comprobante tal y como lo dejó el SRI. De aquí salen el motivo del
   *  rechazo y el PDF; null = no se ha podido consultar todavía. */
  salida: Comprobante | null;
  /** El sondeo sigue vivo: esta pantalla puede cambiar sola. */
  vigilando: boolean;
  onVer: () => void;
  onOtra: () => void;
}) {
  const d = DESENLACES[clave];
  const mensajes = salida?.mensajes ?? [];
  const [bajando, setBajando] = useState(false);
  const [falloPdf, setFalloPdf] = useState<string | null>(null);
  return (
    <div
      className="fc-modal__panel"
      style={{ maxWidth: 440, textAlign: "center" }}
      role="status"
      aria-live="polite"
    >
      <span
        className={`fc-estado ${d.clase}`}
        aria-hidden="true"
        style={{ width: 52, height: 52, borderRadius: "50%", padding: 0, justifyContent: "center" }}
      >
        <Svg d={d.icono} tamano={24} />
      </span>
      <p style={{ fontSize: 16.5, fontWeight: 700, margin: "16px 0 0" }}>{d.titulo(doc)}</p>
      <p style={{ fontSize: 13.5, color: "var(--texto-suave)", margin: "7px 0 0", lineHeight: 1.55 }}>
        {d.texto()}
      </p>
      {mensajes.length > 0 && (
        <p style={{ fontSize: 12.5, color: "var(--error-texto)", margin: "10px 0 0" }}>{mensajes[0]}</p>
      )}
      {/* Se dice que la pantalla sigue mirando, porque va a cambiar sola
          delante del usuario. Cuando el sondeo se agota deja de decirlo: el
          texto de arriba vale igual sin él. */}
      {vigilando && (
        <p style={{ fontSize: 12, color: "var(--texto-tenue)", margin: "10px 0 0" }}>
          Seguimos mirando: si el SRI contesta mientras tienes esto abierto, lo verás aquí.
        </p>
      )}
      {aviso && (
        <p
          style={{
            margin: "12px 0 0",
            padding: "10px 12px",
            borderRadius: "var(--radio-campo)",
            background: "var(--aviso-bg)",
            color: "var(--aviso-texto)",
            fontSize: 12.5,
            lineHeight: 1.5,
            textAlign: "left",
            textWrap: "pretty",
          }}
        >
          {aviso}
        </p>
      )}
      {falloPdf && (
        <p className="fc-error" role="alert" style={{ margin: "10px 0 0" }}>
          {falloPdf}
        </p>
      )}
      <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 22, flexWrap: "wrap" }}>
        {/* Autorizada es justo cuando se quiere el PDF, y la ruta existe
            (`GET /comprobantes/{id}/ride`, la misma del historial). Sin
            autorización no hay RIDE que bajar, así que fuera de aquí no se
            ofrece un botón que solo daría un 404. */}
        {clave === "autorizado" && salida !== null && (
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            disabled={bajando}
            onClick={async () => {
              setBajando(true);
              setFalloPdf(null);
              try {
                await api.descargar(`/comprobantes/${salida.id}/ride`, `${salida.numero ?? doc}.pdf`);
              } catch (e) {
                // El PDF se dibuja DESPUÉS de la autorización, en el mismo paso
                // que manda el correo (`_paso_ride_y_correo`), así que recién
                // autorizada el servidor contesta «Archivo aún no disponible»
                // durante un par de segundos. Se dice el motivo y qué hacer.
                setFalloPdf(
                  `${textoError(e)} Si se acaba de autorizar, el PDF tarda unos segundos; también lo tienes en tu historial.`,
                );
              } finally {
                setBajando(false);
              }
            }}
          >
            {bajando ? "Descargando…" : "Descargar PDF"}
          </button>
        )}
        <button
          type="button"
          className={`fc-btn ${clave === "autorizado" ? "fc-btn--contorno" : "fc-btn--primario"}`}
          onClick={onVer}
        >
          Ver {doc}
        </button>
        <button type="button" className="fc-btn fc-btn--contorno" onClick={onOtra}>
          Crear otra
        </button>
      </div>
    </div>
  );
}

const textoError = (e: unknown) =>
  e instanceof ErrorLimitePlan
    ? `${e.message}${e.limite.plan_sugerido ? ` Con el plan ${e.limite.plan_sugerido} lo tienes cubierto.` : ""}`
    : e instanceof Error
      ? e.message
      : "No pudimos completar la acción. Inténtalo de nuevo.";

interface Props {
  onCerrar: () => void;
  /** Vuelve a pedir el listado del historial. Se llama también cuando la
   *  emisión falla con el borrador ya creado: ese borrador existe y tiene que
   *  verse. */
  onRecargar: () => Promise<unknown> | void;
  /** Cierra el modal y lleva a la bandeja de retenciones recibidas. Solo lo usa
   *  la nota al pie del selector: la retención no se emite desde aquí. */
  onRetenciones: () => void;
}

/** Espera a saber QUÉ DIJO EL SRI.
 *
 *  El 202 de `/emitir` solo encola: firmar y hablar con el SRI ocurre después,
 *  en el worker (app/tasks/emision.py), así que el estado que devuelve esa
 *  respuesta es siempre PENDIENTE y no dice nada. Hay que preguntar por el
 *  comprobante, y preguntar un rato: autorizar tarda entre un segundo y varios
 *  minutos (medido sobre los comprobantes reales de un negocio: 1 s, 2 s, 9 s,
 *  17 s, 99 s, 138 s, 152 s, 204 s). Por eso se mira seguido al principio, donde
 *  caen los rápidos, y cada vez más espaciado después: 16 consultas repartidas
 *  en 3 min 40 s —lo justo para cubrir el más lento de los medidos— y se para.
 *  Pasado ese techo el comprobante sale igual —el pipeline reintenta los fallos
 *  transitorios del SRI con espera creciente— y el historial lo cuenta.
 *
 *  Un fallo de red al consultar NO cambia el desenlace: la emisión ya fue
 *  aceptada, lo único que se pierde es el detalle de esa vuelta. */
const PAUSAS = [
  1200, 1200, 1500, 2000, 3000, 4000, 5000, 8000, 10000, 15000, 20000, 30000, 30000, 30000, 30000,
  30000,
];

/** Tras cuántas consultas se para la rueda y se enseña el desenlace. Cubre los
 *  envíos de uno o dos segundos, que son los más frecuentes; a partir de ahí
 *  «tarda unos segundos» dejaría de ser verdad, y el sondeo sigue por detrás. */
const VUELTAS_RUEDA = 4;

/** Los estados en los que el SRI YA se pronunció. FIRMADO y ENVIADO_SRI no
 *  están: son pasos del camino (PENDIENTE → FIRMADO → ENVIADO_SRI → AUTORIZADO),
 *  no un desenlace, y tomarlos por uno era contar como salido lo que aún viaja. */
const resuelto = (estado: EstadoComprobante) =>
  estado === "AUTORIZADO" || estado === "RECHAZADO" || estado === "DEVUELTO";

const espera = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Suficiente para no mandar un viaje que el servidor va a rechazar con 422
 *  (`EmailStr`); quien valida de verdad es él. */
const CORREO = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function CrearComprobante({ onCerrar, onRecargar, onRetenciones }: Props) {
  const [pantalla, setPantalla] = useState<
    "selector" | "factura" | "revision" | "enviando" | "hecho"
  >("selector");
  /** Qué documento se está creando. La pantalla «factura» sirve para los tres. */
  const [tipo, setTipo] = useState<Tipo>("FACTURA");
  /** `esNota` = lo que las dos notas comparten (la factura de origen, el motivo,
   *  el cliente heredado, no llevar forma de pago). `esDebito` = lo que solo
   *  hace la de débito: cobrar un importe suelto en vez de devolver líneas. */
  const esDebito = tipo === "NOTA_DEBITO";
  const esCredito = tipo === "NOTA_CREDITO";
  const esNota = esCredito || esDebito;
  const doc = DOC[tipo];
  // Cabecera del negocio para la revisión. Ya viene con /panel/estado, que el
  // panel pide al montar: no hay viaje nuevo ni espera.
  const { emisor } = usePlan();

  // Catálogos: se piden al ENTRAR en la factura, no al abrir el selector, y una
  // sola vez — volver con «Otro documento» no los vuelve a pedir.
  const pedidos = useRef(false);
  const [clientes, setClientes] = useState<ClienteFinal[] | null>(null);
  const [productos, setProductos] = useState<Producto[] | null>(null);
  const [nombreValor, setNombreValor] = useState<Record<string, string>>({});
  const [pagos, setPagos] = useState<OpcionPago[] | null>(null);
  const [siguiente, setSiguiente] = useState<SiguienteNumero | null>(null);
  const [errorCatalogo, setErrorCatalogo] = useState<string | null>(null);

  // Formulario. Vive aquí, no en la pantalla que lo pinta: por eso ir a la
  // revisión y volver no pierde ni una línea de lo escrito.
  const [cliente, setCliente] = useState<ClienteFinal | "final" | null>(null);
  const [lineas, setLineas] = useState<Linea[]>([]);
  const [pago, setPago] = useState(0);
  const [eligiendo, setEligiendo] = useState(false);
  /** Correo escrito a mano en la revisión. null = el de la ficha del cliente. */
  const [correoManual, setCorreoManual] = useState<string | null>(null);
  /** La dirección que va IMPRESA en esta factura (`direccion_envio`), con la
   *  misma tri-estado que el correo y por lo mismo:
   *    null → no se ha tocado, manda la de la ficha del cliente;
   *    ""   → esta factura sale SIN dirección (quien despliega el campo y borra
   *           lo que había está pidiendo eso, no «pon la de siempre»);
   *    texto → esa, y la ficha del cliente NO se toca.
   *  null es además lo que mantiene el campo plegado: sin abrir no hay nada que
   *  mandar y la factura se comporta exactamente como antes. */
  const [direccionManual, setDireccionManual] = useState<string | null>(null);

  // Lo propio de la nota de crédito.
  const [acreditables, setAcreditables] = useState<FacturaAcreditable[] | null>(null);
  /** La factura elegida del historial. Manda sobre todo lo demás: cliente,
   *  número, fecha y el tope del importe salen de ella. */
  const [origen, setOrigen] = useState<FacturaAcreditable | null>(null);
  /** «La factura es de otro sistema»: número y fecha a mano, sin comprobación
   *  posible. Es la salida de emergencia, no el camino. */
  const [aMano, setAMano] = useState(false);
  const [numeroMano, setNumeroMano] = useState("");
  const [fechaMano, setFechaMano] = useState("");
  const [motivo, setMotivo] = useState("");
  /** Lo propio de la nota de débito: lo que se le quiere cobrar, CON IVA. Es al
   *  revés que el precio de una línea de factura (que va sin IVA) y lo decide el
   *  servidor, no esta pantalla: ver `NotaDebitoIn.valor_recargo`. */
  const [recargo, setRecargo] = useState("");

  // Envío. `borrador` guarda el id del POST /facturas para que un segundo
  // intento EMITA el mismo borrador en vez de crear otro.
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [borrador, setBorrador] = useState<string | null>(null);
  /** Lo que no se pudo guardar en el catálogo al emitir. No es un error de la
   *  factura —esa salió— pero el usuario marcó una casilla y tiene derecho a
   *  saber que no se cumplió: ver `guardarProductos`. */
  const [avisoProductos, setAvisoProductos] = useState<string | null>(null);
  /** El comprobante recién emitido, tal y como lo ve el servidor. Manda sobre lo
   *  que dice la última pantalla: null = todavía no se ha podido consultar. */
  const [salida, setSalida] = useState<Comprobante | null>(null);
  /** Id que el sondeo está mirando. null = no hay nada que mirar, porque el SRI
   *  ya contestó o porque se agotó la espera. */
  const [siguiendo, setSiguiendo] = useState<string | null>(null);
  /** El mismo id, pero legible AL INSTANTE. El estado no vale para esto: cuando
   *  se pulsa «Crear otra», React tarda un ciclo en limpiar el efecto y una
   *  respuesta ya en vuelo puede colarse en ese hueco. */
  const sondeando = useRef<string | null>(null);

  useEffect(() => {
    if (pantalla !== "factura" || pedidos.current) return;
    pedidos.current = true;
    const fallo = (e: unknown) => setErrorCatalogo(textoError(e));
    void api.get<ClienteFinal[]>("/clientes").then(setClientes).catch(fallo);
    void api.get<Producto[]>("/productos").then(setProductos).catch(fallo);
    void api.get<OpcionPago[]>("/comprobantes/formas-pago").then(setPagos).catch(fallo);
    // Los nombres de talla/color no vienen en /productos (solo ids). Si esto
    // falla, la variante se etiqueta con su código y se sigue pudiendo elegir.
    void api
      .get<AtributoValor[]>("/atributo-valores")
      .then((v) => setNombreValor(Object.fromEntries(v.map((x) => [x.id, x.valor]))))
      .catch(() => {});
  }, [pantalla]);

  // El número previsto es POR TIPO: cada comprobante lleva su propia serie, así
  // que cambiar de documento tiene que volver a pedirlo. Se blanquea primero
  // porque enseñar el de la factura bajo una nota de crédito sería mentir sobre
  // el único dato que el usuario luego busca. Volver aquí tras emitir también lo
  // refresca: el secuencial ya avanzó.
  // 404 si el negocio todavía no tiene establecimiento activo: el pie enseña un
  // guion. Es un rótulo informativo, no un requisito para emitir.
  useEffect(() => {
    if (pantalla !== "factura") return;
    setSiguiente(null);
    void api
      .get<SiguienteNumero>(`/comprobantes/siguiente-numero?tipo=${tipo}`)
      .then(setSiguiente)
      .catch(() => {});
  }, [pantalla, tipo]);

  // Las facturas que todavía admiten nota. Se piden solo si hacen falta, y se
  // vuelven a pedir tras emitir una nota (`otroComprobante` las pone a null):
  // el saldo de la que se acaba de acreditar ya no es el que se enseñó.
  // Con `solo_con_saldo=false` entran también las ya acreditadas del todo: un
  // recargo no consume saldo de la factura, así que una anulada por completo
  // sigue admitiendo los intereses de los meses que estuvo impagada.
  useEffect(() => {
    if (pantalla !== "factura" || !esNota || acreditables !== null) return;
    void api
      .get<FacturaAcreditable[]>(
        `/comprobantes/acreditables${esDebito ? "?solo_con_saldo=false" : ""}`,
      )
      .then(setAcreditables)
      .catch((e) => setErrorCatalogo(textoError(e)));
  }, [pantalla, esNota, esDebito, acreditables]);

  /** El recargo, como la ÚNICA línea del documento y con la misma aritmética que
   *  el servidor (`crear_nota_debito`: código RECARGO, cantidad 1 y de precio la
   *  base que sale de quitarle el IVA al importe tecleado). Así el desglose, el
   *  cuadro de totales y la revisión salen del mismo `totalizar` que la factura
   *  en vez de una segunda cuenta que se descuadre un céntimo. */
  const lineasRecargo = useMemo<Linea[]>(() => {
    const valor = num(recargo);
    if (valor <= 0) return [];
    const base = baseSinIva(valor, IVA_RECARGO.porcentaje) / 100;
    return [
      {
        clave: "recargo",
        codigo: "RECARGO",
        descripcion: motivo.trim() || "Recargo",
        cantidad: "1",
        precio: String(base),
        // Un recargo no se rebaja: si le cobras menos, cobras menos.
        descuento: "",
        codigoIva: IVA_RECARGO.codigo,
        porcentaje: IVA_RECARGO.porcentaje,
      },
    ];
  }, [recargo, motivo]);

  /** Las líneas del documento que se está armando. En la nota de débito no se
   *  eligen: son el recargo. */
  const lineasDoc = esDebito ? lineasRecargo : lineas;
  const totales = useMemo(() => totalizar(lineasDoc), [lineasDoc]);
  const esConsumidorFinal =
    cliente === "final" ||
    (cliente !== null && cliente.tipo_identificacion === "CONSUMIDOR_FINAL");
  // El tope de $200 limita VENTAS, no devoluciones, y el servidor no lo aplica a
  // la nota: si la factura vino del sistema, ella ya lo cumplió.
  const excedeTope = !esNota && esConsumidorFinal && totales.total > TOPE_CONSUMIDOR_FINAL;

  // Cuánto queda por devolver de la factura elegida, en centavos. El servidor
  // rechaza pasarse; enterarse antes de emitir es mejor que después.
  //
  // SOLO la nota de crédito. La de débito no tiene tope, y no por descuido: un
  // interés por mora sobre una factura de $100 impagada dos años puede superar
  // el principal, así que copiar aquí el límite prohibiría el caso normal. El
  // servidor tampoco lo aplica (ver `crear_nota_debito`).
  const pendiente = origen ? cent(Number(origen.pendiente)) : 0;
  const excedePendiente = esCredito && origen !== null && totales.total > pendiente;
  /** Con las líneas tal como salieron de la factura, la nota la anula entera.
   *  Quitar una o bajar una cantidad la convierte en una corrección parcial: es
   *  la única diferencia entre las dos cosas, y por eso no hay un interruptor
   *  que elegir. */
  const anulaTodo = esCredito && origen !== null && totales.total === pendiente;

  /** Como mucho dos decimales, que es lo que acepta el servidor
   *  (`valor_recargo` con `decimal_places=2`): así 20,001 se corrige aquí y no
   *  vuelve como un 422 que no dice gran cosa. */
  const recargoValido = /^\d+(?:[.,]\d{1,2})?$/.test(recargo.trim()) && num(recargo) > 0;
  /** Hay importes que sencillamente NO se pueden expresar con el IVA dentro: se
   *  redondea al céntimo y el SRI recalcula base×tarifa, así que 10,00 sale
   *  10,01. Es un centavo, pero es el importe que va en el documento y en el
   *  cobro, así que se avisa antes de emitir en vez de descubrirlo después. */
  const desviaUnCentavo = esDebito && recargoValido && totales.total !== cent(num(recargo));

  /** La ficha del cliente, solo para saber a qué correo va la copia. En la nota
   *  sale de la factura de origen; si esa ficha ya no está en la libreta, el
   *  campo queda vacío y se puede escribir a mano en la revisión. */
  const ficha = origen
    ? ((clientes ?? []).find((c) => c.id === origen.cliente_final_id) ?? null)
    : cliente !== null && cliente !== "final"
      ? cliente
      : null;

  /** La dirección que se va a IMPRIMIR, ya resuelta, con la misma regla que el
   *  servidor (`crear_factura`): la de la ficha mientras el campo no se toque, y
   *  a partir de ahí manda lo escrito, incluido el vacío.
   *
   *  El recorte a 300 es el tope de `direccionComprador` en el XSD. La ficha
   *  admite 1000 y el servidor recorta en silencio lo que viene de ella, pero
   *  `direccion_envio` es frontera de confianza y se rechaza con un 422: si el
   *  campo se despliega precargado con una dirección larga de hace meses, sin
   *  este recorte la factura rebotaría por algo que el usuario no escribió. */
  const direccion = direccionManual ?? ficha?.direccion?.slice(0, 300) ?? "";

  /** A nombre de quién sale. Con factura de origen manda SU snapshot —el que el
   *  SRI autorizó—, no la libreta de hoy: si el cliente se renombró, la nota
   *  tiene que citar el nombre de la factura. */
  const comprador: Comprador | null = origen
    ? {
        nombre: (origen.cliente_final_id === null ? null : origen.cliente) ?? "Consumidor final",
        identificacion: origen.cliente_identificacion ?? "9999999999999",
      }
    : cliente === null
      ? null
      : cliente === "final"
        ? // Sin ficha no hay dirección de partida, pero sí puede escribirse una:
          // una entrega a domicilio cobrada sin pedir datos sigue teniendo un
          // sitio a donde va, y el servidor la acepta igual (`_comprador_de`).
          { nombre: "Consumidor final", identificacion: "9999999999999", direccion }
        : {
            nombre: cliente.razon_social,
            identificacion: cliente.identificacion,
            // La EMITIDA, no la de la ficha: es lo que se va a firmar y lo que
            // el RIDE reimprimirá dentro de un año.
            direccion,
            telefono: cliente.telefono,
          };

  // El de la ficha mientras no se toque; en cuanto se edita manda lo escrito
  // (incluido el vacío: borrarlo es pedir que no se mande copia).
  const correo = correoManual ?? ficha?.email ?? "";
  const correoValido = correo === "" || CORREO.test(correo);

  const documentoManualValido = NUMERO_COMPROBANTE.test(numeroMano.trim()) && fechaMano !== "";
  /** La nota sin factura de origen NO tiene comprador propio: hay que elegirlo,
   *  igual que en una factura. Con origen, el comprador ya viene dado. */
  const origenValido = esNota
    ? aMano
      ? documentoManualValido && cliente !== null
      : origen !== null
    : cliente !== null;

  // Con el borrador ya creado, editar aquí no cambiaría nada de lo guardado: el
  // formulario se congela y solo queda reintentar el envío o cerrar.
  const congelado = borrador !== null;

  const editar = (clave: string, cambio: Partial<Linea>) =>
    setLineas((ls) => ls.map((l) => (l.clave === clave ? { ...l, ...cambio } : l)));

  function agregar(p: Producto, v: ProductoVariante | null) {
    const etiqueta = v ? etiquetaVariante(v, nombreValor) : "";
    setLineas((ls) => [
      ...ls,
      {
        clave: `${p.id}-${v?.id ?? ""}-${ls.length}-${Date.now()}`,
        // El código del comprobante es el de la VARIANTE cuando la hay.
        codigo: v ? v.codigo : p.codigo,
        descripcion: etiqueta ? `${p.nombre} (${etiqueta})` : p.nombre,
        cantidad: "1",
        // `precio_sin_iva` en null en la variante = hereda el del producto.
        precio: String(Number(v?.precio_sin_iva ?? p.precio_sin_iva)),
        descuento: "",
        codigoIva: p.codigo_iva,
        porcentaje: Number(p.porcentaje_iva),
      },
    ]);
    // El selector NO se cierra: una factura de seis líneas obligaba a pulsar
    // «Agregar ítem» seis veces y a reescribir la búsqueda cada vez. Se cierra
    // con su propio botón, cuando el usuario ha terminado de añadir.
  }

  /** Los códigos que YA están cogidos, para que el de una línea a mano no choque
   *  (ver `codigoDe`). Del catálogo cargado y de sus variantes, que comparten el
   *  mismo índice único del servidor. */
  const codigosDelCatalogo = useMemo(
    () =>
      (productos ?? []).flatMap((p) => [p.codigo, ...p.variantes.map((v) => v.codigo)]),
    [productos],
  );

  /** Una línea EN BLANCO, para facturar algo que no está en el catálogo.
   *
   *  Hasta ahora no había forma: todo salía del buscador, y quien vendía algo
   *  suelto —una reparación, un artículo que aún no había dado de alta— tenía
   *  que salirse a Catálogo, crearlo y volver a empezar la factura. */
  function agregarAMano() {
    setLineas((ls) => [
      ...ls,
      {
        clave: `mano-${ls.length}-${Date.now()}`,
        codigo: "",
        descripcion: "",
        cantidad: "1",
        precio: "",
        descuento: "",
        codigoIva: IVA_A_MANO[0].codigo,
        porcentaje: IVA_A_MANO[0].porcentaje,
        aMano: true,
        // Marcada por omisión, como pide la maqueta: quien lo escribe una vez
        // casi siempre lo va a volver a vender, y desmarcar cuesta un clic.
        guardar: true,
      },
    ]);
    // Al revés que el del catálogo: aquí el sitio donde escribir aparece justo
    // debajo, y dejar el buscador abierto encima solo lo taparía.
    setEligiendo(false);
  }

  /** Escribir la descripción de una línea a mano le recalcula el código.
   *
   *  Se recalcula en cada tecla, no al guardar: ese código es el que va IMPRESO
   *  en la línea y el que se enseña debajo, así que el usuario ve desde el
   *  principio con qué nombre le va a quedar el artículo. */
  function describir(clave: string, descripcion: string) {
    setLineas((ls) => {
      const ocupados = new Set([
        ...codigosDelCatalogo,
        // Las demás líneas de ESTA factura, que aún no existen en el catálogo y
        // por eso no están en la lista de arriba: dos «Silla» seguidas darían el
        // mismo código y la segunda no se podría guardar.
        ...ls.filter((x) => x.clave !== clave).map((x) => x.codigo),
      ]);
      return ls.map((l) =>
        l.clave === clave ? { ...l, descripcion, codigo: codigoDe(descripcion, ocupados) } : l,
      );
    });
  }

  /** Elegir la factura del historial rellena la nota entera: número, fecha,
   *  comprador y líneas. Es el camino principal, y el único en el que hay algo
   *  que comprobar antes de emitir. */
  function elegirFactura(f: FacturaAcreditable) {
    setOrigen(f);
    // El cliente deja de ser una decisión: la nota va al de la factura y el
    // servidor rechaza cualquier otro. Se limpia el que hubiera para no dejar
    // dos verdades a la vez en pantalla.
    setCliente(null);
    // La nota de débito no arranca de las líneas de la factura: no devuelve lo
    // vendido, cobra un importe aparte.
    setLineas(esDebito ? [] : lineasDe(f));
    setCorreoManual(null);
    setEligiendo(false);
  }

  const opcion = pagos?.[pago];
  const puedeEnviar =
    !enviando &&
    (congelado ||
      (origenValido &&
        (!esNota || motivoValido(motivo)) &&
        (!esDebito || recargoValido) &&
        lineasDoc.length > 0 &&
        // También el precio: `num()` devuelve 0 para un campo vacío, así que
        // borrar un precio para reescribirlo y despistarse emitía una línea a
        // $0,00 —o una factura entera a cero— y el servidor la acepta.
        lineasDoc.every((l) => num(l.cantidad) > 0 && num(l.precio) > 0) &&
        // Sin descripción no hay línea: `ItemFacturaIn.descripcion` la exige, y
        // además es lo único que el cliente va a leer en el papel.
        lineas.every((l) => !l.aMano || l.descripcion.trim() !== "") &&
        !lineasDoc.some(descuentoExcede) &&
        !excedeTope &&
        !excedePendiente));

  /** Qué se le cuenta al usuario al final, sacado del estado REAL: autorizado es
   *  un desenlace de verdad, «va en camino» es otro, y FIRMADO/ENVIADO_SRI son
   *  camino. Sin esto, el caso que MÁS ocurre —el SRI autoriza en un segundo—
   *  caía en «está en proceso» y la pantalla negaba un documento ya válido. */
  const claveDesenlace: ClaveDesenlace =
    salida === null || salida.estado === "PENDIENTE"
      ? "cola"
      : salida.estado === "AUTORIZADO"
        ? "autorizado"
        : salida.estado === "DEVUELTO"
          ? "devuelto"
          : salida.estado === "RECHAZADO"
            ? "fallido"
            : "camino";

  // Sigue mirando el comprobante mientras el modal esté abierto: la autorización
  // llega en un segundo o en varios minutos, así que la pantalla se actualiza
  // sola en vez de congelar un texto que ya no es cierto. Al desmontar (el
  // usuario cierra el modal) se corta, para no dejar una petición colgando ni un
  // setState sobre algo que ya no está.
  //
  // `onRecargar` NO va en las dependencias a propósito: el padre la recrea en
  // cada render, y como el propio sondeo la llama, listarla reiniciaría la
  // espera desde cero en bucle.
  useEffect(() => {
    if (siguiendo === null) return;
    let vivo = true;
    // `vivo` por sí solo no basta: React ejecuta la limpieza DESPUÉS del clic, y
    // en ese hueco puede aterrizar la respuesta de una vuelta ya en vuelo. Sin
    // esta comprobación, pulsar «Crear otra» justo en ese instante sustituye el
    // formulario en blanco recién abierto por el desenlace del documento
    // anterior. El ref lo dice al momento, sin esperar al ciclo de React.
    const mio = siguiendo;
    sondeando.current = mio;
    const sigoSiendoYo = () => vivo && sondeando.current === mio;
    void (async () => {
      // El estado justo después de `/emitir` es siempre PENDIENTE y el historial
      // ya se recargó con él: solo interesa lo que cambie a partir de ahí.
      let previo: EstadoComprobante = "PENDIENTE";
      for (let i = 0; i < PAUSAS.length; i++) {
        await espera(PAUSAS[i]);
        if (!sigoSiendoYo()) return;
        // Se sale de la rueda por el TIEMPO transcurrido, no por cuántas
        // respuestas llegaron: si una consulta se queda colgada —el móvil pierde
        // cobertura, un portal cautivo se traga la conexión— la pantalla
        // «Firmando y enviando al SRI…» no tiene botón de cerrar y el usuario se
        // queda encerrado en ella hasta que el navegador corte, minutos después.
        if (i + 1 >= VUELTAS_RUEDA) setPantalla("hecho");
        const c = await api.get<Comprobante>(`/comprobantes/${mio}`).catch(() => null);
        if (!sigoSiendoYo()) return;
        if (c !== null) {
          setSalida(c);
          // El historial de detrás se recarga cuando el estado CAMBIA de verdad,
          // no en cada vuelta.
          if (c.estado !== previo) {
            previo = c.estado;
            void onRecargar();
          }
          if (resuelto(c.estado)) break;
        }
      }
      if (!sigoSiendoYo()) return;
      setSiguiendo(null);
      setPantalla("hecho");
    })();
    return () => {
      vivo = false;
      if (sondeando.current === mio) sondeando.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siguiendo]);

  /** Da de alta en el catálogo los artículos escritos a mano con la casilla
   *  marcada.
   *
   *  CUÁNDO: justo después de que el borrador exista y ANTES de mandarlo al SRI.
   *  Ese es el instante en que la factura deja de ser un formulario del
   *  navegador y pasa a ser un documento del historial: aunque el envío falle
   *  después, ese comprobante está guardado, se reintenta desde el historial y
   *  cita el artículo, así que el artículo tiene que existir. Guardar antes —al
   *  escribir la línea, o al pulsar «Revisar»— llenaría el catálogo de cosas de
   *  facturas que nadie llegó a emitir, y cada una consume cupo del plan.
   *  Guardar después del `/emitir` perdería el artículo justo cuando la red
   *  falla, que es cuando el usuario menos va a volver a escribirlo.
   *
   *  QUÉ NO HACE: tumbar la emisión. La ruta consume cupo (`exigir_cupo_productos`)
   *  y contesta 402 cuando se acabó; también puede chocar el código con un
   *  artículo desactivado, que no sale en /productos. Perder la factura por eso
   *  sería cambiar lo importante por lo accesorio, así que se traga el fallo y
   *  se cuenta al final, con su motivo.
   *
   *  De uno en uno y no en paralelo: el cupo se comprueba fila a fila, y dos
   *  peticiones a la vez pueden pasar las dos el último hueco. */
  async function guardarProductos(nuevos: Linea[]) {
    const fallos: string[] = [];
    for (const l of nuevos) {
      try {
        const alta = await api.post<Producto>("/productos", {
          codigo: l.codigo.slice(0, 25),
          nombre: l.descripcion.trim().slice(0, 300),
          // BIEN y sin inventario, que es la elección REVERSIBLE: un bien se
          // puede pasar a servicio desde Catálogo, mientras que un servicio
          // rechaza categoría y variantes (`servicio_sin_categoria`) hasta que
          // alguien le cambie el tipo. Y preguntarlo aquí sería una tercera
          // casilla en una línea que se está escribiendo con prisa.
          tipo: "BIEN",
          precio_sin_iva: String(num(l.precio)),
          codigo_iva: l.codigoIva,
        });
        // El catálogo cargado se queda al día sin volver a pedirlo: con «Crear
        // otra» el buscador ya lo encuentra, y —lo que importa— el código del
        // recién creado pasa a contar como ocupado, así que escribir dos veces
        // el mismo artículo en la misma sesión no choca contra sí mismo.
        setProductos((ps) => (ps === null ? ps : [...ps, alta]));
      } catch (e) {
        fallos.push(`«${l.descripcion.trim()}»: ${textoError(e)}`);
      }
    }
    setAvisoProductos(
      fallos.length === 0
        ? null
        : `Tu ${doc} salió bien, pero no pudimos guardar ${
            fallos.length === 1 ? "este artículo" : "estos artículos"
          } en tu catálogo — ${fallos.join(" ")} Agrégalo desde Catálogo cuando quieras.`,
    );
  }

  /** Emite de verdad. Solo se llega aquí desde la revisión: el botón del
   *  formulario ya no envía nada. */
  async function emitirComprobante() {
    // Guarda contra el doble clic: sin esto, dos pulsaciones seguidas crean dos
    // facturas (y queman dos comprobantes del plan).
    if (enviando || !puedeEnviar || !correoValido) return;
    setEnviando(true);
    setError(null);
    setPantalla("enviando");
    let id = borrador;
    try {
      if (id === null) {
        // Solo para ESTE comprobante: el servidor lo guarda en el payload y no
        // toca la ficha del cliente. Se manda en cuanto el usuario TOCA el campo
        // (`correoManual !== null`), incluido si lo deja vacío: el vacío
        // significa «no mandes copia», y omitirlo haría que el servidor usara el
        // de la ficha, que es justo lo que se acaba de borrar.
        const copia = correoManual !== null ? { email_envio: correo } : {};
        // Igual que el correo, y por lo mismo: mientras el campo no se
        // despliegue no se manda nada y el servidor coge la de la ficha; en
        // cuanto se toca manda lo escrito, y el vacío significa «esta factura va
        // sin dirección». Solo en la factura: `<direccionComprador>` no existe
        // en el XML de las notas y `_NotaSobreFactura` ni siquiera acepta el
        // campo.
        const domicilio =
          direccionManual !== null ? { direccion_envio: direccionManual.trim() } : {};
        const items = lineas.map((l) => ({
          codigo: l.codigo.slice(0, 25),
          descripcion: l.descripcion.trim().slice(0, 300),
          cantidad: String(num(l.cantidad)),
          precio_unitario: String(num(l.precio)),
          // Siempre, aunque sea 0: `ItemFacturaIn.descuento` tiene ese valor por
          // omisión, así que mandarlo no cambia nada donde no lo hay y evita una
          // rama más aquí.
          descuento: String(num(l.descuento)),
          codigo_iva: l.codigoIva,
        }));
        const idCliente = cliente !== null && cliente !== "final" ? cliente.id : null;
        // Lo que las dos notas comparten, que es todo menos el importe: contra
        // qué factura van y por qué (`_NotaSobreFactura` en el servidor).
        const nota = {
          ...copia,
          // Con factura de origen el comprador es el suyo, sin discusión: el
          // servidor compara los dos y rechaza la nota si no coinciden.
          cliente_final_id: origen ? origen.cliente_final_id : idCliente,
          ...(origen
            ? { factura_id: origen.id }
            : { doc_modificado: { numero: numeroMano.trim(), fecha: fechaMano } }),
          motivo: motivo.trim(),
        };
        const creado = await api.post<Comprobante>(
          RUTA[tipo],
          esDebito
            ? // CON IVA: se manda lo tecleado tal cual y el servidor desglosa.
              // Mandar la base calculada aquí sería enviarle una cuenta que él
              // vuelve a hacer, con dos sitios donde se puede descuadrar.
              { ...nota, valor_recargo: String(num(recargo)) }
            : esCredito
              ? { ...nota, items }
              : {
                  ...copia,
                  ...domicilio,
                  items,
                  cliente_final_id: idCliente,
                  // Sin la lista cargada no se inventa una forma de pago: el
                  // servidor aplica su propio valor por omisión.
                  ...(opcion ? { forma_pago: opcion.codigo, plazo_dias: opcion.plazo_dias } : {}),
                },
        );
        // A partir de aquí el borrador EXISTE, pase lo que pase con el envío.
        id = creado.id;
        setBorrador(id);
        // Dentro del `if`: un segundo intento reemite ESTE borrador, y volver a
        // guardar daría de alta el artículo dos veces (o gastaría otro hueco del
        // plan para chocar con el que ya se creó).
        const aGuardar = lineas.filter((l) => l.aMano && l.guardar);
        if (aGuardar.length > 0) await guardarProductos(aGuardar);
      }
      // Segundo paso, y puede fallar por su cuenta con el borrador ya guardado.
      await api.post<Comprobante>(`/comprobantes/${id}/emitir`, {});
      await onRecargar();
      // El desenlace NO lo decide esta respuesta: el 202 solo encola, así que
      // quien lo sabrá es el sondeo, y él pasa a la pantalla final.
      setSiguiendo(id);
    } catch (e) {
      setPantalla("revision");
      if (id !== null) {
        // Que la PETICIÓN falle no significa que el envío no llegara: el
        // servidor pudo asignar número y encolar, y perderse solo la respuesta
        // (móvil que cambia de celda, proxy que corta). Antes de decir nada se
        // le pregunta al comprobante en qué estado quedó; invitar a rehacerla
        // cuando ya salió acabaría en dos facturas.
        const real = await api
          .get<Comprobante>(`/comprobantes/${id}`)
          .catch(() => null);
        void onRecargar();
        if (real && real.numero !== null) {
          setError(
            `Tu ${doc} ${real.numero} SÍ se envió: perdimos la respuesta, pero ya está en camino. ` +
              "Míralo en tu historial; no la emitas otra vez.",
          );
        } else {
          setError(
            `Creamos el borrador, pero no pudimos enviarlo al SRI: ${textoError(e)} ` +
              "Ya aparece en tu historial como pendiente: reintenta el envío aquí o ciérralo y hazlo más tarde.",
          );
        }
      } else {
        setError(textoError(e));
      }
    } finally {
      setEnviando(false);
    }
  }

  /** «Crear otro»: el formulario en blanco, sin cerrar el modal ni cambiar de
   *  tipo de documento. El número previsto y las facturas acreditables se
   *  vuelven a pedir solos: el secuencial ya avanzó con el que se acaba de
   *  emitir, y el saldo de la factura acreditada ya no es el que se enseñó. */
  function otroComprobante() {
    setCliente(null);
    setLineas([]);
    setCorreoManual(null);
    setDireccionManual(null);
    setAvisoProductos(null);
    setBorrador(null);
    // Deja de mirar el anterior: la pantalla ya no lo enseña. El ref corta la
    // vuelta que pudiera estar en vuelo AHORA; el estado corta el efecto después.
    sondeando.current = null;
    setSiguiendo(null);
    setSalida(null);
    setError(null);
    setOrigen(null);
    setAMano(false);
    setNumeroMano("");
    setFechaMano("");
    setMotivo("");
    setRecargo("");
    setAcreditables(null);
    setPantalla("factura");
  }

  /** Cambiar de documento vacía el formulario: las líneas de una factura no son
   *  las de la nota que se iba a hacer, y arrastrarlas se emite sin querer. */
  function elegirTipo(t: Tipo) {
    if (t !== tipo) {
      setTipo(t);
      otroComprobante();
      return;
    }
    setPantalla("factura");
  }

  if (pantalla === "selector") {
    return (
      <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Crear comprobante">
        <PanelSelector
          onElegir={elegirTipo}
          onRetenciones={onRetenciones}
          onCerrar={onCerrar}
        />
      </div>
    );
  }

  // `comprador` no puede ser null aquí: sin saber a nombre de quién sale, el
  // botón de revisar está apagado.
  if (pantalla === "revision" && comprador !== null) {
    return (
      <Revision
        emisor={emisor}
        tipo={tipo}
        numero={siguiente?.numero ?? null}
        comprador={comprador}
        origen={
          esNota
            ? {
                numero: origen ? origen.numero : numeroMano.trim(),
                fecha: origen ? origen.fecha_emision : fechaMano,
                motivo: motivo.trim(),
                tecleada: origen === null,
              }
            : undefined
        }
        formaPago={esNota ? undefined : opcion?.etiqueta}
        lineas={lineasDoc}
        totales={totales}
        correo={correo}
        onCorreo={setCorreoManual}
        correoValido={correoValido}
        error={error}
        aviso={avisoProductos}
        congelado={congelado}
        onVolver={() => setPantalla("factura")}
        onEmitir={() => void emitirComprobante()}
        onCerrar={onCerrar}
      />
    );
  }

  if (pantalla === "enviando") {
    return (
      <div className="fc-modal" role="dialog" aria-modal="true" aria-label={`Emitiendo la ${doc}`}>
        <div
          className="fc-modal__panel"
          style={{ maxWidth: 400, textAlign: "center" }}
          role="status"
          aria-live="polite"
        >
          <span
            aria-hidden="true"
            style={{
              width: 30,
              height: 30,
              display: "inline-block",
              border: "3px solid var(--borde)",
              borderTopColor: "var(--verde-acento)",
              borderRadius: "50%",
              animation: "dbSpin .8s linear infinite",
            }}
          />
          <p style={{ fontSize: 15, fontWeight: 600, margin: "16px 0 0" }}>
            Firmando y enviando al SRI…
          </p>
          <p style={{ fontSize: 13, color: "var(--texto-tenue)", margin: "6px 0 0" }}>
            Tarda unos segundos.
          </p>
        </div>
      </div>
    );
  }

  if (pantalla === "hecho") {
    // El rótulo del diálogo sale del MISMO desenlace que el resto del panel:
    // anunciar «emitida» una que el SRI devolvió, o una que todavía va de viaje,
    // es la mentira que se vino a arreglar, solo que en el canal que no se ve.
    return (
      <div
        className="fc-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${ETIQUETA_TIPO[tipo]}: ${DESENLACES[claveDesenlace].titulo(doc)}`}
      >
        <PanelDesenlace
          clave={claveDesenlace}
          doc={doc}
          salida={salida}
          vigilando={siguiendo !== null}
          aviso={avisoProductos}
          // El historial está justo detrás y ya se recargó con este comprobante
          // arriba del todo: cerrar ES verlo, sin inventar una ruta de detalle
          // que el servidor no tiene.
          onVer={onCerrar}
          onOtra={otroComprobante}
        />
      </div>
    );
  }

  return (
    <div
      className="fc-modal"
      role="dialog"
      aria-modal="true"
      aria-label={`Nueva ${doc}`}
    >
      <div className="fc-modal__panel fc-modal__panel--fijo" style={{ maxWidth: 760 }}>
        <Cabecera
          fijo
          titulo={`Nueva ${doc}`}
          subtitulo={
            esDebito
              ? "Para cobrarle algo de más sobre una factura que ya emitiste."
              : esCredito
                ? "Para anular o corregir una factura que ya emitiste."
                : "Se firma con tu certificado y se envía al SRI."
          }
          onCerrar={onCerrar}
        />

        <div className="fc-modal__cuerpo fc-scroll" style={{ paddingTop: 18, display: "grid", gap: 20 }}>
          {errorCatalogo && (
            <p className="fc-error" role="alert">
              {errorCatalogo}
            </p>
          )}

          {/* «Nota de débito» no le dice nada a quien no es contador, y el
              nombre tampoco ayuda: suena a que le quitas algo. Se explica en la
              primera línea de la pantalla, con lo que de verdad hace y con
              ejemplos —los intereses, un gasto—, no con la definición del SRI. */}
          {esDebito && (
            <p
              style={{
                display: "flex",
                gap: 10,
                alignItems: "flex-start",
                margin: 0,
                padding: "12px 14px",
                borderRadius: "var(--radio-campo)",
                background: "var(--aviso-bg)",
                color: "var(--aviso-texto)",
                fontSize: 13,
                lineHeight: 1.55,
                textWrap: "pretty",
              }}
            >
              <span aria-hidden="true" style={{ display: "grid", flex: "none", marginTop: 1 }}>
                <Svg d={ICONO_MAS} tamano={16} />
              </span>
              <span>
                Con esto le cobras <strong>de más</strong> sobre una factura que ya emitiste: los
                intereses de un pago atrasado, un gasto que le repercutes. La factura original
                sigue valiendo —esto se le suma— y no vendes nada nuevo, así que no hay productos
                que agregar: eliges la factura, dices por qué y cuánto.
              </span>
            </p>
          )}

          {/* La factura que se modifica va PRIMERO en la nota, y no es un dato
              más: elegirla decide el cliente, las líneas y el tope del importe.
              Preguntar antes por el cliente sería preguntar algo que la propia
              factura ya responde. */}
          {esNota && (
            <section>
              <span className="fc-label">
                {esDebito ? "Factura a la que le cobras" : "Factura que modifica"}
              </span>
              {origen !== null ? (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 11,
                    flexWrap: "wrap",
                    padding: "12px 14px",
                    borderRadius: "var(--radio-campo)",
                    background: "var(--exito-bg)",
                    border: "1px solid var(--exito-borde)",
                  }}
                >
                  <span style={{ flex: "1 1 190px", minWidth: 0 }}>
                    <span className="fc-mono" style={{ display: "block", fontWeight: 600, fontSize: 13.5 }}>
                      {origen.numero}
                    </span>
                    <span
                      style={{ display: "block", fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 1 }}
                    >
                      {fechaCorta(origen.fecha_emision)} · {dinero(origen.total)}
                    </span>
                  </span>
                  {/* El comprador viene con la factura y aquí no se toca: la
                      nota va siempre al mismo cliente, y cambiarlo solo
                      produciría un rechazo del servidor. */}
                  <span style={{ flex: "1 1 190px", minWidth: 0, textAlign: "right" }}>
                    <span style={{ display: "block", fontSize: 11.5, color: "var(--texto-tenue)" }}>
                      A nombre de
                    </span>
                    <span style={{ display: "block", fontWeight: 600, fontSize: 13 }}>
                      {comprador?.nombre}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="fc-btn fc-btn--contorno"
                    style={{ padding: "7px 14px", fontSize: 12.5 }}
                    disabled={congelado}
                    onClick={() => {
                      setOrigen(null);
                      setLineas([]);
                    }}
                  >
                    Cambiar
                  </button>
                </div>
              ) : aMano ? (
                <div style={{ display: "grid", gap: 10 }}>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <label style={{ flex: "1 1 220px", minWidth: 0 }}>
                      <span className="fc-label">Número de la factura</span>
                      <input
                        className="fc-campo fc-mono"
                        inputMode="numeric"
                        disabled={congelado}
                        aria-invalid={numeroMano !== "" && !NUMERO_COMPROBANTE.test(numeroMano.trim())}
                        placeholder="001-001-000000123"
                        value={numeroMano}
                        onChange={(e) => setNumeroMano(e.target.value)}
                      />
                    </label>
                    <label style={{ flex: "1 1 160px", minWidth: 0 }}>
                      <span className="fc-label">Fecha de esa factura</span>
                      {/* Campo de fecha del navegador: en el móvil abre su propio
                          calendario y nunca deja escribir un 31 de febrero. */}
                      <input
                        className="fc-campo"
                        type="date"
                        disabled={congelado}
                        max={hoyEnEcuador()}
                        value={fechaMano}
                        onChange={(e) => setFechaMano(e.target.value)}
                      />
                    </label>
                  </div>
                  {numeroMano !== "" && !NUMERO_COMPROBANTE.test(numeroMano.trim()) && (
                    <p className="fc-error" role="alert" style={{ margin: 0 }}>
                      El número va en tres bloques: 001-001-000000123.
                    </p>
                  )}
                  {/* Sin la factura delante no hay nada que comprobar, y hay que
                      decirlo: el SRI sí compara, y una cifra mal copiada vuelve
                      como devolución cuando ya no se puede corregir. */}
                  <p
                    style={{
                      display: "flex",
                      gap: 9,
                      alignItems: "flex-start",
                      margin: 0,
                      padding: "10px 12px",
                      borderRadius: "var(--radio-campo)",
                      background: "var(--aviso-bg)",
                      color: "var(--aviso-texto)",
                      fontSize: 12.5,
                      lineHeight: 1.5,
                    }}
                  >
                    <span aria-hidden="true" style={{ display: "grid", flex: "none", marginTop: 1 }}>
                      <Svg d={ICONO_AVISO} tamano={15} />
                    </span>
                    <span>
                      Esta factura no está en tu historial, así que no podemos comprobar nada:
                      ni el número, ni la fecha, ni el importe. Cópialos de la factura, tal cual.
                      Si el SRI no los reconoce, devolverá la nota.
                    </span>
                  </p>
                  <button
                    type="button"
                    className="fc-btn fc-btn--texto"
                    style={{ justifySelf: "start", fontSize: 12.5, padding: 0 }}
                    disabled={congelado}
                    onClick={() => {
                      setAMano(false);
                      setNumeroMano("");
                      setFechaMano("");
                      setCliente(null);
                      setLineas([]);
                    }}
                  >
                    ‹ Buscarla en mi historial
                  </button>
                </div>
              ) : (
                <div style={{ display: "grid", gap: 9 }}>
                  <SelectorFactura
                    facturas={acreditables}
                    recargo={esDebito}
                    onElegir={elegirFactura}
                  />
                  <button
                    type="button"
                    className="fc-btn fc-btn--texto"
                    style={{ justifySelf: "start", fontSize: 12.5, padding: 0 }}
                    disabled={congelado}
                    onClick={() => setAMano(true)}
                  >
                    La factura es de otro sistema
                  </button>
                </div>
              )}
            </section>
          )}

          {/* En la nota con factura elegida el comprador ya está decidido y se
              enseña arriba: pedirlo otra vez sería ofrecer cambiar lo que no se
              puede cambiar. */}
          {(!esNota || aMano) && (
          <section>
            <span className="fc-label">Cliente</span>
            {cliente === null ? (
              <BuscadorCliente
                clientes={clientes}
                // El correo y la dirección escritos a mano eran para el cliente
                // anterior: con otro cliente vuelven a salir de su ficha. Sin
                // esto, cambiar de cliente le mandaba la factura al correo del
                // otro y se la imprimía con su domicilio.
                onElegir={(c) => {
                  setCliente(c);
                  setCorreoManual(null);
                  setDireccionManual(null);
                }}
              />
            ) : (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 11,
                  padding: "12px 14px",
                  borderRadius: "var(--radio-campo)",
                  background: "var(--exito-bg)",
                  border: "1px solid var(--exito-borde)",
                }}
              >
                <span className="fc-avatar" aria-hidden="true">
                  {cliente === "final" ? "?" : inicial(cliente.razon_social)}
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "block", fontWeight: 600, fontSize: 13.5 }}>
                    {cliente === "final" ? "Consumidor final" : cliente.razon_social}
                  </span>
                  <span
                    className="fc-mono"
                    style={{ display: "block", fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 1 }}
                  >
                    {cliente === "final" ? "9999999999999" : cliente.identificacion}
                  </span>
                </span>
                <button
                  type="button"
                  className="fc-btn fc-btn--contorno"
                  style={{ padding: "7px 14px", fontSize: 12.5 }}
                  disabled={congelado}
                  onClick={() => setCliente(null)}
                >
                  Cambiar
                </button>
              </div>
            )}
            {excedeTope && (
              <p className="fc-error" role="alert">
                Consumidor final permite hasta {dinero(TOPE_CONSUMIDOR_FINAL / 100)}. Elige un
                cliente con su identificación para este monto.
              </p>
            )}

            {/* LA DIRECCIÓN DEL COMPRADOR, plegada. Va impresa en la factura
                (`<direccionComprador>`), pero es opcional en el XML y la mayoría
                de las ventas de mostrador no la necesitan: quien no la usa no la
                ve. Se despliega ya rellena con la de la ficha, que es lo que se
                va a imprimir de todas formas, y desde ahí se cambia para ESTA
                entrega o se borra para que la factura salga sin ella.

                Solo en la factura: las notas no tienen ese campo en su XML. Y
                solo con el cliente ya elegido, que es de donde sale lo
                precargado; también con «consumidor final», que no tiene ficha
                pero sí puede tener una dirección de entrega. */}
            {!esNota && cliente !== null && (
              <div style={{ marginTop: 12 }}>
                {direccionManual === null ? (
                  <button
                    type="button"
                    className="fc-btn fc-btn--texto"
                    style={{ fontSize: 12.5, padding: 0 }}
                    disabled={congelado}
                    aria-expanded={false}
                    onClick={() => setDireccionManual(ficha?.direccion?.slice(0, 300) ?? "")}
                  >
                    + Agregar dirección
                  </button>
                ) : (
                  <>
                    <label className="fc-label" htmlFor="fc-direccion">
                      Dirección
                    </label>
                    <input
                      id="fc-direccion"
                      className="fc-campo"
                      // El tope del XML. El campo se corta aquí en vez de dejar
                      // escribir de más y devolver un 422 al final del viaje.
                      maxLength={300}
                      // El botón que lo despliega desaparece: sin esto el foco
                      // se queda en la nada y en el móvil no sale el teclado.
                      autoFocus
                      disabled={congelado}
                      placeholder="Av. Amazonas N34-120 y Av. Atahualpa"
                      value={direccionManual}
                      onChange={(e) => setDireccionManual(e.target.value)}
                    />
                    <p style={{ fontSize: 12, color: "var(--texto-tenue)", margin: "6px 0 0", lineHeight: 1.5 }}>
                      Se imprime en la factura. Vale solo para esta: cambiarla no toca la ficha de
                      tu cliente, y si la dejas vacía la factura sale sin dirección.
                    </p>
                  </>
                )}
              </div>
            )}
          </section>
          )}

          {/* Va IMPRESO en el comprobante, así que se pide con esas palabras y
              no como un campo interno de la aplicación. */}
          {esNota && (
            <section>
              <label className="fc-label" htmlFor="fc-motivo">
                Motivo
              </label>
              <textarea
                id="fc-motivo"
                className="fc-campo"
                rows={2}
                maxLength={300}
                disabled={congelado}
                aria-invalid={motivo !== "" && !motivoValido(motivo)}
                placeholder={
                  esDebito
                    ? "Ej.: Interés por mora de 60 días"
                    : "Ej.: El cliente devolvió el producto"
                }
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                style={{ resize: "vertical" }}
              />
              <p style={{ fontSize: 12, color: "var(--texto-tenue)", margin: "6px 0 0" }}>
                {esDebito
                  ? "Por qué le cobras esto de más. Va impreso en el comprobante y es lo único que tu cliente va a leer."
                  : "Por qué anulas o corriges. Va impreso en el comprobante."}
              </p>
              {motivo !== "" && !motivoValido(motivo) && (
                <p className="fc-error" role="alert">
                  Escríbelo con palabras: lo va a leer tu cliente.
                </p>
              )}
            </section>
          )}

          {/* EL IMPORTE VA CON IVA. Es al revés que el precio de una línea de
              factura, que va sin él, así que no basta con no mentir: hay que
              decirlo en la etiqueta, repetirlo en la ayuda y enseñar el desglose
              debajo. Quien teclea aquí piensa «cóbrale 20 dólares», no «cóbrale
              una base imponible de 17,39»; pedirle la base para que le salga un
              total de 23,00 sería pedirle que haga la cuenta al revés. Lo
              desglosa el servidor (`crear_nota_debito`); esto solo lo enseña. */}
          {esDebito && (
            <section>
              <label className="fc-label" htmlFor="fc-recargo">
                Valor del recargo
              </label>
              <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
                <span style={{ fontSize: 15, fontWeight: 600, color: "var(--texto-tenue)" }}>$</span>
                <input
                  id="fc-recargo"
                  className="fc-campo"
                  style={{ width: 150 }}
                  type="number"
                  min="0"
                  step="0.01"
                  inputMode="decimal"
                  disabled={congelado}
                  aria-invalid={recargo !== "" && !recargoValido}
                  placeholder="20.00"
                  value={recargo}
                  onChange={(e) => setRecargo(e.target.value)}
                />
                <span style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>
                  IVA {IVA_RECARGO.porcentaje}% incluido
                </span>
              </div>
              <p style={{ fontSize: 12, color: "var(--texto-tenue)", margin: "6px 0 0", lineHeight: 1.5 }}>
                Lo que quieres cobrarle EN TOTAL, con el IVA dentro. Escribe 20 y le cobras 20; el
                impuesto se desglosa solo, aquí abajo.
              </p>
              {recargo !== "" && !recargoValido && (
                <p className="fc-error" role="alert">
                  Escribe un importe mayor que cero, con dos decimales como mucho.
                </p>
              )}
              {/* El céntimo que no se puede expresar: se dice ANTES de emitir y
                  con el número exacto, porque es el que va en el documento. */}
              {desviaUnCentavo && (
                <p style={{ fontSize: 12.5, color: "var(--aviso-texto)", margin: "8px 0 0", lineHeight: 1.5 }}>
                  Ojo: con el IVA dentro, {dinero(num(recargo))} no sale exacto. La nota saldrá por{" "}
                  <strong>{dinero(totales.total / 100)}</strong>. Es un centavo de redondeo del
                  impuesto y no se puede evitar.
                </p>
              )}
            </section>
          )}

          {/* La nota de débito no tiene líneas ni catálogo, y no es una carencia:
              no vende nada, cobra un importe. Su «línea» es el recargo de arriba. */}
          {!esDebito && (
          <section>
            <div
              style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 9 }}
            >
              <span className="fc-label" style={{ flex: 1, marginBottom: 0 }}>
                Qué le vendiste
              </span>
              {/* Deshacer los recortes sin volver a elegir la factura: quitar
                  cuatro líneas y arrepentirse no puede costar empezar de cero. */}
              {esNota && origen !== null && !anulaTodo && (
                <button
                  type="button"
                  className="fc-btn fc-btn--texto"
                  style={{ fontSize: 12.5, padding: 0 }}
                  disabled={congelado}
                  onClick={() => setLineas(lineasDe(origen))}
                >
                  Devolver la factura entera
                </button>
              )}
              {/* La salida para lo que NO está en el catálogo. Hasta ahora todo
                  tenía que pasar por el buscador, así que vender algo suelto
                  obligaba a irse a Catálogo, crearlo y rehacer la factura. */}
              <button
                type="button"
                className="fc-btn fc-btn--texto"
                style={{ fontSize: 12.5, padding: 0 }}
                disabled={congelado}
                onClick={agregarAMano}
              >
                Escribir a mano
              </button>
              <button
                type="button"
                className="fc-btn fc-btn--contorno"
                style={{ padding: "7px 14px", fontSize: 12.5 }}
                disabled={congelado}
                aria-expanded={eligiendo}
                onClick={() => setEligiendo((v) => !v)}
              >
                + Agregar ítem
              </button>
            </div>

            {/* Anular y corregir no son dos botones: son el mismo formulario con
                las líneas tocadas o sin tocar. Se dice con esas palabras, que es
                lo que hay que hacer, y no «nota total / nota parcial». */}
            {esNota && origen !== null && (
              <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: "0 0 10px", lineHeight: 1.55 }}>
                Esto es lo que le facturaste. Déjalo como está para anular la factura entera, o
                quita líneas y baja cantidades para devolverle solo una parte.
              </p>
            )}

            {eligiendo && (
              <SelectorProducto
                productos={productos}
                nombreValor={nombreValor}
                onElegir={agregar}
                onCerrar={() => setEligiendo(false)}
              />
            )}

            {lineas.length === 0 && !eligiendo && (
              <div
                style={{
                  border: "1px dashed var(--borde-campo)",
                  borderRadius: "var(--radio-panel)",
                  padding: "22px 16px",
                  textAlign: "center",
                  fontSize: 13,
                  color: "var(--texto-tenue)",
                }}
              >
                {esNota && origen !== null
                  ? "Quitaste todas las líneas: así no hay nada que devolver."
                  : "Todavía no agregaste nada. Búscalo en tu catálogo o escríbelo a mano."}
              </div>
            )}

            {lineas.map((l) => {
              // Sin descripción todavía no hay nada que nombrar, y una etiqueta
              // «Cantidad de » a medias es peor que una genérica.
              const nombre = l.descripcion.trim() || "la línea nueva";
              const excede = descuentoExcede(l);
              return (
              <div
                key={l.clave}
                style={{ padding: "11px 0", borderBottom: "1px solid var(--borde)" }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <div style={{ flex: "1 1 190px", minWidth: 0 }}>
                  {l.aMano ? (
                    <>
                      <input
                        className="fc-campo"
                        style={{ padding: "7px 9px", fontWeight: 600 }}
                        maxLength={300}
                        autoFocus
                        disabled={congelado}
                        aria-label="Qué le vendiste"
                        placeholder="Qué le vendiste"
                        value={l.descripcion}
                        onChange={(e) => describir(l.clave, e.target.value)}
                      />
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          flexWrap: "wrap",
                          fontSize: 11.5,
                          color: "var(--texto-tenue)",
                          marginTop: 4,
                        }}
                      >
                        {/* El código NO se pregunta: sale de la descripción (ver
                            `codigoDe`). Se enseña porque va impreso en el papel
                            y porque es con el que quedará guardado. */}
                        <span className="fc-mono">{l.codigo || "—"}</span>
                        <select
                          className="fc-campo"
                          style={{ width: "auto", padding: "4px 8px", fontSize: 11.5 }}
                          disabled={congelado}
                          aria-label={`IVA de ${nombre}`}
                          value={l.codigoIva}
                          onChange={(e) => {
                            const t = IVA_A_MANO.find((x) => x.codigo === e.target.value);
                            // La tarifa acompaña SIEMPRE al código: `totalizar`
                            // calcula con `porcentaje` y el servidor con la tabla
                            // del `codigo_iva`. Separarlos descuadra el IVA.
                            if (t) editar(l.clave, { codigoIva: t.codigo, porcentaje: t.porcentaje });
                          }}
                        >
                          {IVA_A_MANO.map((t) => (
                            <option key={t.codigo} value={t.codigo}>
                              {t.etiqueta}
                            </option>
                          ))}
                        </select>
                      </div>
                    </>
                  ) : (
                    <>
                      <div style={{ fontWeight: 600, fontSize: 13.5 }}>{l.descripcion}</div>
                      <div style={{ fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 1 }}>
                        <span className="fc-mono">{l.codigo}</span> · IVA {l.porcentaje}%
                      </div>
                    </>
                  )}
                </div>
                <input
                  className="fc-campo"
                  style={{ width: 72, padding: "7px 9px" }}
                  type="number"
                  min="0"
                  step="1"
                  disabled={congelado}
                  aria-label={`Cantidad de ${nombre}`}
                  value={l.cantidad}
                  onChange={(e) => editar(l.clave, { cantidad: e.target.value })}
                />
                <input
                  className="fc-campo"
                  style={{ width: 104, padding: "7px 9px" }}
                  type="number"
                  min="0"
                  step="0.01"
                  disabled={congelado}
                  aria-label={`Precio de ${nombre}`}
                  placeholder="0.00"
                  value={l.precio}
                  onChange={(e) => editar(l.clave, { precio: e.target.value })}
                />
                <span
                  style={{
                    width: 92,
                    textAlign: "right",
                    fontWeight: 600,
                    fontSize: 13.5,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {dinero(importeLinea(l) / 100)}
                </span>
                <button
                  type="button"
                  className="fc-btn-icono"
                  disabled={congelado}
                  aria-label={`Quitar ${nombre}`}
                  onClick={() => setLineas((ls) => ls.filter((x) => x.clave !== l.clave))}
                >
                  <Svg d={ICONO_CERRAR} tamano={13} />
                </button>
                </div>

                {/* Segundo renglón de la línea: lo que casi nunca se usa. Va
                    debajo y no en la fila de arriba para que la línea normal
                    —descripción, cantidad, precio, importe— siga cabiendo de una
                    sola vez en la pantalla de un móvil. */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                    flexWrap: "wrap",
                    marginTop: l.conDescuento || l.aMano ? 9 : 6,
                  }}
                >
                  {/* EL DESCUENTO, plegado tras «+ descuento»: el servidor lo
                      acepta desde siempre (`ItemFacturaIn.descuento`) pero la
                      inmensa mayoría de las líneas no rebajan nada, y un campo
                      más por línea es un campo más que repasar en cada factura. */}
                  {l.conDescuento ? (
                    <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                      <span style={{ fontSize: 12, color: "var(--texto-tenue)" }}>Descuento $</span>
                      <input
                        className="fc-campo"
                        style={{ width: 92, padding: "5px 8px", fontSize: 12.5 }}
                        type="number"
                        min="0"
                        step="0.01"
                        inputMode="decimal"
                        autoFocus
                        disabled={congelado}
                        aria-invalid={excede}
                        aria-label={`Descuento de ${nombre}`}
                        placeholder="0.00"
                        value={l.descuento}
                        onChange={(e) => editar(l.clave, { descuento: e.target.value })}
                      />
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="fc-btn fc-btn--texto"
                      style={{ fontSize: 12, padding: 0 }}
                      disabled={congelado}
                      aria-expanded={false}
                      onClick={() => editar(l.clave, { conDescuento: true })}
                    >
                      + descuento
                    </button>
                  )}

                  {/* La casilla de la maqueta, MARCADA por omisión: quien
                      escribe algo a mano casi siempre lo va a volver a vender.
                      Se da de alta al emitir, no ahora (ver `guardarProductos`). */}
                  {l.aMano && (
                    <label
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        fontSize: 12.5,
                        color: "var(--texto-suave)",
                      }}
                    >
                      <input
                        type="checkbox"
                        disabled={congelado}
                        checked={l.guardar ?? false}
                        onChange={(e) => editar(l.clave, { guardar: e.target.checked })}
                      />
                      Guardar en mis productos
                    </label>
                  )}
                </div>

                {/* El servidor rechaza la factura entera por esto, así que se
                    dice AQUÍ y con el número de la línea, no al final del viaje
                    con un 422 que habla de «el ítem». */}
                {excede && (
                  <p className="fc-error" role="alert" style={{ margin: "7px 0 0" }}>
                    El descuento no puede pasar de{" "}
                    {dinero(cent(num(l.cantidad) * num(l.precio)) / 100)}, que es lo que suma esta
                    línea. Bájalo, o sube la cantidad o el precio.
                  </p>
                )}
              </div>
              );
            })}
          </section>
          )}

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <div
              style={{
                display: "grid",
                gap: 7,
                minWidth: 240,
                padding: "14px 16px",
                borderRadius: "var(--radio-panel)",
                background: "var(--superficie-tenue)",
              }}
            >
              {/* AQUÍ el subtotal se enseña ANTES de descontar y el descuento va
                  restando debajo, para que la columna se pueda seguir con el
                  dedo: 100 − 20 + 12 = 92. En el documento no es así —el
                  `totalSinImpuestos` del XML ya viene descontado, y la pantalla
                  de revisión lo copia tal cual porque es el papel que va a
                  salir—, pero esto no es el papel: es la cuenta mientras se
                  arma, y la que tiene que cuadrarle a quien está vendiendo. */}
              <Fila
                etiqueta={esDebito ? "Recargo sin IVA" : "Subtotal"}
                valor={dinero((totales.subtotal + totales.descuento) / 100)}
              />
              {totales.descuento > 0 && (
                <Fila etiqueta="Descuento" valor={`− ${dinero(totales.descuento / 100)}`} />
              )}
              <Fila
                etiqueta={esDebito ? `IVA ${IVA_RECARGO.porcentaje}%` : "IVA"}
                valor={dinero(totales.iva / 100)}
              />
              <Fila
                etiqueta={esDebito ? "Le cobras" : esCredito ? "Le devuelves" : "Total"}
                valor={dinero(totales.total / 100)}
                fuerte
              />
            </div>
          </div>

          {/* En una frase: qué está pasando con esta factura. El usuario tipo no
              es contador y «nota parcial» no le dice nada; «de $115 le devuelves
              $57.50 y el resto sigue en pie», sí. */}
          {esCredito && origen !== null && (
            <div
              style={{
                padding: "12px 14px",
                borderRadius: "var(--radio-campo)",
                background: anulaTodo ? "var(--error-bg)" : "var(--superficie-tenue)",
                color: anulaTodo ? "var(--error-texto)" : "var(--texto-suave)",
                fontSize: 13,
                lineHeight: 1.55,
                textWrap: "pretty",
              }}
            >
              {Number(origen.acreditado) > 0 && (
                <p style={{ margin: "0 0 5px", fontSize: 12.5 }}>
                  De esta factura ya le devolviste {dinero(origen.acreditado)}; quedan{" "}
                  {dinero(origen.pendiente)}.
                </p>
              )}
              <p style={{ margin: 0 }}>
                {anulaTodo
                  ? Number(origen.acreditado) > 0
                    ? `Le devuelves todo lo que quedaba de la factura ${origen.numero}. Después de esto no queda nada por corregir.`
                    : `Anulas la factura ${origen.numero} entera: le devuelves todo lo que pagó.`
                  : `Corriges una parte: de ${dinero(origen.pendiente)} le devuelves ${dinero(
                      totales.total / 100,
                    )}. El resto de la factura ${origen.numero} sigue en pie.`}
              </p>
            </div>
          )}
          {/* La misma frase que en la nota de crédito, con lo que aquí importa:
              la factura NO se toca, la deuda del cliente sube. Sin jerga: nadie
              necesita saber qué es «recargo sobre documento sustento». */}
          {esDebito && origen !== null && recargoValido && (
            <div
              style={{
                padding: "12px 14px",
                borderRadius: "var(--radio-campo)",
                background: "var(--superficie-tenue)",
                color: "var(--texto-suave)",
                fontSize: 13,
                lineHeight: 1.55,
                textWrap: "pretty",
              }}
            >
              A la factura {origen.numero}, de {dinero(origen.total)}, le sumas{" "}
              {dinero(totales.total / 100)}. La factura sigue igual: lo que cambia es lo que tu
              cliente te debe, que pasa a ser{" "}
              {dinero((cent(Number(origen.total)) + totales.total) / 100)}.
            </div>
          )}
          {/* El servidor lo rechaza igual, pero enterarse aquí es enterarse
              antes de gastar un comprobante del plan.

              La segunda frase es la causa que MÁS va a aparecer y la que no se
              adivina: las líneas precargadas llegan sin el descuento que llevaba
              la factura (`lineasDe` lo explica), así que suman de más nada más
              elegirla, sin que el usuario haya tocado nada. Decirle solo «baja
              alguna cantidad» le haría recortar una devolución que sí es
              entera. */}
          {excedePendiente && origen !== null && (
            <p className="fc-error" role="alert" style={{ marginTop: 0 }}>
              No puedes devolverle más de lo que queda de la factura {origen.numero}:{" "}
              {dinero(origen.pendiente)}. Si esa factura llevaba descuento, ponlo también aquí con
              «+ descuento»; si no, baja alguna cantidad o quita una línea.
            </p>
          )}

          {/* Ninguna de las dos notas lleva forma de pago: sus XML no tienen ese
              bloque y el servidor tampoco la pide. Ofrecer un chip que no viaja
              a ninguna parte solo haría creer que se eligió algo. */}
          {!esNota && (
          <section>
            <span className="fc-label">Forma de pago</span>
            <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
              {(pagos ?? []).map((o, i) => (
                // La clave es el par (codigo, plazo): dos opciones pueden
                // compartir código y diferenciarse solo por el plazo, así que
                // `codigo` a secas no sirve de clave.
                <button
                  key={`${o.codigo}-${o.plazo_dias ?? 0}`}
                  type="button"
                  className="fc-chip"
                  aria-pressed={pago === i}
                  disabled={congelado}
                  onClick={() => setPago(i)}
                >
                  {o.etiqueta}
                </button>
              ))}
              {pagos === null && (
                <span style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>
                  Cargando las formas de pago…
                </span>
              )}
            </div>
          </section>
          )}

          {error && (
            <p className="fc-error" role="alert">
              {error}
            </p>
          )}
        </div>

        {/* El pie no desplaza con el cuerpo: con diez líneas en la factura,
            llegar al botón obligaba a bajar hasta el final. */}
        <div className="fc-modal__pie" style={{ borderTop: "1px solid var(--borde)" }}>
          <button
            type="button"
            className="fc-btn fc-btn--texto"
            disabled={congelado}
            onClick={() => setPantalla("selector")}
          >
            ‹ Otro documento
          </button>
          <span
            className="fc-mono"
            style={{ flex: 1, textAlign: "center", fontSize: 12.5, color: "var(--texto-tenue)" }}
            // El servidor NO reserva este número: si alguien emite entre
            // medias, el definitivo será otro.
            title={siguiente ? "Número previsto; el definitivo lo asigna el SRI al emitir" : undefined}
          >
            {siguiente?.numero ?? "—"}
          </span>
          {/* Ya NO emite: lleva a la revisión, que es donde se decide. Emitir es
              irreversible y no puede ser el resultado de un solo clic desde el
              formulario. */}
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            disabled={!puedeEnviar}
            onClick={() => setPantalla("revision")}
          >
            {esNota ? "Revisar nota" : "Revisar factura"}
          </button>
        </div>
      </div>
    </div>
  );
}
