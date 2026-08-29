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
  const [editando, setEditando] = useState<ClienteFinal | "nuevo" | null>(null);

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
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              disabled={topeLleno}
              onClick={() => setEditando("nuevo")}
            >
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
                      style={{
                        cursor: "pointer",
                        ...(tope > 0 && i >= tope ? { opacity: 0.45 } : undefined),
                      }}
                      onClick={() => setEditando(c)}
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

      {editando && (
        <FormularioCliente
          cliente={editando === "nuevo" ? null : editando}
          onCerrar={() => setEditando(null)}
          onGuardado={async () => {
            setEditando(null);
            await cargar();
            await recargar();
          }}
        />
      )}
    </div>
  );
}

const TIPOS_ID: Array<{ id: ClienteFinal["tipo_identificacion"]; label: string }> = [
  { id: "CEDULA", label: "Cédula" },
  { id: "RUC", label: "RUC" },
  { id: "PASAPORTE", label: "Pasaporte" },
  { id: "ID_EXTERIOR", label: "Identificación del exterior" },
  { id: "CONSUMIDOR_FINAL", label: "Consumidor final" },
];

function FormularioCliente({
  cliente,
  onCerrar,
  onGuardado,
}: {
  cliente: ClienteFinal | null;
  onCerrar: () => void;
  onGuardado: () => void;
}) {
  const [tipoId, setTipoId] = useState<ClienteFinal["tipo_identificacion"]>(
    cliente?.tipo_identificacion ?? "CEDULA",
  );
  const [identificacion, setIdentificacion] = useState(cliente?.identificacion ?? "");
  const [razonSocial, setRazonSocial] = useState(cliente?.razon_social ?? "");
  const [email, setEmail] = useState(cliente?.email ?? "");
  const [telefono, setTelefono] = useState(cliente?.telefono ?? "");
  const [direccion, setDireccion] = useState(cliente?.direccion ?? "");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function guardar() {
    setGuardando(true);
    setError(null);
    const cuerpo = {
      tipo_identificacion: tipoId,
      identificacion: identificacion.trim(),
      razon_social: razonSocial.trim(),
      email: email.trim() || null,
      telefono: telefono.trim() || null,
      direccion: direccion.trim() || null,
    };
    try {
      if (cliente) {
        await api.put(`/clientes/${cliente.id}`, cuerpo);
      } else {
        await api.post("/clientes", cuerpo);
      }
      onGuardado();
    } catch (e) {
      setError(
        e instanceof ErrorLimitePlan
          ? e.message
          : e instanceof Error
            ? e.message
            : "No pudimos guardar el cliente",
      );
    } finally {
      setGuardando(false);
    }
  }

  const valido = identificacion.trim().length >= 3 && razonSocial.trim().length >= 2;

  return (
    <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Cliente">
      <div className="fc-modal__panel" style={{ maxWidth: 520 }}>
        <p className="fc-kicker">{cliente ? "Editar cliente" : "Nuevo cliente"}</p>
        <h2 className="fc-titulo" style={{ fontSize: 20, marginBottom: 18 }}>
          {cliente ? cliente.razon_social : "Agregar a tu libreta"}
        </h2>

        <div style={{ display: "grid", gap: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="fc-label" htmlFor="cf-tipo">
                Tipo de identificación
              </label>
              <select
                id="cf-tipo"
                className="fc-campo"
                value={tipoId}
                onChange={(e) => setTipoId(e.target.value as ClienteFinal["tipo_identificacion"])}
              >
                {TIPOS_ID.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="fc-label" htmlFor="cf-id">
                Número
              </label>
              <input
                id="cf-id"
                className="fc-campo fc-mono"
                value={identificacion}
                onChange={(e) => setIdentificacion(e.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="fc-label" htmlFor="cf-nombre">
              Nombre o razón social
            </label>
            <input
              id="cf-nombre"
              className="fc-campo"
              value={razonSocial}
              onChange={(e) => setRazonSocial(e.target.value)}
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label className="fc-label" htmlFor="cf-email">
                Correo
              </label>
              <input
                id="cf-email"
                type="email"
                className="fc-campo"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div>
              <label className="fc-label" htmlFor="cf-telefono">
                Teléfono
              </label>
              <input
                id="cf-telefono"
                className="fc-campo"
                value={telefono}
                onChange={(e) => setTelefono(e.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="fc-label" htmlFor="cf-direccion">
              Dirección
            </label>
            <input
              id="cf-direccion"
              className="fc-campo"
              value={direccion}
              onChange={(e) => setDireccion(e.target.value)}
            />
          </div>

          {error && (
            <p className="fc-error" role="alert">
              {error}
            </p>
          )}

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="fc-btn fc-btn--contorno" onClick={onCerrar}>
              Cancelar
            </button>
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              disabled={!valido || guardando}
              onClick={() => void guardar()}
            >
              {guardando ? "Guardando…" : cliente ? "Guardar cambios" : "Agregar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export { ErrorLimitePlan };
export type { VistaPreviaCarga };
