/** Comprobantes: historial con filtros por tipo y bandeja de retenciones
 *  recibidas (maqueta líneas 366-526). La bandeja depende de la bandera
 *  `archivos` del plan; sin ella se muestra el muro. */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/cliente";
import type { Comprobante as TComprobante } from "../api/tipos";
import { usePlan } from "../plan/PlanContexto";
import { MuroPlan } from "../plan/Bloqueos";
import { Retenciones } from "./Retenciones";
import { ETIQUETA_TIPO, dinero, fechaCorta, tonoEstado } from "../util/formato";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";

export type Filtro = "todos" | "factura" | "credito" | "debito" | "retencion" | "guia";

const FILTROS: Array<{ id: Filtro; label: string; tipos: string[] }> = [
  { id: "todos", label: "Todos", tipos: [] },
  { id: "factura", label: "Facturas", tipos: ["FACTURA"] },
  { id: "credito", label: "Notas de crédito", tipos: ["NOTA_CREDITO"] },
  { id: "debito", label: "Notas de débito", tipos: ["NOTA_DEBITO"] },
  { id: "retencion", label: "Retenciones", tipos: ["RETENCION"] },
  { id: "guia", label: "Guías de remisión", tipos: ["GUIA_REMISION"] },
];

interface Props {
  onVerPlanes: () => void;
  /** Filtro pedido desde la barra lateral (al tocar un ítem del submenú). */
  filtroExterno?: Filtro;
  /** Avisa a la barra lateral qué filtro quedó activo, para resaltarlo ahí. */
  onFiltro?: (f: Filtro) => void;
  /** Avisa a la barra lateral cuántos hay por filtro, para el conteo del
   *  submenú (maqueta: "Todos 9", "Facturas 6", …). */
  onConteos?: (c: Record<string, number>) => void;
}

export function Comprobantes({ onVerPlanes, filtroExterno, onFiltro, onConteos }: Props) {
  const { permite } = usePlan();
  const [filtro, setFiltroInterno] = useState<Filtro>(filtroExterno ?? "todos");
  const [busqueda, setBusqueda] = useState("");

  // La barra lateral es la fuente de verdad cuando manda un filtro nuevo
  useEffect(() => {
    if (filtroExterno && filtroExterno !== filtro) setFiltroInterno(filtroExterno);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroExterno]);

  function setFiltro(f: Filtro) {
    setFiltroInterno(f);
    onFiltro?.(f);
  }
  const [docs, setDocs] = useState<TComprobante[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vigente = true;
    api
      .get<TComprobante[]>("/comprobantes")
      .then((d) => vigente && setDocs(d))
      .catch((e) => vigente && setError(e instanceof Error ? e.message : "Error"));
    return () => {
      vigente = false;
    };
  }, []);

  const visibles = useMemo(() => {
    if (!docs) return [];
    const cfg = FILTROS.find((f) => f.id === filtro)!;
    const texto = busqueda.trim().toLowerCase();
    return docs.filter((d) => {
      if (cfg.tipos.length && !cfg.tipos.includes(d.tipo)) return false;
      if (!texto) return true;
      return (
        (d.numero ?? "").toLowerCase().includes(texto) ||
        (d.clave_acceso ?? "").includes(texto)
      );
    });
  }, [docs, filtro, busqueda]);

  const cuentaPorFiltro = useMemo(() => {
    const cuenta: Record<string, number> = {};
    for (const f of FILTROS) {
      cuenta[f.id] = f.tipos.length
        ? (docs ?? []).filter((d) => f.tipos.includes(d.tipo)).length
        : (docs ?? []).length;
    }
    return cuenta;
  }, [docs]);

  useEffect(() => {
    onConteos?.(cuentaPorFiltro);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cuentaPorFiltro]);

  // La bandeja de retenciones recibidas exige la bandera `archivos` del plan
  if (filtro === "retencion" && !permite("archivos")) {
    return (
      <div style={{ display: "grid", gap: 18 }}>
        <BarraFiltros
          filtro={filtro}
          onFiltro={setFiltro}
          cuentas={cuentaPorFiltro}
          busqueda={busqueda}
          onBusqueda={setBusqueda}
        />
        {/* Texto literal de la maqueta (Dashboard.dc.html, líneas 456-458) */}
        <MuroPlan
          titulo="El resumen de retenciones viene con un plan superior"
          texto="Tus retenciones recibidas siguen sumándose. Al activar el plan que incluye este resumen, verás aquí el crédito acumulado y podrás descargar cada archivo."
          textoBoton="Ver los planes"
          onVerPlanes={onVerPlanes}
        />
      </div>
    );
  }

  // Con el filtro de retenciones, la tabla genérica se APAGA y se sustituye por
  // su panel propio: son documentos recibidos, no emitidos, y no comparten ni
  // columnas ni estados con el resto del historial.
  if (filtro === "retencion") {
    return (
      <div style={{ display: "grid", gap: 18 }}>
        <BarraFiltros
          filtro={filtro}
          onFiltro={setFiltro}
          cuentas={cuentaPorFiltro}
          busqueda={busqueda}
          onBusqueda={setBusqueda}
        />
        <Retenciones />
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <BarraFiltros
        filtro={filtro}
        onFiltro={setFiltro}
        cuentas={cuentaPorFiltro}
        busqueda={busqueda}
        onBusqueda={setBusqueda}
      />

      {error && <ErrorSeccion mensaje={error} />}
      {!error && !docs && <Cargando />}
      {docs && (
        <section className="fc-tarjeta fc-tarjeta--tabla">
          {visibles.length === 0 ? (
            <Vacio
              titulo={
                busqueda
                  ? "Sin resultados para esa búsqueda."
                  : "Todavía no has emitido comprobantes de este tipo."
              }
              ayuda={
                busqueda
                  ? "Prueba con el nombre del cliente o el número del comprobante."
                  : "Cuando emitas el primero aparecerá aquí con su estado del SRI."
              }
            />
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="fc-tabla">
                <thead>
                  <tr>
                    <th scope="col">Número</th>
                    <th scope="col">Tipo</th>
                    <th scope="col">Fecha</th>
                    <th scope="col" className="fc-num">Total</th>
                    <th scope="col">Estado SRI</th>
                    <th scope="col">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {visibles.map((d) => {
                    const tono = tonoEstado(d.estado);
                    return (
                      <tr key={d.id}>
                        <td className="fc-mono">{d.numero ?? "Borrador"}</td>
                        <td>{ETIQUETA_TIPO[d.tipo] ?? d.tipo}</td>
                        <td>{fechaCorta(d.fecha_emision)}</td>
                        <td className="fc-num">{dinero(d.total)}</td>
                        <td>
                          <span className={`fc-estado ${tono.clase}`}>
                            <span className="fc-estado__punto" />
                            {tono.label}
                          </span>
                          {d.mensajes.length > 0 && (
                            <div
                              style={{
                                fontSize: 12,
                                color: "var(--error-texto)",
                                marginTop: 6,
                                maxWidth: "38ch",
                              }}
                            >
                              {d.mensajes[0]}
                            </div>
                          )}
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 6 }}>
                            {d.estado === "AUTORIZADO" && (
                              <>
                                <a
                                  className="fc-btn-icono"
                                  href={`/api/v1/comprobantes/${d.id}/ride`}
                                  title="Descargar el RIDE en PDF"
                                  aria-label="Descargar el RIDE en PDF"
                                >
                                  PDF
                                </a>
                                <a
                                  className="fc-btn-icono"
                                  href={`/api/v1/comprobantes/${d.id}/xml`}
                                  title="Descargar el XML autorizado"
                                  aria-label="Descargar el XML autorizado"
                                >
                                  XML
                                </a>
                              </>
                            )}
                            {(d.estado === "DEVUELTO" || d.estado === "RECHAZADO") && (
                              <BotonReintentar id={d.id} onListo={setDocs} />
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function BarraFiltros({
  filtro,
  onFiltro,
  cuentas,
  busqueda,
  onBusqueda,
}: {
  filtro: Filtro;
  onFiltro: (f: Filtro) => void;
  cuentas: Record<string, number>;
  busqueda: string;
  onBusqueda: (v: string) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", flex: 1 }}>
        {FILTROS.map((f) => (
          <button
            key={f.id}
            type="button"
            className="fc-chip"
            aria-pressed={filtro === f.id}
            onClick={() => onFiltro(f.id)}
          >
            {f.label}
            {cuentas[f.id] > 0 && <span className="fc-chip__contador">{cuentas[f.id]}</span>}
          </button>
        ))}
      </div>
      <label style={{ minWidth: 220 }}>
        <span className="fc-label" style={{ position: "absolute", left: -9999 }}>
          Buscar comprobante
        </span>
        <input
          className="fc-campo"
          type="search"
          value={busqueda}
          onChange={(e) => onBusqueda(e.target.value)}
          placeholder="Buscar por número o clave"
        />
      </label>
    </div>
  );
}

function BotonReintentar({
  id,
  onListo,
}: {
  id: string;
  onListo: (docs: TComprobante[]) => void;
}) {
  const [enviando, setEnviando] = useState(false);
  return (
    <button
      type="button"
      className="fc-btn fc-btn--contorno"
      style={{ padding: "6px 14px", fontSize: 12.5 }}
      disabled={enviando}
      onClick={async () => {
        setEnviando(true);
        try {
          await api.post(`/comprobantes/${id}/reintentar`);
          onListo(await api.get<TComprobante[]>("/comprobantes"));
        } finally {
          setEnviando(false);
        }
      }}
    >
      {enviando ? "Reintentando…" : "Reintentar"}
    </button>
  );
}
