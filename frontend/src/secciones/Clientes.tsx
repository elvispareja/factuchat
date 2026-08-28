/** Clientes: libreta con tope por plan y carga masiva con vista previa
 *  (maqueta líneas 527-604). El tope bloquea el ALTA, nunca la facturación:
 *  ese matiz es explícito en el copy de la maqueta. */

import { useEffect, useMemo, useState } from "react";
import { ErrorLimitePlan, api } from "../api/cliente";
import type { ClienteFinal, VistaPreviaCarga } from "../api/tipos";
import { usePlan } from "../plan/PlanContexto";
import { FranjaTope } from "../plan/Bloqueos";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";
import { CargaMasiva } from "./CargaMasiva";

export function Clientes({ onVerPlanes }: { onVerPlanes: () => void }) {
  const { plan, recargar } = usePlan();
  const [clientes, setClientes] = useState<ClienteFinal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busqueda, setBusqueda] = useState("");
  const [importando, setImportando] = useState(false);

  const cargar = () =>
    api
      .get<ClienteFinal[]>("/clientes")
      .then(setClientes)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visibles = useMemo(() => {
    const t = busqueda.trim().toLowerCase();
    if (!t) return clientes ?? [];
    return (clientes ?? []).filter(
      (c) => c.razon_social.toLowerCase().includes(t) || c.identificacion.includes(t),
    );
  }, [clientes, busqueda]);

  const tope = plan?.clientes.tope ?? 0;
  const usados = plan?.clientes.usados ?? 0;
  const topeLleno = tope > 0 && usados >= tope;
  const pct = tope > 0 ? Math.min(100, Math.round((usados / tope) * 100)) : 34;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <section className="fc-tarjeta">
        <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <p className="fc-kicker">Tu libreta</p>
            <p className="fc-cifra" style={{ fontSize: 24, margin: "0 0 4px" }}>
              {tope > 0 ? `${usados} de ${tope} guardados` : `${usados} clientes, sin límite`}
            </p>
            <div
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Clientes guardados"
              style={{
                height: 5,
                borderRadius: 999,
                background: "var(--superficie-tenue)",
                overflow: "hidden",
                marginTop: 10,
                maxWidth: 320,
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${pct}%`,
                  borderRadius: 999,
                  background: topeLleno ? "var(--aviso-punto)" : "var(--verde-acento)",
                  animation: "dbBar .8s cubic-bezier(.16,1,.3,1) both",
                }}
              />
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button
              type="button"
              className="fc-btn fc-btn--contorno"
              onClick={() => setImportando(true)}
            >
              Importar desde Excel
            </button>
            <button type="button" className="fc-btn fc-btn--primario">
              Nuevo cliente
            </button>
          </div>
        </div>

        {topeLleno && (
          <FranjaTope
            texto="Llegaste al límite de tu plan. Tus clientes siguen aquí y puedes seguir facturándoles, pero para guardar nuevos necesitas subir de plan."
            onSubirPlan={onVerPlanes}
          />
        )}
      </section>

      {importando && (
        <CargaMasiva
          onCerrar={() => setImportando(false)}
          onListo={async () => {
            setImportando(false);
            await cargar();
            await recargar();
          }}
          onVerPlanes={onVerPlanes}
        />
      )}

      {error && <ErrorSeccion mensaje={error} />}
      {!error && !clientes && <Cargando />}
      {clientes && (
        <section className="fc-tarjeta fc-tarjeta--tabla">
          <div style={{ padding: "16px 18px", borderBottom: "1px solid var(--borde)" }}>
            <label>
              <span className="fc-label" style={{ position: "absolute", left: -9999 }}>
                Buscar cliente
              </span>
              <input
                className="fc-campo"
                type="search"
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
                placeholder="Buscar por nombre o identificación"
                style={{ maxWidth: 340 }}
              />
            </label>
          </div>
          {visibles.length === 0 ? (
            <Vacio
              titulo={
                busqueda ? "Sin resultados para esa búsqueda." : "Tu libreta está vacía."
              }
              ayuda={
                busqueda
                  ? "Prueba con el nombre o la identificación del cliente."
                  : "Guarda un cliente y lo tendrás listo para facturarle en un toque."
              }
            />
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="fc-tabla">
                <thead>
                  <tr>
                    <th scope="col">Cliente</th>
                    <th scope="col">Identificación</th>
                    <th scope="col">Contacto</th>
                  </tr>
                </thead>
                <tbody>
                  {visibles.map((c, i) => (
                    <tr
                      key={c.id}
                      // Los que exceden el tope se atenúan pero siguen usables
                      style={tope > 0 && i >= tope ? { opacity: 0.45 } : undefined}
                    >
                      <td style={{ fontWeight: 600 }}>{c.razon_social}</td>
                      <td className="fc-mono">
                        {c.tipo_identificacion === "RUC" ? "RUC " : ""}
                        {c.tipo_identificacion === "CEDULA" ? "Cédula " : ""}
                        {c.identificacion}
                      </td>
                      <td style={{ color: "var(--texto-tenue)" }}>
                        {c.email ?? c.telefono ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export { ErrorLimitePlan };
export type { VistaPreviaCarga };
