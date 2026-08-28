/** Cola global de comprobantes (Superadmin, esComp): los rechazados del SRI
 *  piden acción, así que su motivo se muestra completo. */

import { useEffect, useMemo, useState } from "react";
import { sa, type ComprobanteInterno } from "../api";
import { Cargando, ErrorSeccion, Vacio } from "../../ui/Estados";
import { ETIQUETA_TIPO, dinero, tonoEstado } from "../../util/formato";

const FILTROS = [
  { id: "todos", label: "Todos" },
  { id: "problema", label: "Con problema" },
  { id: "proceso", label: "En proceso" },
  { id: "AUTORIZADO", label: "Autorizados" },
];

export function ComprobantesInternos() {
  const [docs, setDocs] = useState<ComprobanteInterno[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filtro, setFiltro] = useState("todos");

  const cargar = () =>
    sa
      .comprobantes(200)
      .then(setDocs)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visibles = useMemo(() => {
    if (!docs) return [];
    if (filtro === "problema") {
      return docs.filter((d) => d.estado === "RECHAZADO" || d.estado === "DEVUELTO");
    }
    if (filtro === "proceso") {
      return docs.filter((d) =>
        ["PENDIENTE", "FIRMADO", "ENVIADO_SRI"].includes(d.estado),
      );
    }
    if (filtro === "AUTORIZADO") return docs.filter((d) => d.estado === "AUTORIZADO");
    return docs;
  }, [docs, filtro]);

  if (error) return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  if (!docs) return <Cargando />;

  const conProblema = docs.filter(
    (d) => d.estado === "RECHAZADO" || d.estado === "DEVUELTO",
  ).length;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", flex: 1 }}>
          {FILTROS.map((f) => (
            <button
              key={f.id}
              type="button"
              className="fc-chip"
              aria-pressed={filtro === f.id}
              onClick={() => setFiltro(f.id)}
            >
              {f.label}
              {f.id === "problema" && conProblema > 0 && (
                <span className="fc-chip__contador">{conProblema}</span>
              )}
            </button>
          ))}
        </div>
        <button type="button" className="fc-btn fc-btn--contorno" onClick={() => void cargar()}>
          Actualizar
        </button>
      </div>

      <section className="fc-tarjeta fc-tarjeta--tabla">
        {visibles.length === 0 ? (
          <Vacio titulo="No hay comprobantes con ese filtro." />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="fc-tabla">
              <thead>
                <tr>
                  <th scope="col">Emisor</th>
                  <th scope="col">Tipo</th>
                  <th scope="col">Número</th>
                  <th scope="col" className="fc-num">Total</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Motivo</th>
                </tr>
              </thead>
              <tbody>
                {visibles.map((d) => {
                  const tono = tonoEstado(d.estado);
                  const motivos = Object.values(d.mensajes ?? {})
                    .flat()
                    .map((m) => m?.legible)
                    .filter(Boolean) as string[];
                  return (
                    <tr key={d.id}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{d.cliente}</div>
                        <div className="fc-mono" style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                          {d.ruc}
                        </div>
                      </td>
                      <td>{ETIQUETA_TIPO[d.tipo] ?? d.tipo}</td>
                      <td className="fc-mono">{d.numero ?? "—"}</td>
                      <td className="fc-num">{dinero(d.total)}</td>
                      <td>
                        <span className={`fc-estado ${tono.clase}`}>
                          <span className="fc-estado__punto" />
                          {tono.label}
                        </span>
                        {d.intentos > 1 && (
                          <div style={{ fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 4 }}>
                            {d.intentos} intentos
                          </div>
                        )}
                      </td>
                      <td style={{ maxWidth: 340, fontSize: 12.5, color: "var(--error-texto)" }}>
                        {motivos.length > 0 ? motivos.join(" · ") : ""}
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
