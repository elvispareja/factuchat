/** Artículos/Servicios (maqueta líneas 605-686).
 *
 * El plan sin la bandera `stock` NO oculta el catálogo: añade una franja al pie
 * y degrada la columna Stock a un chip gris "Sin conteo". */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/cliente";
import type { Atributo, AtributoValor, Categoria, Producto } from "../api/tipos";
import { usePlan } from "../plan/PlanContexto";
import { ChipSinConteo, FranjaPlan } from "../plan/Bloqueos";
import { dinero } from "../util/formato";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";
import { Categorias } from "./Categorias";

export type FiltroTipo = "todos" | "articulo" | "servicio" | "categorias";

/** Los nombres que el listado necesita y no vienen en /productos (que solo
 *  trae ids). `orden` es la posición del atributo dentro de su categoría, para
 *  que «Nike / Rojo» salga siempre igual y no en el orden en que la base
 *  devuelva las filas. */
type Indice = {
  categoria: Record<string, string>;
  orden: Record<string, number>;
  valor: Record<string, string>;
};
const INDICE_VACIO: Indice = { categoria: {}, orden: {}, valor: {} };

const etiquetaAtributos = (p: Producto, indice: Indice) =>
  [...p.atributos]
    .sort((a, b) => (indice.orden[a.atributo_id] ?? 0) - (indice.orden[b.atributo_id] ?? 0))
    .map((a) => indice.valor[a.atributo_valor_id])
    .filter(Boolean)
    .join(" / ");

interface Props {
  onVerPlanes: () => void;
  filtroExterno?: FiltroTipo;
  onFiltro?: (f: FiltroTipo) => void;
  onConteos?: (c: Record<string, number>) => void;
}

export function Catalogo({ onVerPlanes, filtroExterno, onFiltro, onConteos }: Props) {
  const { plan, permite, planPara } = usePlan();
  const [productos, setProductos] = useState<Producto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tipo, setTipoInterno] = useState<FiltroTipo>(filtroExterno ?? "todos");
  const [busqueda, setBusqueda] = useState("");
  const [editando, setEditando] = useState<Producto | "nuevo" | null>(null);

  useEffect(() => {
    if (filtroExterno && filtroExterno !== tipo) setTipoInterno(filtroExterno);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroExterno]);

  function setTipo(t: FiltroTipo) {
    setTipoInterno(t);
    onFiltro?.(t);
  }

  const cargar = () =>
    api
      .get<Producto[]>("/productos")
      .then(setProductos)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Los tres catálogos se piden UNA vez y se indexan por id. Cruzarlos por
  // fila serían 40 peticiones para pintar una segunda línea de texto.
  const [indice, setIndice] = useState<Indice>(INDICE_VACIO);
  useEffect(() => {
    Promise.all([
      api.get<Categoria[]>("/categorias"),
      api.get<Atributo[]>("/atributos"),
      api.get<AtributoValor[]>("/atributo-valores"),
    ])
      .then(([cats, attrs, valores]) =>
        setIndice({
          categoria: Object.fromEntries(cats.map((c) => [c.id, c.nombre])),
          orden: Object.fromEntries(attrs.map((a, i) => [a.id, i])),
          valor: Object.fromEntries(valores.map((v) => [v.id, v.valor])),
        }),
      )
      // Es el rótulo de una columna, no el listado: si falla se cae al guion
      // en vez de tumbar la pantalla entera con un error.
      .catch(() => setIndice(INDICE_VACIO));
  }, []);

  useEffect(() => {
    onConteos?.({
      todos: productos?.length ?? 0,
      articulo: (productos ?? []).filter((p) => p.tipo === "BIEN").length,
      servicio: (productos ?? []).filter((p) => p.tipo === "SERVICIO").length,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productos]);

  const visibles = useMemo(() => {
    const t = busqueda.trim().toLowerCase();
    return (productos ?? []).filter((p) => {
      if (tipo === "articulo" && p.tipo !== "BIEN") return false;
      if (tipo === "servicio" && p.tipo !== "SERVICIO") return false;
      if (!t) return true;
      return p.nombre.toLowerCase().includes(t) || p.codigo.toLowerCase().includes(t);
    });
  }, [productos, tipo, busqueda]);

  const tope = plan?.productos.tope ?? 0;
  const total = productos?.length ?? 0;
  const conteo =
    tope > 0
      ? `${total} de ${tope} en catálogo`
      : `${total} ${tipo === "servicio" ? "servicios" : tipo === "articulo" ? "artículos" : "en catálogo"}, sin límite`;

  const sinStock = !permite("stock");

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <section className="fc-tarjeta">
        {tipo !== "categorias" && (
          <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <p className="fc-kicker">Lo que vendes</p>
              <p className="fc-cifra" style={{ fontSize: 24, margin: 0 }}>
                {conteo}
              </p>
            </div>
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              onClick={() => setEditando("nuevo")}
            >
              Nuevo producto
            </button>
          </div>
        )}

        <div style={{ display: "flex", gap: 8, marginTop: tipo === "categorias" ? 0 : 18, flexWrap: "wrap" }}>
          {(
            [
              { id: "todos", label: "Todos" },
              { id: "articulo", label: "Artículos" },
              { id: "servicio", label: "Servicios" },
              { id: "categorias", label: "Categorías" },
            ] as Array<{ id: FiltroTipo; label: string }>
          ).map((f) => (
            <button
              key={f.id}
              type="button"
              className="fc-chip"
              aria-pressed={tipo === f.id}
              onClick={() => setTipo(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </section>

      {tipo === "categorias" && <Categorias />}

      {tipo !== "categorias" && error && <ErrorSeccion mensaje={error} />}
      {tipo !== "categorias" && !error && !productos && <Cargando />}
      {tipo !== "categorias" && productos && (
        <>
          <section className="fc-tarjeta fc-tarjeta--tabla">
            <div style={{ padding: "16px 18px", borderBottom: "1px solid var(--borde)" }}>
              <label>
                <span className="fc-label" style={{ position: "absolute", left: -9999 }}>
                  Buscar producto
                </span>
                <input
                  className="fc-campo"
                  type="search"
                  value={busqueda}
                  onChange={(e) => setBusqueda(e.target.value)}
                  placeholder="Buscar por nombre o código"
                  style={{ maxWidth: 340 }}
                />
              </label>
            </div>
            {visibles.length === 0 ? (
              <Vacio
                titulo={
                  busqueda
                    ? "Sin resultados para esa búsqueda."
                    : "Todavía no tienes nada en el catálogo."
                }
                ayuda={
                  busqueda
                    ? "Prueba con el nombre o el código del producto."
                    : "Agrega lo que vendes con su precio sin impuesto: el IVA se calcula al facturar."
                }
              />
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="fc-tabla">
                  <thead>
                    <tr>
                      <th scope="col">Producto</th>
                      <th scope="col">Categoría</th>
                      <th scope="col" className="fc-num">Precio</th>
                      <th scope="col">IVA</th>
                      <th scope="col">Stock</th>
                      <th scope="col" style={{ textAlign: "right" }}>Editar</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibles.map((p) => {
                      const valores = etiquetaAtributos(p, indice);
                      const categoria = p.categoria_id ? indice.categoria[p.categoria_id] : null;
                      return (
                        <tr key={p.id} onClick={() => setEditando(p)} style={{ cursor: "pointer" }}>
                          <td>
                            <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                              <Miniatura producto={p} />
                              <span>
                                {/* Quien abre el modal con el teclado es este
                                    botón, no la fila: el onClick del <tr> es
                                    comodidad de ratón (igual que en Clientes). */}
                                <button
                                  type="button"
                                  className="fc-btn fc-btn--texto"
                                  style={{
                                    fontWeight: 600,
                                    fontSize: 13.5,
                                    color: "var(--texto)",
                                    textAlign: "left",
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setEditando(p);
                                  }}
                                >
                                  {p.nombre}
                                </button>
                                <span
                                  className="fc-mono"
                                  style={{
                                    display: "block",
                                    fontSize: 11.5,
                                    color: "var(--texto-tenue)",
                                    marginTop: 1,
                                  }}
                                >
                                  {p.codigo}
                                </span>
                              </span>
                            </div>
                          </td>
                          <td>
                            {categoria ? (
                              <>
                                <span style={{ display: "block" }}>{categoria}</span>
                                {valores && (
                                  <span
                                    style={{
                                      display: "block",
                                      fontSize: 11.5,
                                      color: "var(--texto-tenue)",
                                      marginTop: 1,
                                    }}
                                  >
                                    {valores}
                                  </span>
                                )}
                              </>
                            ) : (
                              <span style={{ color: "var(--texto-tenue)" }}>—</span>
                            )}
                          </td>
                          <td className="fc-num">{dinero(p.precio_sin_iva)}</td>
                          <td>
                            <span className="fc-estado fc-estado--exito">
                              {Number(p.porcentaje_iva)}%
                            </span>
                          </td>
                          <td>
                            <CeldaStock producto={p} sinConteo={sinStock} />
                          </td>
                          <td style={{ textAlign: "right" }}>
                            <button
                              type="button"
                              className="fc-btn-icono"
                              aria-label={`Editar ${p.nombre}`}
                              onClick={(e) => {
                                // Sin esto se dispararía también el onClick de la fila
                                e.stopPropagation();
                                setEditando(p);
                              }}
                            >
                              <svg
                                width="14"
                                height="14"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                aria-hidden="true"
                              >
                                <path d="M12 20h9" />
                                <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                              </svg>
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {sinStock && (
            <FranjaPlan
              texto={`El control de stock viene desde el plan ${planPara("stock") ?? "Independiente"}. Tu catálogo funciona igual: solo dejamos de llevarte el conteo de unidades.`}
              onVerPlanes={onVerPlanes}
            />
          )}
        </>
      )}

      {editando && (
        <FormularioProducto
          producto={editando === "nuevo" ? null : editando}
          // También al cerrar, no solo al guardar: si el producto se creó pero
          // su imagen falló, el modal se queda abierto avisando y el usuario
          // puede cancelar — el producto ya existe y tiene que salir en la lista.
          onCerrar={() => {
            setEditando(null);
            void cargar();
          }}
          onGuardado={() => {
            setEditando(null);
            void cargar();
          }}
        />
      )}
    </div>
  );
}

/* --- Imagen del producto ---------------------------------------------------
   El servidor manda `tiene_imagen` (un booleano), nunca la ruta; los bytes se
   piden aparte a GET /productos/{id}/imagen, que exige Authorization. */

const MAX_IMAGEN = 2 * 1024 * 1024;
const TIPOS_IMAGEN = ["image/jpeg", "image/png", "image/webp"];

const cuadroImagen = (lado: number) =>
  ({
    flex: "none",
    display: "block",
    width: lado,
    height: lado,
    borderRadius: 10,
    objectFit: "cover",
    background: "var(--superficie-tenue)",
    border: "1px solid var(--borde)",
  }) as const;

/** Miniatura del producto, o un recuadro gris del mismo tamaño si no tiene
 *  imagen (así la columna no baila).
 *
 *  No vale un `<img src="/api/v1/…">`: el navegador no adjunta el token y la
 *  petición volvería 401. Se traen los bytes con `api.blob` y se pinta el blob.
 *  La URL se libera al desmontar o al cambiar de producto; si no, cada recarga
 *  del listado deja un blob retenido hasta que se recargue la pestaña. */
function Miniatura({ producto, lado = 40 }: { producto: Producto; lado?: number }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    setUrl(null);
    if (!producto.tiene_imagen) return;
    let vigente = true;
    let creada: string | null = null;
    api
      .blob(`/productos/${producto.id}/imagen`)
      .then((bytes) => {
        // Ya desmontado: no se llega a crear la URL, así que no hay qué liberar
        if (!vigente) return;
        creada = URL.createObjectURL(bytes);
        setUrl(creada);
      })
      .catch(() => {
        /* se queda el recuadro gris: la fila no depende de la foto */
      });
    return () => {
      vigente = false;
      if (creada) URL.revokeObjectURL(creada);
    };
  }, [producto.id, producto.tiene_imagen]);

  return url ? (
    <img src={url} alt="" style={cuadroImagen(lado)} />
  ) : (
    <span style={cuadroImagen(lado)} aria-hidden="true" />
  );
}

const TARIFAS_IVA: Array<{ id: string; label: string }> = [
  { id: "4", label: "15% — general" },
  { id: "2", label: "12%" },
  { id: "3", label: "14%" },
  { id: "5", label: "5%" },
  { id: "0", label: "0% — tarifa cero" },
  { id: "6", label: "No objeto de impuesto" },
];

/** Clave estable de una combinación: los valores ordenados, para que 38/Rojo y
 *  Rojo/38 caigan en la misma casilla. Con ella los datos ya tecleados
 *  sobreviven a que se marque o desmarque otro valor y la matriz se recalcule. */
const claveCombinacion = (valorIds: string[]) => [...valorIds].sort().join("|");

/** Trozo de SKU: mayúsculas, sin acentos ni símbolos («Rojo oscuro» → ROJOOSCURO).
 *  NFD separa la tilde de la letra y el filtro de abajo se lleva la tilde suelta
 *  junto con los espacios, así que «Café» sale CAFE y no CAF. */
const trozoSku = (s: string) =>
  s
    .normalize("NFD")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");

/** Código sugerido de una combinación: el del producto más un sufijo por valor
 *  (NIKETN-38-ROJO), recortado a los 25 caracteres que admite el backend. */
function codigoSugerido(codigoProducto: string, valores: string[]): string {
  const raiz = trozoSku(codigoProducto) || "VAR";
  const partes = valores.map(trozoSku).filter(Boolean);
  for (let corte = 12; corte >= 1; corte--) {
    const candidato = [raiz, ...partes.map((p) => p.slice(0, corte))].join("-");
    if (candidato.length <= 25) return candidato;
  }
  return [raiz, ...partes.map((p) => p.slice(0, 1))].join("-").slice(0, 25);
}

/** "2.000000" del servidor se muestra como "2"; null como campo vacío. */
const numeroEditable = (v: string | null) => (v === null || v === "" ? "" : String(Number(v)));

/** Lo tecleado en una fila de la matriz. `codigo` sin tocar = sigue al del
 *  producto; en cuanto se edita, manda el usuario (va impreso en el comprobante). */
/** `id` solo lo llevan las combinaciones que ya existen en el servidor: viaja de
 *  vuelta al guardar para que cambiar el SKU sea un cambio de nombre y no el
 *  borrado de esa variante con todo su stock. */
type DatosFila = { id?: string; codigo?: string; stock: string; precio: string };
const FILA_VACIA: DatosFila = { stock: "", precio: "" };

/** 6 tallas x 4 colores x 3 materiales ya son 72 filas de inputs; sin tope, un
 *  par de clics distraídos cuelgan la pestaña. */
const TOPE_COMBINACIONES = 200;

const celda = { padding: "8px 10px" } as const;

// `sinStock` (la bandera del plan) ya no entra: lo único que la miraba era el
// bloque de stock que ahora está comentado. Al devolverlo a la vista hay que
// volver a pasarla desde `Catalogo`, que la sigue calculando para el listado.
function FormularioProducto({
  producto,
  onCerrar,
  onGuardado,
}: {
  producto: Producto | null;
  onCerrar: () => void;
  onGuardado: () => void;
}) {
  const [nombre, setNombre] = useState(producto?.nombre ?? "");
  const [codigo, setCodigo] = useState(producto?.codigo ?? "");
  const [tipoProducto, setTipoProducto] = useState<"BIEN" | "SERVICIO">(producto?.tipo ?? "BIEN");
  const [precio, setPrecio] = useState(producto?.precio_sin_iva ?? "");
  const [codigoIva, setCodigoIva] = useState(producto?.codigo_iva ?? "4");
  // Sin setter a propósito: los dos campos siguen viajando a `ProductoIn` (el
  // backend los espera y el producto sin variantes necesita su stock), pero ya
  // no se editan desde aquí — su interfaz está comentada más abajo, junto al
  // «Stock inicial». Si se vuelve a mostrar, hay que devolverles el setter.
  const [manejaInventario] = useState(producto?.maneja_inventario ?? false);
  const [stock] = useState(producto?.stock ?? "0");
  const [mostrarEnTienda, setMostrarEnTienda] = useState(producto?.mostrar_en_tienda ?? false);
  // Un producto SERVICIO no tiene categoría ni atributos (solo los BIEN
  // tangibles se organizan así): si el producto editado viniera con datos
  // viejos de antes de esta regla, se ignoran al abrir el formulario.
  const esProductoServicio = producto?.tipo === "SERVICIO";
  const [categoriaId, setCategoriaId] = useState(
    !esProductoServicio ? (producto?.categoria_id ?? "") : "",
  );
  const [categorias, setCategorias] = useState<Categoria[] | null>(null);
  const [atributosCategoria, setAtributosCategoria] = useState<Atributo[] | null>(null);
  const [valoresPorAtributo, setValoresPorAtributo] = useState<Record<string, AtributoValor[]>>({});
  // Qué valores tiene disponibles el producto: varios por atributo (Talla 38, 39
  // y 40). De aquí salen las combinaciones a la venta.
  const [seleccion, setSeleccion] = useState<Record<string, string[]>>(() => {
    if (!producto || esProductoServicio) return {};
    const mapa: Record<string, string[]> = {};
    for (const a of producto.atributos) {
      mapa[a.atributo_id] = [...(mapa[a.atributo_id] ?? []), a.atributo_valor_id];
    }
    return mapa;
  });
  // Lo tecleado por combinación, indexado por clave estable (no por posición):
  // así marcar una talla más recalcula la matriz sin borrar los 20 stocks ya
  // escritos, y desmarcarla por error no los pierde.
  const [datosFila, setDatosFila] = useState<Record<string, DatosFila>>(() => {
    if (!producto || esProductoServicio) return {};
    return Object.fromEntries(
      (producto.variantes ?? []).map((v) => [
        claveCombinacion(v.valores.map((x) => x.atributo_valor_id)),
        {
          id: v.id,
          codigo: v.codigo,
          stock: numeroEditable(v.stock),
          precio: numeroEditable(v.precio_sin_iva),
        },
      ]),
    );
  });
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Imagen: `nueva` es lo elegido en esta sesión del modal y `quitar` marca el
  // borrado de la que ya está. Ninguna de las dos viaja en el JSON del
  // producto; van por su propio endpoint multipart al guardar.
  const [imagenNueva, setImagenNueva] = useState<File | null>(null);
  const [quitarImagen, setQuitarImagen] = useState(false);
  const [vistaPrevia, setVistaPrevia] = useState<string | null>(null);
  const [arrastrando, setArrastrando] = useState(false);

  // La vista previa es un blob del disco del usuario: hay que devolverlo. Sin
  // el revoke, elegir cinco fotos seguidas deja cinco en memoria.
  useEffect(() => {
    if (!imagenNueva) {
      setVistaPrevia(null);
      return;
    }
    const url = URL.createObjectURL(imagenNueva);
    setVistaPrevia(url);
    return () => URL.revokeObjectURL(url);
  }, [imagenNueva]);

  // El servidor vuelve a validar tipo y tamaño (y mira los BYTES, no el
  // content_type: esa es la que manda). Esto es solo para no hacerle esperar
  // una subida de 8 MB que va a acabar en 400.
  function elegirImagen(archivo: File | undefined | null) {
    if (!archivo) return;
    if (!TIPOS_IMAGEN.includes(archivo.type)) {
      setError("La imagen tiene que ser JPG, PNG o WEBP.");
      return;
    }
    if (archivo.size > MAX_IMAGEN) {
      setError("La imagen supera los 2 MB permitidos.");
      return;
    }
    setError(null);
    setQuitarImagen(false);
    setImagenNueva(archivo);
  }

  const esServicio = tipoProducto === "SERVICIO";
  const hayImagenGuardada = Boolean(producto?.tiene_imagen) && !quitarImagen;

  // Una lista vacía por un fallo de red se lee igual que «no tienes ninguna»,
  // y el usuario acaba creyendo que perdió sus categorías. El error se dice.
  useEffect(() => {
    api
      .get<Categoria[]>("/categorias")
      .then(setCategorias)
      .catch((e) => {
        setCategorias([]);
        setError(e instanceof Error ? e.message : "No pudimos cargar las categorías");
      });
  }, []);

  // Al editar un producto que ya tenía categoría y atributos elegidos, este
  // efecto corre con categoriaId ya lleno en el primer render: sin la
  // bandera, limpiaría la selección de inmediato aunque el usuario no tocó
  // nada. En cualquier OTRO cambio de categoriaId (vacía o hacia otra
  // distinta), los atributos elegidos dejan de ser válidos y hay que
  // soltarlos todos — si no, "Guardar" manda una combinación
  // categoría/atributo que el backend rechaza con un 400 que el usuario no
  // puede explicarse, porque no tocó ninguna selección.
  // Id del producto en el servidor: el que llega por props, o el que devolvió
  // el POST. Ver `guardar()`.
  const idGuardado = useRef<string | null>(producto?.id ?? null);

  const primeraVez = useRef(true);
  useEffect(() => {
    const esPrimera = primeraVez.current;
    primeraVez.current = false;
    if (!esPrimera) setSeleccion({});
    if (!categoriaId) {
      setAtributosCategoria([]);
      return;
    }
    api
      .get<Atributo[]>(`/atributos?categoria_id=${categoriaId}`)
      .then((lista) => {
        setAtributosCategoria(lista);
        for (const a of lista) {
          if (a.id in valoresPorAtributo) continue;
          api
            .get<AtributoValor[]>(`/atributo-valores?atributo_id=${a.id}`)
            .then((valores) => setValoresPorAtributo((prev) => ({ ...prev, [a.id]: valores })))
            .catch((e) => {
              // Sin aviso, el atributo se queda sin opciones y el producto se
              // guarda sin ese valor como si el usuario no lo hubiera puesto.
              setValoresPorAtributo((prev) => ({ ...prev, [a.id]: [] }));
              setError(
                e instanceof Error
                  ? e.message
                  : `No pudimos cargar los valores de ${a.nombre}`,
              );
            });
        }
      })
      .catch((e) => {
        setAtributosCategoria([]);
        setError(e instanceof Error ? e.message : "No pudimos cargar los atributos");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categoriaId]);

  function alternarValor(atributoId: string, valorId: string) {
    setSeleccion((prev) => {
      const marcados = prev[atributoId] ?? [];
      return {
        ...prev,
        [atributoId]: marcados.includes(valorId)
          ? marcados.filter((v) => v !== valorId)
          : [...marcados, valorId],
      };
    });
  }

  // Producto cartesiano de los valores marcados: Talla=[38,39] x Color=[Rojo,
  // Negro] son 4 filas. Un atributo con un solo valor marcado no multiplica
  // nada, simplemente es fijo para todo el producto.
  const { filas, exceso } = useMemo(() => {
    const ejes = (atributosCategoria ?? [])
      .map((a) => ({
        id: a.id,
        // Se recorre el catálogo del atributo, no lo marcado, para que las filas
        // salgan en el orden del negocio (38, 39, 40) y no en el de los clics.
        valores: (valoresPorAtributo[a.id] ?? []).filter((v) =>
          (seleccion[a.id] ?? []).includes(v.id),
        ),
      }))
      .filter((eje) => eje.valores.length > 0);
    if (ejes.length === 0) return { filas: [], exceso: 0 };
    const total = ejes.reduce((n, eje) => n * eje.valores.length, 1);
    if (total > TOPE_COMBINACIONES) return { filas: [], exceso: total };

    let combos: Array<Array<{ atributoId: string; valor: AtributoValor }>> = [[]];
    for (const eje of ejes) {
      combos = combos.flatMap((combo) =>
        eje.valores.map((valor) => [...combo, { atributoId: eje.id, valor }]),
      );
    }
    return {
      exceso: 0,
      filas: combos.map((combo) => ({
        clave: claveCombinacion(combo.map((c) => c.valor.id)),
        etiqueta: combo.map((c) => c.valor.valor).join(" / "),
        valores: combo.map((c) => ({
          atributo_id: c.atributoId,
          atributo_valor_id: c.valor.id,
        })),
        sugerido: codigoSugerido(
          codigo,
          combo.map((c) => c.valor.valor),
        ),
      })),
    };
  }, [atributosCategoria, valoresPorAtributo, seleccion, codigo]);

  const hayVariantes = !esServicio && filas.length > 0;
  const codigoDeFila = (f: (typeof filas)[number]) =>
    (datosFila[f.clave]?.codigo ?? f.sugerido).trim();
  const editarFila = (clave: string, cambio: Partial<DatosFila>) =>
    setDatosFila((prev) => ({ ...prev, [clave]: { ...FILA_VACIA, ...prev[clave], ...cambio } }));

  // El backend rechaza esto con un 400, pero avisar aquí evita el viaje y deja
  // claro cuál de las 30 filas es la que estorba.
  const errorFilas = !hayVariantes
    ? null
    : filas.some((f) => !codigoDeFila(f))
      ? "Cada combinación necesita un código."
      : new Set(filas.map(codigoDeFila)).size !== filas.length
        ? "Hay dos combinaciones con el mismo código."
        : null;

  async function guardar() {
    setGuardando(true);
    setError(null);
    const cuerpo = {
      codigo: codigo.trim(),
      nombre: nombre.trim(),
      tipo: tipoProducto,
      precio_sin_iva: precio,
      codigo_iva: codigoIva,
      // Con el campo de stock oculto ya nadie puede marcar esta casilla, así que
      // sin esto TODO producto nuevo nacía sin inventario: es el interruptor que
      // el backend mira para avisar de sobreventa y para descontar al facturar.
      // Las variantes SON el inventario, así que un producto que las tiene lo
      // lleva por definición; y editar uno que ya lo tenía no se lo quita.
      maneja_inventario: esServicio ? false : hayVariantes || manejaInventario,
      // stock_minimo no se edita aquí, pero el PUT reemplaza el registro entero:
      // sin reenviarlo, corregir una tilde del nombre borraba el mínimo y con él
      // el aviso de «bajo» en la tabla.
      stock_minimo: producto?.stock_minimo ?? null,
      // Con variantes el stock vive en cada combinación: dejar aquí un número
      // sería un segundo inventario que nadie descuenta.
      stock: esServicio || !manejaInventario || hayVariantes ? "0" : stock,
      mostrar_en_tienda: mostrarEnTienda,
      categoria_id: esServicio ? null : categoriaId || null,
      atributos: esServicio
        ? []
        : Object.entries(seleccion).flatMap(([atributoId, valores]) =>
            valores.map((atributoValorId) => ({
              atributo_id: atributoId,
              atributo_valor_id: atributoValorId,
            })),
          ),
      variantes: hayVariantes
        ? filas.map((f) => {
            const d = datosFila[f.clave] ?? FILA_VACIA;
            return {
              id: d.id ?? null, // null = combinación nueva, el servidor la crea
              codigo: codigoDeFila(f),
              // null = hereda el precio del producto (la talla 45 puede costar
              // más sin obligar a rellenar 30 precios).
              precio_sin_iva: d.precio.trim() === "" ? null : d.precio,
              stock: d.stock.trim() === "" ? "0" : d.stock,
              valores: f.valores,
            };
          })
        : [],
    };
    try {
      // Un producto nuevo NO tiene id hasta que el servidor lo crea, y la
      // imagen se sube a /productos/{id}/imagen: primero el JSON, y la foto
      // después con el id que devuelve la respuesta. Al editar el id ya existe,
      // pero el camino es el mismo para no tener dos.
      const guardado = idGuardado.current
        ? await api.put<Producto>(`/productos/${idGuardado.current}`, cuerpo)
        : await api.post<Producto>("/productos", cuerpo);
      // A partir de aquí el producto EXISTE. Si la imagen falla y el usuario
      // reintenta, esto hace que el segundo intento edite en vez de crear un
      // duplicado.
      idGuardado.current = guardado.id;

      try {
        if (imagenNueva) {
          await api.subir(`/productos/${guardado.id}/imagen`, imagenNueva);
        } else if (quitarImagen && guardado.tiene_imagen) {
          await api.delete(`/productos/${guardado.id}/imagen`);
        }
      } catch (e) {
        // El producto sí se guardó: decir «no pudimos guardar el producto»
        // sería mentira y el usuario lo crearía otra vez. El modal se queda
        // abierto para reintentar solo la imagen; al cerrar, la lista recarga.
        setError(
          `Guardamos el producto, pero la imagen no se subió: ${
            e instanceof Error ? e.message : "error desconocido"
          }`,
        );
        return;
      }
      onGuardado();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos guardar el producto");
    } finally {
      setGuardando(false);
    }
  }

  // La matriz sale de dos peticiones encadenadas (/atributos y luego los
  // valores de cada uno). Hasta que llegan, `filas` está vacía: guardar en esa
  // ventana mandaría «sin variantes» y el producto perdería su inventario sin
  // que nadie lo pidiera. Por eso, al editar un producto con categoría, el
  // botón espera a que la matriz esté cargada.
  const matrizCargada =
    esServicio ||
    !categoriaId ||
    (atributosCategoria !== null &&
      atributosCategoria.every((a) => valoresPorAtributo[a.id] !== undefined));

  const valido =
    nombre.trim().length >= 1 &&
    codigo.trim().length >= 1 &&
    Number(precio) >= 0 &&
    !errorFilas &&
    exceso === 0 &&
    matrizCargada;

  return (
    <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Producto">
      {/* La matriz no cabe en 520: el panel se ensancha solo cuando hay filas, y
          la tabla lleva su propio scroll horizontal para no mover la página. */}
      <div className="fc-modal__panel" style={{ maxWidth: hayVariantes ? 820 : 520 }}>
        <p className="fc-kicker">{producto ? "Editar producto" : "Nuevo producto"}</p>
        <h2 className="fc-titulo" style={{ fontSize: 20, marginBottom: 18 }}>
          {producto ? producto.nombre : "Agregar al catálogo"}
        </h2>

        <div style={{ display: "grid", gap: 14 }}>
          <div style={{ display: "flex", gap: 8 }}>
            {(["BIEN", "SERVICIO"] as const).map((t) => (
              <button
                key={t}
                type="button"
                className="fc-chip"
                aria-pressed={tipoProducto === t}
                onClick={() => {
                  setTipoProducto(t);
                  // Solo los artículos (BIEN) tienen categoría/atributos: un
                  // servicio no, así que al cambiar a Servicio se suelta
                  // cualquier selección previa para no mandarla al guardar.
                  if (t === "SERVICIO") {
                    setCategoriaId("");
                    setSeleccion({});
                  }
                }}
              >
                {t === "BIEN" ? "Artículo" : "Servicio"}
              </button>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 140px", gap: 12 }}>
            <div>
              <label className="fc-label" htmlFor="prod-nombre">
                Nombre
              </label>
              <input
                id="prod-nombre"
                className="fc-campo"
                value={nombre}
                onChange={(e) => setNombre(e.target.value)}
              />
            </div>
            <div>
              <label className="fc-label" htmlFor="prod-codigo">
                Código
              </label>
              <input
                id="prod-codigo"
                className="fc-campo"
                value={codigo}
                onChange={(e) => setCodigo(e.target.value)}
              />
            </div>
          </div>

          {/* La imagen NO viaja en el JSON del producto: se sube aparte, por
              multipart, a /productos/{id}/imagen. Ver `guardar()`. */}
          <div>
            <span className="fc-label">Imagen</span>
            {vistaPrevia || hayImagenGuardada ? (
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                {vistaPrevia ? (
                  <img src={vistaPrevia} alt="" style={cuadroImagen(64)} />
                ) : (
                  producto && <Miniatura producto={producto} lado={64} />
                )}
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, wordBreak: "break-all" }}>
                    {imagenNueva ? imagenNueva.name : "Imagen actual"}
                  </div>
                  <button
                    type="button"
                    className="fc-btn fc-btn--texto"
                    onClick={() => {
                      setImagenNueva(null);
                      // Solo hay que pedirle el borrado al servidor si había una
                      // guardada; descartar la recién elegida no toca el disco.
                      setQuitarImagen(Boolean(producto?.tiene_imagen));
                    }}
                  >
                    Quitar
                  </button>
                </div>
              </div>
            ) : (
              <label
                className="fc-dropzone"
                data-arrastrando={arrastrando ? "true" : "false"}
                onDragOver={(e) => {
                  // Sin preventDefault el navegador se lleva el archivo a otra
                  // pestaña en vez de dejarlo soltar aquí.
                  e.preventDefault();
                  setArrastrando(true);
                }}
                onDragLeave={() => setArrastrando(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setArrastrando(false);
                  elegirImagen(e.dataTransfer.files?.[0]);
                }}
              >
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="var(--verde-medio)"
                  strokeWidth="1.9"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 16V4M7 9l5-5 5 5M4 20h16" />
                </svg>
                <span style={{ fontSize: 13.5, fontWeight: 600, color: "var(--verde-marca)" }}>
                  Arrastra la foto o haz clic
                </span>
                <span style={{ fontSize: 12, color: "#8A9A91" }}>JPG, PNG o WEBP · hasta 2 MB</span>
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={(e) => elegirImagen(e.target.files?.[0])}
                />
              </label>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="fc-label" htmlFor="prod-precio">
                Precio sin IVA
              </label>
              <input
                id="prod-precio"
                className="fc-campo"
                type="number"
                min="0"
                step="0.01"
                value={precio}
                onChange={(e) => setPrecio(e.target.value)}
              />
            </div>
            <div>
              <label className="fc-label" htmlFor="prod-iva">
                IVA
              </label>
              <select
                id="prod-iva"
                className="fc-campo"
                value={codigoIva}
                onChange={(e) => setCodigoIva(e.target.value)}
              >
                {TARIFAS_IVA.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {!esServicio && (
            <div>
              <label className="fc-label" htmlFor="prod-categoria">
                Categoría
              </label>
              <select
                id="prod-categoria"
                className="fc-campo"
                value={categoriaId}
                onChange={(e) => setCategoriaId(e.target.value)}
              >
                <option value="">Sin categoría</option>
                {(categorias ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nombre}
                  </option>
                ))}
              </select>
            </div>
          )}

          {!esServicio && atributosCategoria && atributosCategoria.length > 0 && (
            <div style={{ display: "grid", gap: 12 }}>
              <p style={{ fontSize: 12, color: "var(--texto-tenue)", margin: 0 }}>
                Marca todos los valores que vendes. Si marcas varias tallas o varios colores,
                abajo sale una fila por combinación, cada una con su código y su stock.
              </p>
              {atributosCategoria.map((a) => (
                <div key={a.id}>
                  <span className="fc-label" id={`prod-attr-${a.id}`}>
                    {a.nombre}
                  </span>
                  <div
                    role="group"
                    aria-labelledby={`prod-attr-${a.id}`}
                    style={{ display: "flex", gap: 6, flexWrap: "wrap" }}
                  >
                    {(valoresPorAtributo[a.id] ?? []).length === 0 && (
                      <span style={{ fontSize: 12, color: "var(--texto-tenue)" }}>
                        Sin valores configurados.
                      </span>
                    )}
                    {(valoresPorAtributo[a.id] ?? []).map((v) => (
                      <button
                        key={v.id}
                        type="button"
                        className="fc-chip"
                        style={{ padding: "6px 13px" }}
                        aria-pressed={(seleccion[a.id] ?? []).includes(v.id)}
                        onClick={() => alternarValor(a.id, v.id)}
                      >
                        {v.valor}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {exceso > 0 && (
            <p className="fc-error" role="alert">
              Con lo marcado salen {exceso} combinaciones y no caben en la pantalla. Desmarca
              algunos valores o parte el producto en varios.
            </p>
          )}

          {hayVariantes && (
            <div>
              <span className="fc-label">Combinaciones a la venta ({filas.length})</span>
              <div
                style={{
                  overflowX: "auto",
                  border: "1px solid var(--borde)",
                  borderRadius: 12,
                }}
              >
                <table className="fc-tabla" style={{ minWidth: 520 }}>
                  <thead>
                    <tr>
                      <th scope="col" style={celda}>
                        Combinación
                      </th>
                      <th scope="col" style={celda}>
                        Código
                      </th>
                      <th scope="col" style={celda}>
                        Stock
                      </th>
                      <th scope="col" style={celda}>
                        Precio
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filas.map((f) => {
                      const d = datosFila[f.clave] ?? FILA_VACIA;
                      return (
                        <tr key={f.clave}>
                          <td style={celda}>{f.etiqueta}</td>
                          <td style={celda}>
                            <input
                              className="fc-campo fc-mono"
                              style={{ padding: "7px 9px", width: 175 }}
                              aria-label={`Código de ${f.etiqueta}`}
                              maxLength={25}
                              value={d.codigo ?? f.sugerido}
                              onChange={(e) => editarFila(f.clave, { codigo: e.target.value })}
                            />
                          </td>
                          <td style={celda}>
                            <input
                              className="fc-campo"
                              style={{ padding: "7px 9px", width: 90 }}
                              type="number"
                              min="0"
                              placeholder="0"
                              aria-label={`Stock de ${f.etiqueta}`}
                              value={d.stock}
                              onChange={(e) => editarFila(f.clave, { stock: e.target.value })}
                            />
                          </td>
                          <td style={celda}>
                            <input
                              className="fc-campo"
                              style={{ padding: "7px 9px", width: 120 }}
                              type="number"
                              min="0"
                              step="0.01"
                              aria-label={`Precio de ${f.etiqueta}`}
                              placeholder={
                                Number(precio) >= 0 && precio !== ""
                                  ? `Hereda ${dinero(precio)}`
                                  : "Hereda el del producto"
                              }
                              value={d.precio}
                              onChange={(e) => editarFila(f.clave, { precio: e.target.value })}
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p style={{ fontSize: 12, color: "var(--texto-tenue)", margin: "8px 0 0" }}>
                El código va impreso en el comprobante: se propone uno y puedes cambiarlo. El
                precio vacío hereda el del producto.
              </p>
              {errorFilas && (
                <p className="fc-error" role="alert">
                  {errorFilas}
                </p>
              )}
            </div>
          )}
          {!esServicio && categoriaId && atributosCategoria && atributosCategoria.length === 0 && (
            <p style={{ fontSize: 12, color: "var(--texto-tenue)", margin: 0 }}>
              Esta categoría no tiene atributos configurados todavía.
            </p>
          )}

          {/* OCULTO A PROPÓSITO — no está perdido, está comentado.
              Desde que existen variantes, el conteo real vive en cada
              combinación (la tabla de arriba, una fila por talla/color). Un
              «Stock inicial» del producto entero sería un SEGUNDO sitio donde
              escribir lo mismo, y uno de los dos acabaría mintiendo.
              Los campos `maneja_inventario` y `stock` SÍ se siguen mandando al
              backend en `guardar()`: `ProductoIn` los espera y el producto sin
              variantes necesita su stock; solo se dejan de editar aquí. Para
              devolverlo a la vista, descomenta esto y vuelve a poner los
              setters en los `useState` de arriba.

          {!esServicio && !sinStock && (
            <div style={{ display: "grid", gap: 10 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13.5 }}>
                <input
                  type="checkbox"
                  checked={manejaInventario}
                  onChange={(e) => setManejaInventario(e.target.checked)}
                />
                Llevar el conteo de stock
              </label>
              {manejaInventario &&
                (hayVariantes ? (
                  <p style={{ fontSize: 12, color: "var(--texto-tenue)", margin: 0 }}>
                    El stock lo lleva cada combinación en la tabla de arriba.
                  </p>
                ) : (
                  <div>
                    <label className="fc-label" htmlFor="prod-stock">
                      Stock inicial
                    </label>
                    <input
                      id="prod-stock"
                      className="fc-campo"
                      type="number"
                      min="0"
                      value={stock}
                      onChange={(e) => setStock(e.target.value)}
                    />
                  </div>
                ))}
            </div>
          )}
          */}

          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              background: "rgba(34,197,94,.07)",
              border: "1px solid rgba(22,121,74,.2)",
              borderRadius: 13,
              padding: "12px 14px",
              fontSize: 13.5,
            }}
          >
            <input
              type="checkbox"
              checked={mostrarEnTienda}
              onChange={(e) => setMostrarEnTienda(e.target.checked)}
            />
            <span>
              <strong style={{ fontWeight: 600 }}>Mostrar en tienda.</strong> Aparece en Tienda en
              línea → Mi tienda, con este precio y este stock.
            </span>
          </label>

          {error && (
            <p className="fc-error" role="alert">
              {error}
            </p>
          )}

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="fc-btn fc-btn--contorno" onClick={onCerrar}>
              Cancelar
            </button>
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              disabled={!valido || guardando}
              onClick={() => void guardar()}
            >
              {guardando ? "Guardando…" : producto ? "Guardar cambios" : "Agregar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CeldaStock({ producto, sinConteo }: { producto: Producto; sinConteo: boolean }) {
  // El plan manda antes que cualquier otra condición de stock
  if (sinConteo) return <ChipSinConteo />;
  // Un servicio y un artículo con el conteo desactivado son cosas distintas
  // aunque los dos se queden sin número: llamar «Servicio» a unas zapatillas
  // solo porque no llevan inventario confunde a quien lee la tabla.
  if (producto.tipo === "SERVICIO") {
    return (
      <span className="fc-estado fc-estado--neutro">
        <span className="fc-estado__punto" />
        Servicio
      </span>
    );
  }
  if (!producto.maneja_inventario) return <ChipSinConteo />;
  const stock = Number(producto.stock);
  const minimo = producto.stock_minimo === null ? null : Number(producto.stock_minimo);
  if (stock <= 0) {
    return (
      <span className="fc-estado fc-estado--error">
        <span className="fc-estado__punto" />
        Agotado
      </span>
    );
  }
  if (minimo !== null && stock <= minimo) {
    return (
      <span className="fc-estado fc-estado--aviso">
        <span className="fc-estado__punto" />
        {stock} bajo
      </span>
    );
  }
  // Mismo chip que el resto de la columna (la maqueta los quiere todos iguales);
  // el número suelto de antes rompía la fila.
  return (
    <span className="fc-estado fc-estado--exito">
      <span className="fc-estado__punto" />
      <span style={{ fontVariantNumeric: "tabular-nums" }}>{stock}</span>
    </span>
  );
}
