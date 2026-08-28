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

type FiltroTipo = "todos" | "articulo" | "servicio";

export function Catalogo({ onVerPlanes }: { onVerPlanes: () => void }) {
  const { plan, permite, planPara } = usePlan();
  const [productos, setProductos] = useState<Producto[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tipo, setTipo] = useState<FiltroTipo>("todos");
  const [busqueda, setBusqueda] = useState("");

  useEffect(() => {
    let vigente = true;
    api
      .get<Producto[]>("/productos")
      .then((d) => vigente && setProductos(d))
      .catch((e) => vigente && setError(e instanceof Error ? e.message : "Error"));
    return () => {
      vigente = false;
    };
  }, []);

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
          <button type="button" className="fc-btn fc-btn--primario">
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
                    </tr>
                  </thead>
                  <tbody>
                    {visibles.map((p) => (
                      <tr key={p.id}>
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
