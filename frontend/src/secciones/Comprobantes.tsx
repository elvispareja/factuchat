/** Comprobantes: historial con filtros por tipo y bandeja de retenciones
 *  recibidas (maqueta líneas 366-526). La bandeja depende de la bandera
 *  `archivos` del plan; sin ella se muestra el muro.
 *
 *  Desde aquí se crea también un comprobante nuevo (modal en NuevaFactura). */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/cliente";
import type { Comprobante as TComprobante } from "../api/tipos";
import { usePlan } from "../plan/PlanContexto";
import { MuroPlan } from "../plan/Bloqueos";
import { Retenciones } from "./Retenciones";
import { CrearComprobante } from "./NuevaFactura";
import { ETIQUETA_ID, dinero, tonoEstado } from "../util/formato";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";

export type Filtro = "todos" | "factura" | "credito" | "debito" | "retencion";

const FILTROS: Array<{ id: Filtro; label: string; tipos: string[] }> = [
  { id: "todos", label: "Todos", tipos: [] },
  { id: "factura", label: "Facturas", tipos: ["FACTURA"] },
  { id: "credito", label: "Notas de crédito", tipos: ["NOTA_CREDITO"] },
  { id: "debito", label: "Notas de débito", tipos: ["NOTA_DEBITO"] },
  { id: "retencion", label: "Retenciones", tipos: ["RETENCION"] },
];

interface Props {
  onVerPlanes: () => void;
  /** Filtro pedido desde la barra lateral (al tocar un ítem del submenú). */
  filtroExterno?: Filtro;
  /** Avisa a la barra lateral qué filtro quedó activo, para resaltarlo ahí. */
  onFiltro?: (f: Filtro) => void;
  /** Avisa a la barra lateral cuántos hay por filtro, para el conteo del
   *  submenú (maqueta: "Todos 9", "Facturas 6", …). */
  onConteos?: (c: Record<string, number>) => void;
}

export function Comprobantes({ onVerPlanes, filtroExterno, onFiltro, onConteos }: Props) {
  const { permite } = usePlan();
  const [filtro, setFiltroInterno] = useState<Filtro>(filtroExterno ?? "todos");
  const [busqueda, setBusqueda] = useState("");
  const [creando, setCreando] = useState(false);
  /** Píldora flotante para lo que no debe tumbar la tabla (una descarga que
   *  falla, por ejemplo): el error de sección se reserva para el listado. */
  const [aviso, setAviso] = useState<string | null>(null);

  // La barra lateral es la fuente de verdad cuando manda un filtro nuevo
  useEffect(() => {
    if (filtroExterno && filtroExterno !== filtro) setFiltroInterno(filtroExterno);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroExterno]);

  function setFiltro(f: Filtro) {
    setFiltroInterno(f);
    onFiltro?.(f);
  }
  const [docs, setDocs] = useState<TComprobante[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = () =>
    api
      .get<TComprobante[]>("/comprobantes")
      .then((docs) => {
        setDocs(docs);
        // Se recarga tras cada emisión: sin limpiar, un fallo de red suelto
        // dejaba la sección entera sustituida por el cartel de error, con la
        // factura recién emitida invisible hasta cambiar de sección y volver.
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visibles = useMemo(() => {
    if (!docs) return [];
    const cfg = FILTROS.find((f) => f.id === filtro)!;
    const texto = busqueda.trim().toLowerCase();
    return docs.filter((d) => {
      if (cfg.tipos.length && !cfg.tipos.includes(d.tipo)) return false;
      if (!texto) return true;
      // Cliente, número o monto, que es lo que promete el marcador de posición
      // (el detalle y la clave van de propina: no estorban y a veces salvan).
      return [d.numero, d.clave_acceso, d.cliente, d.cliente_identificacion, d.detalle, d.total]
        .some((campo) => (campo ?? "").toLowerCase().includes(texto));
    });
  }, [docs, filtro, busqueda]);

  const cuentaPorFiltro = useMemo(() => {
    const cuenta: Record<string, number> = {};
    for (const f of FILTROS) {
      cuenta[f.id] = f.tipos.length
        ? (docs ?? []).filter((d) => f.tipos.includes(d.tipo)).length
        : (docs ?? []).length;
    }
    return cuenta;
  }, [docs]);

  useEffect(() => {
    onConteos?.(cuentaPorFiltro);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cuentaPorFiltro]);

  const cabecera = (
    <>
      <BarraFiltros
        filtro={filtro}
        onFiltro={setFiltro}
        cuentas={cuentaPorFiltro}
        total={docs?.length ?? 0}
        onCrear={() => setCreando(true)}
      />
      {creando && (
        <CrearComprobante onCerrar={() => setCreando(false)} onRecargar={cargar} />
      )}
    </>
  );

  // La bandeja de retenciones recibidas exige la bandera `archivos` del plan
  if (filtro === "retencion" && !permite("archivos")) {
    return (
      <div style={{ display: "grid", gap: 18 }}>
        {cabecera}
        {/* Texto literal de la maqueta (Dashboard.dc.html, líneas 456-458) */}
        <MuroPlan
          titulo="El resumen de retenciones viene con un plan superior"
          texto="Tus retenciones recibidas siguen sumándose. Al activar el plan que incluye este resumen, verás aquí el crédito acumulado y podrás descargar cada archivo."
          textoBoton="Ver los planes"
          onVerPlanes={onVerPlanes}
        />
      </div>
    );
  }

  // Con el filtro de retenciones, la tabla genérica se APAGA y se sustituye por
  // su panel propio: son documentos recibidos, no emitidos, y no comparten ni
  // columnas ni estados con el resto del historial.
  if (filtro === "retencion") {
    return (
      <div style={{ display: "grid", gap: 18 }}>
        {cabecera}
        <Retenciones />
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 18 }}>
      {cabecera}
      <FranjaArchivo />

      {error && <ErrorSeccion mensaje={error} />}
      {!error && !docs && <Cargando />}
      {docs && (
        <section className="fc-tarjeta fc-tarjeta--tabla">
          <div
            style={{
              display: "flex",
              gap: 12,
              alignItems: "center",
              flexWrap: "wrap",
              padding: "16px 18px",
              borderBottom: "1px solid var(--borde)",
            }}
          >
            {/* Ancho, no un campo pequeño arrinconado: es la herramienta
                principal de esta pantalla. La lupa va dentro, sobre el campo. */}
            <label style={{ flex: 1, minWidth: 220, position: "relative" }}>
              <span className="fc-label" style={{ position: "absolute", left: -9999 }}>
                Buscar comprobante
              </span>
              <span
                aria-hidden="true"
                style={{
                  position: "absolute",
                  left: 14,
                  top: "50%",
                  transform: "translateY(-50%)",
                  display: "grid",
                  color: "var(--texto-tenue)",
                  pointerEvents: "none",
                }}
              >
                <Icono d={ICONO_LUPA} tamano={15} />
              </span>
              <input
                className="fc-campo"
                type="search"
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
                placeholder="Buscar por cliente, número o monto"
                style={{ paddingLeft: 38 }}
              />
            </label>
            <span
              style={{ fontSize: 12.5, color: "var(--texto-tenue)", whiteSpace: "nowrap" }}
            >
              {visibles.length} de {docs.length}{" "}
              {docs.length === 1 ? "comprobante" : "comprobantes"}
            </span>
          </div>

          {visibles.length === 0 ? (
            <Vacio
              titulo={
                busqueda
                  ? "Sin resultados para esa búsqueda."
                  : "Todavía no has emitido comprobantes de este tipo."
              }
              ayuda={
                busqueda
                  ? "Prueba con el nombre del cliente o el número del comprobante."
                  : "Cuando emitas el primero aparecerá aquí con su estado del SRI."
              }
            />
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="fc-tabla">
                <thead>
                  <tr>
                    <th scope="col">Número</th>
                    <th scope="col">Cliente</th>
                    <th scope="col">Detalle</th>
                    <th scope="col" className="fc-num">Total</th>
                    <th scope="col">Estado SRI</th>
                    <th scope="col">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {visibles.map((d) => {
                    const tono = tonoEstado(d.estado);
                    return (
                      <tr key={d.id}>
                        <td className="fc-mono">{d.numero ?? "Borrador"}</td>
                        <td>
                          {/* `cliente` en null NO es un dato que falta: es una
                              venta hecha a consumidor final. */}
                          <span style={{ fontWeight: 600, fontSize: 13.5 }}>
                            {d.cliente ?? "Consumidor final"}
                          </span>
                          <span
                            style={{
                              display: "block",
                              fontSize: 11.5,
                              color: "var(--texto-tenue)",
                              marginTop: 1,
                            }}
                          >
                            {d.cliente_identificacion
                              ? `${ETIQUETA_ID[d.cliente_tipo_id ?? ""] ?? d.cliente_tipo_id ?? ""} ${d.cliente_identificacion}`.trim()
                              : "Sin identificación"}
                          </span>
                        </td>
                        <td style={{ color: "var(--texto-tenue)", fontSize: 12.5, maxWidth: "32ch" }}>
                          {d.detalle ?? "—"}
                        </td>
                        <td className="fc-num" style={{ fontWeight: 600 }}>
                          {dinero(d.total)}
                        </td>
                        <td>
                          <span className={`fc-estado ${tono.clase}`}>
                            <span className="fc-estado__punto" />
                            {tono.label}
                          </span>
                          {d.mensajes.length > 0 && (
                            <div
                              style={{
                                fontSize: 12,
                                color: "var(--error-texto)",
                                marginTop: 6,
                                maxWidth: "38ch",
                              }}
                            >
                              {d.mensajes[0]}
                            </div>
                          )}
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                            {/* El servidor tiene integración de WhatsApp, pero
                                NO una ruta para mandar un comprobante ya
                                emitido (solo el webhook del asistente). El
                                botón se pinta como en la maqueta y se dice por
                                qué no se puede pulsar, en vez de llamar a una
                                ruta inventada que devolvería 404. */}
                            <button
                              type="button"
                              className="fc-btn-icono"
                              disabled
                              title="Enviar por WhatsApp todavía no está disponible: el servidor aún no tiene esa ruta."
                              aria-label="Enviar por WhatsApp (no disponible)"
                              style={{ opacity: 0.45, cursor: "not-allowed" }}
                            >
                              <Icono d={ICONO_WHATSAPP} />
                            </button>
                            {d.estado === "AUTORIZADO" && (
                              <>
                                <BotonDescarga
                                  id={d.id}
                                  archivo="ride"
                                  nombre={`${d.numero ?? d.id}.pdf`}
                                  titulo="Descargar el RIDE en PDF"
                                  icono={ICONO_DESCARGA}
                                  onFallo={setAviso}
                                />
                                <BotonDescarga
                                  id={d.id}
                                  archivo="xml"
                                  nombre={`${d.numero ?? d.id}.xml`}
                                  titulo="Descargar el XML autorizado"
                                  icono={ICONO_XML}
                                  onFallo={setAviso}
                                />
                              </>
                            )}
                            {(d.estado === "DEVUELTO" || d.estado === "RECHAZADO") && (
                              <BotonReintentar id={d.id} onListo={setDocs} onFallo={setAviso} />
                            )}
                            {/* Borrador que nunca llegó al SRI: se crea la
                                factura y luego se envía, y si lo segundo falla
                                queda PENDIENTE sin número. Sin este botón no
                                había forma de rescatarlo desde ninguna pantalla
                                y la única salida era rehacerlo, duplicándolo. */}
                            {d.estado === "PENDIENTE" && d.numero === null && (
                              <BotonEnviar id={d.id} onListo={setDocs} onFallo={setAviso} />
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {aviso && (
        <button
          type="button"
          className="fc-toast"
          data-tono="error"
          aria-live="assertive"
          onClick={() => setAviso(null)}
          title="Descartar"
        >
          {aviso}
        </button>
      )}
    </div>
  );
}

/* --- Iconos ---------------------------------------------------------------- */

const ICONO_WHATSAPP =
  "M20.5 11.6a8.5 8.5 0 01-12.7 7.4L3 20.5l1.6-4.7A8.5 8.5 0 1120.5 11.6z M9.3 9.4c.3-.6 1.4-.5 1.7 0l.6 1.2-.8.9c.4.9 1 1.5 1.9 1.9l.9-.8 1.2.6c.5.3.6 1.4 0 1.7-1.4.7-3.4-.2-4.6-1.4s-2.1-3.2-1.4-4.6z";
const ICONO_DESCARGA = "M12 3v12M7 11l5 5 5-5M4 20h16";
const ICONO_XML = "m9 8-5 4 5 4M15 8l5 4-5 4";
const ICONO_CAJA = "M3 8h18v12H3zM3 8l2-4h14l2 4M12 4v4M9 13h6";
const ICONO_LUPA = "M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.35-4.35";

function Icono({ d, tamano = 14 }: { d: string; tamano?: number }) {
  return (
    <svg
      width={tamano}
      height={tamano}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  );
}

/* --- Piezas de la sección --------------------------------------------------- */

/** Franja de la maqueta: los siete años que exige el SRI. «Descargar todo» se
 *  pinta pero no se puede pulsar — no hay ruta de exportación masiva en el
 *  servidor, y un botón que devuelve 404 miente peor que uno apagado. */
function FranjaArchivo() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        flexWrap: "wrap",
        background: "var(--superficie)",
        border: "1px solid var(--borde)",
        borderRadius: "var(--radio-tarjeta)",
        padding: "16px 20px",
      }}
    >
      {/* Icono sobre pastilla verde, como el resto de avisos del panel: sin
          fondo se perdía contra el blanco de la tarjeta. */}
      <span
        aria-hidden="true"
        style={{
          display: "grid",
          placeItems: "center",
          width: 34,
          height: 34,
          flexShrink: 0,
          borderRadius: 11,
          background: "rgba(34,197,94,.12)",
          color: "var(--verde-medio)",
        }}
      >
        <Icono d={ICONO_CAJA} tamano={17} />
      </span>
      <span
        style={{
          flex: 1,
          minWidth: 220,
          fontSize: 13.5,
          lineHeight: 1.55,
          color: "var(--texto-suave)",
          textWrap: "pretty",
        }}
      >
        Guardamos tus comprobantes por siete años, como exige la normativa. Puedes descargarlos
        todos en un archivo cuando quieras.
      </span>
      <button
        type="button"
        className="fc-btn fc-btn--contorno"
        disabled
        title="La descarga de todo el archivo todavía no está disponible."
      >
        Descargar todo
      </button>
    </div>
  );
}

function BarraFiltros({
  filtro,
  onFiltro,
  cuentas,
  total,
  onCrear,
}: {
  filtro: Filtro;
  onFiltro: (f: Filtro) => void;
  cuentas: Record<string, number>;
  total: number;
  onCrear: () => void;
}) {
  return (
    <section className="fc-tarjeta">
      <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <p className="fc-kicker">Tu historial</p>
          <p className="fc-cifra" style={{ fontSize: 24, margin: 0 }}>
            {total} {total === 1 ? "comprobante" : "comprobantes"}
          </p>
        </div>
        <button type="button" className="fc-btn fc-btn--primario" onClick={onCrear}>
          + Crear comprobante
        </button>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 18 }}>
        {FILTROS.map((f) => (
          <button
            key={f.id}
            type="button"
            className="fc-chip"
            aria-pressed={filtro === f.id}
            onClick={() => onFiltro(f.id)}
          >
            {f.label}
            {cuentas[f.id] > 0 && <span className="fc-chip__contador">{cuentas[f.id]}</span>}
          </button>
        ))}
      </div>
    </section>
  );
}

/** Descarga del RIDE/XML.
 *
 *  No vale un `<a href="/api/v1/…">`: el navegador no adjunta el token y el
 *  servidor exige Authorization, así que el enlace acababa en 401 y bajando un
 *  archivo vacío. `api.descargar` hace la petición con la sesión (y renueva el
 *  token si toca) y entrega el blob. */
function BotonDescarga({
  id,
  archivo,
  nombre,
  titulo,
  icono,
  onFallo,
}: {
  id: string;
  archivo: "ride" | "xml";
  nombre: string;
  titulo: string;
  icono: string;
  onFallo: (mensaje: string) => void;
}) {
  const [bajando, setBajando] = useState(false);
  return (
    <button
      type="button"
      className="fc-btn-icono"
      disabled={bajando}
      title={titulo}
      aria-label={titulo}
      style={bajando ? { opacity: 0.45, cursor: "progress" } : undefined}
      onClick={async () => {
        setBajando(true);
        try {
          await api.descargar(`/comprobantes/${id}/${archivo}`, nombre);
        } catch (e) {
          onFallo(e instanceof Error ? e.message : "No pudimos descargar el archivo");
        } finally {
          setBajando(false);
        }
      }}
    >
      <Icono d={icono} />
    </button>
  );
}

/** Manda al SRI un borrador que se quedó a medias.
 *
 *  Emitir son dos pasos —crear la factura y enviarla—, así que un fallo en el
 *  segundo deja la factura creada pero sin número. Es la misma llamada que hace
 *  el modal al pulsar «Revisar y enviar al SRI»: el servidor solo la acepta
 *  sobre un borrador PENDIENTE sin clave de acceso, que es justo este caso. */
function BotonEnviar({
  id,
  onListo,
  onFallo,
}: {
  id: string;
  onListo: (docs: TComprobante[]) => void;
  onFallo: (mensaje: string) => void;
}) {
  const [enviando, setEnviando] = useState(false);
  return (
    <button
      type="button"
      className="fc-btn fc-btn--contorno"
      style={{ padding: "6px 14px", fontSize: 12.5 }}
      disabled={enviando}
      title="Este borrador no llegó a enviarse al SRI"
      onClick={async () => {
        setEnviando(true);
        try {
          await api.post(`/comprobantes/${id}/emitir`, {});
          onListo(await api.get<TComprobante[]>("/comprobantes"));
        } catch (e) {
          onFallo(e instanceof Error ? e.message : "No pudimos enviarlo al SRI");
        } finally {
          setEnviando(false);
        }
      }}
    >
      {enviando ? "Enviando…" : "Enviar al SRI"}
    </button>
  );
}

function BotonReintentar({
  id,
  onListo,
  onFallo,
}: {
  id: string;
  onListo: (docs: TComprobante[]) => void;
  onFallo: (mensaje: string) => void;
}) {
  const [enviando, setEnviando] = useState(false);
  return (
    <button
      type="button"
      className="fc-btn fc-btn--contorno"
      style={{ padding: "6px 14px", fontSize: 12.5 }}
      disabled={enviando}
      onClick={async () => {
        setEnviando(true);
        try {
          await api.post(`/comprobantes/${id}/reintentar`);
          onListo(await api.get<TComprobante[]>("/comprobantes"));
        } catch (e) {
          // Sin esto el botón volvía a «Reintentar» como si nada: un 403 por
          // firma caducada no se veía en ninguna parte.
          onFallo(e instanceof Error ? e.message : "No pudimos reintentar el envío");
        } finally {
          setEnviando(false);
        }
      }}
    >
      {enviando ? "Reintentando…" : "Reintentar"}
    </button>
  );
}
