/** Auditoría: registro inmutable, SOLO LECTURA (Superadmin, esAudit).
 *  No existe ningún control que escriba aquí, ni en la interfaz ni en la API. */

import { useEffect, useMemo, useState } from "react";
import { sa, type EntradaAuditoria } from "../api";
import { Cargando, ErrorSeccion, Vacio } from "../../ui/Estados";

const ACCIONES_DESTACADAS: Record<string, string> = {
  IMPERSONACION_INICIO: "fc-estado--error",
  IMPERSONACION_FIN: "fc-estado--neutro",
  SA_ESTADO_TENANT: "fc-estado--aviso",
  SA_ALTA_CLIENTE: "fc-estado--exito",
  LOGIN_FALLIDO: "fc-estado--aviso",
  SESIONES_REVOCADAS: "fc-estado--error",
};

export function Auditoria() {
  const [entradas, setEntradas] = useState<EntradaAuditoria[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filtro, setFiltro] = useState("");

  useEffect(() => {
    sa.auditoria()
      .then(setEntradas)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));
  }, []);

  const visibles = useMemo(() => {
    const t = filtro.trim().toLowerCase();
    if (!t) return entradas ?? [];
    return (entradas ?? []).filter(
      (e) =>
        e.accion.toLowerCase().includes(t) ||
        (e.actor ?? "").toLowerCase().includes(t) ||
        (e.cliente ?? "").toLowerCase().includes(t),
    );
  }, [entradas, filtro]);

  if (error) return <ErrorSeccion mensaje={error} />;
  if (!entradas) return <Cargando />;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <input
          className="fc-campo"
          type="search"
          value={filtro}
          onChange={(e) => setFiltro(e.target.value)}
          placeholder="Filtrar por acción, operador o cliente"
          aria-label="Filtrar auditoría"
          style={{ maxWidth: 360 }}
        />
        <span className="fc-estado fc-estado--neutro">
          <span className="fc-estado__punto" />
          Solo lectura
        </span>
      </div>

      <section className="fc-tarjeta fc-tarjeta--tabla">
        {visibles.length === 0 ? (
          <Vacio titulo="Sin entradas para ese filtro." />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="fc-tabla">
              <thead>
                <tr>
                  <th scope="col">Fecha</th>
                  <th scope="col">Operador</th>
                  <th scope="col">Acción</th>
                  <th scope="col">Cliente</th>
                  <th scope="col">Detalle</th>
                  <th scope="col">IP</th>
                </tr>
              </thead>
              <tbody>
                {visibles.map((e) => (
                  <tr key={e.id}>
                    <td className="fc-mono" style={{ whiteSpace: "nowrap" }}>
                      {e.fecha.slice(0, 19).replace("T", " ")}
                    </td>
                    <td>
                      {e.actor ?? "—"}
                      {e.rol && (
                        <div style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>{e.rol}</div>
                      )}
                    </td>
                    <td>
                      <span
                        className={`fc-estado ${ACCIONES_DESTACADAS[e.accion] ?? "fc-estado--neutro"}`}
                      >
                        <span className="fc-estado__punto" />
                        {e.accion}
                      </span>
                    </td>
                    <td>{e.cliente ?? "— (global)"}</td>
                    <td style={{ maxWidth: 320 }}>
                      <Detalle entrada={e} />
                    </td>
                    <td className="fc-mono" style={{ fontSize: 11.5 }}>
                      {e.ip ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Detalle({ entrada }: { entrada: EntradaAuditoria }) {
  const d = entrada.despues as Record<string, unknown> | null;
  if (!d) return <span style={{ color: "var(--texto-tenue)" }}>—</span>;

  const imp = d._impersonacion as { actor_rol_real?: string } | undefined;
  const motivo = typeof d.motivo === "string" ? d.motivo : null;

  return (
    <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>
      {motivo && <div style={{ color: "var(--texto-suave)" }}>{motivo}</div>}
      {imp && (
        <div style={{ color: "var(--error-texto)", fontWeight: 600, marginTop: 3 }}>
          Durante una impersonación ({imp.actor_rol_real})
        </div>
      )}
      {!motivo && !imp && (
        <code style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
          {entrada.tabla ?? ""} {entrada.registro_id?.slice(0, 8) ?? ""}
        </code>
      )}
    </div>
  );
}
