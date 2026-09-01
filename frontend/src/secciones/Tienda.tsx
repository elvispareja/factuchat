/** Tienda en línea del panel (maqueta líneas 687-886).
 *
 * VITRINA INTERNA: la usa el equipo del negocio, no el comprador. La doctrina
 * de la maqueta manda: "Solo tu equipo accede, con los precios y el stock de
 * Artículos/Servicios." */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/cliente";
import type { Atributo, AtributoValor } from "../api/tipos";
import { usePlan } from "../plan/PlanContexto";
import { MuroPlan } from "../plan/Bloqueos";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";
import { dinero } from "../util/formato";

type Pestana = "pedidos" | "vitrina" | "config";

const PESTANAS: Array<{ id: Pestana; label: string }> = [
  { id: "pedidos", label: "Pedidos" },
  { id: "vitrina", label: "Mi tienda" },
  { id: "config", label: "Configuración" },
];

const ETIQUETA_ESTADO: Record<string, { label: string; clase: string }> = {
  POR_REVISAR: { label: "Por revisar", clase: "fc-estado--aviso" },
  TRANSFERENCIA_POR_CONFIRMAR: { label: "Pago por revisar", clase: "fc-estado--aviso" },
  POR_ENTREGAR: { label: "Por entregar", clase: "fc-estado--exito" },
  PAGADO: { label: "Pagado", clase: "fc-estado--exito" },
  ANULADO: { label: "Anulado", clase: "fc-estado--neutro" },
};

interface Pedido {
  id: string;
  numero: string;
  estado: string;
  metodo_pago: string;
  comprador: string;
  identificado: boolean;
  items: Array<{ nombre: string; cantidad: string }>;
  subtotal: string;
  iva: string;
  total: string;
  tiene_comprobante_pago: boolean;
  comprobante_id: string | null;
  creado: string;
}

/** Una combinación a la venta (talla 38 roja). El servidor ya resolvió el
 *  precio heredado: si la variante no tenía precio propio, aquí llega el del
 *  producto, así que la vitrina nunca vuelve a decidir de dónde sale. */
interface VarianteVitrina {
  id: string;
  codigo: string;
  precio_sin_iva: string;
  stock: string;
  agotado: boolean;
  valores: Array<{ atributo_id: string; atributo_valor_id: string }>;
}

interface ArticuloVitrina {
  id: string;
  codigo: string;
  nombre: string;
  precio_sin_iva: string;
  porcentaje_iva: string;
  tipo: string;
  maneja_inventario: boolean;
  stock: string;
  agotado: boolean;
  variantes: VarianteVitrina[];
}

/** La vitrina manda los atributos como ids; los nombres («Talla», «38») viven
 *  en el catálogo de atributos. `orden` conserva el del catálogo, para que las
 *  tallas salgan 38, 39, 40 y no en el orden en que se crearon las variantes. */
type Indice = Record<string, { nombre: string; orden: number }>;
type Nombres = { atributo: Indice; valor: Indice };

interface LineaPedido {
  /** La variante si la hay, el producto si no: identifica la fila del pedido. */
  clave: string;
  producto_id: string;
  variante_id: string | null;
  nombre: string;
  codigo: string;
  precio: string;
  cantidad: number;
  /** Stock disponible; null cuando el artículo no lleva conteo. */
  tope: number | null;
}

const tiene = (v: VarianteVitrina, atributoId: string, valorId: string) =>
  v.valores.some((x) => x.atributo_id === atributoId && x.atributo_valor_id === valorId);

function Estado({ clase, texto }: { clase: string; texto: string }) {
  return (
    <span className={`fc-estado ${clase}`}>
      <span className="fc-estado__punto" />
      {texto}
    </span>
  );
}

export function Tienda({ onVerPlanes }: { onVerPlanes: () => void }) {
  const { permite, planPara } = usePlan();
  const [pestana, setPestana] = useState<Pestana>("pedidos");

  if (!permite("tienda")) {
    const destino = planPara("tienda") ?? "Empresario";
    return (
      <MuroPlan
        titulo="Tu tienda existe. Está esperando."
        texto={`La tienda en línea viene con el plan ${destino}. Tu catálogo y tus fotos siguen guardados tal como los dejaste, y vuelve a funcionar el mismo día que actives el plan.`}
        textoBoton={`Activar el plan ${destino}`}
        onVerPlanes={onVerPlanes}
      />
    );
  }

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div className="fc-tabs" role="tablist" aria-label="Secciones de la tienda">
        {PESTANAS.map((p) => (
          <button
            key={p.id}
            type="button"
            role="tab"
            className="fc-tab"
            aria-selected={pestana === p.id}
            onClick={() => setPestana(p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {pestana === "pedidos" && <Pedidos />}
      {pestana === "vitrina" && <MiTienda />}
      {pestana === "config" && <ConfiguracionTienda />}
    </div>
  );
}

function Pedidos() {
  const [datos, setDatos] = useState<{ resumen: Record<string, number>; pedidos: Pedido[] } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [trabajando, setTrabajando] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setError(null);
    try {
      setDatos(await api.get("/tienda/pedidos"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function accion(id: string, ruta: string) {
    setTrabajando(id);
    setError(null);
    try {
      await api.post(`/tienda/pedidos/${id}/${ruta}`);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos completar la acción");
    } finally {
      setTrabajando(null);
    }
  }

  if (error && !datos) return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  if (!datos) return <Cargando />;

  const r = datos.resumen;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div className="fc-kpi">
        <Contador etiqueta="Por revisar" valor={r.POR_REVISAR ?? 0} />
        <Contador
          etiqueta="Transferencias por confirmar"
          valor={r.TRANSFERENCIA_POR_CONFIRMAR ?? 0}
        />
        <Contador etiqueta="Por entregar" valor={r.POR_ENTREGAR ?? 0} />
        <Contador etiqueta="Pagados" valor={r.PAGADO ?? 0} />
      </div>

      {error && (
        <p className="fc-error" role="alert">
          {error}
        </p>
      )}

      <section className="fc-tarjeta fc-tarjeta--tabla">
        {datos.pedidos.length === 0 ? (
          <Vacio
            titulo="Todavía no hay pedidos."
            ayuda="Cuando tu equipo cierre una venta desde la vitrina, el pedido aparecerá aquí con su estado."
          />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="fc-tabla">
              <thead>
                <tr>
                  <th scope="col">Pedido</th>
                  <th scope="col">Comprador</th>
                  <th scope="col">Artículos</th>
                  <th scope="col" className="fc-num">Total</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Acción</th>
                </tr>
              </thead>
              <tbody>
                {datos.pedidos.map((p) => {
                  const tono = ETIQUETA_ESTADO[p.estado] ?? {
                    label: p.estado,
                    clase: "fc-estado--neutro",
                  };
                  return (
                    <tr key={p.id}>
                      <td className="fc-mono" style={{ fontWeight: 600 }}>
                        {p.numero}
                      </td>
                      <td>
                        <div>{p.comprador}</div>
                        <div style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                          {p.identificado ? "Identificado" : "Consumidor final"}
                        </div>
                      </td>
                      <td>{p.items.length}</td>
                      <td className="fc-num">{dinero(p.total)}</td>
                      <td>
                        <span className={`fc-estado ${tono.clase}`}>
                          <span className="fc-estado__punto" />
                          {tono.label}
                        </span>
                        {p.tiene_comprobante_pago && (
                          <div style={{ fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 4 }}>
                            Con comprobante adjunto
                          </div>
                        )}
                      </td>
                      <td>
                        {p.estado === "TRANSFERENCIA_POR_CONFIRMAR" && (
                          <button
                            type="button"
                            className="fc-btn fc-btn--contorno"
                            style={{ padding: "6px 14px", fontSize: 12.5 }}
                            disabled={trabajando === p.id}
                            onClick={() => void accion(p.id, "confirmar-pago")}
                          >
                            Revisar pago
                          </button>
                        )}
                        {p.estado === "POR_ENTREGAR" && !p.comprobante_id && (
                          <button
                            type="button"
                            className="fc-btn fc-btn--primario"
                            style={{ padding: "6px 14px", fontSize: 12.5 }}
                            disabled={trabajando === p.id}
                            onClick={() => void accion(p.id, "facturar")}
                          >
                            Facturar
                          </button>
                        )}
                        {p.comprobante_id && (
                          <span style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>
                            Ya está en Comprobantes
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function MiTienda() {
  const [articulos, setArticulos] = useState<ArticuloVitrina[] | null>(null);
  const [nombres, setNombres] = useState<Nombres>({ atributo: {}, valor: {} });
  const [error, setError] = useState<string | null>(null);
  const [lineas, setLineas] = useState<LineaPedido[]>([]);
  // Vive aquí y no en el panel: al crearse el pedido el panel se vacía y
  // desaparece, y con él se iría el aviso de que la venta quedó registrada.
  const [creado, setCreado] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const arts = await api.get<ArticuloVitrina[]>("/tienda/vitrina");
        // Solo se piden los nombres si hay algo que nombrar. Si fallan, el
        // selector sigue funcionando con etiquetas pobres en vez de caerse.
        if (arts.some((a) => (a.variantes ?? []).length > 0)) {
          const [atrs, vals] = await Promise.all([
            api.get<Atributo[]>("/atributos").catch(() => [] as Atributo[]),
            api.get<AtributoValor[]>("/atributo-valores").catch(() => [] as AtributoValor[]),
          ]);
          setNombres({
            atributo: Object.fromEntries(
              atrs.map((x, i) => [x.id, { nombre: x.nombre, orden: i }]),
            ),
            valor: Object.fromEntries(vals.map((x, i) => [x.id, { nombre: x.valor, orden: i }])),
          });
        }
        setArticulos(arts);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
    })();
  }, []);

  function agregar(linea: LineaPedido) {
    setCreado(null);
    setLineas((prev) => {
      const i = prev.findIndex((x) => x.clave === linea.clave);
      if (i < 0) return [...prev, linea];
      const copia = [...prev];
      const cantidad = copia[i].cantidad + 1;
      copia[i] = {
        ...copia[i],
        cantidad: copia[i].tope !== null ? Math.min(cantidad, copia[i].tope) : cantidad,
      };
      return copia;
    });
  }

  if (error) return <ErrorSeccion mensaje={error} />;
  if (!articulos) return <Cargando />;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <section className="fc-tarjeta">
        <p className="fc-kicker">Tu inventario en vista de tienda</p>
        <p style={{ fontSize: 13.5, color: "var(--texto-suave)", margin: "6px 0 0" }}>
          Selecciona productos y cierra la venta aquí mismo. La vitrina es tu herramienta de venta:
          tus clientes no necesitan entrar aquí.
        </p>
      </section>

      {creado && (
        <p className="fc-tarjeta" style={{ fontSize: 13, color: "var(--exito-texto)" }}>
          Pedido {creado} creado. Está en la pestaña Pedidos.
        </p>
      )}

      {lineas.length > 0 && (
        <PedidoEnCurso lineas={lineas} setLineas={setLineas} onCreado={setCreado} />
      )}

      {articulos.length === 0 ? (
        <section className="fc-tarjeta">
          <Vacio
            titulo="Aún no has puesto productos en la vitrina."
            ayuda="Marca «Mostrar en tienda» en los artículos que quieras vender desde aquí."
          />
        </section>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: 14,
          }}
        >
          {articulos.map((a) => (
            <TarjetaArticulo key={a.id} a={a} nombres={nombres} onAgregar={agregar} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Una tarjeta de la vitrina. Con variantes hay que elegir la combinación antes
 *  de añadirla: el precio, el stock y el código que va a la factura son los de
 *  la variante, no los del producto. */
function TarjetaArticulo({
  a,
  nombres,
  onAgregar,
}: {
  a: ArticuloVitrina;
  nombres: Nombres;
  onAgregar: (l: LineaPedido) => void;
}) {
  const [sel, setSel] = useState<Record<string, string>>({});

  // Los ejes del selector salen de las propias variantes: Talla=[38,39], Color=[Rojo,Negro].
  const ejes = useMemo(() => {
    const porAtributo = new Map<string, string[]>();
    for (const v of a.variantes ?? []) {
      for (const x of v.valores) {
        const vals = porAtributo.get(x.atributo_id) ?? [];
        if (!vals.includes(x.atributo_valor_id)) vals.push(x.atributo_valor_id);
        porAtributo.set(x.atributo_id, vals);
      }
    }
    return [...porAtributo]
      .map(([id, valores]) => ({
        id,
        nombre: nombres.atributo[id]?.nombre ?? "Opción",
        valores: valores
          .map((vid) => ({ id: vid, nombre: nombres.valor[vid]?.nombre ?? vid.slice(0, 8) }))
          .sort((x, y) => (nombres.valor[x.id]?.orden ?? 0) - (nombres.valor[y.id]?.orden ?? 0)),
      }))
      .sort((x, y) => (nombres.atributo[x.id]?.orden ?? 0) - (nombres.atributo[y.id]?.orden ?? 0));
  }, [a, nombres]);

  const completa = ejes.length > 0 && ejes.every((e) => sel[e.id]);
  const elegida = useMemo(
    () =>
      completa
        ? ((a.variantes ?? []).find((v) => ejes.every((e) => tiene(v, e.id, sel[e.id]))) ?? null)
        : null,
    [a, ejes, sel, completa],
  );

  /** Un valor se ofrece si queda alguna variante CON stock que lo lleve y que
   *  encaje con lo ya elegido en los otros ejes: con Rojo puesto, la talla 38
   *  sale deshabilitada si solo quedaba en negro. */
  function disponible(ejeId: string, valorId: string) {
    return (a.variantes ?? []).some(
      (v) =>
        !v.agotado &&
        tiene(v, ejeId, valorId) &&
        ejes.every((e) => e.id === ejeId || !sel[e.id] || tiene(v, e.id, sel[e.id])),
    );
  }

  // Con variantes el stock del producto es 0 por diseño: quien manda es el de
  // las combinaciones, o la tarjeta entera saldría agotada siempre.
  const agotado = ejes.length > 0 ? (a.variantes ?? []).every((v) => v.agotado) : a.agotado;

  const precios = (a.variantes ?? []).map((v) => Number(v.precio_sin_iva));
  const precio = elegida
    ? dinero(elegida.precio_sin_iva)
    : precios.length > 0
      ? Math.max(...precios) > Math.min(...precios)
        ? `${dinero(Math.min(...precios))} – ${dinero(Math.max(...precios))}`
        : dinero(Math.min(...precios))
      : dinero(a.precio_sin_iva);

  function estado(): { clase: string; texto: string } {
    if (agotado) return { clase: "fc-estado--error", texto: "Agotado" };
    if (ejes.length > 0) {
      if (!completa) {
        const que = ejes.map((e) => e.nombre.toLowerCase()).join(" y ");
        return { clase: "fc-estado--neutro", texto: `Elige ${que}` };
      }
      if (!elegida || elegida.agotado)
        return { clase: "fc-estado--error", texto: "Esa combinación no está disponible" };
      return {
        clase: "fc-estado--exito",
        texto: a.maneja_inventario ? `${Number(elegida.stock)} disponibles` : "Disponible",
      };
    }
    if (a.maneja_inventario)
      return { clase: "fc-estado--exito", texto: `${Number(a.stock)} disponibles` };
    if (a.tipo === "SERVICIO") return { clase: "fc-estado--neutro", texto: "Servicio" };
    // Artículo sin conteo de unidades: al comprador no le importa que no
    // llevemos inventario, solo que puede pedirlo. Antes caía aquí y se
    // anunciaba como «Servicio».
    return { clase: "fc-estado--exito", texto: "Disponible" };
  }

  const puedeAnadir = !agotado && (ejes.length === 0 || Boolean(elegida && !elegida.agotado));
  const tono = estado();

  function anadir() {
    const detalle = ejes
      .map((e) => e.valores.find((v) => v.id === sel[e.id])?.nombre)
      .filter(Boolean)
      .join(" / ");
    onAgregar({
      clave: elegida ? elegida.id : a.id,
      producto_id: a.id,
      variante_id: elegida?.id ?? null,
      nombre: elegida ? `${a.nombre} · ${detalle}` : a.nombre,
      codigo: elegida ? elegida.codigo : a.codigo,
      precio: elegida ? elegida.precio_sin_iva : a.precio_sin_iva,
      cantidad: 1,
      tope: a.maneja_inventario ? Number(elegida ? elegida.stock : a.stock) : null,
    });
  }

  return (
    <article className="fc-tarjeta" style={{ padding: "16px 18px 18px", opacity: agotado ? 0.55 : 1 }}>
      <div style={{ fontSize: 14.5, fontWeight: 600, marginBottom: 4 }}>{a.nombre}</div>
      <div className="fc-mono" style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
        {elegida ? elegida.codigo : a.codigo}
      </div>
      <div className="fc-cifra" style={{ fontSize: 20, margin: "10px 0 2px" }}>
        {precio}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--texto-tenue)", marginBottom: 10 }}>
        sin impuesto · IVA {Number(a.porcentaje_iva)}%
      </div>

      {/* Un desplegable por atributo: no crece con las combinaciones, así que
          treinta tallas no deforman la tarjeta. */}
      {ejes.map((e) => (
        <label key={e.id} style={{ display: "block", marginBottom: 8 }}>
          <span className="fc-label" style={{ fontSize: 11, marginBottom: 4 }}>
            {e.nombre}
          </span>
          <select
            className="fc-campo"
            style={{ padding: "8px 10px", fontSize: 13 }}
            value={sel[e.id] ?? ""}
            onChange={(ev) => setSel((prev) => ({ ...prev, [e.id]: ev.target.value }))}
          >
            <option value="">Elegir…</option>
            {e.valores.map((v) => {
              const hay = disponible(e.id, v.id);
              return (
                <option key={v.id} value={v.id} disabled={!hay}>
                  {v.nombre}
                  {hay ? "" : " · agotado"}
                </option>
              );
            })}
          </select>
        </label>
      ))}

      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Estado clase={tono.clase} texto={tono.texto} />
        <button
          type="button"
          className="fc-btn fc-btn--contorno"
          style={{ padding: "6px 14px", fontSize: 12.5, marginLeft: "auto" }}
          disabled={!puedeAnadir}
          onClick={anadir}
        >
          Añadir
        </button>
      </div>
    </article>
  );
}

/** El pedido que se está armando. Cada línea manda `variante_id` cuando la
 *  venta es de una combinación: de ahí saca el servidor el precio, el código
 *  del comprobante y el stock que descuenta. */
function PedidoEnCurso({
  lineas,
  setLineas,
  onCreado,
}: {
  lineas: LineaPedido[];
  setLineas: React.Dispatch<React.SetStateAction<LineaPedido[]>>;
  onCreado: (numero: string) => void;
}) {
  const [metodos, setMetodos] = useState<Array<{ id: string; label: string; activo: boolean }>>([]);
  const [metodo, setMetodo] = useState("");
  const [comprador, setComprador] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Array<{ id: string; label: string; activo: boolean }>>("/tienda/metodos")
      .then((ms) => {
        const activos = ms.filter((m) => m.activo);
        setMetodos(activos);
        setMetodo((prev) => prev || (activos[0]?.id ?? ""));
      })
      .catch(() => setMetodos([]));
  }, []);

  const total = lineas.reduce((s, l) => s + Number(l.precio) * l.cantidad, 0);

  async function crear() {
    setEnviando(true);
    setError(null);
    try {
      const pedido = await api.post<{ numero: string }>("/tienda/pedidos", {
        items: lineas.map((l) => ({
          producto_id: l.producto_id,
          variante_id: l.variante_id,
          cantidad: String(l.cantidad),
        })),
        metodo_pago: metodo,
        comprador_nombre: comprador.trim() || null,
      });
      setComprador("");
      onCreado(pedido.numero);
      setLineas([]); // último: desmonta este panel
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos crear el pedido");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="fc-tarjeta">
      <p className="fc-kicker">Pedido en curso</p>
      <div style={{ overflowX: "auto", marginTop: 12 }}>
        <table className="fc-tabla">
          <thead>
            <tr>
              <th scope="col">Artículo</th>
              <th scope="col">Código</th>
              <th scope="col" className="fc-num">Cantidad</th>
              <th scope="col" className="fc-num">Precio</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {lineas.map((l) => (
              <tr key={l.clave}>
                <td>{l.nombre}</td>
                <td className="fc-mono">{l.codigo}</td>
                <td className="fc-num">
                  <input
                    className="fc-campo"
                    type="number"
                    min={1}
                    max={l.tope ?? undefined}
                    step="1"
                    style={{ width: 78, padding: "6px 8px", fontSize: 13 }}
                    value={l.cantidad}
                    aria-label={`Cantidad de ${l.nombre}`}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      setLineas((prev) =>
                        prev.map((x) =>
                          x.clave === l.clave
                            ? { ...x, cantidad: Number.isFinite(n) && n >= 1 ? n : 1 }
                            : x,
                        ),
                      );
                    }}
                  />
                </td>
                <td className="fc-num">{dinero(Number(l.precio) * l.cantidad)}</td>
                <td>
                  <button
                    type="button"
                    className="fc-btn fc-btn--contorno"
                    style={{ padding: "6px 12px", fontSize: 12.5 }}
                    onClick={() => setLineas((prev) => prev.filter((x) => x.clave !== l.clave))}
                  >
                    Quitar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "flex-end",
          flexWrap: "wrap",
          marginTop: 14,
        }}
      >
        <label style={{ flex: "1 1 180px" }}>
          <span className="fc-label">Comprador (opcional)</span>
          <input
            className="fc-campo"
            value={comprador}
            onChange={(e) => setComprador(e.target.value)}
            placeholder="Consumidor final"
          />
        </label>
        <label style={{ flex: "1 1 180px" }}>
          <span className="fc-label">Cómo cobras</span>
          <select className="fc-campo" value={metodo} onChange={(e) => setMetodo(e.target.value)}>
            {metodos.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <div style={{ marginLeft: "auto", textAlign: "right" }}>
          <div style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>Subtotal sin IVA</div>
          <div className="fc-cifra" style={{ fontSize: 20 }}>
            {dinero(total)}
          </div>
        </div>
        <button
          type="button"
          className="fc-btn fc-btn--primario"
          disabled={enviando || !metodo}
          onClick={() => void crear()}
        >
          {enviando ? "Creando…" : "Crear pedido"}
        </button>
      </div>

      {error && (
        <p className="fc-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function ConfiguracionTienda() {
  const [metodos, setMetodos] = useState<
    Array<{ id: string; label: string; nota: string; activo: boolean }> | null
  >(null);

  useEffect(() => {
    api
      .get<Array<{ id: string; label: string; nota: string; activo: boolean }>>("/tienda/metodos")
      .then(setMetodos)
      .catch(() => setMetodos([]));
  }, []);

  return (
    <div className="fc-split">
      <div style={{ display: "grid", gap: 18 }}>
        <section className="fc-tarjeta--oscura">
          <div className="fc-halo" />
          <div style={{ position: "relative", zIndex: 1 }}>
            <p className="fc-kicker" style={{ color: "var(--verde-claro)" }}>
              Tu tienda es interna
            </p>
            <p
              style={{
                fontSize: 13.5,
                lineHeight: 1.55,
                color: "#A6BFB2",
                margin: "8px 0 14px",
                maxWidth: "46ch",
              }}
            >
              La vitrina es tu herramienta de venta: tú o tu equipo seleccionan los productos del
              inventario, cierran la venta y el comprobante sale al instante. Tus clientes no
              necesitan entrar aquí.
            </p>
            <div
              style={{
                background: "rgba(255,255,255,.06)",
                border: "1px solid rgba(92,230,143,.28)",
                borderRadius: 13,
                padding: "12px 14px",
                fontSize: 12.5,
                color: "#DDF3E6",
              }}
            >
              Solo tu equipo accede, con los precios y el stock de Artículos/Servicios.
            </div>
          </div>
        </section>

        <section className="fc-tarjeta">
          <h3 className="fc-titulo" style={{ fontSize: 18, marginBottom: 8 }}>
            Tus precios se cargan sin IVA
          </h3>
          <p style={{ fontSize: 13, lineHeight: 1.5, color: "var(--texto-suave)", margin: 0 }}>
            En Artículos/Servicios cada producto lleva su precio sin impuesto y su tarifa de IVA por
            separado. La tienda calcula el impuesto al facturar — así nunca hay dobles cobros ni
            descuadres.
          </p>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              background: "var(--superficie-suave)",
              border: "1px solid #EFF2EE",
              borderRadius: 14,
              padding: "13px 16px",
              marginTop: 14,
            }}
          >
            <span className="fc-mono" style={{ fontSize: 12, color: "var(--texto-suave)" }}>
              $100.00 + IVA 15%
            </span>
            <span style={{ color: "#8A9A91" }}>→</span>
            <span className="fc-mono" style={{ fontSize: 12, fontWeight: 700 }}>
              $115.00 en la factura
            </span>
          </div>
        </section>

        <section className="fc-tarjeta">
          <h3 className="fc-titulo" style={{ fontSize: 18, marginBottom: 8 }}>
            Si el comprador no quiere dar sus datos
          </h3>
          <p style={{ fontSize: 13, lineHeight: 1.5, color: "var(--texto-suave)", margin: 0 }}>
            Se emite igual, a consumidor final, y le llega su comprobante sin que entregue nada. Así
            tu venta queda declarada. Por norma del SRI, sin datos del comprador se puede facturar
            hasta $200: por encima de ese monto la vitrina te pedirá su cédula o RUC.
          </p>
          <div
            style={{
              display: "flex",
              gap: 10,
              alignItems: "center",
              background: "rgba(34,197,94,.07)",
              border: "1px solid rgba(22,121,74,.2)",
              borderRadius: 14,
              padding: "14px 16px",
              marginTop: 14,
              fontSize: 13.5,
              color: "var(--texto)",
            }}
          >
            <strong style={{ fontWeight: 600 }}>Activo siempre.</strong> Tu tienda nunca vende sin
            comprobante.
          </div>
        </section>
      </div>

      <section className="fc-tarjeta">
        <p className="fc-kicker">Cómo cobras</p>
        <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
          {(metodos ?? []).map((m) => (
            <div
              key={m.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                borderRadius: 13,
                padding: "13px 15px",
                background: m.activo ? "var(--superficie)" : "var(--superficie-suave)",
                border: `1px solid ${m.activo ? "var(--borde)" : "#EFF2EE"}`,
              }}
            >
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: "block", fontSize: 14, fontWeight: 600 }}>{m.label}</span>
                <span style={{ display: "block", fontSize: 12.5, color: "var(--texto-tenue)" }}>
                  {m.nota}
                </span>
              </span>
              <span
                style={{
                  fontSize: 11.5,
                  fontWeight: 600,
                  color: m.activo ? "var(--exito-texto)" : "var(--texto-tenue)",
                }}
              >
                {m.activo ? "Activo" : "Sin conectar"}
              </span>
            </div>
          ))}
        </div>
        <p style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--texto-tenue)", marginTop: 14 }}>
          El dinero entra directo a tu cuenta Payphone, no pasa por Factuchat. Si no la conectas, tu
          tienda cobra por transferencia y por WhatsApp.
        </p>
      </section>
    </div>
  );
}

function Contador({ etiqueta, valor }: { etiqueta: string; valor: number }) {
  return (
    <div className="fc-tarjeta" style={{ padding: "16px 18px 18px" }}>
      <div className="fc-cifra" style={{ fontSize: 24 }}>
        {valor}
      </div>
      <div style={{ fontSize: 12.5, color: "var(--texto-tenue)", marginTop: 4 }}>{etiqueta}</div>
    </div>
  );
}
