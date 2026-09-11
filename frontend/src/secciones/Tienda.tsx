/** Tienda en línea del panel (maqueta líneas 687-886).
 *
 * VITRINA INTERNA: la usa el equipo del negocio, no el comprador. La doctrina
 * de la maqueta manda: "Solo tu equipo accede, con los precios y el stock de
 * Artículos/Servicios." */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api/cliente";
import type { Atributo, AtributoValor, Categoria } from "../api/tipos";
import { usePlan } from "../plan/PlanContexto";
import { MuroPlan } from "../plan/Bloqueos";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";
import { dinero } from "../util/formato";
import { importeLinea, totalizar, type LineaCalculable } from "../util/totales";

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
  /** Código de la tabla 17 del SRI: es la clave por la que se agrupa el IVA. */
  codigo_iva: string;
  tipo: string;
  maneja_inventario: boolean;
  stock: string;
  agotado: boolean;
  /** Para filtrar. Un servicio nunca la tiene. */
  categoria_id: string | null;
  /** Los valores que este artículo declara (Marca=Sony, Color=Rojo). Existen
   *  aunque el artículo NO tenga variantes, así que el filtro se lee de aquí. */
  atributos: Array<{ atributo_id: string; atributo_valor_id: string }>;
  variantes: VarianteVitrina[];
}

/** La vitrina manda los atributos como ids; los nombres («Talla», «38») viven
 *  en el catálogo de atributos. `orden` conserva el del catálogo, para que las
 *  tallas salgan 38, 39, 40 y no en el orden en que se crearon las variantes. */
type Indice = Record<string, { nombre: string; orden: number }>;
type Nombres = { atributo: Indice; valor: Indice; categoria: Record<string, string> };

interface LineaPedido {
  /** La variante si la hay, el producto si no: identifica la fila del pedido. */
  clave: string;
  producto_id: string;
  variante_id: string | null;
  nombre: string;
  codigo: string;
  /** Lo que se cobra en ESTA venta. Nace con el de lista y se puede corregir,
   *  igual que al emitir una factura: el dueño decide a cuánto vende hoy. */
  precio: string;
  /** El del catálogo cuando se añadió, para avisar si el de arriba ya no es
   *  ese. No se envía al servidor: él lo vuelve a leer del producto. */
  precio_lista: string;
  /** Del artículo, para calcular el IVA del carrito igual que el servidor. */
  codigo_iva: string;
  porcentaje_iva: number;
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

/** Un artículo pasa el filtro de precio si ALGUNO de sus precios cae dentro:
 *  con variantes la tarjeta enseña un rango, y filtrar por el del producto
 *  escondería la talla que sí vale lo que se busca. */
function enRango(a: ArticuloVitrina, desde: number | null, hasta: number | null) {
  if (desde === null && hasta === null) return true;
  const precios = (a.variantes ?? []).length
    ? (a.variantes ?? []).map((v) => Number(v.precio_sin_iva))
    : [Number(a.precio_sin_iva)];
  return precios.some(
    (x) => Number.isFinite(x) && (desde === null || x >= desde) && (hasta === null || x <= hasta),
  );
}

/** Una fila de chips: «Todas» más un valor por opción presente en la vitrina. */
function FilaChips({
  grupo,
  rotulo,
  opciones,
  activa,
  onElegir,
}: {
  /** Identifica la fila. Sale del id del atributo, no del rótulo: dos
   *  categorías pueden tener un atributo llamado igual. */
  grupo: string;
  rotulo?: string;
  opciones: Array<{ id: string; nombre: string; cuantos: number }>;
  activa: string | null;
  onElegir: (id: string | null) => void;
}) {
  const id = `filtro-${grupo}`;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      {rotulo && (
        <span className="fc-label" id={id} style={{ margin: 0, fontSize: 11 }}>
          {rotulo}
        </span>
      )}
      <div
        role="group"
        aria-labelledby={rotulo ? id : undefined}
        aria-label={rotulo ? undefined : "Filtrar por categoría"}
        style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
      >
        <button
          type="button"
          className="fc-chip"
          style={{ padding: "6px 13px" }}
          aria-pressed={activa === null}
          onClick={() => onElegir(null)}
        >
          Todas
        </button>
        {opciones.map((o) => (
          <button
            key={o.id}
            type="button"
            className="fc-chip"
            style={{ padding: "6px 13px" }}
            aria-pressed={activa === o.id}
            onClick={() => onElegir(activa === o.id ? null : o.id)}
          >
            {o.nombre}
            <span className="fc-chip__contador">{o.cuantos}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function MiTienda() {
  const [articulos, setArticulos] = useState<ArticuloVitrina[] | null>(null);
  const [nombres, setNombres] = useState<Nombres>({ atributo: {}, valor: {}, categoria: {} });
  const [error, setError] = useState<string | null>(null);
  const [lineas, setLineas] = useState<LineaPedido[]>([]);
  // Vive aquí y no en el carrito: al crearse el pedido el modal se cierra, y
  // con él se iría el aviso de que la venta quedó registrada.
  const [creado, setCreado] = useState<string | null>(null);
  // Abierto es independiente de que haya líneas: «Borrar todo» deja el carrito
  // vacío sin cerrar el modal de golpe en la cara de quien lo pulsó.
  const [abierto, setAbierto] = useState(false);

  // Filtros de la vitrina
  const [categoria, setCategoria] = useState<string | null>(null);
  const [porAtributo, setPorAtributo] = useState<Record<string, string | null>>({});
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");

  // Se piden aquí y no en el carrito: dentro del modal se volverían a pedir en
  // cada apertura, y sin método elegido no se puede crear el pedido.
  const [metodos, setMetodos] = useState<Array<{ id: string; label: string; activo: boolean }>>([]);
  const [metodo, setMetodo] = useState("");
  // Aquí y no en el modal: el modal se desmonta al cerrarlo, y cerrarlo para
  // seguir añadiendo artículos es el camino normal. Dentro, el nombre tecleado
  // se perdía en cada vuelta a la vitrina.
  const [comprador, setComprador] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const arts = await api.get<ArticuloVitrina[]>("/tienda/vitrina");
        // Los nombres son los rótulos de los filtros y del selector de
        // variantes. Si fallan, la vitrina sigue en pie con etiquetas pobres.
        const [cats, atrs, vals] = await Promise.all([
          api.get<Categoria[]>("/categorias").catch(() => [] as Categoria[]),
          api.get<Atributo[]>("/atributos").catch(() => [] as Atributo[]),
          api.get<AtributoValor[]>("/atributo-valores").catch(() => [] as AtributoValor[]),
        ]);
        setNombres({
          categoria: Object.fromEntries(cats.map((c) => [c.id, c.nombre])),
          atributo: Object.fromEntries(atrs.map((x, i) => [x.id, { nombre: x.nombre, orden: i }])),
          valor: Object.fromEntries(vals.map((x, i) => [x.id, { nombre: x.valor, orden: i }])),
        });
        setArticulos(arts);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
    })();
  }, []);

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

  // El aviso de venta hecha se va solo, como el resto de los del panel: es una
  // confirmación, no un estado. Quedarse fijo encima de la vitrina hasta la
  // siguiente venta era ruido, y además mentía al rato.
  useEffect(() => {
    if (creado === null) return;
    const t = window.setTimeout(() => setCreado(null), 4000);
    return () => window.clearTimeout(t);
  }, [creado]);

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
    // Se abre al añadir: la venta se cierra en el mostrador y así se ve de una
    // lo que lleva el cliente sin buscar el carrito.
    setAbierto(true);
  }

  const todos = useMemo(() => articulos ?? [], [articulos]);

  /** Los tres filtros por separado, para poder contar cada fila de chips
   *  aplicando TODOS los demás menos el suyo. Un chip que dice «12» y al
   *  pulsarlo deja la vitrina vacía es peor que no poner número. */
  const filtra = useMemo(() => {
    // Una casilla a medio teclear («1.») no debe vaciar la vitrina: hasta que
    // el número sea válido, ese extremo del rango no filtra.
    const tope = (v: string) => {
      const n = Number(v);
      return v.trim() === "" || !Number.isFinite(n) ? null : n;
    };
    const min = tope(desde);
    const max = tope(hasta);
    return {
      categoria: (a: ArticuloVitrina) => categoria === null || a.categoria_id === categoria,
      precio: (a: ArticuloVitrina) => enRango(a, min, max),
      /** `salvo` excluye una fila del cómputo: es la que se está contando. */
      atributos: (a: ArticuloVitrina, salvo?: string) =>
        Object.entries(porAtributo).every(
          ([atrId, valId]) =>
            atrId === salvo ||
            valId === null ||
            (a.atributos ?? []).some(
              (x) => x.atributo_id === atrId && x.atributo_valor_id === valId,
            ),
        ),
    };
  }, [categoria, porAtributo, desde, hasta]);

  // Las categorías salen de lo que hay en la vitrina, no del catálogo entero:
  // un chip que no filtra nada solo estorba.
  const categorias = useMemo(() => {
    const cuenta = new Map<string, number>();
    for (const a of todos) {
      if (!a.categoria_id) continue;
      // La LISTA de chips sale de toda la vitrina, para que no aparezcan y
      // desaparezcan al teclear; el NÚMERO sí respeta los demás filtros, y un
      // cero avisa de que ahí no queda nada sin tener que pulsarlo.
      if (!cuenta.has(a.categoria_id)) cuenta.set(a.categoria_id, 0);
      if (filtra.atributos(a) && filtra.precio(a)) {
        cuenta.set(a.categoria_id, (cuenta.get(a.categoria_id) ?? 0) + 1);
      }
    }
    return [...cuenta]
      .map(([id, cuantos]) => ({ id, nombre: nombres.categoria[id] ?? "Categoría", cuantos }))
      .sort((x, y) => x.nombre.localeCompare(y.nombre, "es"));
  }, [todos, nombres, filtra]);

  // Una fila por atributo de la categoría elegida. SOLO con categoría elegida:
  // los atributos son POR CATEGORÍA, así que sin una no hay un juego de filas
  // que signifique algo, solo el de todas las categorías amontonadas.
  const filasAtributo = useMemo(() => {
    if (categoria === null) return [];
    const enJuego = todos.filter((a) => filtra.categoria(a) && filtra.precio(a));
    const porId = new Map<string, Map<string, number>>();
    for (const a of enJuego) {
      for (const x of a.atributos ?? []) {
        const vals = porId.get(x.atributo_id) ?? new Map<string, number>();
        // El recuento de ESTA fila ignora lo ya elegido en ella misma, pero
        // respeta lo elegido en las otras.
        if (filtra.atributos(a, x.atributo_id)) {
          vals.set(x.atributo_valor_id, (vals.get(x.atributo_valor_id) ?? 0) + 1);
        } else if (!vals.has(x.atributo_valor_id)) {
          vals.set(x.atributo_valor_id, 0);
        }
        porId.set(x.atributo_id, vals);
      }
    }
    return [...porId]
      .map(([id, vals]) => ({
        id,
        nombre: (nombres.atributo[id]?.nombre ?? "Opción").toUpperCase(),
        opciones: [...vals]
          .map(([vid, cuantos]) => ({
            id: vid,
            nombre: nombres.valor[vid]?.nombre ?? vid.slice(0, 8),
            cuantos,
          }))
          .sort((x, y) => x.nombre.localeCompare(y.nombre, "es", { numeric: true })),
      }))
      .filter((f) => f.opciones.length > 1)
      .sort((x, y) => (nombres.atributo[x.id]?.orden ?? 0) - (nombres.atributo[y.id]?.orden ?? 0));
  }, [todos, nombres, filtra, categoria]);

  const visibles = useMemo(
    () => todos.filter((a) => filtra.categoria(a) && filtra.atributos(a) && filtra.precio(a)),
    [todos, filtra],
  );

  const hayFiltro = categoria !== null || desde !== "" || hasta !== "" ||
    Object.values(porAtributo).some((v) => v !== null);

  function limpiarFiltros() {
    setCategoria(null);
    setPorAtributo({});
    setDesde("");
    setHasta("");
  }

  const unidades = lineas.reduce((n, l) => n + l.cantidad, 0);
  // Estable entre renders: el modal la usa como dependencia de su efecto de
  // Escape, y una flecha nueva en cada render lo reengancharía sin parar.
  const cerrarCarrito = useCallback(() => setAbierto(false), []);

  if (error) return <ErrorSeccion mensaje={error} />;
  if (!articulos) return <Cargando />;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <section className="fc-tarjeta">
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 300px" }}>
            <p className="fc-kicker">Tu inventario en vista de tienda</p>
            <p style={{ fontSize: 13.5, color: "var(--texto-suave)", margin: "6px 0 0" }}>
              Selecciona productos y cierra la venta aquí mismo. La vitrina es tu herramienta de
              venta: tus clientes no necesitan entrar aquí.
            </p>
          </div>
          {lineas.length > 0 && (
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              onClick={() => setAbierto(true)}
            >
              Ver carrito
              <span className="fc-chip__contador">{unidades}</span>
            </button>
          )}
        </div>
      </section>

      {/* Flotante y efímero, con la clase del panel: `.fc-toast` se ancla abajo
          al centro y trae su propia animación de entrada. Se puede descartar
          antes de tiempo tocándolo. El texto va corto a propósito: la clase
          recorta con puntos suspensivos y no debe llegar a hacerlo en un móvil. */}
      {creado && (
        <button
          type="button"
          className="fc-toast"
          aria-live="polite"
          title="Descartar"
          onClick={() => setCreado(null)}
        >
          Pedido {creado} creado. Está en Pedidos.
        </button>
      )}

      {/* La barra NO depende de que algún filtro tenga opciones. Si dependiera,
          al teclear el dígito que deja el rango sin resultados se desmontaría
          entera: el campo perdería el foco a media cifra y desaparecería el
          único botón que quita los filtros, dejando la vitrina vacía sin salida.
          Cada fila se gatea por su cuenta; el rango de precio siempre aplica. */}
      {articulos.length > 0 && (
        <section className="fc-tarjeta" style={{ display: "grid", gap: 10 }}>
          {categorias.length > 0 && (
            <FilaChips
              grupo="categoria"
              opciones={categorias}
              activa={categoria}
              onElegir={(id) => {
                setCategoria(id);
                // Los atributos de la categoría anterior ya no aplican.
                setPorAtributo({});
              }}
            />
          )}
          {/* De lo general a lo detallado: las filas de atributo aparecen al
              elegir una categoría. Todas a la vez —Color, Material, Número,
              Talla de todas las categorías juntas— es un muro que nadie lee, y
              además mezcla filas que ni siquiera aplican al mismo artículo. */}
          {filasAtributo.map((f) => (
            <FilaChips
              key={f.id}
              grupo={f.id}
              rotulo={f.nombre}
              opciones={f.opciones}
              activa={porAtributo[f.id] ?? null}
              onElegir={(id) => setPorAtributo((prev) => ({ ...prev, [f.id]: id }))}
            />
          ))}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span className="fc-label" style={{ margin: 0, fontSize: 11 }}>
              PRECIO SIN IVA
            </span>
            <input
              className="fc-campo"
              type="number"
              min="0"
              step="0.01"
              style={{ width: 110, padding: "6px 10px", fontSize: 13 }}
              placeholder="Desde $"
              aria-label="Precio desde"
              value={desde}
              onChange={(e) => setDesde(e.target.value)}
            />
            <input
              className="fc-campo"
              type="number"
              min="0"
              step="0.01"
              style={{ width: 110, padding: "6px 10px", fontSize: 13 }}
              placeholder="Hasta $"
              aria-label="Precio hasta"
              value={hasta}
              onChange={(e) => setHasta(e.target.value)}
            />
            {hayFiltro && (
              <button
                type="button"
                className="fc-btn fc-btn--texto"
                style={{ fontSize: 12.5 }}
                onClick={limpiarFiltros}
              >
                Quitar filtros
              </button>
            )}
            <span
              style={{ marginLeft: "auto", fontSize: 12, color: "var(--texto-tenue)" }}
              aria-live="polite"
            >
              {visibles.length} de {articulos.length}
            </span>
          </div>
        </section>
      )}

      {articulos.length === 0 ? (
        <section className="fc-tarjeta">
          <Vacio
            titulo="Aún no has puesto productos en la vitrina."
            ayuda="Marca «Mostrar en tienda» en los artículos que quieras vender desde aquí."
          />
        </section>
      ) : visibles.length === 0 ? (
        <section className="fc-tarjeta">
          <Vacio
            titulo="Ningún artículo coincide con el filtro."
            ayuda="Prueba con otra categoría o amplía el rango de precio."
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
          {visibles.map((a) => (
            <TarjetaArticulo key={a.id} a={a} nombres={nombres} onAgregar={agregar} />
          ))}
        </div>
      )}

      {abierto && (
        <CarritoModal
          lineas={lineas}
          setLineas={setLineas}
          metodos={metodos}
          metodo={metodo}
          setMetodo={setMetodo}
          comprador={comprador}
          setComprador={setComprador}
          onCerrar={cerrarCarrito}
          onCreado={(numero) => {
            setCreado(numero);
            setComprador("");
            setAbierto(false);
          }}
        />
      )}
    </div>
  );
}


/** Un eje del selector de combinaciones: «Talla» con sus valores. */
interface Eje {
  id: string;
  nombre: string;
  valores: Array<{ id: string; nombre: string }>;
}

/** La línea del carrito para un artículo, con o sin combinación elegida. */
function lineaDe(a: ArticuloVitrina, elegida: VarianteVitrina | null, detalle: string): LineaPedido {
  // `String(Number(...))` como en la emisión de una factura: el catálogo
  // guarda 4 decimales y sin esto la casilla editable diría «40.0000».
  const precio = String(Number(elegida ? elegida.precio_sin_iva : a.precio_sin_iva));
  return {
    clave: elegida ? elegida.id : a.id,
    producto_id: a.id,
    variante_id: elegida?.id ?? null,
    nombre: elegida ? `${a.nombre} · ${detalle}` : a.nombre,
    codigo: elegida ? elegida.codigo : a.codigo,
    precio,
    precio_lista: precio,
    codigo_iva: a.codigo_iva,
    porcentaje_iva: Number(a.porcentaje_iva),
    cantidad: 1,
    tope: a.maneja_inventario ? Number(elegida ? elegida.stock : a.stock) : null,
  };
}

/** Una tarjeta de la vitrina. Todas miden y se comportan igual: nombre, precio,
 *  estado y un botón al fondo. Los artículos con combinaciones NO traen los
 *  selectores aquí —duplicaban la altura de la tarjeta y estiraban toda la
 *  fila—: los piden en su propio diálogo. */
function TarjetaArticulo({
  a,
  nombres,
  onAgregar,
}: {
  a: ArticuloVitrina;
  nombres: Nombres;
  onAgregar: (l: LineaPedido) => void;
}) {
  const [eligiendo, setEligiendo] = useState(false);
  const cerrar = useCallback(() => setEligiendo(false), []);

  // Los ejes salen de las propias variantes: Talla=[38,39], Color=[Rojo,Negro].
  const ejes: Eje[] = useMemo(() => {
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

  const conVariantes = ejes.length > 0;
  // Con variantes el stock del producto es 0 por diseño: quien manda es el de
  // las combinaciones, o la tarjeta entera saldría agotada siempre.
  const agotado = conVariantes ? (a.variantes ?? []).every((v) => v.agotado) : a.agotado;

  const precios = (a.variantes ?? []).map((v) => Number(v.precio_sin_iva));
  const precio =
    precios.length > 0
      ? Math.max(...precios) > Math.min(...precios)
        ? `${dinero(Math.min(...precios))} – ${dinero(Math.max(...precios))}`
        : dinero(Math.min(...precios))
      : dinero(a.precio_sin_iva);

  function estado(): { clase: string; texto: string } {
    if (agotado) return { clase: "fc-estado--error", texto: "Agotado" };
    if (!a.maneja_inventario) {
      // Artículo sin conteo de unidades: al comprador no le importa que no
      // llevemos inventario, solo que puede pedirlo.
      return a.tipo === "SERVICIO"
        ? { clase: "fc-estado--neutro", texto: "Servicio" }
        : { clase: "fc-estado--exito", texto: "Disponible" };
    }
    const unidades = conVariantes
      ? (a.variantes ?? []).reduce((n, v) => n + Number(v.stock), 0)
      : Number(a.stock);
    return { clase: "fc-estado--exito", texto: `${unidades} disponibles` };
  }
  const tono = estado();

  return (
    <article
      className="fc-tarjeta"
      style={{
        padding: "16px 18px 18px",
        opacity: agotado ? 0.55 : 1,
        // En columna y con el bloque de abajo empujado: así los chips y los
        // botones de toda la fila quedan a la misma altura aunque un nombre
        // ocupe dos líneas.
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ fontSize: 14.5, fontWeight: 600, marginBottom: 4 }}>{a.nombre}</div>
      <div className="fc-mono" style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
        {a.codigo}
      </div>
      <div className="fc-cifra" style={{ fontSize: 20, margin: "10px 0 2px" }}>
        {precio}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
        sin impuesto · IVA {Number(a.porcentaje_iva)}%
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginTop: "auto",
          paddingTop: 10,
          marginBottom: 10,
        }}
      >
        <Estado clase={tono.clase} texto={tono.texto} />
      </div>
      <button
        type="button"
        className="fc-btn fc-btn--primario"
        style={{ width: "100%", justifyContent: "center" }}
        disabled={agotado}
        onClick={() => (conVariantes ? setEligiendo(true) : onAgregar(lineaDe(a, null, "")))}
      >
        {conVariantes ? "Elegir opciones" : "Agregar al carrito"}
      </button>

      {eligiendo && (
        <ModalVariante
          a={a}
          ejes={ejes}
          onCerrar={cerrar}
          onAgregar={(l) => {
            setEligiendo(false);
            onAgregar(l);
          }}
        />
      )}
    </article>
  );
}

/** Elegir la combinación que se vende. Aquí caben el código, el stock y el
 *  precio de la combinación exacta, que en la tarjeta no cabían. */
function ModalVariante({
  a,
  ejes,
  onAgregar,
  onCerrar,
}: {
  a: ArticuloVitrina;
  ejes: Eje[];
  onAgregar: (l: LineaPedido) => void;
  onCerrar: () => void;
}) {
  const [sel, setSel] = useState<Record<string, string>>({});
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panel.current?.focus();
  }, []);

  useEffect(() => {
    const alPulsar = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCerrar();
    };
    document.addEventListener("keydown", alPulsar);
    return () => document.removeEventListener("keydown", alPulsar);
  }, [onCerrar]);

  const completa = ejes.every((e) => sel[e.id]);
  const elegida = completa
    ? ((a.variantes ?? []).find((v) => ejes.every((e) => tiene(v, e.id, sel[e.id]))) ?? null)
    : null;

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

  const detalle = ejes
    .map((e) => e.valores.find((v) => v.id === sel[e.id])?.nombre)
    .filter(Boolean)
    .join(" / ");
  const puede = Boolean(elegida && !elegida.agotado);
  const falta = ejes.map((e) => e.nombre.toLowerCase()).join(" y ");

  return createPortal(
    <div
      className="fc-modal"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCerrar();
      }}
    >
      <div
        ref={panel}
        className="fc-modal__panel fc-modal__panel--fijo"
        style={{ maxWidth: 430 }}
        role="dialog"
        aria-modal="true"
        aria-label={`Elegir opciones de ${a.nombre}`}
        tabIndex={-1}
      >
        <div className="fc-modal__cabecera">
          <div style={{ flex: 1, minWidth: 0 }}>
            <p className="fc-kicker">Elige la combinación</p>
            <h2 style={{ fontSize: 16.5, fontWeight: 600, margin: "2px 0 0" }}>{a.nombre}</h2>
          </div>
          <button
            type="button"
            className="fc-btn-icono"
            aria-label="Cerrar"
            onClick={onCerrar}
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M5 5l14 14M19 5L5 19" />
            </svg>
          </button>
        </div>

        <div
          className="fc-modal__cuerpo fc-scroll"
          style={{ paddingTop: 14, paddingBottom: 18, display: "grid", gap: 12 }}
        >
          {ejes.map((e) => (
            <label key={e.id} style={{ display: "block" }}>
              <span className="fc-label">{e.nombre}</span>
              <select
                className="fc-campo"
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

          {/* El resumen de la combinación: lo que la tarjeta no podía enseñar. */}
          <div
            style={{
              borderTop: "1px solid var(--borde)",
              paddingTop: 12,
              display: "grid",
              gap: 4,
              fontSize: 13,
            }}
            aria-live="polite"
          >
            {elegida ? (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                  <span style={{ color: "var(--texto-suave)" }}>Código</span>
                  <span className="fc-mono">{elegida.codigo}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                  <span style={{ color: "var(--texto-suave)" }}>Precio sin IVA</span>
                  <span style={{ fontWeight: 600 }}>{dinero(elegida.precio_sin_iva)}</span>
                </div>
                {a.maneja_inventario && (
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <span style={{ color: "var(--texto-suave)" }}>Quedan</span>
                    <span>{Number(elegida.stock)}</span>
                  </div>
                )}
              </>
            ) : (
              <p style={{ margin: 0, color: "var(--texto-suave)" }}>
                {completa
                  ? "Esa combinación no existe. Prueba con otra."
                  : `Elige ${falta} para ver el precio y el stock.`}
              </p>
            )}
          </div>
        </div>

        <div className="fc-modal__pie" style={{ borderTop: "1px solid var(--borde)" }}>
          <button type="button" className="fc-btn fc-btn--contorno" onClick={onCerrar}>
            Cancelar
          </button>
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            disabled={!puede}
            onClick={() => elegida && onAgregar(lineaDe(a, elegida, detalle))}
          >
            Agregar al carrito
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}


/** El carrito, en modal. Se abre al agregar un artículo: la venta se cierra en
 *  el mostrador y así se ve de una lo que lleva el cliente.
 *
 *  Cada línea manda `variante_id` cuando la venta es de una combinación: de ahí
 *  saca el servidor el código del comprobante y el stock que descuenta. El
 *  PRECIO sí se manda desde aquí y es editable, igual que al emitir una
 *  factura: quien vende es el dueño y decide a cuánto vende hoy. */
function CarritoModal({
  lineas,
  setLineas,
  metodos,
  metodo,
  setMetodo,
  comprador,
  setComprador,
  onCerrar,
  onCreado,
}: {
  lineas: LineaPedido[];
  setLineas: React.Dispatch<React.SetStateAction<LineaPedido[]>>;
  metodos: Array<{ id: string; label: string; activo: boolean }>;
  metodo: string;
  setMetodo: (v: string) => void;
  comprador: string;
  setComprador: (v: string) => void;
  onCerrar: () => void;
  onCreado: (numero: string) => void;
}) {
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panel = useRef<HTMLDivElement>(null);

  // El foco va UNA vez, al abrir. Si dependiera de `onCerrar` se reejecutaría
  // en cada render del padre —las líneas viven en MiTienda— y cada tecla del
  // precio arrancaría el foco del campo: se podría escribir un solo carácter.
  useEffect(() => {
    panel.current?.focus();
  }, []);

  useEffect(() => {
    const alPulsar = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCerrar();
    };
    document.addEventListener("keydown", alPulsar);
    return () => document.removeEventListener("keydown", alPulsar);
  }, [onCerrar]);

  /** Los totales con la MISMA aritmética que el servidor (`calcular_items`):
   *  agrupa el IVA por tarifa en centavos y sin coma flotante. */
  const calculables: LineaCalculable[] = lineas.map((l) => ({
    cantidad: String(l.cantidad),
    precio: l.precio,
    descuento: "",
    codigoIva: l.codigo_iva,
    porcentaje: l.porcentaje_iva,
  }));
  const totales = totalizar(calculables);

  // Un precio vacío o en cero es casi siempre un descuido, no una donación: el
  // mismo freno que pone la emisión de una factura.
  const preciosOk = lineas.every((l) => Number(l.precio) > 0);

  function cambiar(clave: string, cambio: Partial<LineaPedido>) {
    setLineas((prev) => prev.map((x) => (x.clave === clave ? { ...x, ...cambio } : x)));
  }

  function sumar(l: LineaPedido, paso: number) {
    const n = l.cantidad + paso;
    if (n < 1) return;
    cambiar(l.clave, { cantidad: l.tope !== null ? Math.min(n, l.tope) : n });
  }

  async function crear() {
    setEnviando(true);
    setError(null);
    try {
      const pedido = await api.post<{ numero: string }>("/tienda/pedidos", {
        items: lineas.map((l) => ({
          producto_id: l.producto_id,
          variante_id: l.variante_id,
          cantidad: String(l.cantidad),
          // El precio de esta venta. El servidor lo toma tal cual y guarda
          // aparte el de lista; el catálogo no se toca.
          precio_unitario: String(Number(l.precio)),
        })),
        metodo_pago: metodo,
        comprador_nombre: comprador.trim() || null,
      });
      setLineas([]);
      onCreado(pedido.numero);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos crear el pedido");
    } finally {
      setEnviando(false);
    }
  }

  return createPortal(
    <div
      className="fc-modal"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCerrar();
      }}
    >
      <div
        ref={panel}
        className="fc-modal__panel fc-modal__panel--fijo"
        style={{ maxWidth: 620 }}
        role="dialog"
        aria-modal="true"
        aria-label="Tu carrito"
        tabIndex={-1}
      >
        {/* `.fc-modal__cabecera` ya es flex con space-between: un envoltorio
            extra dejaría la ✕ pegada al título en vez de al borde. */}
        <div className="fc-modal__cabecera">
          <h2 style={{ fontSize: 17, fontWeight: 600, margin: 0, flex: 1, minWidth: 0 }}>
            Tu carrito
          </h2>
          <button
            type="button"
            className="fc-btn-icono"
            aria-label="Cerrar el carrito"
            onClick={onCerrar}
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M5 5l14 14M19 5L5 19" />
            </svg>
          </button>
        </div>

        {/* `.fc-modal__cuerpo` solo trae relleno lateral: sin el de abajo, lo
            último —«Borrar todo», o el aviso de error— queda pegado a la línea
            del pie. */}
        <div className="fc-modal__cuerpo fc-scroll" style={{ paddingTop: 14, paddingBottom: 18 }}>
          {lineas.length === 0 ? (
            <p style={{ fontSize: 13.5, color: "var(--texto-suave)", margin: "8px 0 16px" }}>
              El carrito está vacío. Vuelve a la vitrina y agrega lo que vas a vender.
            </p>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {lineas.map((l, i) => (
                <div
                  key={l.clave}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 12,
                    flexWrap: "wrap",
                    paddingBottom: 12,
                    borderBottom: "1px solid var(--borde)",
                  }}
                >
                  <div style={{ flex: "1 1 190px", minWidth: 0 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 600 }}>{l.nombre}</div>
                    <div className="fc-mono" style={{ fontSize: 11, color: "var(--texto-tenue)" }}>
                      {l.codigo}
                    </div>
                  </div>

                  <label style={{ display: "block" }}>
                    <span className="fc-label" style={{ fontSize: 10.5, marginBottom: 3 }}>
                      Precio unit.
                    </span>
                    <input
                      className="fc-campo"
                      type="number"
                      min="0"
                      step="0.01"
                      style={{ width: 94, padding: "6px 8px", fontSize: 13 }}
                      value={l.precio}
                      aria-label={`Precio de ${l.nombre}`}
                      placeholder="0.00"
                      onChange={(e) => cambiar(l.clave, { precio: e.target.value })}
                    />
                    {Number(l.precio) !== Number(l.precio_lista) && (
                      <div style={{ fontSize: 10.5, color: "var(--texto-tenue)", marginTop: 3 }}>
                        lista {dinero(l.precio_lista)}
                      </div>
                    )}
                  </label>

                  <div>
                    <span className="fc-label" style={{ fontSize: 10.5, marginBottom: 3 }}>
                      Cantidad
                    </span>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <button
                        type="button"
                        className="fc-btn-icono"
                        aria-label={`Quitar una unidad de ${l.nombre}`}
                        disabled={l.cantidad <= 1}
                        onClick={() => sumar(l, -1)}
                      >
                        −
                      </button>
                      <span
                        style={{
                          minWidth: 26,
                          textAlign: "center",
                          fontSize: 13.5,
                          fontVariantNumeric: "tabular-nums",
                        }}
                        aria-live="polite"
                      >
                        {l.cantidad}
                      </span>
                      <button
                        type="button"
                        className="fc-btn-icono"
                        aria-label={`Añadir una unidad de ${l.nombre}`}
                        disabled={l.tope !== null && l.cantidad >= l.tope}
                        onClick={() => sumar(l, 1)}
                      >
                        +
                      </button>
                    </div>
                  </div>

                  <div style={{ textAlign: "right", minWidth: 86 }}>
                    <span className="fc-label" style={{ fontSize: 10.5, marginBottom: 3 }}>
                      Importe
                    </span>
                    <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                      {dinero(importeLinea(calculables[i]) / 100)}
                    </div>
                  </div>

                  <button
                    type="button"
                    className="fc-btn-icono"
                    aria-label={`Quitar ${l.nombre} del carrito`}
                    style={{ marginTop: 16 }}
                    onClick={() => setLineas((prev) => prev.filter((x) => x.clave !== l.clave))}
                  >
                    <svg
                      width="12"
                      height="12"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.4"
                      strokeLinecap="round"
                      aria-hidden="true"
                    >
                      <path d="M5 5l14 14M19 5L5 19" />
                    </svg>
                  </button>
                </div>
              ))}

              <div style={{ display: "grid", gap: 4, fontSize: 13 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--texto-suave)" }}>Subtotal sin IVA</span>
                  <span>{dinero(totales.subtotal / 100)}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--texto-suave)" }}>IVA</span>
                  <span>{dinero(totales.iva / 100)}</span>
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontWeight: 600,
                    fontSize: 15,
                    marginTop: 2,
                  }}
                >
                  <span>Total</span>
                  <span className="fc-cifra">{dinero(totales.total / 100)}</span>
                </div>
              </div>

              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
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
                  <select
                    className="fc-campo"
                    value={metodo}
                    onChange={(e) => setMetodo(e.target.value)}
                  >
                    {metodos.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <button
                type="button"
                className="fc-btn fc-btn--texto"
                style={{
                  fontSize: 12.5,
                  color: "var(--error-texto)",
                  justifySelf: "center",
                  marginTop: 2,
                }}
                onClick={() => setLineas([])}
              >
                Borrar todo
              </button>
            </div>
          )}

          {error && (
            <p className="fc-error" role="alert" style={{ marginTop: 12 }}>
              {error}
            </p>
          )}
        </div>

        <div className="fc-modal__pie" style={{ borderTop: "1px solid var(--borde)" }}>
          <button
            type="button"
            className="fc-btn fc-btn--contorno"
            onClick={onCerrar}
            disabled={enviando}
          >
            Volver a la tienda
          </button>
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            disabled={enviando || lineas.length === 0 || !metodo || !preciosOk}
            title={preciosOk ? undefined : "Hay una línea sin precio"}
            onClick={() => void crear()}
          >
            {enviando ? "Creando…" : "Crear pedido"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
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
