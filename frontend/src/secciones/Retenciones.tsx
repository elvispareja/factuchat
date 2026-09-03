/** Bandeja de retenciones recibidas (Dashboard.dc.html, líneas 380-449).
 *
 * Tres tarjetas de resumen, la banda de custodia de siete años y la tabla de
 * seis columnas con descarga de XML por fila.
 *
 * El inquilino NUNCA emite una retención: solo la recibe. Por eso la primera
 * columna es «Quién te retuvo» y no «Cliente».
 *
 * Las cifras vienen calculadas del servidor. La maqueta las traía escritas a
 * mano y no cuadraban entre sí (14 documentos y $1,556.70 de saldo frente a 6
 * filas que suman $710.77): aquí todo sale de la misma consulta, así que el
 * conteo, el saldo y la tabla hablan siempre del mismo período.
 *
 * SUBIR A MANO (`SubirRetencion`). El buzón por correo está apagado y al
 * cliente le retienen igual: su cliente le manda el XML por WhatsApp o se lo
 * entrega impreso. Por eso el cargador NO se esconde con `activo` en falso —el
 * servidor, con el módulo apagado, sigue listando y sumando lo de origen
 * MANUAL—: el interruptor apaga la automatización, no el archivador del
 * cliente.
 */

import { useEffect, useRef, useState } from "react";
import { ErrorApi, api, sesion } from "../api/cliente";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";
import { dinero, fechaCorta } from "../util/formato";

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
  tiene_xml: boolean;
  tiene_pdf: boolean;
}

interface Bandeja {
  activo: boolean;
  buzon: string | null;
  periodo: { desde: string; hasta: string };
  saldo: string;
  saldo_renta: string;
  saldo_iva: string;
  documentos: number;
  agentes: number;
  retenciones: RetencionFila[];
}

export function Retenciones() {
  const [datos, setDatos] = useState<Bandeja | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = () =>
    api
      .get<Bandeja>("/retenciones")
      .then(setDatos)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) return <ErrorSeccion mensaje={error} />;
  if (!datos) return <Cargando />;

  const pendientes = datos.retenciones.filter((r) => !r.verificada).length;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="fc-kpi">
        <section className="fc-tarjeta--oscura" style={{ padding: "20px 22px" }}>
          <div className="fc-halo" />
          <div style={{ position: "relative", zIndex: 1 }}>
            <p className="fc-kicker" style={{ color: "var(--verde-claro)", margin: 0 }}>
              Saldo a tu favor
            </p>
            <div
              className="fc-cifra"
              style={{ fontSize: 30, margin: "8px 0 6px", color: "var(--texto-sobre-oscuro)" }}
            >
              {dinero(datos.saldo)}
            </div>
            <p style={{ fontSize: 12.5, color: "#A6BFB2", margin: 0, lineHeight: 1.5 }}>
              Crédito acumulado del semestre, listo para descontar.
            </p>
            {/* La maqueta mostraba una sola cifra; renta e IVA son impuestos
                distintos y el desglose evita que alguien reste lo que no debe. */}
            <p style={{ fontSize: 11.5, color: "#8FB3A0", margin: "8px 0 0", lineHeight: 1.5 }}>
              {dinero(datos.saldo_iva)} de IVA (baja tu declaración mensual) ·{" "}
              {dinero(datos.saldo_renta)} de renta (crédito de la anual)
            </p>
            {pendientes > 0 && (
              <p style={{ fontSize: 11.5, color: "#E8C766", margin: "6px 0 0", lineHeight: 1.5 }}>
                {pendientes === 1
                  ? "1 comprobante está comprobándose con el SRI y todavía no suma."
                  : `${pendientes} comprobantes se están comprobando con el SRI y todavía no suman.`}
              </p>
            )}
          </div>
        </section>

        <section className="fc-tarjeta" style={{ padding: "20px 22px" }}>
          <p className="fc-kicker" style={{ margin: 0 }}>
            Retenciones recibidas
          </p>
          <div className="fc-cifra" style={{ fontSize: 30, margin: "8px 0 6px" }}>
            {datos.documentos}
          </div>
          <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0, lineHeight: 1.5 }}>
            {datos.agentes === 1
              ? "De 1 empresa este semestre."
              : `De ${datos.agentes} empresas distintas este semestre.`}
          </p>
        </section>

        <section className="fc-tarjeta" style={{ padding: "20px 22px" }}>
          <p className="fc-kicker" style={{ margin: 0 }}>
            Reenvía y listo
          </p>
          <p
            style={{
              fontSize: 13,
              lineHeight: 1.55,
              color: "var(--texto-suave)",
              margin: "8px 0 12px",
            }}
          >
            Manda el XML al chat y el asistente lo lee, lo clasifica y lo suma solo.
          </p>
          {datos.buzon && (
            <p
              className="fc-mono"
              style={{
                fontSize: 12,
                background: "var(--superficie-tenue)",
                border: "1px solid var(--borde)",
                borderRadius: "var(--radio-campo)",
                padding: "9px 11px",
                margin: 0,
                wordBreak: "break-all",
              }}
            >
              {datos.buzon}
            </p>
          )}
        </section>
      </div>

      <SubirRetencion onRegistrada={cargar} periodo={datos.periodo} />

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
          Guardamos el XML y el PDF de cada comprobante de retención, con su detalle de renta y de
          IVA, por siete años. Baja uno o todos cuando los necesites.
        </div>
      </section>

      <section className="fc-tarjeta fc-tarjeta--tabla">
        {datos.retenciones.length === 0 ? (
          <Vacio
            titulo="Todavía no has guardado ninguna retención."
            ayuda={
              datos.buzon
                ? `Cuando una empresa te retenga, sube aquí arriba el XML que te manda —o reenvíalo a ${datos.buzon}— y aparecerá en esta lista.`
                : "Cuando una empresa te retenga, sube aquí arriba el XML que te manda y aparecerá en esta lista."
            }
          />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="fc-tabla" style={{ minWidth: 860 }}>
              <thead>
                <tr>
                  <th scope="col">Quién te retuvo</th>
                  <th scope="col">Fecha</th>
                  <th scope="col">Concepto</th>
                  <th scope="col" className="fc-num">
                    Ret. renta
                  </th>
                  <th scope="col" className="fc-num">
                    Ret. IVA
                  </th>
                  <th scope="col" className="fc-num">
                    Archivo
                  </th>
                </tr>
              </thead>
              <tbody>
                {datos.retenciones.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{r.quien}</div>
                      <div className="fc-mono" style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                        {r.numero}
                        {r.ruc ? ` · ${r.ruc}` : ""}
                      </div>
                      {/* Copia nueva, no está en la maqueta: una retención solo
                          suma cuando el SRI confirma que existe.
                          Los DOS estados se pintan, no solo el pendiente. Antes
                          «verificada» era la ausencia de chip, y eso se leía
                          igual que «no pasa nada aquí»; desde que el propio
                          cliente sube comprobantes, lo que quiere saber al
                          volver es exactamente cuál de los dos es: el que ya
                          descuenta y el que todavía no. */}
                      {/* TRES estados, no dos: pendiente, confirmada y
                          RECHAZADA. `verificada: false` vale para las dos
                          últimas, y pintarlas igual dejaba un documento muerto
                          diciendo «comprobando» para siempre, con el usuario
                          esperando una respuesta que ya había llegado. */}
                      <div
                        className={`fc-estado ${
                          r.verificada
                            ? "fc-estado--exito"
                            : r.respondido
                              ? "fc-estado--error"
                              : "fc-estado--aviso"
                        }`}
                        style={{ marginTop: 6, fontSize: 11 }}
                        title={r.verificacion ?? undefined}
                      >
                        <span className="fc-estado__punto" />
                        {r.verificada
                          ? "Confirmada · suma a tu saldo"
                          : r.respondido
                            ? "El SRI no la reconoce · no suma"
                            : "Comprobando con el SRI · todavía no suma"}
                      </div>
                      {/* El motivo, escrito. Estaba solo en el `title`, que en
                          un móvil no existe, y es justo lo que hay que leer
                          para saber que toca pedirle el comprobante bueno. */}
                      {!r.verificada && r.respondido && r.verificacion && (
                        <p
                          style={{
                            margin: "4px 0 0",
                            fontSize: 11.5,
                            color: "var(--texto-tenue)",
                            textWrap: "pretty",
                          }}
                        >
                          {r.verificacion}
                        </p>
                      )}
                    </td>
                    <td style={{ fontSize: 13 }}>{r.fecha ? fechaCorta(r.fecha) : "—"}</td>
                    <td style={{ fontSize: 13, color: "var(--texto-suave)" }}>
                      {r.concepto ?? "—"}
                    </td>
                    <td className="fc-num">{dinero(r.renta)}</td>
                    <td className="fc-num">{dinero(r.iva)}</td>
                    <td className="fc-num">
                      {r.tiene_xml ? (
                        <button
                          type="button"
                          className="fc-btn fc-btn--contorno"
                          style={{ padding: "5px 13px", fontSize: 12 }}
                          title="Descargar XML"
                          onClick={() => void bajarXml(r)}
                        >
                          XML
                        </button>
                      ) : (
                        /* No es un fallo: el servidor solo custodia el fichero
                           cuando hay clave de cifrado configurada, y hasta
                           entonces registra la fila sin él. Lo que sostiene el
                           crédito son los datos y la clave de acceso, así que
                           se dice en vez de dejar un guion mudo. */
                        <span
                          style={{ fontSize: 12, color: "var(--texto-tenue)" }}
                          title="Guardamos los datos de esta retención, no el archivo."
                        >
                          Sin archivo
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/* --- Subir una retención a mano ---------------------------------------------
   `POST /retenciones` (multipart, campo `archivo`) devuelve la fila ya creada,
   la misma que pinta la tabla.

   Ni la extensión ni el tamaño se comprueban aquí. El servidor lee el fichero
   acotado a 4 MB y es su parser quien dice si eso es una retención y de quién:
   adelantarse mirando el nombre del archivo solo añadiría una segunda opinión
   que puede contradecir a la que manda. El `accept` es una comodidad del
   diálogo del sistema, no un filtro. */

/** Qué hacer con cada rechazo. El QUÉ PASÓ ya lo cuenta el servidor con su
 *  propia frase («El comprobante retiene a 1790099999001, que no es el RUC de
 *  este buzón»); esto es el QUÉ HAGO AHORA, y va por código de estado y no por
 *  el texto: leer el mensaje para decidir se rompe en cuanto alguien le cambie
 *  una coma. */
const QUE_HACER: Record<number, string> = {
  409: "No hace falta subirla otra vez: ya la tienes en la lista de abajo, con su crédito.",
  422:
    "Tiene que ser el archivo XML del comprobante de retención, tal cual te lo mandó tu cliente y" +
    " a tu nombre. Si te dio otra cosa —la factura, un PDF, una foto—, pídele el XML de la retención.",
};

const ICONO_SUBIR = "M12 16V4M7 9l5-5 5 5M4 20h16";

/** El cargador. Se pinta SIEMPRE, también con el buzón apagado: es hoy la única
 *  puerta por la que entra una retención. */
function SubirRetencion({
  onRegistrada,
  periodo,
}: {
  onRegistrada: () => Promise<unknown>;
  /** El semestre que la lista y el saldo enseñan. Lo de fuera se guarda igual,
   *  pero no aparece aquí, y hay que decirlo. */
  periodo: { desde: string; hasta: string };
}) {
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastrando, setArrastrando] = useState(false);
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queHacer, setQueHacer] = useState<string | null>(null);
  const [listo, setListo] = useState<RetencionFila | null>(null);

  // Las fechas son ISO («2026-03-12»), así que comparar como texto ordena bien y
  // no arrastra la zona horaria de `new Date`, que en Ecuador cambia el día.
  const fueraDelPeriodo =
    listo !== null &&
    listo.fecha !== null &&
    (listo.fecha < periodo.desde || listo.fecha >= periodo.hasta);

  async function subir(archivo: File | undefined | null) {
    if (!archivo || subiendo) return;
    setSubiendo(true);
    setError(null);
    setQueHacer(null);
    setListo(null);
    try {
      const fila = await api.subir<RetencionFila>("/retenciones", archivo);
      setListo(fila);
      // El saldo, el conteo y la lista salen de la misma consulta: recargarla
      // es lo único que mantiene las tres cifras hablando del mismo período.
      await onRegistrada();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos leer el archivo");
      setQueHacer(e instanceof ErrorApi ? (QUE_HACER[e.status] ?? null) : null);
    } finally {
      setSubiendo(false);
      // Sin esto, volver a elegir EL MISMO fichero no dispara `change` y el
      // reintento no hace nada: el navegador compara con el valor anterior.
      if (entrada.current) entrada.current.value = "";
    }
  }

  return (
    <section className="fc-tarjeta">
      <p className="fc-kicker" style={{ margin: 0 }}>
        Te retuvieron
      </p>
      <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--texto-suave)", margin: "8px 0 0" }}>
        Cuando un cliente te paga, puede quedarse con una parte y entregarla al SRI a tu nombre. Ese
        dinero ya lo pusiste tú: descuenta lo que te toca pagar. Al retenerte, tu cliente te manda un
        comprobante en un <strong>archivo XML</strong> —por correo o por WhatsApp—. Súbelo aquí y lo
        guardamos con tu crédito.
      </p>
      <p style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--texto-tenue)", margin: "8px 0 16px" }}>
        Al subirlo se lo preguntamos al SRI. Mientras contesta lo ves en la lista, pero todavía no
        suma al saldo: así el crédito que te enseñamos es siempre el que puedes declarar de verdad.
        Cuando el SRI lo confirma, entra solo.
      </p>

      {/* Mismo molde que SubirFirma y que la imagen del catálogo: `.fc-dropzone`,
          el mismo icono y el mismo `data-arrastrando`. El `tabIndex` y el
          teclado sí son de aquí: el `<input type=file>` va oculto con
          `display:none`, así que sin esto la zona solo se puede usar con
          ratón. */}
      <label
        className="fc-dropzone"
        role="button"
        tabIndex={subiendo ? -1 : 0}
        aria-busy={subiendo}
        data-arrastrando={arrastrando ? "true" : "false"}
        style={subiendo ? { cursor: "progress", opacity: 0.6 } : undefined}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            entrada.current?.click();
          }
        }}
        onDragOver={(e) => {
          // Sin preventDefault el navegador se lleva el archivo a otra pestaña
          // en vez de dejarlo soltar aquí.
          e.preventDefault();
          setArrastrando(true);
        }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={(e) => {
          e.preventDefault();
          setArrastrando(false);
          void subir(e.dataTransfer.files?.[0]);
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
          {subiendo ? "Comprobando el archivo…" : "Arrastra el XML de la retención o haz clic"}
        </span>
        {!subiendo && (
          <span style={{ fontSize: 12, color: "#8A9A91" }}>Un archivo .xml · hasta 4 MB</span>
        )}
        <input
          ref={entrada}
          type="file"
          accept=".xml,text/xml,application/xml"
          disabled={subiendo}
          onChange={(e) => void subir(e.target.files?.[0])}
        />
      </label>

      {/* Registrada NO es «ya la puedes descontar»: se dice entera la mitad
          buena y la que falta, en verde, porque no es un problema. */}
      {listo && (
        <p
          role="status"
          style={{
            margin: "14px 0 0",
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
          Guardada la <strong>{listo.numero}</strong>
          {listo.quien ? ` de ${listo.quien}` : ""} por {dinero(listo.renta)} de renta y{" "}
          {dinero(listo.iva)} de IVA.{" "}
          {/* La lista y el saldo son SOLO del semestre en curso. Sin este aviso,
              subir la retención de diciembre en enero la hacía desaparecer:
              quedaba guardada, pero la pantalla decía «ya está en tu lista»
              sobre una lista donde no estaba, y al reintentarla salía un «ya la
              tienes» que tampoco se podía comprobar. */}
          {fueraDelPeriodo ? (
            <>
              Es del {listo.fecha ? fechaCorta(listo.fecha) : "un período anterior"}, así que no
              sale en esta lista: aquí solo se ve el semestre en curso. Está guardada y cuenta
              para el período al que pertenece.
            </>
          ) : (
            <>Ya está en tu lista; entrará en el saldo en cuanto el SRI confirme que existe.</>
          )}
        </p>
      )}

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
    </section>
  );
}

/** Descarga el XML con el token de sesión: la ruta está autenticada, así que no
 *  sirve un enlace directo. El servidor lo descifra al vuelo. */
async function bajarXml(r: RetencionFila) {
  const respuesta = await fetch(`/api/v1/retenciones/${r.id}/xml`, {
    headers: sesion.access ? { Authorization: `Bearer ${sesion.access}` } : {},
  });
  if (!respuesta.ok) return;
  const blob = await respuesta.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `retencion-${r.numero}.xml`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
