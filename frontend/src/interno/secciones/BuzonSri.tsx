/** Buzón SRI del panel interno (Superadmin.dc.html, líneas 898-948).
 *
 * Tres bloques verticales, como la maqueta: la banda del feature flag, la tabla
 * de correos recibidos —atenuada a opacidad .55 cuando el módulo está apagado,
 * no oculta— y la banda ámbar de los inquilinos que no reciben nada.
 *
 * El visor de "XML crudo" solo aparece en las filas con ERROR, y el contenido no
 * viene en el listado: se pide aparte y el servidor lo descifra, porque el
 * correo se guarda cifrado en reposo.
 */

import { useCallback, useEffect, useState } from "react";
import { sa, type Operador } from "../api";
import { Cargando, ErrorSeccion, Vacio } from "../../ui/Estados";

interface CorreoBuzon {
  id: string;
  recibido: string;
  inquilino: string;
  buzon: string | null;
  remitente: string | null;
  tipo: string;
  estado: string;
  es_error: boolean;
  motivo_error: string | null;
}

interface Callado {
  inquilino: string;
  dias: number;
  umbral: number;
}

interface RespuestaBuzon {
  activo: boolean;
  dominio: string;
  correos: CorreoBuzon[];
  callados: Callado[];
}

const TONO: Record<string, { bg: string; borde: string; color: string }> = {
  PROCESADO: { bg: "rgba(34,197,94,.1)", borde: "rgba(22,121,74,.28)", color: "#16794A" },
  ERROR: { bg: "rgba(168,53,44,.08)", borde: "rgba(168,53,44,.3)", color: "#A8352C" },
  DUPLICADO: { bg: "#FFF8E8", borde: "#F2E4C0", color: "#8A6410" },
  RECIBIDO: { bg: "var(--superficie-tenue)", borde: "var(--borde)", color: "var(--texto-tenue)" },
};

export function BuzonSri({ operador }: { operador: Operador }) {
  const [datos, setDatos] = useState<RespuestaBuzon | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [abierto, setAbierto] = useState<string | null>(null);
  const [xml, setXml] = useState<Record<string, string>>({});
  const [alternando, setAlternando] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setError(null);
    try {
      setDatos(await sa.buzon());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function alternar() {
    if (!datos) return;
    setAlternando(true);
    try {
      const r = await sa.alternarBuzon(!datos.activo);
      setAviso(r.mensaje);
      window.setTimeout(() => setAviso(null), 3200);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos cambiar el interruptor");
    } finally {
      setAlternando(false);
    }
  }

  async function verXml(id: string) {
    if (abierto === id) {
      setAbierto(null);
      return;
    }
    setAbierto(id);
    if (xml[id] !== undefined) return;
    try {
      const r = await sa.buzonCrudo(id);
      setXml((previo) => ({ ...previo, [id]: r.xml }));
    } catch (e) {
      setXml((previo) => ({
        ...previo,
        [id]: e instanceof Error ? `[${e.message}]` : "[No pudimos abrir el mensaje]",
      }));
    }
  }

  if (error && !datos) return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  if (!datos) return <Cargando />;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      {aviso && (
        <p role="status" className="fc-estado fc-estado--exito" style={{ justifySelf: "start" }}>
          <span className="fc-estado__punto" />
          {aviso}
        </p>
      )}

      {/* Banda del feature flag */}
      <section
        className="fc-tarjeta"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          flexWrap: "wrap",
          padding: "15px 18px",
          borderColor: datos.activo ? "rgba(22,121,74,.28)" : "var(--aviso-borde)",
        }}
      >
        <span
          className="fc-mono"
          style={{
            display: "inline-block",
            background: datos.activo ? "rgba(34,197,94,.1)" : "var(--aviso-bg)",
            border: `1px solid ${datos.activo ? "rgba(22,121,74,.28)" : "var(--aviso-borde)"}`,
            color: datos.activo ? "var(--exito-texto)" : "var(--aviso-texto)",
            borderRadius: "var(--radio-pildora)",
            padding: "5px 13px",
            fontSize: 11.5,
            fontWeight: 700,
          }}
        >
          BUZON_ACTIVO = {datos.activo ? "true" : "false"}
        </span>
        <div
          style={{
            flex: 1,
            minWidth: 240,
            fontSize: 13,
            lineHeight: 1.5,
            color: "var(--texto-suave)",
            textWrap: "pretty",
          }}
        >
          {datos.activo
            ? // La maqueta solo redactó el estado apagado; este es su complemento
              `El módulo está encendido: los inquilinos ven su bandeja de retenciones y su saldo, y los correos que llegan a ${datos.dominio} se suman a su crédito.`
            : "Estructura preparada. Mientras el flag esté apagado, los clientes no ven nada y los correos solo se registran para depurar."}
        </div>
        {operador.es_superadmin && (
          <button
            type="button"
            className="fc-btn fc-btn--oscuro"
            style={{ flexShrink: 0 }}
            disabled={alternando}
            onClick={() => void alternar()}
          >
            {datos.activo ? "Apagar el módulo" : "Encender el módulo"}
          </button>
        )}
      </section>

      {/* Tabla de correos */}
      <section
        className="fc-tarjeta fc-tarjeta--tabla"
        style={{ opacity: datos.activo ? 1 : 0.55, transition: "opacity .3s" }}
      >
        {datos.correos.length === 0 ? (
          <Vacio
            titulo="Todavía no ha llegado ningún correo."
            ayuda="Aquí caen los comprobantes que los proveedores reenvían al buzón de cada inquilino."
          />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <div style={{ minWidth: 920 }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "104px 1.2fr 1.2fr 150px 120px 120px",
                  gap: 12,
                  padding: "11px 18px",
                  background: "var(--superficie-suave)",
                  borderBottom: "1px solid var(--superficie-tab)",
                  fontSize: 10.5,
                  fontWeight: 700,
                  letterSpacing: ".07em",
                  textTransform: "uppercase",
                  color: "var(--texto-tenue)",
                }}
              >
                <div>Recibido</div>
                <div>Inquilino · buzón</div>
                <div>Remitente</div>
                <div>Contenido</div>
                <div>Parseo</div>
                <div />
              </div>

              {datos.correos.map((c) => {
                const tono = TONO[c.estado] ?? TONO.RECIBIDO;
                return (
                  <div key={c.id} style={{ borderBottom: "1px solid var(--superficie-tab)" }}>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "104px 1.2fr 1.2fr 150px 120px 120px",
                        gap: 12,
                        padding: "12px 18px",
                        alignItems: "center",
                      }}
                    >
                      <div
                        style={{ fontSize: 12, color: "var(--texto-tenue)", whiteSpace: "nowrap" }}
                      >
                        {momento(c.recibido)}
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, ...ELIPSIS }}>
                          {c.inquilino}
                        </div>
                        <div
                          className="fc-mono"
                          style={{ fontSize: 10.5, color: "#8A9A91", ...ELIPSIS }}
                        >
                          {c.buzon ?? "—"}
                        </div>
                      </div>
                      <div style={{ fontSize: 12, color: "var(--texto-tenue)", ...ELIPSIS }}>
                        {c.remitente ?? "—"}
                      </div>
                      <div
                        style={{
                          fontSize: 12.5,
                          color: "var(--texto-suave)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {c.tipo}
                      </div>
                      <div>
                        <span
                          style={{
                            display: "inline-block",
                            background: tono.bg,
                            border: `1px solid ${tono.borde}`,
                            color: tono.color,
                            borderRadius: "var(--radio-pildora)",
                            padding: "3px 10px",
                            fontSize: 10.5,
                            fontWeight: 700,
                          }}
                        >
                          {c.estado}
                        </span>
                      </div>
                      <div style={{ textAlign: "right" }}>
                        {c.es_error && (
                          <button
                            type="button"
                            onClick={() => void verXml(c.id)}
                            style={{
                              background: "none",
                              border: "1px solid rgba(168,53,44,.35)",
                              color: "#A8352C",
                              padding: "5px 12px",
                              borderRadius: "var(--radio-pildora)",
                              fontSize: 11,
                              fontWeight: 700,
                              cursor: "pointer",
                              whiteSpace: "nowrap",
                              font: "inherit",
                            }}
                          >
                            {abierto === c.id ? "Cerrar XML" : "Ver XML crudo"}
                          </button>
                        )}
                      </div>
                    </div>

                    {abierto === c.id && (
                      <div style={{ background: "#0C2318", padding: "13px 18px" }}>
                        <div
                          className="fc-mono"
                          style={{
                            fontSize: 11,
                            lineHeight: 1.7,
                            color: "#8FCCA9",
                            wordBreak: "break-all",
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          {xml[c.id] ?? "Descifrando el mensaje…"}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>

      {/* Banda ámbar: buzones callados */}
      {datos.callados.map((c) => (
        <section
          key={c.inquilino}
          className="fc-tarjeta"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "14px 18px",
            borderColor: "var(--aviso-borde)",
          }}
        >
          <span
            aria-hidden="true"
            style={{
              width: 9,
              height: 9,
              borderRadius: "50%",
              background: "var(--aviso-punto)",
              flexShrink: 0,
            }}
          />
          <div style={{ flex: 1, minWidth: 0, fontSize: 13 }}>
            <strong style={{ fontWeight: 700 }}>{c.inquilino}</strong> no recibe correos en su buzón
            desde su alta ({c.dias} días). Si llega a {c.umbral}, se le recuerda configurar el
            reenvío desde el SRI.
          </div>
        </section>
      ))}
    </div>
  );
}

const ELIPSIS = {
  whiteSpace: "nowrap" as const,
  overflow: "hidden" as const,
  textOverflow: "ellipsis" as const,
};

/** "Hoy 10:18" / "Ayer 18:40" / "12 ago 09:22", como la maqueta. */
function momento(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const hora = d.toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit", hour12: false });
  const hoy = new Date();
  const mismoDia = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (mismoDia(d, hoy)) return `Hoy ${hora}`;
  const ayer = new Date(hoy);
  ayer.setDate(ayer.getDate() - 1);
  if (mismoDia(d, ayer)) return `Ayer ${hora}`;
  return `${d.toLocaleDateString("es-EC", { day: "numeric", month: "short" })} ${hora}`;
}
