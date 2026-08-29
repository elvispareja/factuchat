/** Clientes del panel interno: listado, ficha con acciones auditadas e
 *  impersonación (Superadmin.dc.html, bloques `esClientes` y `esFicha`).
 *
 *  El listado sigue la maqueta pieza por pieza: buscador con lupa, exportación
 *  a CSV, alta de cliente, dos filas de chips (estado y plan), la tabla de
 *  siete columnas cuya fila entera abre la ficha, y el pie con el conteo y la
 *  paginación de 25 en 25.
 */

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import {
  sa,
  type ClienteInterno,
  type FichaCliente,
  type Operador,
  type SesionImpersonacion,
} from "../api";
import { Cargando, ErrorSeccion } from "../../ui/Estados";
import { NuevoCliente } from "./NuevoCliente";
import { dinero, fechaCorta } from "../../util/formato";
import { sesion } from "../../api/cliente";

/** Los cinco estados de cartera de la maqueta. El servidor los deriva; aquí
 *  solo se filtran, para que la columna y el chip no puedan discrepar. */
const ESTADOS = ["Todos", "ACTIVO", "EN_PRUEBA", "SUSPENDIDO", "MOROSO", "CANCELADO"];
const PLANES = ["Todos", "Inicial", "Independiente", "Emprendedor", "Empresario"];
const POR_PAGINA = 25;

const HORA = new Intl.DateTimeFormat("es-EC", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const DIA_MES = new Intl.DateTimeFormat("es-EC", { day: "2-digit", month: "short" });

function mismoDia(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/** «Hoy 10:42», «Ayer 15:27», «19 ago 16:03» — como en la maqueta. */
function momentoCorto(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const hoy = new Date();
  if (mismoDia(d, hoy)) return `Hoy ${HORA.format(d)}`;
  const ayer = new Date(hoy);
  ayer.setDate(hoy.getDate() - 1);
  if (mismoDia(d, ayer)) return `Ayer ${HORA.format(d)}`;
  return `${DIA_MES.format(d)} ${HORA.format(d)}`;
}

interface Props {
  operador: Operador;
  onImpersonar: (s: SesionImpersonacion) => void;
  /** Deja el conteo en el subtítulo de la cabecera: «10 inquilinos · …». */
  onResumen?: (texto: string | null) => void;
}

export function ClientesInternos({ operador, onImpersonar, onResumen }: Props) {
  const [clientes, setClientes] = useState<ClienteInterno[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busqueda, setBusqueda] = useState("");
  const [filtroEstado, setFiltroEstado] = useState("Todos");
  const [filtroPlan, setFiltroPlan] = useState("Todos");
  const [pagina, setPagina] = useState(1);
  const [abierto, setAbierto] = useState<ClienteInterno | null>(null);
  const [dandoAlta, setDandoAlta] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const [exportando, setExportando] = useState(false);

  const cargar = () =>
    sa
      .clientes()
      .then(setClientes)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!onResumen) return;
    onResumen(clientes ? `${clientes.length} inquilinos` : null);
    return () => onResumen(null);
  }, [clientes, onResumen]);

  const filtradas = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    return (clientes ?? [])
      .filter((c) => filtroEstado === "Todos" || c.estado_cartera === filtroEstado)
      .filter((c) => filtroPlan === "Todos" || c.plan === filtroPlan)
      .filter((c) => !q || c.razon_social.toLowerCase().includes(q) || c.ruc.includes(q));
  }, [clientes, busqueda, filtroEstado, filtroPlan]);

  const paginas = Math.max(1, Math.ceil(filtradas.length / POR_PAGINA));
  // Al estrechar el filtro la página actual puede dejar de existir
  const paginaActual = Math.min(pagina, paginas);
  const visibles = filtradas.slice((paginaActual - 1) * POR_PAGINA, paginaActual * POR_PAGINA);

  function filtrar(fn: () => void) {
    fn();
    setPagina(1);
  }

  async function exportar() {
    setExportando(true);
    setError(null);
    try {
      await sa.exportarClientes();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos generar el CSV");
    } finally {
      setExportando(false);
    }
  }

  if (error && !clientes) {
    return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  }
  if (!clientes) return <Cargando />;

  if (abierto) {
    return (
      <Ficha
        cliente={abierto}
        operador={operador}
        onVolver={() => {
          setAbierto(null);
          void cargar();
        }}
        onImpersonar={onImpersonar}
      />
    );
  }

  return (
    <div style={{ animation: "dbIn .35s ease-out both" }}>
      <div
        style={{
          display: "flex",
          gap: 10,
          flexWrap: "wrap",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <div className="fc-sa-busca">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--texto-tenue)"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="M16.5 16.5L21 21" />
          </svg>
          <input
            value={busqueda}
            onChange={(e) => filtrar(() => setBusqueda(e.target.value))}
            placeholder="Buscar por RUC o nombre"
            autoComplete="off"
            aria-label="Buscar cliente por RUC o nombre"
          />
        </div>
        <button
          type="button"
          className="fc-btn fc-btn--contorno"
          onClick={() => void exportar()}
          disabled={exportando}
        >
          {exportando ? "Generando…" : "Exportar CSV"}
        </button>
        {/* Solo quien puede actuar da de alta: LECTURA mira y no ve el botón,
            igual que en la maqueta (sc-if puedeActuar). El servidor lo exige
            otra vez en POST /sa/clientes, que va con PUEDE_ACTUAR. */}
        {operador.puede_actuar && (
          <button
            type="button"
            className="fc-btn fc-btn--oscuro"
            style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
            onClick={() => setDandoAlta(true)}
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.6"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
            Nuevo cliente
          </button>
        )}
      </div>

      <div className="fc-sa-chips" style={{ marginBottom: 8 }} role="group" aria-label="Filtrar por estado">
        {ESTADOS.map((e) => (
          <button
            key={e}
            type="button"
            className="fc-sa-chip"
            aria-pressed={filtroEstado === e}
            onClick={() => filtrar(() => setFiltroEstado(e))}
          >
            {e}
          </button>
        ))}
      </div>
      <div className="fc-sa-chips" style={{ marginBottom: 16 }} role="group" aria-label="Filtrar por plan">
        {PLANES.map((pl) => (
          <button
            key={pl}
            type="button"
            className="fc-sa-chip"
            aria-pressed={filtroPlan === pl}
            onClick={() => filtrar(() => setFiltroPlan(pl))}
          >
            {pl}
          </button>
        ))}
      </div>

      {/* La maqueta saca los avisos como píldora flotante abajo al centro
          (bloque `aviso`), no como una línea que empuja la tabla. */}
      {(aviso || error) &&
        createPortal(
          <div role="status" className="fc-toast" data-tono={error ? "error" : "exito"}>
            {error ?? aviso}
          </div>,
          document.body,
        )}

      <div className="fc-sa-tabla">
        <div className="fc-sa-tabla__scroll">
          <div className="fc-sa-tabla__ancho">
            <div className="fc-sa-fila fc-sa-fila--cabecera">
              <div>RUC</div>
              <div>Cliente</div>
              <div>Plan</div>
              <div>Estado</div>
              <div>Cupo del mes</div>
              <div>Alta</div>
              <div>Último comp.</div>
            </div>

            {visibles.map((c) => (
              <button
                key={c.id}
                type="button"
                className="fc-sa-fila"
                onClick={() => setAbierto(c)}
                aria-label={`Abrir la ficha de ${c.razon_social}`}
              >
                <div className="fc-sa-fila__ruc">{c.ruc}</div>
                <div className="fc-sa-fila__nombre">{c.razon_social}</div>
                <div className="fc-sa-fila__plan">{c.plan ?? "—"}</div>
                <div>
                  <span className="fc-sa-pill" data-estado={c.estado_cartera}>
                    {c.estado_cartera.replace("_", " ")}
                  </span>
                </div>
                <Cupo usados={c.usados} cupo={c.cupo} />
                <div className="fc-sa-fila__dato">{fechaCorta(c.alta.slice(0, 10))}</div>
                <div className="fc-sa-fila__dato">{momentoCorto(c.ultimo_comp)}</div>
              </button>
            ))}

            {visibles.length === 0 && (
              <div
                style={{
                  padding: 36,
                  textAlign: "center",
                  fontSize: 13.5,
                  color: "var(--texto-tenue)",
                }}
              >
                Sin resultados con esos filtros.
              </div>
            )}
          </div>
        </div>

        <div className="fc-sa-pie">
          <span>
            {filtradas.length} {filtradas.length === 1 ? "cliente" : "clientes"} · página{" "}
            {paginaActual} de {paginas}
          </span>
          {paginas > 1 ? (
            <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
              <button
                type="button"
                onClick={() => setPagina(paginaActual - 1)}
                disabled={paginaActual <= 1}
              >
                Anterior
              </button>
              <button
                type="button"
                onClick={() => setPagina(paginaActual + 1)}
                disabled={paginaActual >= paginas}
              >
                Siguiente
              </button>
            </span>
          ) : (
            <span>{POR_PAGINA} por página</span>
          )}
        </div>
      </div>

      {dandoAlta && (
        <NuevoCliente
          onCerrar={() => setDandoAlta(false)}
          onCreado={(mensaje) => {
            setDandoAlta(false);
            setAviso(mensaje);
            window.setTimeout(() => setAviso(null), 6000);
            void cargar();
          }}
        />
      )}
    </div>
  );
}

/** Cupo del mes: la cifra y la barra, que cambia de color al acercarse al
 *  tope (85%) y al llegar a él, igual que en la maqueta. */
function Cupo({ usados, cupo }: { usados: number; cupo: number }) {
  const pct = cupo > 0 ? Math.round((usados / cupo) * 100) : 0;
  const tono = pct >= 100 ? "lleno" : pct >= 85 ? "aviso" : "normal";
  return (
    <div>
      <div className="fc-sa-cupo__cifra">
        {usados} / {cupo > 0 ? cupo : "—"}
      </div>
      <div
        className="fc-sa-cupo__carril"
        role="img"
        aria-label={cupo > 0 ? `${pct}% del cupo del mes` : "sin cupo asignado"}
      >
        <div
          className="fc-sa-cupo__lleno"
          data-tono={tono}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
    </div>
  );
}

function Ficha({
  cliente,
  operador,
  onVolver,
  onImpersonar,
}: {
  cliente: ClienteInterno;
  operador: Operador;
  onVolver: () => void;
  onImpersonar: (s: SesionImpersonacion) => void;
}) {
  const [motivo, setMotivo] = useState("");
  const [ficha, setFicha] = useState<FichaCliente | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accion, setAccion] = useState<"impersonar" | "suspender" | "editar" | null>(null);
  const [motivoAccion, setMotivoAccion] = useState("");
  const [trabajando, setTrabajando] = useState(false);
  const [datosEdicion, setDatosEdicion] = useState({
    razon_social: "",
    nombre_comercial: "",
    email: "",
    telefono: "",
  });

  async function abrir() {
    setError(null);
    try {
      setFicha(await sa.ficha(cliente.id, motivo.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos abrir la ficha");
    }
  }

  async function confirmar() {
    setTrabajando(true);
    setError(null);
    try {
      if (accion === "impersonar") {
        const s = await sa.impersonar(cliente.id, motivoAccion.trim());
        // El token de impersonación reemplaza al del operador mientras dure
        sesion.guardar(s.token, sesion.refresh ?? "");
        onImpersonar(s);
      } else if (accion === "suspender") {
        await sa.cambiarEstado(cliente.id, "SUSPENDIDO", motivoAccion.trim());
        onVolver();
      } else if (accion === "editar") {
        await sa.editarCliente(cliente.id, {
          razon_social: datosEdicion.razon_social.trim(),
          nombre_comercial: datosEdicion.nombre_comercial.trim() || null,
          email: datosEdicion.email.trim(),
          telefono: datosEdicion.telefono.trim() || null,
          motivo: motivoAccion.trim(),
        });
        setFicha(await sa.ficha(cliente.id, motivo.trim()));
      }
      setAccion(null);
      setMotivoAccion("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos completar la acción");
    } finally {
      setTrabajando(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <button
        type="button"
        className="fc-btn fc-btn--texto"
        style={{ justifySelf: "start" }}
        onClick={onVolver}
      >
        ← Volver a clientes
      </button>

      {!ficha && (
        <section className="fc-tarjeta">
          <p className="fc-kicker">Abrir la ficha de {cliente.razon_social}</p>
          <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--texto-suave)" }}>
            Ver la ficha es acceder a los datos de un contribuyente. Escribe por qué la necesitas:
            queda en la auditoría junto a tu nombre.
          </p>
          <label className="fc-label" htmlFor="motivo-ficha" style={{ marginTop: 14 }}>
            Motivo
          </label>
          <input
            id="motivo-ficha"
            className="fc-campo"
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            placeholder="Ej.: reclamo por cobro duplicado del mes de agosto"
          />
          {error && (
            <p className="fc-error" role="alert">
              {error}
            </p>
          )}
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            style={{ marginTop: 14 }}
            disabled={motivo.trim().length < 3}
            onClick={() => void abrir()}
          >
            Abrir ficha
          </button>
        </section>
      )}

      {ficha && (
        <>
          <section className="fc-tarjeta">
            <p className="fc-kicker">Ficha del cliente</p>
            <h2 className="fc-titulo" style={{ fontSize: 22, marginBottom: 4 }}>
              {ficha.razon_social}
            </h2>
            <p className="fc-mono" style={{ color: "var(--texto-tenue)", margin: "0 0 18px" }}>
              RUC {ficha.ruc} · {ficha.email}
            </p>
            <div className="fc-kpi">
              <Dato etiqueta="Plan" valor={ficha.plan.nombre ?? "sin plan"} />
              <Dato etiqueta="Precio" valor={ficha.plan.precio ? dinero(ficha.plan.precio) : "—"} />
              <Dato
                etiqueta="Comprobantes del mes"
                valor={String(ficha.consumo.comprobantes_mes)}
              />
              <Dato etiqueta="Ambiente SRI" valor={ficha.ambiente_sri} />
            </div>
            <div style={{ marginTop: 16 }}>
              <Dato
                etiqueta="Firma electrónica"
                valor={
                  ficha.certificado.subject
                    ? `Vence el ${fechaCorta(ficha.certificado.vence?.slice(0, 10) ?? "")}`
                    : "Sin certificado cargado"
                }
              />
            </div>
          </section>

          {operador.puede_actuar && (
            <section className="fc-tarjeta">
              <p className="fc-kicker">Acciones de soporte</p>
              <p style={{ fontSize: 13, color: "var(--texto-tenue)", margin: "6px 0 14px" }}>
                Todas quedan registradas en auditoría con tu nombre y tu motivo.
              </p>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="fc-btn fc-btn--contorno"
                  onClick={() => {
                    setDatosEdicion({
                      razon_social: ficha.razon_social,
                      nombre_comercial: ficha.nombre_comercial ?? "",
                      email: ficha.email,
                      telefono: ficha.telefono ?? "",
                    });
                    setAccion("editar");
                  }}
                >
                  Editar datos
                </button>
                <button
                  type="button"
                  className="fc-btn fc-btn--contorno"
                  onClick={() => setAccion("impersonar")}
                >
                  Entrar como este cliente
                </button>
                <button
                  type="button"
                  className="fc-btn fc-btn--contorno"
                  onClick={() => setAccion("suspender")}
                >
                  Suspender cuenta
                </button>
              </div>

              {accion && (
                <div
                  style={{
                    marginTop: 18,
                    padding: "16px 18px",
                    background: "var(--superficie-suave)",
                    border: "1px solid var(--borde-campo)",
                    borderRadius: "var(--radio-panel)",
                  }}
                >
                  <p style={{ fontSize: 13.5, fontWeight: 600, margin: "0 0 4px" }}>
                    {accion === "impersonar"
                      ? `Vas a entrar en la cuenta de ${ficha.razon_social}`
                      : accion === "suspender"
                        ? `Vas a suspender a ${ficha.razon_social}`
                        : `Vas a editar los datos de ${ficha.razon_social}`}
                  </p>
                  <p style={{ fontSize: 13, color: "var(--texto-suave)", margin: "0 0 12px" }}>
                    {accion === "impersonar"
                      ? "Verás su panel como si fueras el cliente, y cada acción quedará registrada a tu nombre. La sesión dura 30 minutos."
                      : accion === "suspender"
                        ? "El cliente dejará de poder emitir hasta que lo reactives."
                        : "Corrige razón social, nombre comercial, correo o teléfono. El RUC no se puede cambiar."}
                  </p>

                  {accion === "editar" && (
                    <div style={{ display: "grid", gap: 12, marginBottom: 14 }}>
                      <div>
                        <label className="fc-label" htmlFor="ed-razon-social">
                          Razón social
                        </label>
                        <input
                          id="ed-razon-social"
                          className="fc-campo"
                          value={datosEdicion.razon_social}
                          onChange={(e) =>
                            setDatosEdicion((d) => ({ ...d, razon_social: e.target.value }))
                          }
                        />
                      </div>
                      <div>
                        <label className="fc-label" htmlFor="ed-nombre-comercial">
                          Nombre comercial
                        </label>
                        <input
                          id="ed-nombre-comercial"
                          className="fc-campo"
                          value={datosEdicion.nombre_comercial}
                          onChange={(e) =>
                            setDatosEdicion((d) => ({ ...d, nombre_comercial: e.target.value }))
                          }
                        />
                      </div>
                      <div>
                        <label className="fc-label" htmlFor="ed-email">
                          Correo
                        </label>
                        <input
                          id="ed-email"
                          type="email"
                          className="fc-campo"
                          value={datosEdicion.email}
                          onChange={(e) => setDatosEdicion((d) => ({ ...d, email: e.target.value }))}
                        />
                      </div>
                      <div>
                        <label className="fc-label" htmlFor="ed-telefono">
                          Teléfono
                        </label>
                        <input
                          id="ed-telefono"
                          className="fc-campo"
                          value={datosEdicion.telefono}
                          onChange={(e) =>
                            setDatosEdicion((d) => ({ ...d, telefono: e.target.value }))
                          }
                        />
                      </div>
                    </div>
                  )}

                  <label className="fc-label" htmlFor="motivo-accion">
                    Motivo ({accion === "editar" ? "mínimo 5" : "mínimo 10"} caracteres)
                  </label>
                  <input
                    id="motivo-accion"
                    className="fc-campo"
                    value={motivoAccion}
                    onChange={(e) => setMotivoAccion(e.target.value)}
                  />
                  {error && (
                    <p className="fc-error" role="alert">
                      {error}
                    </p>
                  )}
                  <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
                    <button
                      type="button"
                      className="fc-btn fc-btn--contorno"
                      onClick={() => {
                        setAccion(null);
                        setError(null);
                      }}
                    >
                      Cancelar
                    </button>
                    <button
                      type="button"
                      className="fc-btn fc-btn--primario"
                      disabled={
                        trabajando ||
                        motivoAccion.trim().length < (accion === "editar" ? 5 : 10) ||
                        (accion === "editar" &&
                          (datosEdicion.razon_social.trim().length < 2 ||
                            !datosEdicion.email.trim()))
                      }
                      onClick={() => void confirmar()}
                    >
                      {trabajando ? "Registrando…" : "Confirmar"}
                    </button>
                  </div>
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}

function Dato({ etiqueta, valor }: { etiqueta: string; valor: string }) {
  return (
    <div>
      <div className="fc-kicker" style={{ marginBottom: 5 }}>
        {etiqueta}
      </div>
      <div style={{ fontSize: 14.5, fontWeight: 600 }}>{valor}</div>
    </div>
  );
}
