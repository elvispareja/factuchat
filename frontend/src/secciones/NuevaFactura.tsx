/** Crear comprobante: el selector de tipo (pantalla 1) y el modal de nueva
 *  factura (pantalla 2).
 *
 *  SOLO la factura existe. Las otras tres tarjetas se pintan como en la
 *  maqueta, pero atenuadas y sin destino: el servidor no tiene rutas ni
 *  esquemas para nota de crédito, nota de débito ni retención, y un formulario
 *  que finge funcionar es peor que un «Próximamente» honesto.
 *
 *  El panel NO lleva overflow ni max-height propios: `.fc-modal` desplaza el
 *  fondo y `.fc-modal__panel` se centra con `margin: auto` (ver el comentario
 *  largo en design/componentes.css). Reponer aquí un `overflow` es justo lo que
 *  dejaba la cabecera y el pie irrecuperables en los modales altos.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ErrorLimitePlan, api } from "../api/cliente";
import type {
  AtributoValor,
  ClienteFinal,
  Comprobante,
  OpcionPago,
  Producto,
  ProductoVariante,
  SiguienteNumero,
} from "../api/tipos";
import { dinero, inicial } from "../util/formato";
import type { LineaCalculable } from "../util/totales";
import { TOPE_CONSUMIDOR_FINAL, cent, num, totalizar } from "../util/totales";

/** Una línea de la factura: lo que hay que calcular más lo que hay que pintar. */
interface Linea extends LineaCalculable {
  clave: string;
  codigo: string;
  descripcion: string;
}

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

/* --- Pantalla 1: elegir el tipo de documento -------------------------------- */

const TONOS = {
  verde: { fondo: "rgba(34,197,94,.12)", color: "var(--verde-medio)" },
  rojo: { fondo: "var(--error-bg)", color: "var(--error-texto)" },
  ambar: { fondo: "var(--aviso-bg)", color: "var(--aviso-texto)" },
  gris: { fondo: "var(--superficie-tenue)", color: "var(--texto-tenue)" },
} as const;

const TIPOS: Array<{
  id: string;
  titulo: string;
  texto: string;
  tono: keyof typeof TONOS;
  icono: string;
  disponible: boolean;
}> = [
  {
    id: "FACTURA",
    titulo: "Factura",
    texto: "Le vendiste un producto o un servicio.",
    tono: "verde",
    icono: ICONO_DOC,
    disponible: true,
  },
  {
    id: "NOTA_CREDITO",
    titulo: "Nota de crédito",
    texto: "Anular o corregir una factura ya emitida.",
    tono: "rojo",
    icono: ICONO_MENOS,
    disponible: false,
  },
  {
    id: "NOTA_DEBITO",
    titulo: "Nota de débito",
    texto: "Cobrar un recargo o interés sobre una factura.",
    tono: "ambar",
    icono: ICONO_MAS,
    disponible: false,
  },
  {
    id: "RETENCION",
    titulo: "Retención recibida",
    texto: "Tu cliente te retuvo y te mandó el comprobante.",
    tono: "gris",
    icono: ICONO_PORCENTAJE,
    disponible: false,
  },
];

function Cabecera({
  titulo,
  subtitulo,
  onCerrar,
}: {
  titulo: string;
  subtitulo: string;
  onCerrar: () => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 18 }}>
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

function PanelSelector({ onFactura, onCerrar }: { onFactura: () => void; onCerrar: () => void }) {
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
              disabled={!t.disponible}
              // Los cuatro que faltan no se navegan, y se dice por qué en vez
              // de dejar al usuario probando clics que no hacen nada.
              title={t.disponible ? undefined : "Todavía no está disponible"}
              // Condicionado, no solo `disabled`: si algún día se sustituye por
              // aria-disabled (para que el título se lea y el botón se enfoque),
              // pulsar «Nota de crédito» abriría el formulario de FACTURA sin
              // avisar. Emitir el documento equivocado no puede depender de un
              // atributo del navegador.
              onClick={t.disponible ? onFactura : undefined}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 13,
                padding: "13px 15px",
                textAlign: "left",
                font: "inherit",
                color: "inherit",
                background: "var(--superficie)",
                cursor: t.disponible ? "pointer" : "not-allowed",
                opacity: t.disponible ? 1 : 0.5,
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
              {t.disponible ? (
                <span aria-hidden="true" style={{ color: "var(--texto-tenue)", display: "grid" }}>
                  <Svg d={ICONO_CHEVRON} tamano={15} />
                </span>
              ) : (
                <span
                  style={{
                    flex: "none",
                    fontSize: 11,
                    color: "var(--texto-tenue)",
                    border: "1px solid var(--borde)",
                    borderRadius: "var(--radio-pildora)",
                    padding: "3px 9px",
                  }}
                >
                  Próximamente
                </span>
              )}
            </button>
          );
        })}
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

function Fila({ etiqueta, valor, fuerte }: { etiqueta: string; valor: ReactNode; fuerte?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 20 }}>
      <span style={{ fontSize: fuerte ? 14 : 13, color: fuerte ? "var(--texto)" : "var(--texto-tenue)" }}>
        {etiqueta}
      </span>
      <span
        style={{
          fontSize: fuerte ? 18 : 13,
          fontWeight: fuerte ? 700 : 500,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {valor}
      </span>
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
}

export function CrearComprobante({ onCerrar, onRecargar }: Props) {
  const [pantalla, setPantalla] = useState<"selector" | "factura">("selector");

  // Catálogos: se piden al ENTRAR en la factura, no al abrir el selector, y una
  // sola vez — volver con «Otro documento» no los vuelve a pedir.
  const pedidos = useRef(false);
  const [clientes, setClientes] = useState<ClienteFinal[] | null>(null);
  const [productos, setProductos] = useState<Producto[] | null>(null);
  const [nombreValor, setNombreValor] = useState<Record<string, string>>({});
  const [pagos, setPagos] = useState<OpcionPago[] | null>(null);
  const [siguiente, setSiguiente] = useState<SiguienteNumero | null>(null);
  const [errorCatalogo, setErrorCatalogo] = useState<string | null>(null);

  // Formulario
  const [cliente, setCliente] = useState<ClienteFinal | "final" | null>(null);
  const [lineas, setLineas] = useState<Linea[]>([]);
  const [pago, setPago] = useState(0);
  const [eligiendo, setEligiendo] = useState(false);

  // Envío. `borrador` guarda el id del POST /facturas para que un segundo
  // intento EMITA el mismo borrador en vez de crear otro.
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [borrador, setBorrador] = useState<string | null>(null);

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
    // 404 si el negocio todavía no tiene establecimiento activo: el pie enseña
    // un guion. Es un rótulo informativo, no un requisito para emitir.
    void api.get<SiguienteNumero>("/comprobantes/siguiente-numero").then(setSiguiente).catch(() => {});
  }, [pantalla]);

  const totales = useMemo(() => totalizar(lineas), [lineas]);
  const esConsumidorFinal =
    cliente === "final" ||
    (cliente !== null && cliente.tipo_identificacion === "CONSUMIDOR_FINAL");
  const excedeTope = esConsumidorFinal && totales.total > TOPE_CONSUMIDOR_FINAL;

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
        codigoIva: p.codigo_iva,
        porcentaje: Number(p.porcentaje_iva),
      },
    ]);
    // El selector NO se cierra: una factura de seis líneas obligaba a pulsar
    // «Agregar ítem» seis veces y a reescribir la búsqueda cada vez. Se cierra
    // con su propio botón, cuando el usuario ha terminado de añadir.
  }

  const opcion = pagos?.[pago];
  const puedeEnviar =
    !enviando &&
    (congelado ||
      (cliente !== null &&
        lineas.length > 0 &&
        // También el precio: `num()` devuelve 0 para un campo vacío, así que
        // borrar un precio para reescribirlo y despistarse emitía una línea a
        // $0,00 —o una factura entera a cero— y el servidor la acepta.
        lineas.every((l) => num(l.cantidad) > 0 && num(l.precio) > 0) &&
        !excedeTope));

  async function enviar() {
    // Guarda contra el doble clic: sin esto, dos pulsaciones seguidas crean dos
    // facturas (y queman dos comprobantes del plan).
    if (enviando || !puedeEnviar) return;
    setEnviando(true);
    setError(null);
    let id = borrador;
    try {
      if (id === null) {
        const creado = await api.post<Comprobante>("/comprobantes/facturas", {
          cliente_final_id: cliente !== null && cliente !== "final" ? cliente.id : null,
          items: lineas.map((l) => ({
            codigo: l.codigo.slice(0, 25),
            descripcion: l.descripcion.slice(0, 300),
            cantidad: String(num(l.cantidad)),
            precio_unitario: String(num(l.precio)),
            codigo_iva: l.codigoIva,
          })),
          // Sin la lista cargada no se inventa una forma de pago: el servidor
          // aplica su propio valor por omisión.
          ...(opcion ? { forma_pago: opcion.codigo, plazo_dias: opcion.plazo_dias } : {}),
        });
        // A partir de aquí el borrador EXISTE, pase lo que pase con el envío.
        id = creado.id;
        setBorrador(id);
      }
      // Segundo paso, y puede fallar por su cuenta con el borrador ya guardado.
      await api.post<Comprobante>(`/comprobantes/${id}/emitir`, {});
      await onRecargar();
      onCerrar();
    } catch (e) {
      if (id !== null) {
        // Decir «no se guardó nada» sería mentira: el borrador está en la base
        // y va a salir en el historial. Se recarga por detrás para que se vea.
        setError(
          `Creamos el borrador, pero no pudimos enviarlo al SRI: ${textoError(e)} ` +
            "Ya aparece en tu historial como pendiente: reintenta el envío aquí o ciérralo y hazlo más tarde.",
        );
        void onRecargar();
      } else {
        setError(textoError(e));
      }
    } finally {
      setEnviando(false);
    }
  }

  if (pantalla === "selector") {
    return (
      <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Crear comprobante">
        <PanelSelector onFactura={() => setPantalla("factura")} onCerrar={onCerrar} />
      </div>
    );
  }

  return (
    <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Nueva factura">
      <div className="fc-modal__panel" style={{ maxWidth: 760 }}>
        <Cabecera
          titulo="Nueva factura"
          subtitulo="Se firma con tu certificado y se envía al SRI."
          onCerrar={onCerrar}
        />

        <div style={{ display: "grid", gap: 20 }}>
          {errorCatalogo && (
            <p className="fc-error" role="alert">
              {errorCatalogo}
            </p>
          )}

          <section>
            <span className="fc-label">Cliente</span>
            {cliente === null ? (
              <BuscadorCliente clientes={clientes} onElegir={setCliente} />
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
          </section>

          <section>
            <div
              style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 9 }}
            >
              <span className="fc-label" style={{ flex: 1, marginBottom: 0 }}>
                Qué le vendiste
              </span>
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
                Todavía no agregaste nada.
              </div>
            )}

            {lineas.map((l) => (
              <div
                key={l.clave}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  flexWrap: "wrap",
                  padding: "11px 0",
                  borderBottom: "1px solid var(--borde)",
                }}
              >
                <div style={{ flex: "1 1 190px", minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }}>{l.descripcion}</div>
                  <div style={{ fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 1 }}>
                    <span className="fc-mono">{l.codigo}</span> · IVA {l.porcentaje}%
                  </div>
                </div>
                <input
                  className="fc-campo"
                  style={{ width: 72, padding: "7px 9px" }}
                  type="number"
                  min="0"
                  step="1"
                  disabled={congelado}
                  aria-label={`Cantidad de ${l.descripcion}`}
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
                  aria-label={`Precio de ${l.descripcion}`}
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
                  {dinero(cent(num(l.cantidad) * num(l.precio)) / 100)}
                </span>
                <button
                  type="button"
                  className="fc-btn-icono"
                  disabled={congelado}
                  aria-label={`Quitar ${l.descripcion}`}
                  onClick={() => setLineas((ls) => ls.filter((x) => x.clave !== l.clave))}
                >
                  <Svg d={ICONO_CERRAR} tamano={13} />
                </button>
              </div>
            ))}
          </section>

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
              <Fila etiqueta="Subtotal" valor={dinero(totales.subtotal / 100)} />
              <Fila etiqueta="IVA" valor={dinero(totales.iva / 100)} />
              <Fila etiqueta="Total" valor={dinero(totales.total / 100)} fuerte />
            </div>
          </div>

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

          {error && (
            <p className="fc-error" role="alert">
              {error}
            </p>
          )}

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
              borderTop: "1px solid var(--borde)",
              paddingTop: 16,
            }}
          >
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
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              disabled={!puedeEnviar}
              onClick={() => void enviar()}
            >
              {enviando
                ? "Enviando…"
                : congelado
                  ? "Reintentar el envío"
                  : "Revisar y enviar al SRI"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
