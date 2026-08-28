/** Carga masiva de clientes con vista previa (requisito 3.1).
 *
 * Dos pasos: se analiza y se muestran los errores fila por fila, y solo
 * entonces se confirma. Nada se guarda en el primer paso. */

import { useState } from "react";
import { ErrorLimitePlan, api } from "../api/cliente";
import type { VistaPreviaCarga } from "../api/tipos";
import { MuroPlan } from "../plan/Bloqueos";

interface Props {
  onCerrar: () => void;
  onListo: () => void;
  onVerPlanes: () => void;
}

export function CargaMasiva({ onCerrar, onListo, onVerPlanes }: Props) {
  const [archivo, setArchivo] = useState<File | null>(null);
  const [previa, setPrevia] = useState<VistaPreviaCarga | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bloqueo, setBloqueo] = useState<ErrorLimitePlan | null>(null);
  const [trabajando, setTrabajando] = useState(false);

  async function analizar(f: File) {
    setTrabajando(true);
    setError(null);
    setBloqueo(null);
    try {
      setPrevia(await api.subir<VistaPreviaCarga>("/clientes/carga-masiva/analizar", f));
    } catch (e) {
      if (e instanceof ErrorLimitePlan) setBloqueo(e);
      else setError(e instanceof Error ? e.message : "No pudimos leer el archivo");
    } finally {
      setTrabajando(false);
    }
  }

  async function confirmar() {
    if (!archivo) return;
    setTrabajando(true);
    try {
      await api.subir("/clientes/carga-masiva/confirmar", archivo);
      onListo();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos guardar los clientes");
    } finally {
      setTrabajando(false);
    }
  }

  if (bloqueo) {
    return (
      <MuroPlan
        titulo="La carga masiva viene con un plan superior"
        texto={bloqueo.limite.mensaje}
        onVerPlanes={onVerPlanes}
        extra={
          <button
            type="button"
            className="fc-btn fc-btn--texto"
            style={{ display: "block", margin: "0 auto 16px" }}
            onClick={onCerrar}
          >
            Volver a mis clientes
          </button>
        }
      />
    );
  }

  return (
    <section className="fc-tarjeta" aria-label="Importar clientes desde Excel">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 14 }}>
        <div>
          <p className="fc-kicker">Importar</p>
          <h3 className="fc-titulo" style={{ fontSize: 19 }}>
            Sube tu lista de clientes
          </h3>
        </div>
        <button type="button" className="fc-btn-icono" onClick={onCerrar} aria-label="Cerrar">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--texto-suave)", margin: "0 0 16px" }}>
        Necesitamos al menos las columnas <strong>Identificación</strong> y{" "}
        <strong>Razón social</strong>. Si tu archivo es de Excel, guárdalo como CSV antes de
        subirlo. Te mostramos una vista previa y nada se guarda hasta que lo confirmes.
      </p>

      <label className="fc-label" htmlFor="archivo-clientes">
        Archivo CSV
      </label>
      <input
        id="archivo-clientes"
        className="fc-campo"
        type="file"
        accept=".csv,text/csv"
        onChange={(e) => {
          const f = e.target.files?.[0] ?? null;
          setArchivo(f);
          setPrevia(null);
          if (f) void analizar(f);
        }}
      />

      {error && (
        <p className="fc-error" role="alert" style={{ marginTop: 12 }}>
          {error}
        </p>
      )}

      {previa && (
        <div style={{ marginTop: 20 }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
            <Resumen etiqueta="Listos para guardar" valor={previa.validas} tono="exito" />
            {previa.con_error > 0 && (
              <Resumen etiqueta="Con errores" valor={previa.con_error} tono="error" />
            )}
            {previa.ya_guardados > 0 && (
              <Resumen etiqueta="Ya guardados" valor={previa.ya_guardados} tono="neutro" />
            )}
          </div>

          {!previa.cabe_en_el_plan && (
            <div
              role="status"
              style={{
                background: "var(--aviso-bg)",
                border: "1px solid var(--aviso-borde)",
                borderRadius: "var(--radio-panel)",
                padding: "14px 18px",
                marginBottom: 14,
                fontSize: 13.5,
                color: "var(--aviso-texto-fuerte)",
              }}
            >
              En tu plan caben {previa.disponibles_en_el_plan} clientes más. Guardaremos esos y el
              resto te esperará: sube de plan cuando quieras y los agregas sin volver a subir el
              archivo.
            </div>
          )}

          <div className="fc-tarjeta fc-tarjeta--tabla" style={{ maxHeight: 340, overflow: "auto" }}>
            <table className="fc-tabla">
              <thead>
                <tr>
                  <th scope="col">Fila</th>
                  <th scope="col">Identificación</th>
                  <th scope="col">Razón social</th>
                  <th scope="col">Estado</th>
                </tr>
              </thead>
              <tbody>
                {previa.filas.map((f) => (
                  <tr key={f.numero} style={f.errores.length ? { background: "#FEF4F3" } : undefined}>
                    <td className="fc-mono">{f.numero}</td>
                    <td className="fc-mono">{f.identificacion || "—"}</td>
                    <td>{f.razon_social || "—"}</td>
                    <td>
                      {f.errores.length > 0 ? (
                        <span style={{ color: "var(--error-texto)", fontSize: 12.5 }}>
                          {f.errores.join(". ")}
                        </span>
                      ) : f.ya_guardado ? (
                        <span className="fc-estado fc-estado--neutro">
                          <span className="fc-estado__punto" />
                          Ya lo tienes
                        </span>
                      ) : (
                        <span className="fc-estado fc-estado--exito">
                          <span className="fc-estado__punto" />
                          Listo
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: "flex", gap: 10, marginTop: 16, justifyContent: "flex-end" }}>
            <button type="button" className="fc-btn fc-btn--contorno" onClick={onCerrar}>
              Cancelar
            </button>
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              disabled={trabajando || previa.validas === 0}
              onClick={confirmar}
            >
              {trabajando ? "Guardando…" : `Guardar ${previa.validas} clientes`}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function Resumen({
  etiqueta,
  valor,
  tono,
}: {
  etiqueta: string;
  valor: number;
  tono: "exito" | "error" | "neutro";
}) {
  return (
    <div
      style={{
        border: "1px solid var(--borde)",
        borderRadius: "var(--radio-item)",
        padding: "12px 16px",
        minWidth: 140,
      }}
    >
      <div
        className="fc-cifra"
        style={{
          fontSize: 22,
          color:
            tono === "exito"
              ? "var(--exito-texto)"
              : tono === "error"
                ? "var(--error-texto)"
                : "var(--texto-tenue)",
        }}
      >
        {valor}
      </div>
      <div style={{ fontSize: 12, color: "var(--texto-tenue)" }}>{etiqueta}</div>
    </div>
  );
}
