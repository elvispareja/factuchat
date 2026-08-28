/** Panel interno del equipo Factuchat — 11 secciones (fase 4). */

import { useCallback, useEffect, useMemo, useState } from "react";
import "./interno.css";
import { Cargando, ErrorSeccion } from "../ui/Estados";
import { MENU_INTERNO, type IdSeccionInterna } from "./navegacion";
import { sa, type Operador, type SesionImpersonacion } from "./api";
import { DashboardInterno } from "./secciones/DashboardInterno";
import { ClientesInternos } from "./secciones/ClientesInternos";
import { ComprobantesInternos } from "./secciones/ComprobantesInternos";
import { Marketing } from "./secciones/Marketing";
import { Configuracion } from "./secciones/Configuracion";
import { Auditoria } from "./secciones/Auditoria";
import { BuzonSri } from "./secciones/BuzonSri";
import { ConsumoYCostos } from "./secciones/ConsumoYCostos";
import { WhatsApp } from "./secciones/WhatsApp";
import { EnConstruccion } from "./secciones/EnConstruccion";

export function PanelInterno({ onSalir }: { onSalir: () => void }) {
  const [operador, setOperador] = useState<Operador | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seccion, setSeccion] = useState<IdSeccionInterna>("dash");
  // Algunas secciones ponen su conteo delante del subtítulo («10 inquilinos · …»),
  // como en la maqueta. Lo publica la sección, que es quien lo sabe.
  const [resumen, setResumen] = useState<string | null>(null);
  const [imp, setImp] = useState<SesionImpersonacion | null>(null);

  const cargar = useCallback(async () => {
    setError(null);
    try {
      setOperador(await sa.yo());
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos cargar el panel");
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  const item = useMemo(
    () => MENU_INTERNO.find((m) => m.id === seccion) ?? MENU_INTERNO[0],
    [seccion],
  );

  async function salirDeImpersonacion() {
    if (!imp) return;
    try {
      await sa.salirImpersonacion(imp.impersonacion_id);
    } finally {
      setImp(null);
    }
  }

  if (error) return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  if (!operador) return <Cargando texto="Cargando el panel interno…" />;

  // Configuración es solo para SUPERADMIN: si el rol no alcanza, no se entra
  const visible = MENU_INTERNO.filter((m) => !m.soloSuperadmin || operador.es_superadmin);
  const seccionPermitida = visible.some((m) => m.id === seccion);

  return (
    <>
      {imp && (
        <div className="fc-sa-imp" role="alert">
          <span>{imp.aviso}</span>
          <button type="button" onClick={() => void salirDeImpersonacion()}>
            Salir de impersonación
          </button>
        </div>
      )}

      <div className="fc-sa-shell" data-imp={imp ? "1" : "0"}>
        <aside className="fc-sa-lateral" aria-label="Menú del panel interno">
          <div style={{ padding: "22px 20px 16px" }}>
            <div className="fc-sa-marca">
              Factuchat
              <span style={{ fontSize: 11, verticalAlign: "super", marginLeft: 2, opacity: 0.7 }}>
                ®
              </span>
            </div>
            <div className="fc-sa-badge">SUPERADMIN</div>
          </div>

          <nav className="fc-scroll" style={{ flex: 1, overflowY: "auto", padding: "4px 12px 16px" }}>
            {visible.map((m) => (
              <button
                key={m.id}
                type="button"
                className="fc-sa-item"
                data-activa={seccion === m.id ? "1" : "0"}
                aria-current={seccion === m.id ? "page" : undefined}
                onClick={() => setSeccion(m.id)}
              >
                {m.label}
              </button>
            ))}
          </nav>

          <div
            style={{
              padding: "14px 20px 18px",
              borderTop: "1px solid rgba(255,255,255,.08)",
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <span
              style={{
                width: 32,
                height: 32,
                borderRadius: "50%",
                background: "rgba(92,230,143,.16)",
                color: "#5CE68F",
                display: "grid",
                placeItems: "center",
                fontWeight: 700,
                fontSize: 13,
              }}
              aria-hidden="true"
            >
              {operador.nombre.charAt(0).toUpperCase() || "?"}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span
                style={{
                  display: "block",
                  fontSize: 12.5,
                  fontWeight: 600,
                  color: "#DFF3E7",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {operador.nombre}
              </span>
              <span style={{ display: "block", fontSize: 11, color: "#8FB3A0" }}>
                {operador.rol}
              </span>
            </span>
            <button
              type="button"
              onClick={onSalir}
              aria-label="Cerrar sesión"
              style={{
                background: "none",
                border: "none",
                color: "#8FB3A0",
                cursor: "pointer",
                padding: 4,
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M9 21H5a1 1 0 01-1-1V4a1 1 0 011-1h4M16 17l5-5-5-5M21 12H9"
                  stroke="currentColor"
                  strokeWidth="1.9"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
        </aside>

        <main className="fc-sa-main">
          <header
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              gap: 16,
              marginBottom: 24,
              flexWrap: "wrap",
            }}
          >
            <div style={{ minWidth: 0 }}>
              <h1
                className="fc-titulo"
                style={{ fontSize: 25, marginBottom: 4 }}
              >
                {item.titulo}
              </h1>
              <p style={{ fontSize: 13.5, color: "var(--texto-tenue)", margin: 0 }}>
                {[item.id === "dash" ? mesEnCurso() : resumen, item.subtitulo]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            <span className="fc-sa-reloj">
              <span data-punto />
              {operador.zona} · {operador.hoy}
            </span>
          </header>

          {!seccionPermitida ? (
            <ErrorSeccion mensaje="Tu rol no tiene acceso a esta sección." />
          ) : (
            <>
              {seccion === "dash" && <DashboardInterno onIr={setSeccion} />}
              {seccion === "clientes" && (
                <ClientesInternos
                  operador={operador}
                  onImpersonar={setImp}
                  onResumen={setResumen}
                />
              )}
              {seccion === "comp" && <ComprobantesInternos />}
              {seccion === "mkt" && <Marketing operador={operador} />}
              {seccion === "consumo" && <ConsumoYCostos operador={operador} />}
              {seccion === "wa" && <WhatsApp />}
              {seccion === "config" && <Configuracion operador={operador} />}
              {seccion === "audit" && <Auditoria />}
              {seccion === "buzon" && <BuzonSri operador={operador} />}
              {(seccion === "pagos" || seccion === "soporte") && (
                <EnConstruccion seccion={item.label} />
              )}
            </>
          )}
        </main>
      </div>
    </>
  );
}

/** «Agosto 2026»: el Dashboard general lleva el mes delante del subtítulo,
 *  igual que en la maqueta. */
function mesEnCurso(): string {
  const texto = new Intl.DateTimeFormat("es-EC", { month: "long", year: "numeric" }).format(
    new Date(),
  );
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}
