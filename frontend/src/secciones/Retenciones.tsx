/** Retenciones recibidas: sección propia, fuera de Comprobantes.
 *
 * El inquilino NUNCA emite una retención: solo la recibe. Por eso la columna es
 * «Empresa que retuvo» y no «Cliente», y por eso esto no vive dentro del
 * historial de lo emitido.
 *
 * EL PERÍODO ES EL AÑO. El contribuyente piensa en «lo que me retuvieron este
 * año», que además es el período en que se usa el crédito de renta. El
 * desplegable ofrece los años con datos, y el servidor recalcula saldo, conteo
 * y lista juntos: las tres cifras hablan siempre del mismo período.
 *
 * DOS PUERTAS PARA REGISTRAR, las dos en el MISMO formulario (`PanelRetencion`).
 * Se abre desde el botón de esta sección y desde la tarjeta «Retención
 * recibida» del selector de Comprobantes, que es donde la gente la busca cuando
 * le entregan el papel. Con el XML se lee todo del comprobante y se le pregunta
 * al SRI; sin XML se teclea, y entonces no hay clave de acceso a la que
 * preguntar: la fila SUMA —el papel lo tiene el cliente en la mano y esconderlo
 * le haría declarar de más— pero queda MARCADA como sin respaldo.
 */

import {
  type CSSProperties,
  Fragment,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { ErrorApi, api } from "../api/cliente";
import { usePlan } from "../plan/PlanContexto";
import { MuroPlan } from "../plan/Bloqueos";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";
import { dinero, fechaCorta, hoyEnEcuador } from "../util/formato";
import { cent, num } from "../util/totales";

interface LineaRetencion {
  codigo?: string;
  porcentaje?: string;
  base?: string;
  valor?: string;
  doc_sustento?: string;
}

export interface RetencionFila {
  id: string;
  quien: string;
  ruc: string | null;
  numero: string;
  fecha: string | null;
  concepto: string | null;
  renta: string;
  iva: string;
  origen: string;
  verificada: boolean;
  /** Si el SRI YA contestó. Con `verificada: false` distingue «todavía no se ha
   *  preguntado» de «contestó que no», que es un final y no una espera. */
  respondido: boolean;
  verificacion: string | null;
  base: string;
  retenido: string;
  /** La factura TUYA sobre la que te retuvieron. */
  factura: string | null;
  porcentaje_renta: string | null;
  porcentaje_iva: string | null;
  /** Si suma al crédito, y si lo hace sin confirmación del SRI. */
  cuenta: boolean;
  sin_respaldo: boolean;
  tiene_xml: boolean;
  tiene_pdf: boolean;
  lineas: LineaRetencion[];
}

interface Bandeja {
  activo: boolean;
  buzon: string | null;
  anio: number;
  anios: number[];
  periodo: { desde: string; hasta: string };
  saldo: string;
  saldo_renta: string;
  saldo_iva: string;
  sin_respaldo: string;
  documentos: number;
  agentes: number;
  retenciones: RetencionFila[];
}

/* --- Iconos --------------------------------------------------------------- */

const ICONO_CALENDARIO =
  "M7 3v3M17 3v3M3.5 9h17M4 5.5h16a1 1 0 011 1V20a1 1 0 01-1 1H4a1 1 0 01-1-1V6.5a1 1 0 011-1z";
const ICONO_LUPA = "M11 18a7 7 0 100-14 7 7 0 000 14zM20 20l-4-4";
const ICONO_SUBIR = "M12 16V4M7 9l5-5 5 5M4 20h16";
const ICONO_SOBRE = "M3.5 6.5h17v11h-17zM3.5 6.5l8.5 6.5 8.5-6.5";
const ICONO_CHAT = "M20.5 12a8 8 0 11-3.4-6.5M21 4.5l-8 8";
const ICONO_INFO = "M12 21a9 9 0 100-18 9 9 0 000 18zM12 8.2v.1M11.4 12h.6v4h.6";
const ICONO_CERRAR = "M5 5l14 14M19 5L5 19";
const ICONO_CHEVRON = "M6 9l6 6 6-6";

function Svg({
  d,
  tamano = 16,
  color = "currentColor",
  grosor = 1.9,
}: {
  d: string;
  tamano?: number;
  color?: string;
  grosor?: number;
}) {
  return (
    <svg
      width={tamano}
      height={tamano}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={grosor}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <path d={d} />
    </svg>
  );
}

/** De dónde salió cada fila. Es la columna de icono de la maqueta: dice si la
 *  retención llegó sola o la metió el propio contribuyente. */
const ORIGEN: Record<string, { icono: string; titulo: string }> = {
  BUZON: { icono: ICONO_SOBRE, titulo: "Llegó por correo al buzón" },
  MANUAL: { icono: ICONO_SUBIR, titulo: "La registraste tú" },
  WHATSAPP: { icono: ICONO_CHAT, titulo: "La mandaste por WhatsApp" },
};

/** Los cuatro estados de una fila. `verificada: false` vale para TRES cosas
 *  distintas —tecleada sin clave, esperando respuesta y rechazada— y pintarlas
 *  igual dejaba un documento muerto diciendo «comprobando» para siempre.
 *
 *  La confirmada devuelve `null`: es el caso normal y en la maqueta la fila va
 *  limpia. Lo que hay que señalar es justo lo que NO está confirmado. */
function estadoDe(r: RetencionFila): { clase: string; texto: string } | null {
  if (r.sin_respaldo)
    return { clase: "fc-estado--neutro", texto: "Registrada a mano · suma, sin XML" };
  if (r.verificada) return null;
  if (r.respondido) return { clase: "fc-estado--error", texto: "El SRI no la reconoce · no suma" };
  return { clase: "fc-estado--aviso", texto: "Comprobando con el SRI · todavía no suma" };
}

export function Retenciones({ onVerPlanes }: { onVerPlanes: () => void }) {
  const { permite } = usePlan();
  const [datos, setDatos] = useState<Bandeja | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** `null` hasta que el usuario elige: la primera carga la decide el servidor
   *  (el año en curso en hora de Guayaquil, que no es la del navegador). */
  const [anio, setAnio] = useState<number | null>(null);
  const [busqueda, setBusqueda] = useState("");
  const [registrando, setRegistrando] = useState(false);
  const [detalle, setDetalle] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  /** La última petición disparada. Guardar una retención recarga la bandeja SIN
   *  vaciar la pantalla, así que el desplegable de año sigue vivo mientras esa
   *  recarga viaja: si se cambia el año y la primera respuesta llega la última,
   *  pintaría la lista del año anterior debajo de un selector que dice otro. */
  const peticion = useRef(0);
  const puede = permite("archivos");

  const cargar = () => {
    const mia = ++peticion.current;
    // Sin esto un fallo se queda pegado: la pantalla entera se sustituye por el
    // error, y con ella el botón que volvería a intentarlo.
    setError(null);
    return api
      .get<Bandeja>(`/retenciones${anio ? `?anio=${anio}` : ""}`)
      .then((d) => {
        if (mia === peticion.current) setDatos(d);
      })
      .catch((e) => {
        if (mia === peticion.current) setError(e instanceof Error ? e.message : "Error");
      });
  };

  useEffect(() => {
    // Sin la función del plan el servidor contesta 402: no se le pregunta.
    if (puede) void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anio, puede]);

  // El toast se va solo: es un acuse, no un estado de la pantalla.
  useEffect(() => {
    if (!aviso) return;
    const t = window.setTimeout(() => setAviso(null), 6000);
    return () => window.clearTimeout(t);
  }, [aviso]);

  const filas = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    if (!q || !datos) return datos?.retenciones ?? [];
    return datos.retenciones.filter((r) =>
      [r.quien, r.ruc, r.numero, r.factura, r.concepto]
        .filter(Boolean)
        .some((c) => String(c).toLowerCase().includes(q)),
    );
  }, [datos, busqueda]);

  // El muro va DESPUÉS de los hooks, nunca antes: sacarlo arriba cambiaría el
  // número de hooks que corren entre un render y el siguiente.
  if (!puede) {
    return (
      /* Texto literal de la maqueta (Dashboard.dc.html, líneas 456-458) */
      <MuroPlan
        titulo="El resumen de retenciones viene con un plan superior"
        texto="Tus retenciones recibidas siguen sumándose. Al activar el plan que incluye este resumen, verás aquí el crédito acumulado y podrás descargar cada archivo."
        textoBoton="Ver los planes"
        onVerPlanes={onVerPlanes}
      />
    );
  }

  if (error) return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  if (!datos) return <Cargando />;

  const enEspera = datos.retenciones.filter((r) => !r.cuenta).length;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      {/* La bajada de la maqueta. Va aquí y no en la cabecera del panel porque
          es de ESTA sección: dice en una frase qué es una retención recibida,
          que es justo lo que no sabe quien entra por primera vez. */}
      <p
        style={{
          margin: "-4px 0 2px",
          maxWidth: "78ch",
          fontSize: 14,
          lineHeight: 1.6,
          color: "var(--texto-suave)",
          textWrap: "pretty",
        }}
      >
        Lo que tus clientes retuvieron y entregaron al SRI a tu nombre. Ya está descontado de tus
        impuestos por pagar.
      </p>

      <div className="fc-kpi fc-kpi--tres">
        <section className="fc-tarjeta--oscura" style={{ padding: "20px 22px" }}>
          <div className="fc-halo" />
          <div style={{ position: "relative", zIndex: 1 }}>
            <p className="fc-kicker" style={{ color: "var(--verde-claro)", margin: 0 }}>
              Total retenido este año
            </p>
            <div
              className="fc-cifra"
              style={{ fontSize: 30, margin: "8px 0 6px", color: "var(--texto-sobre-oscuro)" }}
            >
              {dinero(datos.saldo)}
            </div>
            <p style={{ fontSize: 12.5, color: "#A6BFB2", margin: 0, lineHeight: 1.5 }}>
              {datos.documentos === 1 ? "1 documento" : `${datos.documentos} documentos`} de{" "}
              {datos.agentes === 1 ? "1 empresa" : `${datos.agentes} empresas`} en {datos.anio}.
            </p>
            {/* Lo tecleado a mano suma, y se dice cuánto: en una revisión hay
                que saber qué parte del crédito la defiende el XML y cuál el
                papel que el cliente tiene guardado. */}
            {num(datos.sin_respaldo) > 0 && (
              <p style={{ fontSize: 11.5, color: "#E8C766", margin: "8px 0 0", lineHeight: 1.5 }}>
                {dinero(datos.sin_respaldo)} son de retenciones que registraste a mano, sin XML.
              </p>
            )}
            {enEspera > 0 && (
              <p style={{ fontSize: 11.5, color: "#E8C766", margin: "6px 0 0", lineHeight: 1.5 }}>
                {enEspera === 1
                  ? "1 comprobante todavía no suma."
                  : `${enEspera} comprobantes todavía no suman.`}
              </p>
            )}
          </div>
        </section>

        <TarjetaCifra
          titulo="Retención de renta"
          cifra={datos.saldo_renta}
          pie="Acumulada, se descuenta en tu renta anual."
        />
        {/* Renta e IVA son impuestos distintos: sumarlos y restarlos juntos de
            uno solo daría un número que el SRI no acepta. */}
        <TarjetaCifra
          titulo="Retención de IVA"
          cifra={datos.saldo_iva}
          pie="Acumulada, baja tu IVA mensual a pagar."
        />
      </div>

      <section
        className="fc-tarjeta"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
          padding: "14px 16px",
        }}
      >
        <SelectorAnio
          anio={datos.anio}
          anios={datos.anios}
          onCambio={(a) => {
            setDatos(null);
            setDetalle(null);
            setAnio(a);
          }}
        />

        <div style={{ position: "relative", flex: 1, minWidth: 220, maxWidth: 520 }}>
          {/* Lo mismo que el calendario: sin esto, pulsar la lupa no enfoca el
              buscador. */}
          <span
            aria-hidden="true"
            style={{
              position: "absolute",
              left: 13,
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--texto-tenue)",
              display: "grid",
              pointerEvents: "none",
            }}
          >
            <Svg d={ICONO_LUPA} tamano={15} />
          </span>
          <input
            className="fc-campo"
            style={{ paddingLeft: 36 }}
            type="search"
            value={busqueda}
            placeholder="Buscar por empresa, RUC o número de documento"
            aria-label="Buscar en tus retenciones"
            onChange={(e) => setBusqueda(e.target.value)}
          />
        </div>

        <div style={{ display: "flex", gap: 10, marginLeft: "auto", flexWrap: "wrap" }}>
          <button
            type="button"
            className="fc-btn fc-btn--contorno"
            disabled
            title="La descarga de todo el archivo todavía no está disponible."
          >
            Descargar todo
          </button>
          {/* `.fc-btn--primario` y no un verde en línea: `.fc-btn` a secas no
              trae fondo ni `:hover` —cada variante pone el suyo—, así que el
              botón principal de la sección era el único del panel que no
              respondía al pasar por encima. */}
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
            onClick={() => setRegistrando(true)}
          >
            <Svg d={ICONO_SUBIR} tamano={14} grosor={2.1} />
            Subir una retención
          </button>
        </div>
      </section>

      <section className="fc-tarjeta fc-tarjeta--tabla">
        {filas.length === 0 ? (
          <Vacio
            titulo={
              busqueda.trim()
                ? "Ninguna retención coincide con lo que buscas."
                : `No guardaste ninguna retención en ${datos.anio}.`
            }
            ayuda={
              busqueda.trim()
                ? "Prueba con el RUC de la empresa o con el número del comprobante."
                : "Cuando una empresa te retenga, sube aquí el XML que te manda —o escríbela a mano si solo tienes el papel— y aparecerá en esta lista."
            }
          />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="fc-tabla" style={{ minWidth: 1000 }}>
              <thead>
                <tr>
                  {/* Dos rótulos en una sola columna, como la maqueta: debajo
                      del día va el botón que abre el desglose. */}
                  <th scope="col">
                    Emisión
                    <span style={{ display: "block", marginTop: 4 }}>Detalle</span>
                  </th>
                  <th scope="col">
                    <span title="De dónde salió cada retención">Origen</span>
                  </th>
                  <th scope="col">Empresa que retuvo</th>
                  <th scope="col">Factura relacionada</th>
                  <th scope="col" className="fc-num">
                    Base imponible
                  </th>
                  <th scope="col">Renta · IVA</th>
                  <th scope="col" className="fc-num">
                    Valor retenido
                  </th>
                </tr>
              </thead>
              <tbody>
                {filas.map((r) => {
                  const estado = estadoDe(r);
                  const abierta = detalle === r.id;
                  const origen = ORIGEN[r.origen] ?? ORIGEN.MANUAL;
                  return (
                    <Fragment key={r.id}>
                      <tr>
                        <td style={{ whiteSpace: "nowrap" }}>
                          <div style={{ fontSize: 13 }}>{r.fecha ? fechaCorta(r.fecha) : "—"}</div>
                          <button
                            type="button"
                            className="fc-btn fc-btn--contorno"
                            style={{ marginTop: 8, padding: "5px 13px", fontSize: 12 }}
                            aria-expanded={abierta}
                            onClick={() => setDetalle(abierta ? null : r.id)}
                          >
                            {abierta ? "Ocultar" : "Ver detalle"}
                          </button>
                        </td>
                        <td>
                          <span
                            title={origen.titulo}
                            aria-label={origen.titulo}
                            role="img"
                            style={{
                              display: "grid",
                              placeItems: "center",
                              width: 30,
                              height: 30,
                              borderRadius: 9,
                              border: "1px solid var(--borde)",
                              color: "var(--texto-tenue)",
                            }}
                          >
                            <Svg d={origen.icono} tamano={14} />
                          </span>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{r.quien}</div>
                          <div
                            className="fc-mono"
                            style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}
                          >
                            {r.ruc ?? "sin RUC"} · {r.numero}
                          </div>
                          {/* Solo lo que NO está confirmado lleva marca: la fila
                              normal es la de la maqueta, limpia. */}
                          {estado && (
                            <div
                              className={`fc-estado ${estado.clase}`}
                              style={{ marginTop: 6, fontSize: 11 }}
                              title={r.verificacion ?? undefined}
                            >
                              <span className="fc-estado__punto" />
                              {estado.texto}
                            </div>
                          )}
                        </td>
                        <td className="fc-mono" style={{ fontSize: 12.5 }}>
                          {r.factura ?? "—"}
                        </td>
                        <td className="fc-num" style={{ fontSize: 13.5 }}>
                          {dinero(r.base)}
                        </td>
                        <td style={{ fontSize: 13, whiteSpace: "nowrap" }}>
                          {r.porcentaje_renta ? `${r.porcentaje_renta}%` : "—"} ·{" "}
                          {r.porcentaje_iva ? `${r.porcentaje_iva}%` : "—"}
                        </td>
                        <td
                          className="fc-num"
                          style={{ fontWeight: 700, color: "var(--verde-medio)" }}
                        >
                          {dinero(r.retenido)}
                        </td>
                      </tr>
                      {abierta && (
                        <tr>
                          <td colSpan={7} style={{ background: "var(--superficie-tenue)" }}>
                            <Detalle fila={r} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {registrando && (
        <ModalRetencion
          anio={datos.anio}
          onCerrar={() => setRegistrando(false)}
          onGuardada={async (fila, mensaje) => {
            setRegistrando(false);
            setAviso(mensaje);
            setDetalle(fila.id);
            // Saldo, conteo y lista salen de la misma consulta: recargarla es lo
            // único que mantiene las tres cifras hablando del mismo período.
            await cargar();
          }}
        />
      )}

      {aviso && (
        /* El modal se cierra al guardar y el foco cae al body: este aviso es la
           ÚNICA señal de que la retención entró, y lleva además la advertencia
           de «es de otro año». Sin región viva, quien usa lector de pantalla no
           se entera de ninguna de las dos. */
        <button
          type="button"
          className="fc-toast"
          aria-live="polite"
          title="Descartar"
          onClick={() => setAviso(null)}
        >
          {aviso}
        </button>
      )}
    </div>
  );
}

function TarjetaCifra({ titulo, cifra, pie }: { titulo: string; cifra: string; pie: string }) {
  return (
    <section className="fc-tarjeta" style={{ padding: "20px 22px" }}>
      <p className="fc-kicker" style={{ margin: 0 }}>
        {titulo}
      </p>
      <div className="fc-cifra" style={{ fontSize: 30, margin: "8px 0 6px" }}>
        {dinero(cifra)}
      </div>
      <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0, lineHeight: 1.5 }}>
        {pie}
      </p>
    </section>
  );
}

/** El desplegable de año con forma de píldora, como la maqueta. El `<select>`
 *  es el de verdad —teclado y lector de pantalla salen gratis—; lo que se pinta
 *  encima es el icono y la flecha, con la del navegador apagada. */
function SelectorAnio({
  anio,
  anios,
  onCambio,
}: {
  anio: number;
  anios: number[];
  onCambio: (a: number) => void;
}) {
  return (
    <div style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
      {/* Sin `pointerEvents: none` el icono se come el clic: pulsar el
          calendario —que es justo donde se pincha— no desplegaba el año. */}
      <span
        aria-hidden="true"
        style={{
          position: "absolute",
          left: 13,
          color: "var(--texto-tenue)",
          display: "grid",
          pointerEvents: "none",
        }}
      >
        <Svg d={ICONO_CALENDARIO} tamano={14} />
      </span>
      <select
        className="fc-campo"
        aria-label="Año de las retenciones"
        value={anio}
        onChange={(e) => onCambio(Number(e.target.value))}
        style={{
          appearance: "none",
          WebkitAppearance: "none",
          MozAppearance: "none",
          width: "auto",
          paddingLeft: 36,
          paddingRight: 34,
          borderRadius: "var(--radio-pildora)",
          fontWeight: 600,
          fontSize: 13.5,
          cursor: "pointer",
        }}
      >
        {anios.map((a) => (
          <option key={a} value={a}>
            Año {a}
          </option>
        ))}
      </select>
      <span
        aria-hidden="true"
        style={{
          position: "absolute",
          right: 13,
          color: "var(--texto-tenue)",
          display: "grid",
          pointerEvents: "none",
        }}
      >
        <Svg d={ICONO_CHEVRON} tamano={13} grosor={2.1} />
      </span>
    </div>
  );
}

/* --- Detalle de una fila -------------------------------------------------- */

function Detalle({ fila }: { fila: RetencionFila }) {
  const [bajando, setBajando] = useState(false);
  const [fallo, setFallo] = useState<string | null>(null);

  /** La descarga puede fallar de verdad: el servidor devuelve 503 si la clave
   *  de cifrado cambió o el fichero no está. Sin capturarlo, el botón parpadea
   *  y no pasa nada más —ni archivo ni motivo—, y la promesa queda sin atender. */
  async function bajar() {
    setBajando(true);
    setFallo(null);
    try {
      await api.descargar(`/retenciones/${fila.id}/xml`, `retencion-${fila.numero}.xml`);
    } catch (e) {
      setFallo(e instanceof Error ? e.message : "No pudimos bajar el archivo");
    } finally {
      setBajando(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: 12, padding: "4px 0 8px" }}>
      <div style={{ display: "flex", gap: 26, flexWrap: "wrap", fontSize: 13 }}>
        <Dato titulo="Concepto" valor={fila.concepto ?? "—"} />
        <Dato titulo="Cómo entró" valor={(ORIGEN[fila.origen] ?? ORIGEN.MANUAL).titulo} />
        <Dato titulo="Retención de renta" valor={dinero(fila.renta)} />
        <Dato titulo="Retención de IVA" valor={dinero(fila.iva)} />
        <Dato titulo="Total retenido" valor={dinero(fila.retenido)} />
      </div>

      {/* El motivo del rechazo, escrito. En el `title` de la fila no existe en
          un móvil, y es justo lo que hay que leer para saber que toca pedirle
          el comprobante bueno a quien retuvo. */}
      {fila.verificacion && (
        <p
          style={{
            margin: 0,
            fontSize: 12.5,
            lineHeight: 1.55,
            color: "var(--texto-tenue)",
            textWrap: "pretty",
          }}
        >
          {fila.verificacion}
        </p>
      )}

      {fila.sin_respaldo && (
        <p
          style={{
            margin: 0,
            fontSize: 12.5,
            lineHeight: 1.55,
            color: "var(--texto-tenue)",
            textWrap: "pretty",
          }}
        >
          La escribiste a mano, sin el XML, así que no hay clave de acceso con la que preguntarle al
          SRI. Suma a tu crédito igual: guarda el comprobante en papel por si te lo piden.
        </p>
      )}

      {fila.lineas.length > 0 && (
        <div style={{ fontSize: 12.5, color: "var(--texto-suave)" }}>
          {fila.lineas.map((l, i) => (
            <div key={i} style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <span style={{ minWidth: 74 }}>{l.codigo === "2" ? "IVA" : "Renta"}</span>
              <span className="fc-mono">{l.porcentaje ? `${l.porcentaje}%` : "—"}</span>
              <span className="fc-mono">sobre {dinero(l.base ?? "0")}</span>
              <span className="fc-mono">= {dinero(l.valor ?? "0")}</span>
            </div>
          ))}
        </div>
      )}

      <div>
        {fila.tiene_xml ? (
          <button
            type="button"
            className="fc-btn fc-btn--contorno"
            style={{ padding: "6px 14px", fontSize: 12.5 }}
            disabled={bajando}
            onClick={() => void bajar()}
          >
            {bajando ? "Bajando…" : "Descargar el XML"}
          </button>
        ) : (
          /* No es un fallo: el servidor solo custodia el fichero cuando hay
             clave de cifrado configurada, y la tecleada a mano nunca tuvo uno.
             Lo que sostiene el crédito son los datos, así que se dice en vez de
             dejar un hueco mudo. */
          <span style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>
            De esta retención guardamos los datos, no el archivo.
          </span>
        )}
        {fallo && (
          <p className="fc-error" role="alert" style={{ marginTop: 8, fontSize: 12.5 }}>
            {fallo}
          </p>
        )}
      </div>
    </div>
  );
}

function Dato({ titulo, valor }: { titulo: string; valor: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--texto-tenue)" }}>{titulo}</div>
      <div style={{ fontWeight: 600, color: "var(--texto)" }}>{valor}</div>
    </div>
  );
}

/* --- Registrar una retención ------------------------------------------------
   `POST /retenciones` acepta las dos puertas: multipart con `archivo` (el XML,
   que el servidor lee y consulta al SRI) o los campos tecleados.

   Ni la extensión ni el tamaño del XML se comprueban aquí. El servidor lee el
   fichero acotado a 4 MB y es su parser quien dice si eso es una retención y de
   quién: adelantarse mirando el nombre del archivo solo añadiría una segunda
   opinión que puede contradecir a la que manda. */

/** Qué hacer con cada rechazo. El QUÉ PASÓ ya lo cuenta el servidor con su
 *  propia frase; esto es el QUÉ HAGO AHORA, y va por código de estado y no por
 *  el texto: leer el mensaje para decidir se rompe en cuanto alguien le cambie
 *  una coma. */
const QUE_HACER: Record<number, string> = {
  402: "Entra en Retenciones recibidas desde el menú: ahí se ve qué plan la incluye.",
  409: "No hace falta registrarla otra vez: ya la tienes en la lista, con su crédito.",
  422:
    "Si subes un archivo, tiene que ser el XML del comprobante de retención, tal cual te lo mandó" +
    " tu cliente y a tu nombre. Si prefieres escribirla, revisa que los valores no estén en cero.",
};

/** El formulario dentro de su propia capa de modal. Lo usa esta sección; el
 *  selector de Comprobantes monta `PanelRetencion` dentro de la capa que ya
 *  tiene abierta. */
function ModalRetencion({
  anio,
  onCerrar,
  onGuardada,
}: {
  anio: number;
  onCerrar: () => void;
  onGuardada: (fila: RetencionFila, mensaje: string) => Promise<void> | void;
}) {
  return createPortal(
    /* Sin cierre por clic en el fondo. Lo tenía, pero desde aquí no se ve si
       hay una subida en vuelo, y cerrar a media subida dejaba la respuesta del
       servidor —incluido el motivo del rechazo— cayendo sobre un componente ya
       desmontado: ni se veía el fallo ni aparecía la fila. La tecla Escape sí
       mira `guardando`, y desde Comprobantes esta puerta tampoco cierra así. */
    <div className="fc-modal" role="presentation">
      <PanelRetencion anio={anio} onCerrar={onCerrar} onGuardada={onGuardada} />
    </div>,
    document.body,
  );
}

/** El formulario de «Registrar retención recibida», sin la capa del modal.
 *
 *  Vive suelto para que el selector de Comprobantes abra EXACTAMENTE el mismo:
 *  allí el pie lleva «‹ Otro documento» en vez de «Cancelar», que es la única
 *  diferencia entre las dos entradas.
 */
export function PanelRetencion({
  anio,
  onCerrar,
  onGuardada,
  onVolver,
  onVerTodas,
}: {
  /** El año que la lista enseña: lo de fuera se guarda igual, pero no aparece
   *  ahí, y hay que decirlo en vez de dejar que parezca que se perdió. Desde el
   *  selector de Comprobantes no hay lista detrás, y no se avisa de nada. */
  anio?: number;
  onCerrar: () => void;
  onGuardada: (fila: RetencionFila, mensaje: string) => Promise<void> | void;
  /** Si viene, el pie ofrece volver al selector de documentos en vez de
   *  cancelar: es la entrada desde Comprobantes. */
  onVolver?: () => void;
  /** Desde Comprobantes no hay lista detrás, así que tras guardar se ofrece ir
   *  a verla. Desde la propia sección sobra: ya está a la vista. */
  onVerTodas?: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastrando, setArrastrando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queHacer, setQueHacer] = useState<string | null>(null);
  const [listo, setListo] = useState<string | null>(null);

  const [quien, setQuien] = useState("");
  const [ruc, setRuc] = useState("");
  const [numero, setNumero] = useState("");
  // Sin fecha la fila no cae en NINGÚN año: la bandeja filtra por
  // `fecha_emision` entre dos días, así que una retención sin ella se guardaría
  // y no se volvería a ver. Se pide, y viene puesta la de hoy.
  const [fecha, setFecha] = useState(hoyEnEcuador);
  const [base, setBase] = useState("");
  const [factura, setFactura] = useState("");
  const [renta, setRenta] = useState("");
  const [iva, setIva] = useState("");

  useEffect(() => {
    panel.current?.focus();
  }, []);

  // Cerrar a media subida deja la respuesta —incluido el motivo del rechazo—
  // cayendo sobre un componente desmontado: ni se ve el fallo ni aparece la
  // fila. El pie ya está bloqueado mientras sube; la tecla Escape no lo estaba.
  useEffect(() => {
    function alPulsar(e: KeyboardEvent) {
      if (e.key === "Escape" && !guardando) onCerrar();
    }
    document.addEventListener("keydown", alPulsar);
    return () => document.removeEventListener("keydown", alPulsar);
  }, [onCerrar, guardando]);

  // En centavos: sumar dos decimales con coma flotante deja 0.30000000000000004
  // en la cifra que el cliente compara con su papel.
  const credito = (cent(num(renta)) + cent(num(iva))) / 100;
  // El RUC entra en la lista de obligatorios: sin XML no hay clave de acceso,
  // así que la fila se distingue de otra por (número, RUC de quien retuvo). Sin
  // él, el «001-001-000000123» de un cliente choca con el de otro y al segundo
  // se le dice que ya la tiene.
  const puedeGuardar =
    quien.trim().length >= 2 &&
    ruc.trim().length === 13 &&
    numero.trim().length >= 3 &&
    fecha !== "" &&
    credito > 0 &&
    !guardando;

  /** El aviso de «esto no sale en la lista» cuando la retención es de otro año.
   *  Las fechas son ISO, así que basta el prefijo: `new Date` en Ecuador cambia
   *  el día. */
  const mensajeDe = (fila: RetencionFila) => {
    const cabeza = `Guardada la ${fila.numero}${fila.quien ? ` de ${fila.quien}` : ""}.`;
    if (anio !== undefined && fila.fecha && !fila.fecha.startsWith(String(anio))) {
      return `${cabeza} Es de ${fila.fecha.slice(0, 4)}: cámbiale el año a la lista para verla.`;
    }
    return `${cabeza} Ya está en tus retenciones.`;
  };

  async function enviar(archivo: File | null) {
    if (guardando) return;
    setGuardando(true);
    setError(null);
    setQueHacer(null);
    setListo(null);
    try {
      // Los campos vacíos NO se mandan: el servidor los tipa (fecha, decimales)
      // y una cadena vacía es un 422, no un «no lo sé».
      const campos: Record<string, string> = {};
      if (!archivo) {
        campos.quien = quien.trim();
        campos.numero = numero.trim();
        campos.ruc = ruc.trim();
        campos.fecha = fecha;
        if (factura.trim()) campos.factura = factura.trim();
        if (base.trim()) campos.base = String(num(base));
        if (renta.trim()) campos.renta = String(num(renta));
        if (iva.trim()) campos.iva = String(num(iva));
      }
      const fila = await api.subir<RetencionFila>("/retenciones", archivo, campos);
      const mensaje = mensajeDe(fila);
      setListo(mensaje);
      // Se vacía. Desde Comprobantes el modal NO se cierra al guardar, y con los
      // campos puestos el botón seguía activo: el segundo clic borraba el acuse
      // —con su único enlace a la lista— para contestar «ya la tienes». Vacío
      // queda además listo para la siguiente, que ahí es lo normal.
      setQuien("");
      setRuc("");
      setNumero("");
      setFecha(hoyEnEcuador());
      setBase("");
      setFactura("");
      setRenta("");
      setIva("");
      await onGuardada(fila, mensaje);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos registrar la retención");
      setQueHacer(e instanceof ErrorApi ? (QUE_HACER[e.status] ?? null) : null);
    } finally {
      setGuardando(false);
      // Sin esto, volver a elegir EL MISMO fichero no dispara `change` y el
      // reintento no hace nada: el navegador compara con el valor anterior.
      if (entrada.current) entrada.current.value = "";
    }
  }

  return (
    <div
      ref={panel}
      className="fc-modal__panel fc-modal__panel--fijo"
      role="dialog"
      aria-modal="true"
      aria-label="Registrar retención recibida"
      tabIndex={-1}
      style={{ maxWidth: 620 }}
    >
      <div
        className="fc-modal__cabecera"
        style={{ alignItems: "flex-start", padding: "28px 32px 0" }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 className="fc-modal__titulo" style={{ fontSize: 20 }}>
            Registrar retención recibida
          </h2>
          <p style={{ fontSize: 13, color: "var(--texto-tenue)", margin: "5px 0 0" }}>
            Guarda el comprobante que te entregó tu cliente.
          </p>
        </div>
        <button
          type="button"
          className="fc-btn-icono"
          aria-label="Cerrar"
          disabled={guardando}
          onClick={onCerrar}
        >
          <Svg d={ICONO_CERRAR} tamano={14} grosor={2.4} />
        </button>
      </div>

      <div className="fc-modal__cuerpo" style={{ padding: "24px 32px 24px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 11,
            background: "rgba(34,197,94,.06)",
            border: "1px solid rgba(22,121,74,.2)",
            borderRadius: 14,
            padding: "14px 16px",
            marginBottom: 22,
          }}
        >
          <span style={{ marginTop: 1, color: "var(--verde-medio)", display: "grid" }}>
            <Svg d={ICONO_INFO} tamano={16} grosor={2} />
          </span>
          <div style={{ fontSize: 12.5, lineHeight: 1.55, color: "#255C46", textWrap: "pretty" }}>
            Tú no emites retenciones: las recibes, y su valor se descuenta de lo que declaras. Lo
            más rápido es subir el XML y dejar que el asistente lo lea.
          </div>
        </div>

        {/* Mismo molde que la firma .p12 y la imagen del catálogo: `.fc-dropzone`
            y su `data-arrastrando`. El teclado sí es de aquí: el `<input
            type=file>` va oculto, así que sin esto la zona solo se usa con
            ratón. */}
        <label
          className="fc-dropzone"
          role="button"
          tabIndex={guardando ? -1 : 0}
          aria-busy={guardando}
          data-arrastrando={arrastrando ? "true" : "false"}
          style={{ marginBottom: 18, ...(guardando ? { cursor: "progress", opacity: 0.6 } : null) }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              entrada.current?.click();
            }
          }}
          onDragOver={(e) => {
            // Sin preventDefault el navegador se lleva el archivo a otra
            // pestaña en vez de dejarlo soltar aquí.
            e.preventDefault();
            setArrastrando(true);
          }}
          onDragLeave={() => setArrastrando(false)}
          onDrop={(e) => {
            e.preventDefault();
            setArrastrando(false);
            const archivo = e.dataTransfer.files?.[0];
            if (archivo) void enviar(archivo);
          }}
        >
          <Svg d={ICONO_SUBIR} tamano={17} color="var(--verde-medio)" />
          <span style={{ fontSize: 13.5, fontWeight: 600, color: "var(--verde-marca)" }}>
            {guardando ? "Comprobando…" : "Subir el XML de la retención"}
          </span>
          {!guardando && (
            <span style={{ fontSize: 12, color: "#8A9A91" }}>
              Arrástralo o haz clic. Lo leemos, lo consultamos al SRI y lo sumamos solo.
            </span>
          )}
          <input
            ref={entrada}
            type="file"
            accept=".xml,text/xml,application/xml"
            disabled={guardando}
            onChange={(e) => {
              const archivo = e.target.files?.[0];
              if (archivo) void enviar(archivo);
            }}
          />
        </label>

        {/* El puente entre las dos puertas. Estaba metido en el aviso verde y lo
            estiraba al doble de líneas; aquí además está donde se elige. */}
        <p
          style={{
            margin: "-8px 0 20px",
            fontSize: 12,
            lineHeight: 1.55,
            color: "var(--texto-tenue)",
            textWrap: "pretty",
          }}
        >
          Si solo tienes el papel, escríbela abajo: suma igual, pero queda marcada como «sin XML».
        </p>

        <Rejilla columnas="1.5fr 1fr">
          <Campo
            id="ret-quien"
            etiqueta="Quién te retuvo"
            valor={quien}
            onCambio={setQuien}
            placeholder="Nombre o razón social"
            deshabilitado={guardando}
          />
          <Campo
            id="ret-ruc"
            etiqueta="Su RUC"
            valor={ruc}
            onCambio={(v) => setRuc(v.replace(/\D/g, "").slice(0, 13))}
            placeholder="13 dígitos"
            modo="numeric"
            deshabilitado={guardando}
          />
        </Rejilla>

        <Rejilla columnas="1.2fr 1fr 1fr">
          <Campo
            id="ret-numero"
            etiqueta="Número del comprobante"
            valor={numero}
            onCambio={setNumero}
            placeholder="001-001-000001234"
            deshabilitado={guardando}
          />
          <Campo
            id="ret-fecha"
            etiqueta="Fecha"
            valor={fecha}
            onCambio={setFecha}
            tipo="date"
            deshabilitado={guardando}
          />
          <Campo
            id="ret-base"
            etiqueta="Base imponible"
            valor={base}
            onCambio={setBase}
            tipo="number"
            paso="0.01"
            placeholder="0.00"
            deshabilitado={guardando}
          />
        </Rejilla>

        <Rejilla columnas="1fr">
          <Campo
            id="ret-factura"
            etiqueta="¿Sobre cuál de tus facturas te retuvieron?"
            valor={factura}
            onCambio={setFactura}
            placeholder="001-001-000001234"
            ayuda="Si la dejas vacía, la retención se guarda igual y queda sin factura vinculada."
            deshabilitado={guardando}
          />
        </Rejilla>

        <Rejilla columnas="1fr 1fr">
          <Campo
            id="ret-renta"
            etiqueta="Retención de renta"
            valor={renta}
            onCambio={setRenta}
            tipo="number"
            paso="0.01"
            placeholder="0.00"
            deshabilitado={guardando}
          />
          <Campo
            id="ret-iva"
            etiqueta="Retención de IVA"
            valor={iva}
            onCambio={setIva}
            tipo="number"
            paso="0.01"
            placeholder="0.00"
            deshabilitado={guardando}
          />
        </Rejilla>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            background: "var(--superficie-tenue)",
            border: "1px solid var(--borde)",
            borderRadius: 14,
            padding: "16px 18px",
            marginTop: 4,
          }}
        >
          <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--texto-suave)" }}>
            Crédito que suma a tu favor
          </span>
          <span className="fc-cifra" style={{ fontSize: 19, color: "var(--verde-medio)" }}>
            {dinero(credito)}
          </span>
        </div>

        {/* Desde Comprobantes no hay lista detrás que recargar, así que el acuse
            se queda aquí: sin esto, guardar desde ahí no enseñaba nada. */}
        {listo && (
          <p
            role="status"
            style={{
              margin: "16px 0 0",
              padding: "12px 14px",
              borderRadius: "var(--radio-campo)",
              background: "var(--exito-bg)",
              border: "1px solid var(--exito-borde)",
              color: "var(--exito-texto)",
              fontSize: 13,
              lineHeight: 1.55,
              textWrap: "pretty",
            }}
          >
            {listo}
            {onVerTodas && (
              <button
                type="button"
                className="fc-btn fc-btn--texto"
                style={{ display: "block", marginTop: 4, padding: 0, fontSize: 12.5 }}
                onClick={onVerTodas}
              >
                Ver mis retenciones ›
              </button>
            )}
          </p>
        )}

        {error && (
          <p
            className="fc-error"
            role="alert"
            style={{ marginTop: 16, fontSize: 12.5, lineHeight: 1.55, textWrap: "pretty" }}
          >
            {error}
            {queHacer && <span style={{ display: "block", marginTop: 6 }}>{queHacer}</span>}
          </p>
        )}
      </div>

      {/* El cuerpo desplaza por dentro y el pie se queda clavado: sin el borde
          el contenido pasaba por debajo sin nada que los separase. Es lo mismo
          que hacen los otros tres modales de tres partes del panel. */}
      <div
        className="fc-modal__pie"
        style={{ padding: "22px 32px 28px", borderTop: "1px solid var(--borde)" }}
      >
        {onVolver ? (
          <button
            type="button"
            className="fc-btn fc-btn--contorno"
            disabled={guardando}
            onClick={onVolver}
          >
            ‹ Otro documento
          </button>
        ) : (
          <button
            type="button"
            className="fc-btn fc-btn--texto"
            disabled={guardando}
            onClick={onCerrar}
          >
            Cancelar
          </button>
        )}
        <button
          type="button"
          className="fc-btn fc-btn--primario"
          disabled={!puedeGuardar}
          title={credito > 0 ? undefined : "Escribe cuánto te retuvieron de renta o de IVA."}
          onClick={() => void enviar(null)}
        >
          {guardando ? "Guardando…" : "Guardar retención"}
        </button>
      </div>
    </div>
  );
}

function Rejilla({ columnas, children }: { columnas: string; children: ReactNode }) {
  // El reparto va por variable CSS y no por `gridTemplateColumns` en línea: la
  // clase necesita poder apilarlo todo en un teléfono, y una consulta de medios
  // no se puede escribir en un estilo en línea.
  return (
    <div className="fc-rejilla" style={{ "--columnas": columnas } as CSSProperties}>
      {children}
    </div>
  );
}

function Campo({
  id,
  etiqueta,
  valor,
  onCambio,
  placeholder,
  tipo = "text",
  modo,
  paso,
  ayuda,
  deshabilitado,
}: {
  id: string;
  etiqueta: string;
  valor: string;
  onCambio: (v: string) => void;
  placeholder?: string;
  tipo?: string;
  modo?: "numeric";
  /** Salto de la flechita en un campo de dinero. Sin él vale 1, y corregir un
   *  dígito con el cursor encima convierte 8.40 en 9 sin avisar. */
  paso?: string;
  /** Línea bajo el campo, para lo que cambia si se deja vacío. */
  ayuda?: string;
  deshabilitado?: boolean;
}) {
  return (
    <div>
      <label className="fc-label" htmlFor={id}>
        {etiqueta}
      </label>
      <input
        id={id}
        className="fc-campo"
        type={tipo}
        inputMode={modo}
        step={paso}
        min={paso ? "0" : undefined}
        value={valor}
        placeholder={placeholder}
        disabled={deshabilitado}
        aria-describedby={ayuda ? `${id}-ayuda` : undefined}
        onChange={(e) => onCambio(e.target.value)}
      />
      {ayuda && (
        <p
          id={`${id}-ayuda`}
          style={{
            margin: "6px 0 0",
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--texto-tenue)",
            textWrap: "pretty",
          }}
        >
          {ayuda}
        </p>
      )}
    </div>
  );
}
