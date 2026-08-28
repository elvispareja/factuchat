/** Inicio: ventas del mes, próxima declaración por noveno dígito y ranking
 *  (maqueta líneas 203-365). */

import { useEffect, useState } from "react";
import { api } from "../api/cliente";
import type { DatosInicio } from "../api/tipos";
import { usePlan } from "../plan/PlanContexto";
import { dinero, fechaLarga } from "../util/formato";
import { Cargando, ErrorSeccion } from "../ui/Estados";

export function Inicio({ onIr }: { onIr: (s: "comprobantes" | "reportes") => void }) {
  const { plan } = usePlan();
  const [datos, setDatos] = useState<DatosInicio | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vigente = true;
    api
      .get<DatosInicio>("/inicio")
      .then((d) => vigente && setDatos(d))
      .catch((e) => vigente && setError(e instanceof Error ? e.message : "Error"));
    return () => {
      vigente = false;
    };
  }, []);

  if (error) return <ErrorSeccion mensaje={error} />;
  if (!datos) return <Cargando />;

  const decl = datos.proxima_declaracion;

  return (
    <div style={{ display: "grid", gap: 18, animation: "dbIn .45s cubic-bezier(.16,1,.3,1) both" }}>
      <section className="fc-tarjeta--oscura">
        <div className="fc-halo" />
        <div className="fc-kpi" style={{ position: "relative", zIndex: 1 }}>
          <Kpi
            etiqueta="Comprobantes libres"
            valor={plan ? String(plan.restantes) : "—"}
            nota={plan ? `de ${plan.cupo} este mes` : ""}
          />
          <Kpi
            etiqueta="Facturado este mes"
            valor={dinero(datos.ventas_del_mes)}
            nota={`${datos.comprobantes_emitidos} comprobantes autorizados`}
          />
          <Kpi etiqueta="IVA cobrado" valor={dinero(datos.iva_cobrado)} nota="Del período en curso" />
          <Kpi
            etiqueta="Próxima declaración"
            valor={`${decl.dia_maximo}`}
            nota={`de cada mes · noveno dígito ${decl.noveno_digito}`}
          />
        </div>
      </section>

      <div className="fc-split">
        <section className="fc-tarjeta">
          <p className="fc-kicker">Ventas del período</p>
          {datos.ventas_por_dia.length === 0 ? (
            <div className="fc-vacio">
              <p className="fc-vacio__titulo">Todavía no hay ventas este mes.</p>
              <p className="fc-vacio__ayuda">
                En cuanto emitas tu primer comprobante aparecerá aquí.
              </p>
            </div>
          ) : (
            <GraficoBarras datos={datos.ventas_por_dia} />
          )}
          <button
            type="button"
            className="fc-btn fc-btn--oscuro"
            style={{ width: "100%", padding: 12, marginTop: 18 }}
            onClick={() => onIr("reportes")}
          >
            Ver el respaldo completo
          </button>
        </section>

        <section className="fc-tarjeta">
          <p className="fc-kicker">Tu próxima declaración</p>
          <p className="fc-cifra" style={{ fontSize: 30, margin: "0 0 8px" }}>
            {fechaLarga(decl.fecha_limite)}
          </p>
          <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--texto-suave)", margin: 0 }}>
            Tu fecha depende del noveno dígito de tu RUC. En tu caso es {decl.noveno_digito}, así
            que declaras hasta el {decl.dia_maximo} de cada mes.
          </p>
          <p
            style={{
              fontSize: 13,
              color: decl.dias_restantes <= 5 ? "var(--aviso-texto)" : "var(--texto-tenue)",
              marginTop: 12,
              marginBottom: 0,
            }}
          >
            {decl.dias_restantes >= 0
              ? `Faltan ${decl.dias_restantes} días para el período de ${decl.periodo_declarado}.`
              : `El plazo de ${decl.periodo_declarado} ya venció.`}
          </p>
        </section>
      </div>

      <section className="fc-tarjeta">
        <p className="fc-kicker">Quiénes te compran más</p>
        {datos.ranking.length === 0 ? (
          <div className="fc-vacio">
            <p className="fc-vacio__titulo">Aún no hay suficientes ventas para un ranking.</p>
            <p className="fc-vacio__ayuda">Vuelve cuando tengas comprobantes autorizados.</p>
          </div>
        ) : (
          <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 10 }}>
            {datos.ranking.map((fila, i) => (
              <li
                key={fila.cliente}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "12px 14px",
                  border: "1px solid var(--borde)",
                  borderRadius: "var(--radio-item)",
                }}
              >
                <span
                  className="fc-cifra"
                  style={{ width: 22, color: "var(--texto-tenue)", fontSize: 14 }}
                >
                  {i + 1}
                </span>
                <span style={{ flex: 1, minWidth: 0, fontSize: 13.5, fontWeight: 600 }}>
                  {fila.cliente}
                </span>
                <span style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>
                  {fila.comprobantes} comprobantes
                </span>
                <span className="fc-cifra" style={{ fontSize: 15 }}>
                  {dinero(fila.total)}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

function Kpi({ etiqueta, valor, nota }: { etiqueta: string; valor: string; nota: string }) {
  return (
    <div
      style={{
        background: "rgba(255,255,255,.05)",
        border: "1px solid rgba(92,230,143,.22)",
        borderRadius: "var(--radio-item)",
        padding: "16px 18px 17px",
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: ".08em",
          textTransform: "uppercase",
          color: "var(--texto-tenue-oscuro)",
          marginBottom: 10,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {etiqueta}
      </div>
      <div className="fc-cifra" style={{ fontSize: 26, color: "var(--verde-claro)" }}>
        {valor}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--texto-tenue-oscuro)", marginTop: 5 }}>{nota}</div>
    </div>
  );
}

function GraficoBarras({ datos }: { datos: Array<{ fecha: string; total: string }> }) {
  const maximo = Math.max(...datos.map((d) => Number(d.total)), 1);
  return (
    <div
      style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 160, marginTop: 16 }}
      role="img"
      aria-label={`Ventas por día: ${datos.length} días con ventas`}
    >
      {datos.map((d) => (
        <div
          key={d.fecha}
          title={`${d.fecha}: ${dinero(d.total)}`}
          style={{
            flex: 1,
            minWidth: 4,
            height: `${Math.max(4, (Number(d.total) / maximo) * 100)}%`,
            background: "var(--verde-acento)",
            borderRadius: "6px 6px 3px 3px",
            animation: "dbBar .8s cubic-bezier(.16,1,.3,1) both",
          }}
        />
      ))}
    </div>
  );
}
