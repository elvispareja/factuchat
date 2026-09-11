/** Bandeja de retenciones recibidas.
 *
 * El inquilino NUNCA emite una retención: solo la recibe. Por eso la columna es
 * «Empresa que retuvo» y no «Cliente», y por eso esta pantalla vive dentro de
 * Comprobantes pero no comparte ni columnas ni estados con el historial de lo
 * emitido.
 *
 * EL PERÍODO ES EL AÑO. El contribuyente piensa en «lo que me retuvieron este
 * año», que además es el período en que se usa el crédito de renta. El
 * desplegable ofrece los años en los que hay algo, y el servidor recalcula
 * saldo, conteo y lista juntos: las tres cifras hablan siempre del mismo
 * período.
 *
 * DOS PUERTAS PARA REGISTRAR. Con el XML se lee todo del comprobante y se le
 * pregunta al SRI. Sin XML se teclea: entonces no hay clave de acceso a la que
 * preguntar, así que la fila SUMA —el papel lo tiene el cliente en la mano y
 * esconderlo le haría declarar de más— pero queda MARCADA como sin respaldo.
 *
 * El cargador no se esconde con `activo` en falso: el interruptor del buzón
 * apaga la automatización por correo, no el archivador del cliente.
 */

import { Fragment, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ErrorApi, api } from "../api/cliente";
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

interface RetencionFila {
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

/** Los cuatro estados de una fila. `verificada: false` vale para TRES cosas
 *  distintas —tecleada sin clave, esperando respuesta y rechazada— y pintarlas
 *  igual dejaba un documento muerto diciendo «comprobando» para siempre. */
function estadoDe(r: RetencionFila): { clase: string; texto: string } {
  if (r.sin_respaldo)
    return { clase: "fc-estado--neutro", texto: "Registrada a mano · suma, sin XML" };
  if (r.verificada) return { clase: "fc-estado--exito", texto: "Confirmada por el SRI" };
  if (r.respondido)
    return { clase: "fc-estado--error", texto: "El SRI no la reconoce · no suma" };
  return { clase: "fc-estado--aviso", texto: "Comprobando con el SRI · todavía no suma" };
}

export function Retenciones() {
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
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anio]);

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

  if (error) return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  if (!datos) return <Cargando />;

  const enEspera = datos.retenciones.filter((r) => !r.cuenta).length;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="fc-kpi">
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
              Crédito acumulado en {datos.anio}, listo para descontar.{" "}
              {datos.documentos === 1
                ? "1 comprobante"
                : `${datos.documentos} comprobantes`}{" "}
              de{" "}
              {datos.agentes === 1 ? "1 empresa" : `${datos.agentes} empresas distintas`}.
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

        <section className="fc-tarjeta" style={{ padding: "20px 22px" }}>
          <p className="fc-kicker" style={{ margin: 0 }}>
            Retención de renta
          </p>
          <div className="fc-cifra" style={{ fontSize: 30, margin: "8px 0 6px" }}>
            {dinero(datos.saldo_renta)}
          </div>
          <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0, lineHeight: 1.5 }}>
            Crédito para tu declaración anual de impuesto a la renta.
          </p>
        </section>

        <section className="fc-tarjeta" style={{ padding: "20px 22px" }}>
          <p className="fc-kicker" style={{ margin: 0 }}>
            Retención de IVA
          </p>
          <div className="fc-cifra" style={{ fontSize: 30, margin: "8px 0 6px" }}>
            {dinero(datos.saldo_iva)}
          </div>
          <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0, lineHeight: 1.5 }}>
            {/* Renta e IVA son impuestos distintos: sumarlos y restarlos juntos
                de un solo impuesto daría un número fiscalmente falso. */}
            Baja el IVA que declaras. No se mezcla con el de renta.
          </p>
        </section>
      </div>

      <section
        className="fc-tarjeta"
        style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}
      >
        <label className="fc-label" htmlFor="ret-anio" style={{ margin: 0 }}>
          Año
        </label>
        <select
          id="ret-anio"
          className="fc-campo"
          style={{ width: "auto", minWidth: 110 }}
          value={datos.anio}
          onChange={(e) => {
            setDatos(null);
            setDetalle(null);
            setAnio(Number(e.target.value));
          }}
        >
          {datos.anios.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        <input
          className="fc-campo"
          style={{ flex: 1, minWidth: 200, maxWidth: 360 }}
          type="search"
          value={busqueda}
          placeholder="Busca por empresa, RUC, número o factura"
          aria-label="Buscar en tus retenciones"
          onChange={(e) => setBusqueda(e.target.value)}
        />

        <div style={{ display: "flex", gap: 10, marginLeft: "auto", flexWrap: "wrap" }}>
          <button
            type="button"
            className="fc-btn fc-btn--contorno"
            disabled
            title="La descarga de todo el archivo todavía no está disponible."
          >
            Descargar todo
          </button>
          <button
            type="button"
            className="fc-btn fc-btn--oscuro"
            onClick={() => setRegistrando(true)}
          >
            Subir una retención
          </button>
        </div>
      </section>

      <section
        className="fc-tarjeta"
        style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}
      >
        <div
          style={{
            flex: 1,
            minWidth: 260,
            fontSize: 13.5,
            lineHeight: 1.55,
            color: "var(--texto-suave)",
            textWrap: "pretty",
          }}
        >
          Guardamos el XML de cada comprobante de retención, con su detalle de renta y de IVA, por
          siete años.
          {datos.buzon && (
            <>
              {" "}
              También puedes reenviarlos a{" "}
              <span className="fc-mono" style={{ fontSize: 12.5 }}>
                {datos.buzon}
              </span>{" "}
              y entran solos.
            </>
          )}
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
            <table className="fc-tabla" style={{ minWidth: 980 }}>
              <thead>
                <tr>
                  <th scope="col">Emisión</th>
                  <th scope="col">Empresa que retuvo</th>
                  <th scope="col">Factura relacionada</th>
                  <th scope="col" className="fc-num">
                    Base imponible
                  </th>
                  <th scope="col" className="fc-num">
                    Renta · IVA
                  </th>
                  <th scope="col" className="fc-num">
                    Valor retenido
                  </th>
                  <th scope="col" className="fc-num">
                    Detalle
                  </th>
                </tr>
              </thead>
              <tbody>
                {filas.map((r) => {
                  const estado = estadoDe(r);
                  const abierta = detalle === r.id;
                  return (
                    <Fragment key={r.id}>
                      <tr>
                        <td style={{ fontSize: 13, whiteSpace: "nowrap" }}>
                          {r.fecha ? fechaCorta(r.fecha) : "—"}
                        </td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{r.quien}</div>
                          <div
                            className="fc-mono"
                            style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}
                          >
                            {r.ruc ?? "sin RUC"} · {r.numero}
                          </div>
                          <div
                            className={`fc-estado ${estado.clase}`}
                            style={{ marginTop: 6, fontSize: 11 }}
                            title={r.verificacion ?? undefined}
                          >
                            <span className="fc-estado__punto" />
                            {estado.texto}
                          </div>
                        </td>
                        <td className="fc-mono" style={{ fontSize: 12.5 }}>
                          {r.factura ?? "—"}
                        </td>
                        <td className="fc-num">{dinero(r.base)}</td>
                        <td className="fc-num">
                          <div style={{ fontSize: 13 }}>
                            {r.porcentaje_renta ? `${r.porcentaje_renta}%` : "—"} ·{" "}
                            {r.porcentaje_iva ? `${r.porcentaje_iva}%` : "—"}
                          </div>
                          <div style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                            {dinero(r.renta)} · {dinero(r.iva)}
                          </div>
                        </td>
                        <td className="fc-num" style={{ fontWeight: 700 }}>
                          {dinero(r.retenido)}
                        </td>
                        <td className="fc-num">
                          <button
                            type="button"
                            className="fc-btn fc-btn--texto"
                            style={{ padding: "4px 0", fontSize: 12.5 }}
                            aria-expanded={abierta}
                            onClick={() => setDetalle(abierta ? null : r.id)}
                          >
                            {abierta ? "Ocultar" : "Ver detalle"}
                          </button>
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
        <RegistrarRetencion
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

/* --- Detalle de una fila ---------------------------------------------------- */

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
        <Dato titulo="Origen" valor={ORIGEN[fila.origen] ?? fila.origen} />
        <Dato titulo="Base imponible" valor={dinero(fila.base)} />
        <Dato titulo="Retención de renta" valor={dinero(fila.renta)} />
        <Dato titulo="Retención de IVA" valor={dinero(fila.iva)} />
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

const ORIGEN: Record<string, string> = {
  BUZON: "Llegó por correo",
  MANUAL: "La registraste tú",
  WHATSAPP: "La mandaste por WhatsApp",
};

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
  409: "No hace falta registrarla otra vez: ya la tienes en la lista, con su crédito.",
  422:
    "Si subes un archivo, tiene que ser el XML del comprobante de retención, tal cual te lo mandó" +
    " tu cliente y a tu nombre. Si prefieres escribirla, revisa que los valores no estén en cero.",
};

const ICONO_SUBIR = "M12 16V4M7 9l5-5 5 5M4 20h16";

function RegistrarRetencion({
  anio,
  onCerrar,
  onGuardada,
}: {
  /** El año que la lista enseña: lo de fuera se guarda igual, pero no aparece
   *  ahí, y hay que decirlo en vez de dejar que parezca que se perdió. */
  anio: number;
  onCerrar: () => void;
  onGuardada: (fila: RetencionFila, mensaje: string) => Promise<void> | void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastrando, setArrastrando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queHacer, setQueHacer] = useState<string | null>(null);

  const [quien, setQuien] = useState("");
  const [ruc, setRuc] = useState("");
  const [numero, setNumero] = useState("");
  // Sin fecha la fila no cae en NINGÚN año: la bandeja filtra por
  // `fecha_emision` entre dos días, así que una retención sin ella se
  // guardaría y no se volvería a ver. Se pide, y viene puesta la de hoy.
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
  // fila. «Cancelar» ya estaba bloqueado mientras sube; estas dos salidas no.
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
  // El RUC entra en la lista: sin XML no hay clave de acceso, así que la fila
  // se distingue de otra por (número, RUC de quien retuvo). Sin él, el
  // «001-001-000000123» de un cliente choca con el de otro y al segundo se le
  // dice que ya la tiene.
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
    const cabecera = `Guardada la ${fila.numero}${fila.quien ? ` de ${fila.quien}` : ""}.`;
    if (fila.fecha && !fila.fecha.startsWith(String(anio))) {
      return `${cabecera} Es de ${fila.fecha.slice(0, 4)}: cámbiale el año a la lista para verla.`;
    }
    return `${cabecera} Ya está en tu lista.`;
  };

  async function enviar(archivo: File | null) {
    if (guardando) return;
    setGuardando(true);
    setError(null);
    setQueHacer(null);
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
      await onGuardada(fila, mensajeDe(fila));
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

  return createPortal(
    <div
      className="fc-modal"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !guardando) onCerrar();
      }}
    >
      <div
        ref={panel}
        className="fc-modal__panel fc-modal__panel--fijo"
        role="dialog"
        aria-modal="true"
        aria-label="Registrar retención recibida"
        tabIndex={-1}
      >
        <div className="fc-modal__cabecera">
          <div>
            <p className="fc-kicker">Te retuvieron</p>
            <h2 className="fc-modal__titulo" style={{ fontSize: 19, margin: "2px 0 0" }}>
              Registrar retención recibida
            </h2>
          </div>
          <button type="button" className="fc-modal__cerrar" aria-label="Cerrar" onClick={onCerrar}>
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M5 5l14 14M19 5L5 19" />
            </svg>
          </button>
        </div>

        <div className="fc-modal__cuerpo" style={{ paddingTop: 16 }}>
          <p
            style={{
              fontSize: 13,
              lineHeight: 1.55,
              color: "var(--texto-suave)",
              margin: "0 0 16px",
              textWrap: "pretty",
            }}
          >
            Tú no emites retenciones: las recibes. Aquí guardas la que te entregó tu cliente, y su
            valor se descuenta de lo que declaras. Lo más rápido es subir el XML.
          </p>

          <label
            className="fc-dropzone"
            role="button"
            tabIndex={guardando ? -1 : 0}
            aria-busy={guardando}
            data-arrastrando={arrastrando ? "true" : "false"}
            style={guardando ? { cursor: "progress", opacity: 0.6 } : undefined}
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
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--verde-medio)"
              strokeWidth="1.9"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d={ICONO_SUBIR} />
            </svg>
            <span style={{ fontSize: 13.5, fontWeight: 600, color: "var(--verde-marca)" }}>
              {guardando ? "Comprobando…" : "Arrastra el XML de la retención o haz clic"}
            </span>
            {!guardando && (
              <span style={{ fontSize: 12, color: "#8A9A91" }}>
                Lo leemos, lo consultamos al SRI y lo sumamos solo
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

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              margin: "18px 0 14px",
              fontSize: 12,
              fontWeight: 600,
              color: "var(--texto-tenue)",
            }}
          >
            <span style={{ flex: 1, height: 1, background: "var(--borde)" }} />
            O escríbela a mano
            <span style={{ flex: 1, height: 1, background: "var(--borde)" }} />
          </div>

          {/* SIN XML NO HAY CLAVE DE ACCESO, y sin clave no hay a quién
              preguntarle. La fila cuenta igual —el papel lo tiene el cliente en
              la mano— pero queda marcada, y eso se dice antes de escribirla. */}
          <p
            style={{
              fontSize: 12.5,
              lineHeight: 1.55,
              color: "var(--texto-tenue)",
              margin: "0 0 14px",
              textWrap: "pretty",
            }}
          >
            Si solo tienes el papel, escríbela. Suma a tu crédito igual, pero queda marcada como
            «sin XML»: no hay clave de acceso con la que preguntarle al SRI. Guarda el comprobante.
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

          <Rejilla columnas="1fr 1fr 1fr">
            <Campo
              id="ret-factura"
              etiqueta="Sobre cuál de tus facturas"
              valor={factura}
              onCambio={setFactura}
              placeholder="001-001-000000045"
              deshabilitado={guardando}
            />
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
              borderRadius: "var(--radio-tarjeta)",
              padding: "13px 16px",
            }}
          >
            <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--texto-suave)" }}>
              Crédito que suma a tu favor
            </span>
            <span className="fc-cifra" style={{ fontSize: 19, color: "var(--verde-medio)" }}>
              {dinero(credito)}
            </span>
          </div>

          {error && (
            <p
              className="fc-error"
              role="alert"
              style={{ marginTop: 14, fontSize: 12.5, lineHeight: 1.55, textWrap: "pretty" }}
            >
              {error}
              {queHacer && <span style={{ display: "block", marginTop: 6 }}>{queHacer}</span>}
            </p>
          )}
        </div>

        <div className="fc-modal__pie">
          <button
            type="button"
            className="fc-btn fc-btn--texto"
            onClick={onCerrar}
            disabled={guardando}
          >
            Cancelar
          </button>
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            disabled={!puedeGuardar}
            title={
              credito > 0
                ? undefined
                : "Escribe cuánto te retuvieron de renta o de IVA."
            }
            onClick={() => void enviar(null)}
          >
            {guardando ? "Guardando…" : "Guardar la retención"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function Rejilla({ columnas, children }: { columnas: string; children: ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: columnas,
        gap: 12,
        marginBottom: 14,
      }}
    >
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
        onChange={(e) => onCambio(e.target.value)}
      />
    </div>
  );
}
