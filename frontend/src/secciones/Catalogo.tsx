/** Artículos/Servicios (maqueta líneas 605-686).
 *
 * El plan sin la bandera `stock` NO oculta el catálogo: añade una franja al pie
 * y degrada la columna Stock a un chip gris "Sin conteo". */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/cliente";
import type { Producto } from "../api/tipos";
import { usePlan } from "../plan/PlanContexto";
import { ChipSinConteo, FranjaPlan } from "../plan/Bloqueos";
import { dinero } from "../util/formato";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";

export type FiltroTipo = "todos" | "articulo" | "servicio";

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

        <div style={{ display: "flex", gap: 8, marginTop: 18, flexWrap: "wrap" }}>
          {(
            [
              { id: "todos", label: "Todos" },
              { id: "articulo", label: "Artículos" },
              { id: "servicio", label: "Servicios" },
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

      {error && <ErrorSeccion mensaje={error} />}
      {!error && !productos && <Cargando />}
      {productos && (
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
                      <th scope="col">Código</th>
                      <th scope="col" className="fc-num">Precio</th>
                      <th scope="col">IVA</th>
                      <th scope="col">Stock</th>
                      <th scope="col">Tienda</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibles.map((p) => (
                      <tr
                        key={p.id}
                        onClick={() => setEditando(p)}
                        style={{ cursor: "pointer" }}
                      >
                        <td>
                          <div style={{ fontWeight: 600 }}>{p.nombre}</div>
                          <div style={{ fontSize: 12, color: "var(--texto-tenue)" }}>
                            {p.tipo === "SERVICIO" ? "Servicio" : "Artículo"}
                          </div>
                        </td>
                        <td className="fc-mono">{p.codigo}</td>
                        <td className="fc-num">{dinero(p.precio_sin_iva)}</td>
                        <td>{Number(p.porcentaje_iva)}%</td>
                        <td>
                          <CeldaStock producto={p} sinConteo={sinStock} />
                        </td>
                        <td>
                          {p.mostrar_en_tienda ? (
                            <span className="fc-estado fc-estado--exito">
                              <span className="fc-estado__punto" />
                              En tienda
                            </span>
                          ) : (
                            <span className="fc-estado fc-estado--neutro">
                              <span className="fc-estado__punto" />
                              Solo catálogo
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
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
          sinStock={sinStock}
          onCerrar={() => setEditando(null)}
          onGuardado={() => {
            setEditando(null);
            void cargar();
          }}
        />
      )}
    </div>
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

function FormularioProducto({
  producto,
  sinStock,
  onCerrar,
  onGuardado,
}: {
  producto: Producto | null;
  sinStock: boolean;
  onCerrar: () => void;
  onGuardado: () => void;
}) {
  const [nombre, setNombre] = useState(producto?.nombre ?? "");
  const [codigo, setCodigo] = useState(producto?.codigo ?? "");
  const [tipoProducto, setTipoProducto] = useState<"BIEN" | "SERVICIO">(producto?.tipo ?? "BIEN");
  const [precio, setPrecio] = useState(producto?.precio_sin_iva ?? "");
  const [codigoIva, setCodigoIva] = useState(producto?.codigo_iva ?? "4");
  const [manejaInventario, setManejaInventario] = useState(producto?.maneja_inventario ?? false);
  const [stock, setStock] = useState(producto?.stock ?? "0");
  const [mostrarEnTienda, setMostrarEnTienda] = useState(producto?.mostrar_en_tienda ?? false);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const esServicio = tipoProducto === "SERVICIO";

  async function guardar() {
    setGuardando(true);
    setError(null);
    const cuerpo = {
      codigo: codigo.trim(),
      nombre: nombre.trim(),
      tipo: tipoProducto,
      precio_sin_iva: precio,
      codigo_iva: codigoIva,
      maneja_inventario: esServicio ? false : manejaInventario,
      stock: esServicio || !manejaInventario ? "0" : stock,
      mostrar_en_tienda: mostrarEnTienda,
    };
    try {
      if (producto) {
        await api.put(`/productos/${producto.id}`, cuerpo);
      } else {
        await api.post("/productos", cuerpo);
      }
      onGuardado();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos guardar el producto");
    } finally {
      setGuardando(false);
    }
  }

  const valido = nombre.trim().length >= 1 && codigo.trim().length >= 1 && Number(precio) >= 0;

  return (
    <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Producto">
      <div className="fc-modal__panel" style={{ maxWidth: 520 }}>
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
                onClick={() => setTipoProducto(t)}
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
              {manejaInventario && (
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
              )}
            </div>
          )}

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
  if (producto.tipo === "SERVICIO" || !producto.maneja_inventario) {
    return (
      <span className="fc-estado fc-estado--neutro">
        <span className="fc-estado__punto" />
        Servicio
      </span>
    );
  }
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
  return <span style={{ fontVariantNumeric: "tabular-nums" }}>{stock}</span>;
}
