/** Reportes y declaración (maqueta líneas 887-958).
 *  Las cifras salen de comprobantes AUTORIZADOS reales (checklist F3). */

import { useEffect, useState } from "react";
import { api } from "../api/cliente";
import type { ResumenFiscal } from "../api/tipos";
import { dinero, fechaCorta } from "../util/formato";
import { Cargando, ErrorSeccion } from "../ui/Estados";

type Periodo = "mes" | "semestre" | "anio";

const PERIODOS: Array<{ id: Periodo; label: string }> = [
  { id: "mes", label: "Mensual" },
  { id: "semestre", label: "Semestral" },
  { id: "anio", label: "Anual" },
];

function rango(periodo: Periodo): { desde: string; hasta: string } {
  const hoy = new Date();
  const anio = hoy.getFullYear();
  if (periodo === "anio") {
    return { desde: `${anio}-01-01`, hasta: `${anio + 1}-01-01` };
  }
  if (periodo === "semestre") {
    const primerSemestre = hoy.getMonth() < 6;
    return primerSemestre
      ? { desde: `${anio}-01-01`, hasta: `${anio}-07-01` }
      : { desde: `${anio}-07-01`, hasta: `${anio + 1}-01-01` };
  }
  const mes = String(hoy.getMonth() + 1).padStart(2, "0");
  const siguiente = hoy.getMonth() === 11 ? `${anio + 1}-01-01` : `${anio}-${String(hoy.getMonth() + 2).padStart(2, "0")}-01`;
  return { desde: `${anio}-${mes}-01`, hasta: siguiente };
}

export function Reportes() {
  const [periodo, setPeriodo] = useState<Periodo>("mes");
  const [datos, setDatos] = useState<ResumenFiscal | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vigente = true;
    setDatos(null);
    const { desde, hasta } = rango(periodo);
    api
      .get<ResumenFiscal>(`/reportes/resumen?desde=${desde}&hasta=${hasta}`)
      .then((d) => vigente && setDatos(d))
      .catch((e) => vigente && setError(e instanceof Error ? e.message : "Error"));
    return () => {
      vigente = false;
    };
  }, [periodo]);

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div className="fc-tabs" role="tablist" aria-label="Período del reporte">
        {PERIODOS.map((p) => (
          <button
            key={p.id}
            type="button"
            role="tab"
            className="fc-tab"
            aria-selected={periodo === p.id}
            onClick={() => setPeriodo(p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {error && <ErrorSeccion mensaje={error} />}
      {!error && !datos && <Cargando />}
      {datos && (
        <div className="fc-split">
          <section className="fc-tarjeta">
            <p className="fc-kicker">Resumen fiscal</p>
            <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: "0 0 18px" }}>
              Del {fechaCorta(datos.desde)} al {fechaCorta(datos.hasta)} · solo comprobantes
              autorizados
            </p>
            <Linea etiqueta="Ventas sin impuesto" valor={dinero(datos.ventas_sin_iva)} />
            <Linea etiqueta="IVA cobrado" valor={dinero(datos.iva_cobrado)} />
            <Linea etiqueta="Notas de crédito" valor={`− ${dinero(datos.notas_credito)}`} />
            <Linea
              etiqueta="Retenciones que te hicieron"
              valor={`− ${dinero(datos.retenciones_recibidas)}`}
            />
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                gap: 12,
                paddingTop: 16,
                marginTop: 8,
                borderTop: "1px solid var(--borde)",
              }}
            >
              <span style={{ fontSize: 14, fontWeight: 600 }}>Número final a pagar</span>
              <span className="fc-cifra" style={{ fontSize: 28 }}>
                {dinero(datos.a_pagar)}
              </span>
            </div>
          </section>

          <section className="fc-tarjeta">
            <p className="fc-kicker">El respaldo</p>
            <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--texto-suave)" }}>
              Llévale esto a tu contador: {datos.comprobantes_emitidos} comprobantes autorizados en
              el período, con su detalle y su respaldo.
            </p>
            <div style={{ display: "grid", gap: 10, marginTop: 18 }}>
              <span style={{ fontSize: 13.5, color: "var(--texto-suave)" }}>Comprobantes firmados</span>
              <button type="button" className="fc-btn fc-btn--contorno" disabled>
                Descargar PDF
              </button>
              <button type="button" className="fc-btn fc-btn--contorno" disabled>
                Descargar Excel
              </button>
              <p style={{ fontSize: 12, color: "var(--texto-tenue)", margin: 0 }}>
                Las descargas llegan en la próxima entrega.
              </p>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function Linea({ etiqueta, valor }: { etiqueta: string; valor: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 12,
        padding: "10px 0",
        borderBottom: "1px solid var(--borde)",
      }}
    >
      <span style={{ fontSize: 13.5, color: "var(--texto-suave)" }}>{etiqueta}</span>
      <span className="fc-cifra" style={{ fontSize: 16 }}>
        {valor}
      </span>
    </div>
  );
}
