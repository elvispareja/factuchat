/** Configuración: planes con vigencia (Superadmin, esConfig).
 *
 *  Un cambio de precio NO toca las suscripciones vivas: crea una versión futura
 *  del plan. La interfaz lo dice explícitamente antes de guardar. */

import { useEffect, useState } from "react";
import { sa, type Operador, type PlanInterno } from "../api";
import { AvisosAutomaticos } from "./AvisosAutomaticos";
import { Cargando, ErrorSeccion } from "../../ui/Estados";
import { dinero, fechaCorta } from "../../util/formato";

export function Configuracion({ operador }: { operador: Operador }) {
  const [planes, setPlanes] = useState<PlanInterno[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editando, setEditando] = useState<string | null>(null);

  const cargar = () =>
    sa
      .planes()
      .then(setPlanes)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  if (!planes) return <Cargando />;

  const porCodigo = new Map<string, PlanInterno[]>();
  for (const p of planes) {
    porCodigo.set(p.codigo, [...(porCodigo.get(p.codigo) ?? []), p]);
  }

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <AvisosAutomaticos operador={operador} />

      <section className="fc-tarjeta">
        <p className="fc-kicker">Planes y precios</p>
        <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--texto-suave)", margin: "6px 0 0" }}>
          Los precios se cambian hacia adelante: se crea una versión nueva del plan con su fecha
          de vigencia. Quien ya está suscrito conserva el precio que contrató.
        </p>
      </section>

      {[...porCodigo.entries()].map(([codigo, versiones]) => {
        const vigente = versiones.find((v) => v.vigente_ahora) ?? versiones[0];
        const futuras = versiones.filter(
          (v) => !v.vigente_ahora && v.vigente_desde > vigente.vigente_desde,
        );
        return (
          <section key={codigo} className="fc-tarjeta">
            <div style={{ display: "flex", justifyContent: "space-between", gap: 14, flexWrap: "wrap" }}>
              <div>
                <h3 className="fc-titulo" style={{ fontSize: 19, marginBottom: 4 }}>
                  {vigente.nombre}
                </h3>
                <p style={{ fontSize: 13, color: "var(--texto-tenue)", margin: 0 }}>
                  {dinero(vigente.precio)} al mes · desde {fechaCorta(vigente.vigente_desde)} ·{" "}
                  {vigente.suscripciones} suscripciones
                </p>
              </div>
              <button
                type="button"
                className="fc-btn fc-btn--contorno"
                onClick={() => setEditando(editando === codigo ? null : codigo)}
              >
                {editando === codigo ? "Cancelar" : "Cambiar precio"}
              </button>
            </div>

            {futuras.length > 0 && (
              <div
                style={{
                  marginTop: 14,
                  padding: "12px 16px",
                  background: "var(--aviso-bg)",
                  border: "1px solid var(--aviso-borde)",
                  borderRadius: "var(--radio-item)",
                  fontSize: 13,
                  color: "var(--aviso-texto-fuerte)",
                }}
              >
                Programado: {dinero(futuras[0].precio)} desde el{" "}
                {fechaCorta(futuras[0].vigente_desde)}.
              </div>
            )}

            {editando === codigo && (
              <CambioPrecio
                codigo={codigo}
                actual={vigente.precio}
                suscripciones={vigente.suscripciones}
                onListo={async () => {
                  setEditando(null);
                  await cargar();
                }}
              />
            )}
          </section>
        );
      })}
    </div>
  );
}

function CambioPrecio({
  codigo,
  actual,
  suscripciones,
  onListo,
}: {
  codigo: string;
  actual: string;
  suscripciones: number;
  onListo: () => void;
}) {
  const manana = new Date();
  manana.setDate(manana.getDate() + 1);
  const [precio, setPrecio] = useState(actual);
  const [desde, setDesde] = useState(manana.toISOString().slice(0, 10));
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);

  async function guardar() {
    setGuardando(true);
    setError(null);
    try {
      const r = await sa.cambiarPrecio(codigo, precio, desde);
      setAviso(r.aviso);
      window.setTimeout(onListo, 1400);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos guardar el precio");
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div
      style={{
        marginTop: 16,
        padding: "16px 18px",
        background: "var(--superficie-suave)",
        border: "1px solid var(--borde-campo)",
        borderRadius: "var(--radio-panel)",
      }}
    >
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 14 }}>
        <div>
          <label className="fc-label" htmlFor={`precio-${codigo}`}>
            Nuevo precio
          </label>
          <input
            id={`precio-${codigo}`}
            className="fc-campo"
            value={precio}
            onChange={(e) => setPrecio(e.target.value)}
          />
        </div>
        <div>
          <label className="fc-label" htmlFor={`desde-${codigo}`}>
            Vigente desde
          </label>
          <input
            id={`desde-${codigo}`}
            className="fc-campo"
            type="date"
            value={desde}
            min={manana.toISOString().slice(0, 10)}
            onChange={(e) => setDesde(e.target.value)}
          />
        </div>
      </div>
      <p style={{ fontSize: 13, color: "var(--texto-suave)", margin: "12px 0 0" }}>
        {suscripciones > 0
          ? `Las ${suscripciones} suscripciones actuales conservan ${dinero(actual)} hasta esa fecha.`
          : "Nadie está suscrito a esta versión todavía."}
      </p>
      {error && (
        <p className="fc-error" role="alert">
          {error}
        </p>
      )}
      {aviso && (
        <p style={{ fontSize: 13, color: "var(--exito-texto)", marginTop: 10 }} role="status">
          {aviso}
        </p>
      )}
      <button
        type="button"
        className="fc-btn fc-btn--primario"
        style={{ marginTop: 14 }}
        disabled={guardando}
        onClick={() => void guardar()}
      >
        {guardando ? "Guardando…" : `Guardar · vigencia ${fechaCorta(desde)}`}
      </button>
    </div>
  );
}
