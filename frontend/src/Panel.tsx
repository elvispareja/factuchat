/** Panel de clientes: armazón + las 8 secciones (fase 3). */

import { useState } from "react";
import { BarraLateral } from "./shell/BarraLateral";
import { ENCABEZADOS, type IdSeccion } from "./shell/navegacion";
import { usePlan } from "./plan/PlanContexto";
import { MuroPlan } from "./plan/Bloqueos";
import { Cargando, ErrorSeccion } from "./ui/Estados";
import { Inicio } from "./secciones/Inicio";
import { Comprobantes } from "./secciones/Comprobantes";
import { Clientes } from "./secciones/Clientes";
import { Catalogo } from "./secciones/Catalogo";
import { Tienda } from "./secciones/Tienda";
import { Reportes } from "./secciones/Reportes";
import { Tutoriales } from "./secciones/Tutoriales";
import { MiCuenta } from "./secciones/MiCuenta";
import { SubirFirma } from "./secciones/SubirFirma";

export function Panel({ onSalir }: { onSalir: () => void }) {
  const { plan, firma, cargando, error, recargar } = usePlan();
  const [seccion, setSeccion] = useState<IdSeccion>("inicio");
  const [navAbierta, setNavAbierta] = useState(false);
  const [avisoPlanes, setAvisoPlanes] = useState(false);

  const ir = (destino: IdSeccion) => {
    setSeccion(destino);
    setNavAbierta(false);
  };

  const encabezado = ENCABEZADOS[seccion];
  const verPlanes = () => {
    setAvisoPlanes(true);
    window.setTimeout(() => setAvisoPlanes(false), 3200);
  };

  // Sin firma electrónica no hay panel que enseñar: el servidor rechaza todas
  // las rutas de operación, así que pintar el armazón solo llevaría a una
  // pantalla llena de errores. Se va derecho a subirla.
  if (firma && !firma.cargada) return <SubirFirma />;

  return (
    <div className="fc-shell">
      <button
        type="button"
        className="fc-veil"
        data-abierta={navAbierta ? "1" : "0"}
        aria-label="Cerrar menú"
        onClick={() => setNavAbierta(false)}
      />
      <BarraLateral
        activa={seccion}
        onIr={ir}
        abierta={navAbierta}
        onCerrar={() => setNavAbierta(false)}
      />

      <main className="fc-main">
        <header className="fc-cabecera">
          <div style={{ display: "flex", gap: 14, alignItems: "center", minWidth: 0 }}>
            <button
              type="button"
              className="fc-burger"
              aria-label="Menú"
              onClick={() => setNavAbierta(true)}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </button>
            <div style={{ minWidth: 0 }}>
              <p className="fc-kicker">{encabezado.kicker}</p>
              <h1 className="fc-titulo">{encabezado.titulo}</h1>
            </div>
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <span className="fc-pildora-asistente">
              <span data-punto />
              Asistente activo
            </span>
            <button type="button" className="fc-btn fc-btn--texto" onClick={onSalir}>
              Cerrar sesión
            </button>
          </div>
        </header>

        {cargando && !plan && <Cargando texto="Cargando tu panel…" />}
        {error && <ErrorSeccion mensaje={error} onReintentar={() => void recargar()} />}

        {plan && (
          <>
            {seccion === "inicio" && <Inicio onIr={ir} />}
            {seccion === "comprobantes" && <Comprobantes onVerPlanes={verPlanes} />}
            {seccion === "clientes" && <Clientes onVerPlanes={verPlanes} />}
            {seccion === "catalogo" && <Catalogo onVerPlanes={verPlanes} />}
            {seccion === "tienda" && <Tienda onVerPlanes={verPlanes} />}
            {seccion === "reportes" && <Reportes />}
            {seccion === "tutoriales" && <Tutoriales />}
            {seccion === "cuenta" && <MiCuenta onVerPlanes={verPlanes} />}
          </>
        )}

        {avisoPlanes && (
          <div role="status" className="fc-toast">
            El selector de planes llega en la próxima entrega.
          </div>
        )}
      </main>
    </div>
  );
}

/** Muro genérico: contrato de reserva para cualquier sección que se gatee en el
 *  futuro. Hoy ninguna lo usa (solo la tienda tiene su propio muro). */
export function MuroGenerico({ onVerPlanes }: { onVerPlanes: () => void }) {
  return (
    <MuroPlan
      titulo="Esta parte viene con un plan superior"
      texto="Tus datos siguen aquí, tal como los dejaste, y esta sección se abre el mismo día que actives el plan."
      onVerPlanes={onVerPlanes}
    />
  );
}
