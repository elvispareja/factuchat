/** Barra lateral del panel (maqueta líneas 74-200). */

import { usePlan } from "../plan/PlanContexto";
import { IconoCandado } from "../plan/Bloqueos";
import { MENU, type IdSeccion } from "./navegacion";

interface Props {
  activa: IdSeccion;
  onIr: (seccion: IdSeccion) => void;
  abierta: boolean;
  onCerrar: () => void;
}

export function BarraLateral({ activa, onIr, abierta, onCerrar }: Props) {
  const { plan, permite } = usePlan();

  return (
    <aside
      data-abierta={abierta ? "1" : "0"}
      className="fc-lateral"
      aria-label="Menú principal"
    >
      <div className="fc-halo" style={{ top: -90, right: -80 }} />

      <div style={{ position: "relative", zIndex: 1, padding: "22px 22px 18px", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <div
            style={{
              fontFamily: "var(--fuente-mano)",
              fontSize: 29,
              lineHeight: 1,
              fontWeight: 600,
              color: "var(--verde-claro)",
              letterSpacing: ".01em",
            }}
          >
            Factuchat
            <span style={{ fontSize: 11, verticalAlign: "super", marginLeft: 2, opacity: 0.75 }}>
              ®
            </span>
          </div>
          <button
            type="button"
            onClick={onCerrar}
            aria-label="Cerrar menú"
            className="fc-lateral__cerrar"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" stroke="#5CE68F" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {plan && (
          <div
            style={{
              marginTop: 18,
              background: "rgba(255,255,255,.05)",
              border: "1px solid rgba(92,230,143,.22)",
              borderRadius: "var(--radio-item)",
              padding: "14px 16px",
            }}
          >
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: ".08em",
                textTransform: "uppercase",
                color: "var(--texto-tenue-oscuro)",
                marginBottom: 8,
              }}
            >
              Tu plan
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <span
                className="fc-cifra"
                style={{ fontSize: 26, color: "var(--verde-claro)" }}
              >
                {plan.restantes}
              </span>
              <span style={{ fontSize: 12, color: "var(--texto-tenue-oscuro)" }}>
                de {plan.cupo} comprobantes
              </span>
            </div>
            <div
              role="progressbar"
              aria-valuenow={plan.pct_uso}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Comprobantes usados"
              style={{
                height: 5,
                borderRadius: 999,
                background: "rgba(255,255,255,.12)",
                margin: "11px 0 10px",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${plan.pct_uso}%`,
                  borderRadius: 999,
                  background: plan.pocos ? "var(--aviso-punto)" : "var(--verde-acento)",
                  animation: "dbBar .8s cubic-bezier(.16,1,.3,1) both",
                }}
              />
            </div>
            {plan.pocos ? (
              <button
                type="button"
                className="fc-btn fc-btn--primario"
                style={{ width: "100%", padding: 9, fontSize: 12.5, fontWeight: 700, color: "#07130D" }}
                onClick={() => onIr("cuenta")}
              >
                Recargar comprobantes
              </button>
            ) : (
              <div style={{ fontSize: 11.5, color: "var(--texto-tenue-oscuro)" }}>
                {plan.nota_cupo}
              </div>
            )}
          </div>
        )}
      </div>

      <nav
        className="fc-scroll"
        style={{ position: "relative", zIndex: 1, flex: 1, overflowY: "auto", padding: "4px 14px 20px" }}
      >
        {MENU.map((item) => {
          const bloqueado = Boolean(item.requiere) && !permite(item.requiere!);
          const seleccionada = activa === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onIr(item.id)}
              aria-current={seleccionada ? "page" : undefined}
              className="fc-lateral__item"
              data-activa={seleccionada ? "1" : "0"}
            >
              <svg width="19" height="19" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d={item.icono}
                  stroke="currentColor"
                  strokeWidth="1.9"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span style={{ flex: 1, textAlign: "left" }}>{item.label}</span>
              {bloqueado && (
                <span
                  style={{ opacity: 0.65, display: "grid" }}
                  aria-label="Viene con un plan superior"
                >
                  <IconoCandado tamano={14} />
                </span>
              )}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
