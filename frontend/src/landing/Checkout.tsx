/** Checkout público (maqueta líneas 277-674).
 *
 * Tres vías excluyentes —solicitar información, transferencia y Payphone— con
 * una sola casilla legal que cubre los dos consentimientos. La regla maestra de
 * bloqueo es la de la maqueta (línea 2745), pero quien decide de verdad es el
 * servidor: /publico/checkout rechaza el pedido si la aceptación no llega.
 *
 * Diferencias deliberadas frente a la maqueta:
 *   · La referencia la genera el servidor (la maqueta usaba Date.now(), que
 *     colisiona) y el pedido se persiste en la base, no en localStorage.
 *   · El comprobante se valida de verdad: tipo MIME y 5 MB, tal como promete
 *     el copy. La maqueta no validaba nada.
 *   · Los objectURL se revocan también al cerrar (la maqueta los filtraba).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { ConfigPublica, PlanPublico } from "./datos";
import { PROVINCIAS_EC } from "./datos";

const BASE = "/api/v1";
const MAX_BYTES = 5 * 1024 * 1024;
const TIPOS_OK = ["image/jpeg", "image/png", "image/webp", "application/pdf"];

type Via = "whatsapp" | "transferencia" | "tarjeta";

const METODO_API: Record<Via, string> = {
  whatsapp: "OTRO",
  transferencia: "TRANSFERENCIA",
  tarjeta: "PAYPHONE",
};

const VIAS: Array<{ id: Via; titulo: string; desc: string; cta: string }> = [
  {
    id: "whatsapp",
    titulo: "Solicitar información",
    desc: "Agendas cuándo te contactamos y un asesor te escribe por WhatsApp para resolver tus dudas y activar tu plan.",
    cta: "Solicitar información",
  },
  {
    id: "transferencia",
    titulo: "Transferencia o depósito bancario",
    desc: "Te mostramos las cuentas, transfieres y subes el comprobante. Activamos tu plan al confirmar el pago.",
    cta: "Confirmar pedido",
  },
  {
    id: "tarjeta",
    titulo: "Tarjeta de crédito o débito (Payphone)",
    desc: "Pago en línea seguro. No guardamos los datos de tu tarjeta: los procesa Payphone.",
    cta: "Continuar a Payphone",
  },
];

const HORAS = Array.from({ length: 15 }, (_, i) => `${String(i + 7).padStart(2, "0")}:00`);

interface Confirmacion {
  referencia: string;
  plan: string;
  precio: string;
  siguiente_paso: string;
  wa_link: string | null;
}

/** Siete fechas desde hoy saltando los domingos (regla de la maqueta). */
function diasAgendables(): Array<{ iso: string; etiqueta: string }> {
  const salida: Array<{ iso: string; etiqueta: string }> = [];
  const fmt = new Intl.DateTimeFormat("es-EC", { weekday: "short", day: "numeric", month: "short" });
  const d = new Date();
  for (let i = 0; i < 20 && salida.length < 7; i++) {
    if (d.getDay() !== 0) {
      salida.push({
        iso: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`,
        etiqueta: fmt.format(d),
      });
    }
    d.setDate(d.getDate() + 1);
  }
  return salida;
}

export function Checkout({
  plan,
  config,
  onCerrar,
}: {
  plan: PlanPublico;
  config: ConfigPublica | null;
  onCerrar: () => void;
}) {
  const [nombres, setNombres] = useState("");
  const [apellidos, setApellidos] = useState("");
  const [identificacion, setIdentificacion] = useState("");
  const [telefono, setTelefono] = useState("");
  const [email, setEmail] = useState("");
  const [provincia, setProvincia] = useState("Pichincha");
  const [ciudad, setCiudad] = useState("");

  const [via, setVia] = useState<Via>("whatsapp");
  const [acepta, setAcepta] = useState(false);
  const [agDia, setAgDia] = useState("");
  const [agHora, setAgHora] = useState("");
  const [nota, setNota] = useState("");

  const [archivo, setArchivo] = useState<File | null>(null);
  const [archivoUrl, setArchivoUrl] = useState<string>("");
  const [modalBanco, setModalBanco] = useState(false);
  const [modalLegal, setModalLegal] = useState(false);
  const [copiada, setCopiada] = useState<string | null>(null);

  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<Confirmacion | null>(null);

  const dias = useMemo(diasAgendables, []);
  const urlRef = useRef<string>("");

  // La maqueta filtraba los objectURL al cerrar el checkout; aquí se revocan.
  useEffect(() => {
    urlRef.current = archivoUrl;
  }, [archivoUrl]);
  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  const faltaAgenda = via === "whatsapp" && (!agDia || !agHora);
  const faltaComprobante = via === "transferencia" && !archivo;
  const bloqueado = !acepta || faltaAgenda || faltaComprobante;
  // Prioridad de la maqueta: legal, luego agenda, luego comprobante
  const motivo = !acepta
    ? "Acepta las condiciones para poder continuar."
    : faltaAgenda
      ? "Elige el día y la hora en que quieres que te contactemos."
      : faltaComprobante
        ? "Sube tu comprobante para poder confirmar."
        : "";

  function tomarArchivo(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (!TIPOS_OK.includes(f.type)) {
      setError("Sube una foto (JPG, PNG o WEBP) o un PDF de tu comprobante.");
      return;
    }
    if (f.size > MAX_BYTES) {
      setError("El archivo supera los 5 MB permitidos.");
      return;
    }
    if (archivoUrl) URL.revokeObjectURL(archivoUrl);
    setError(null);
    setArchivo(f);
    setArchivoUrl(f.type.startsWith("image/") ? URL.createObjectURL(f) : "");
  }

  function quitarArchivo() {
    if (archivoUrl) URL.revokeObjectURL(archivoUrl);
    setArchivo(null);
    setArchivoUrl("");
  }

  async function copiar(numero: string) {
    try {
      await navigator.clipboard.writeText(numero);
      setCopiada(numero);
      window.setTimeout(() => setCopiada((c) => (c === numero ? null : c)), 2200);
    } catch {
      /* sin portapapeles: el número sigue visible para copiarlo a mano */
    }
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    if (bloqueado || enviando) return;
    setEnviando(true);
    setError(null);
    try {
      const r = await fetch(`${BASE}/publico/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          nombres,
          apellidos,
          identificacion,
          telefono,
          email,
          pais: "Ecuador",
          provincia,
          ciudad,
          plan: plan.codigo,
          metodo_pago: METODO_API[via],
          agenda_dia: via === "whatsapp" ? agDia : null,
          agenda_hora: via === "whatsapp" ? agHora : null,
          mensaje: nota || null,
          // Una casilla, dos consentimientos: así los registra el servidor
          acepta: { condiciones: acepta, datos: acepta },
        }),
      });
      const datos = await r.json();
      if (!r.ok) throw new Error(datos?.detail ?? "No pudimos registrar tu pedido.");

      if (via === "transferencia" && archivo) {
        const cuerpo = new FormData();
        cuerpo.append("archivo", archivo);
        const r2 = await fetch(`${BASE}/publico/checkout/${datos.id}/comprobante`, {
          method: "POST",
          body: cuerpo,
        });
        if (!r2.ok) {
          const d2 = await r2.json().catch(() => null);
          throw new Error(d2?.detail ?? "Tu pedido quedó registrado, pero el comprobante no subió.");
        }
      }

      if (via === "whatsapp" && datos.wa_link) window.open(datos.wa_link, "_blank", "noopener");
      setOk(datos as Confirmacion);
      window.scrollTo(0, 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos registrar tu pedido.");
    } finally {
      setEnviando(false);
    }
  }

  const viaActual = VIAS.find((v) => v.id === via)!;

  return (
    <div className="lp-checkout fc-scroll" role="dialog" aria-modal="true" aria-label="Finaliza tu pedido">
      <div className="lp-ancho">
        <header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            paddingBottom: 22,
            borderBottom: "1px solid rgba(18,61,47,.12)",
            marginBottom: 34,
          }}
        >
          <span className="lp-logo" style={{ color: "var(--verde-medio)", fontSize: 31 }}>
            Factuchat®
          </span>
          <button type="button" className="lp-btn lp-btn--claro lp-btn--pequeno" onClick={onCerrar}>
            ← Volver a los planes
          </button>
        </header>

        {ok ? (
          <PedidoConfirmado datos={ok} config={config} onCerrar={onCerrar} />
        ) : (
          <form onSubmit={enviar}>
            <h1 className="lp-h2" style={{ fontSize: 38, marginBottom: 26 }}>
              Finaliza tu pedido
            </h1>

            <div className="lp-checkout__grid">
              <div style={{ display: "grid", gap: 18 }}>
                <section className="lp-tarjeta">
                  <p className="lp-eyebrow">Paso 1</p>
                  <h2 className="lp-h2" style={{ fontSize: 22, marginBottom: 18 }}>
                    Tus datos
                  </h2>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: "0 16px" }}>
                    <Campo label="Nombres" valor={nombres} set={setNombres} requerido />
                    <Campo label="Apellidos" valor={apellidos} set={setApellidos} requerido />
                    <Campo
                      label="Cédula o RUC"
                      valor={identificacion}
                      set={setIdentificacion}
                      placeholder="1712345678"
                      requerido
                    />
                    <Campo
                      label="Teléfono"
                      valor={telefono}
                      set={setTelefono}
                      placeholder="099 000 0000"
                      requerido
                    />
                    <Campo
                      label="Correo electrónico"
                      valor={email}
                      set={setEmail}
                      tipo="email"
                      placeholder="tucorreo@ejemplo.com"
                      requerido
                    />
                    <label className="lp-campo">
                      <span>Provincia</span>
                      <select value={provincia} onChange={(e) => setProvincia(e.target.value)} required>
                        {PROVINCIAS_EC.map((p) => (
                          <option key={p}>{p}</option>
                        ))}
                      </select>
                    </label>
                    <Campo label="Ciudad" valor={ciudad} set={setCiudad} requerido />
                  </div>
                  <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0 }}>
                    Facturamos en Ecuador. Los demás países se habilitan en cuanto cerremos la
                    integración con su entidad tributaria.
                  </p>
                </section>

                <section className="lp-tarjeta">
                  <p className="lp-eyebrow">Paso 2</p>
                  <h2 className="lp-h2" style={{ fontSize: 22, marginBottom: 18 }}>
                    Forma de pago
                  </h2>
                  {VIAS.map((v) => (
                    <button
                      key={v.id}
                      type="button"
                      className="lp-via"
                      aria-pressed={via === v.id}
                      onClick={() => setVia(v.id)}
                    >
                      <span className="lp-via__titulo">{v.titulo}</span>
                      {via === v.id && <span className="lp-via__desc">{v.desc}</span>}
                    </button>
                  ))}
                  {via === "transferencia" && (
                    <p style={{ fontSize: 13, color: "var(--texto-suave)", margin: "6px 0 0" }}>
                      Usa el botón <strong>Subir documento de transferencia</strong> del resumen para
                      ver nuestras cuentas y adjuntar tu comprobante.
                    </p>
                  )}
                  {via === "tarjeta" && (
                    <p style={{ fontSize: 13, color: "var(--texto-suave)", margin: "6px 0 0" }}>
                      No guardamos los datos de tu tarjeta. VISA · Mastercard · Discover · Diners Club.
                    </p>
                  )}
                </section>
              </div>

              <aside className="lp-resumen">
                <p className="lp-eyebrow" style={{ color: "var(--verde-claro)" }}>
                  Tu pedido
                </p>
                <div style={{ fontFamily: "var(--fuente-titulo)", fontSize: 24, fontWeight: 700 }}>
                  Plan {plan.nombre}
                </div>
                <div className="lp-resumen__fila">
                  <span>Comprobantes</span>
                  <span>{plan.cupo === null ? "Ilimitados" : plan.cupo}</span>
                </div>
                <div className="lp-resumen__fila">
                  <span>Vigencia</span>
                  <span>{plan.codigo === "INICIAL" ? "20 días" : "Mensual"}</span>
                </div>
                <div className="lp-resumen__fila">
                  <span>IVA</span>
                  <span>Incluido</span>
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    margin: "16px 0 18px",
                  }}
                >
                  <span style={{ fontSize: 13.5, color: "#A6BFB2" }}>Total a pagar</span>
                  <strong style={{ fontFamily: "var(--fuente-titulo)", fontSize: 30 }}>
                    ${Number(plan.precio).toFixed(2)}
                  </strong>
                </div>

                {via === "transferencia" && (
                  <>
                    {archivo && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 12,
                          background: "rgba(255,255,255,.06)",
                          border: "1px solid rgba(255,255,255,.14)",
                          borderRadius: 14,
                          padding: 12,
                          marginBottom: 12,
                        }}
                      >
                        <span
                          aria-hidden="true"
                          style={{
                            width: 54,
                            height: 54,
                            flexShrink: 0,
                            borderRadius: 11,
                            border: "1px solid rgba(255,255,255,.2)",
                            display: "grid",
                            placeItems: "center",
                            fontSize: 10,
                            fontWeight: 700,
                            color: "#D93025",
                            background: archivoUrl
                              ? `center/cover url(${archivoUrl})`
                              : "#FFFFFF",
                          }}
                        >
                          {archivoUrl ? "" : "PDF"}
                        </span>
                        <span style={{ flex: 1, minWidth: 0, fontSize: 13 }}>
                          <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {archivo.name}
                          </span>
                          <span style={{ color: "#A6BFB2", fontSize: 12 }}>
                            {(archivo.size / 1024).toFixed(0)} KB
                          </span>
                        </span>
                        <button
                          type="button"
                          onClick={quitarArchivo}
                          className="lp-chip"
                          aria-label="Quitar el comprobante"
                        >
                          ✕ Quitar
                        </button>
                      </div>
                    )}
                    <button
                      type="button"
                      className="lp-btn lp-btn--fantasma"
                      style={{ width: "100%", marginBottom: 14 }}
                      onClick={() => setModalBanco(true)}
                    >
                      {archivo ? "✓ Comprobante adjunto" : "Subir documento de transferencia"}
                    </button>
                  </>
                )}

                <label
                  style={{
                    display: "grid",
                    gridTemplateColumns: "22px 1fr",
                    gap: 11,
                    alignItems: "start",
                    cursor: "pointer",
                    marginBottom: 10,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={acepta}
                    onChange={(e) => setAcepta(e.target.checked)}
                    style={{ width: 20, height: 20, accentColor: "#22C55E", marginTop: 2 }}
                  />
                  <span style={{ fontSize: 13, lineHeight: 1.5, color: "#DDF3E6" }}>
                    Acepto los términos de uso y el tratamiento de mis datos personales.
                  </span>
                </label>
                <button
                  type="button"
                  onClick={() => setModalLegal(true)}
                  style={{
                    background: "none",
                    border: "none",
                    padding: 0,
                    font: "inherit",
                    fontSize: 12.5,
                    color: "var(--verde-claro)",
                    textDecoration: "underline",
                    cursor: "pointer",
                    marginBottom: 16,
                  }}
                >
                  Leer el documento completo
                </button>

                {via === "whatsapp" && acepta && (
                  <div style={{ marginBottom: 16 }}>
                    <p className="lp-eyebrow" style={{ color: "var(--verde-claro)" }}>
                      Agenda tu llamada
                    </p>
                    <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 8 }}>
                      {dias.map((d) => (
                        <button
                          key={d.iso}
                          type="button"
                          className="lp-chip"
                          aria-pressed={agDia === d.iso}
                          onClick={() => setAgDia(d.iso)}
                        >
                          {d.etiqueta}
                        </button>
                      ))}
                    </div>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(5,1fr)",
                        gap: 6,
                        margin: "10px 0",
                      }}
                    >
                      {HORAS.map((h) => (
                        <button
                          key={h}
                          type="button"
                          className="lp-chip"
                          style={{ padding: "7px 4px", fontSize: 12, textAlign: "center" }}
                          aria-pressed={agHora === h}
                          onClick={() => setAgHora(h)}
                        >
                          {h}
                        </button>
                      ))}
                    </div>
                    <textarea
                      value={nota}
                      onChange={(e) => setNota(e.target.value)}
                      rows={2}
                      maxLength={1000}
                      placeholder="¿Algo que debamos saber antes de llamarte? (opcional)"
                      style={{
                        width: "100%",
                        background: "rgba(255,255,255,.06)",
                        border: "1px solid rgba(255,255,255,.16)",
                        borderRadius: 12,
                        color: "var(--texto-sobre-oscuro)",
                        padding: "10px 12px",
                        font: "inherit",
                        fontSize: 13,
                      }}
                    />
                    {agDia && agHora && (
                      <p
                        style={{
                          fontSize: 12.5,
                          color: "var(--verde-claro)",
                          background: "rgba(34,197,94,.12)",
                          border: "1px solid rgba(92,230,143,.3)",
                          borderRadius: 12,
                          padding: "9px 12px",
                          margin: "10px 0 0",
                        }}
                      >
                        Te llamamos el {dias.find((d) => d.iso === agDia)?.etiqueta} a las {agHora}.
                      </p>
                    )}
                    <p style={{ fontSize: 12, color: "#A6BFB2", margin: "8px 0 0" }}>
                      {config?.horario ?? "Lunes a sábado, de 07:00 a 21:00."}
                    </p>
                  </div>
                )}

                {error && (
                  <p
                    role="alert"
                    style={{
                      fontSize: 13,
                      color: "#FFD3CE",
                      background: "rgba(217,83,79,.18)",
                      border: "1px solid rgba(217,83,79,.4)",
                      borderRadius: 12,
                      padding: "10px 12px",
                      margin: "0 0 12px",
                    }}
                  >
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  className="lp-btn lp-btn--verde"
                  style={{ width: "100%" }}
                  disabled={bloqueado || enviando}
                >
                  {enviando ? "Enviando…" : viaActual.cta}
                </button>
                {bloqueado && (
                  <p style={{ fontSize: 12.5, color: "#A6BFB2", textAlign: "center", margin: "10px 0 0" }}>
                    {motivo}
                  </p>
                )}
              </aside>
            </div>
          </form>
        )}
      </div>

      {modalBanco && config && (
        <ModalBanco
          config={config}
          archivo={archivo}
          archivoUrl={archivoUrl}
          copiada={copiada}
          onCopiar={copiar}
          onArchivo={tomarArchivo}
          onCerrar={() => setModalBanco(false)}
        />
      )}
      {modalLegal && (
        <ModalLegal
          onAceptar={() => {
            setAcepta(true);
            setModalLegal(false);
          }}
          onCerrar={() => setModalLegal(false)}
        />
      )}
    </div>
  );
}

function Campo({
  label,
  valor,
  set,
  tipo = "text",
  placeholder,
  requerido,
}: {
  label: string;
  valor: string;
  set: (v: string) => void;
  tipo?: string;
  placeholder?: string;
  requerido?: boolean;
}) {
  return (
    <label className="lp-campo">
      <span>{label}</span>
      <input
        type={tipo}
        value={valor}
        placeholder={placeholder}
        required={requerido}
        onChange={(e) => set(e.target.value)}
      />
    </label>
  );
}

function ModalBanco({
  config,
  archivo,
  archivoUrl,
  copiada,
  onCopiar,
  onArchivo,
  onCerrar,
}: {
  config: ConfigPublica;
  archivo: File | null;
  archivoUrl: string;
  copiada: string | null;
  onCopiar: (n: string) => void;
  onArchivo: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onCerrar: () => void;
}) {
  return (
    <div className="lp-modal" onClick={onCerrar} role="dialog" aria-modal="true" aria-label="Transferencia bancaria">
      <div className="lp-modal__panel fc-scroll" onClick={(e) => e.stopPropagation()}>
        <h3 className="lp-h2" style={{ fontSize: 21, marginBottom: 5 }}>
          Transferencia bancaria
        </h3>
        <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--texto-suave)", margin: "0 0 20px" }}>
          Transfiere el total a cualquiera de nuestras cuentas y sube el comprobante.
        </p>

        <p className="lp-eyebrow">Nuestras cuentas</p>
        <div
          style={{
            background: "var(--superficie-suave)",
            border: "1px solid var(--borde)",
            borderRadius: 16,
            padding: "16px 18px",
            marginBottom: 20,
          }}
        >
          <div style={{ paddingBottom: 14, borderBottom: "1px solid #E9EDE9", marginBottom: 14 }}>
            <div style={{ fontFamily: "var(--fuente-titulo)", fontSize: 16, fontWeight: 700 }}>
              {config.cobro.titular}
            </div>
            <div style={{ fontSize: 13.5, color: "var(--texto-suave)" }}>
              C.I. {config.cobro.identificacion} · {config.cobro.email}
            </div>
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 12,
              marginBottom: 11,
              fontSize: 11.5,
              color: "var(--texto-tenue)",
            }}
          >
            <strong style={{ letterSpacing: ".09em", textTransform: "uppercase" }}>
              Cuentas de ahorros
            </strong>
            <span style={{ fontSize: 12 }}>Toca el número para copiarlo</span>
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {config.cobro.cuentas.map((c) => (
              <button
                key={c.numero}
                type="button"
                className="lp-cuenta"
                data-copiada={copiada === c.numero}
                onClick={() => void onCopiar(c.numero)}
              >
                <span style={{ fontSize: 14, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {c.banco}
                </span>
                <span className="fc-mono" style={{ fontSize: 14.5, color: "var(--verde-medio)" }}>
                  {c.numero}
                </span>
                <span
                  style={{
                    fontSize: 11.5,
                    fontWeight: 600,
                    color: copiada === c.numero ? "var(--verde-medio)" : "var(--texto-tenue)",
                  }}
                >
                  {copiada === c.numero ? "Copiado ✓" : "Copiar"}
                </span>
              </button>
            ))}
          </div>
        </div>

        <label style={{ display: "block", fontSize: 12.5, fontWeight: 600, marginBottom: 7 }}>
          Comprobante de la transferencia
        </label>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 13,
            background: "var(--superficie-suave)",
            border: "1px dashed var(--borde-campo)",
            borderRadius: 14,
            padding: "15px 17px",
            cursor: "pointer",
          }}
        >
          <span
            aria-hidden="true"
            style={{
              width: 46,
              height: 46,
              flexShrink: 0,
              borderRadius: 11,
              border: "1px solid var(--borde)",
              display: "grid",
              placeItems: "center",
              fontSize: 10,
              fontWeight: 700,
              color: "#D93025",
              background: archivoUrl ? `center/cover url(${archivoUrl})` : "var(--superficie)",
            }}
          >
            {archivo && !archivoUrl ? "PDF" : archivoUrl ? "" : "↑"}
          </span>
          <span style={{ flex: 1, minWidth: 0 }}>
            <span style={{ display: "block", fontSize: 14, fontWeight: 600 }}>
              {archivo ? archivo.name : "Sube tu comprobante"}
            </span>
            <span style={{ display: "block", fontSize: 12.5, color: "var(--texto-suave)" }}>
              JPG, PNG o PDF, hasta 5 MB
            </span>
          </span>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp,application/pdf"
            onChange={onArchivo}
            style={{ position: "absolute", width: 1, height: 1, opacity: 0, pointerEvents: "none" }}
          />
        </label>

        <button
          type="button"
          className={archivo ? "lp-btn lp-btn--verde" : "lp-btn lp-btn--claro"}
          style={{ width: "100%", marginTop: 18 }}
          onClick={onCerrar}
        >
          {archivo ? "Listo, volver al pedido" : "Cerrar"}
        </button>
      </div>
    </div>
  );
}

interface DocLegal {
  titulo: string;
  version: string;
  pie: string;
  secciones: Array<{ encabezado: string; parrafos: string[] }>;
}

export function ModalLegal({
  onAceptar,
  onCerrar,
}: {
  onAceptar?: () => void;
  onCerrar: () => void;
}) {
  const [doc, setDoc] = useState<DocLegal | null>(null);

  useEffect(() => {
    fetch(`${BASE}/publico/terminos`)
      .then((r) => r.json())
      .then(setDoc)
      .catch(() => setDoc(null));
  }, []);

  return (
    <div className="lp-modal" onClick={onCerrar} role="dialog" aria-modal="true" aria-label="Términos">
      <div
        className="lp-modal__panel fc-scroll"
        style={{ maxWidth: 720 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="lp-h2" style={{ fontSize: 22, marginBottom: 4 }}>
          {doc?.titulo ?? "Términos de uso y tratamiento de datos"}
        </h3>
        {doc && (
          <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: "0 0 18px" }}>
            Versión {doc.version}
          </p>
        )}
        {doc ? (
          doc.secciones.map((s) => (
            <section key={s.encabezado} style={{ marginBottom: 18 }}>
              <h4 style={{ fontFamily: "var(--fuente-titulo)", fontSize: 15.5, margin: "0 0 6px" }}>
                {s.encabezado}
              </h4>
              {s.parrafos.map((p, i) => (
                <p
                  key={i}
                  style={{ fontSize: 14, lineHeight: 1.62, color: "var(--texto-suave)", margin: "0 0 8px" }}
                >
                  {p}
                </p>
              ))}
            </section>
          ))
        ) : (
          <p style={{ fontSize: 14, color: "var(--texto-suave)" }}>Cargando el documento…</p>
        )}
        {doc && (
          <p style={{ fontSize: 12, color: "var(--texto-tenue)", marginBottom: 18 }}>{doc.pie}</p>
        )}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {/* Fuera del checkout el documento solo se lee: aceptar sin un pedido
              de por medio no significaría nada. */}
          {onAceptar && (
            <button
              type="button"
              className="lp-btn lp-btn--verde"
              onClick={onAceptar}
              disabled={!doc}
            >
              Acepto y continúo
            </button>
          )}
          <button type="button" className="lp-btn lp-btn--claro" onClick={onCerrar}>
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}

function PedidoConfirmado({
  datos,
  config,
  onCerrar,
}: {
  datos: Confirmacion;
  config: ConfigPublica | null;
  onCerrar: () => void;
}) {
  return (
    <section style={{ maxWidth: 640, margin: "0 auto", textAlign: "center" }}>
      <div
        aria-hidden="true"
        style={{
          width: 62,
          height: 62,
          margin: "0 auto 18px",
          borderRadius: "50%",
          background: "rgba(34,197,94,.14)",
          border: "1px solid rgba(22,121,74,.3)",
          display: "grid",
          placeItems: "center",
          fontSize: 26,
          color: "var(--verde-medio)",
        }}
      >
        ✓
      </div>
      <p className="lp-firma" style={{ fontSize: 40 }}>
        ¡Gracias!
      </p>
      <h1 className="lp-h2" style={{ fontSize: 30 }}>
        Recibimos tu pedido.
      </h1>
      <p className="lp-bajada" style={{ margin: "0 auto 24px" }}>
        {datos.siguiente_paso}
      </p>

      <div className="lp-tres" style={{ marginBottom: 24 }}>
        <div className="lp-tarjeta">
          <p className="lp-eyebrow">Pedido</p>
          <strong className="fc-mono" style={{ fontSize: 16 }}>
            {datos.referencia}
          </strong>
        </div>
        <div className="lp-tarjeta">
          <p className="lp-eyebrow">Plan</p>
          <strong style={{ fontSize: 16 }}>{datos.plan}</strong>
        </div>
        <div className="lp-tarjeta">
          <p className="lp-eyebrow">Total</p>
          <strong style={{ fontSize: 16 }}>${Number(datos.precio).toFixed(2)}</strong>
        </div>
      </div>

      {config && (
        <div
          className="lp-oscuro"
          style={{ borderRadius: "var(--radio-tarjeta-grande)", padding: "18px 22px", marginBottom: 22 }}
        >
          <p style={{ fontSize: 13.5, margin: 0, color: "#A6BFB2" }}>
            Horario de atención: {config.horario}
          </p>
        </div>
      )}

      <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
        {datos.wa_link && (
          <a className="lp-btn lp-btn--verde" href={datos.wa_link} target="_blank" rel="noreferrer noopener">
            Escribirnos ahora
          </a>
        )}
        <button type="button" className="lp-btn lp-btn--claro" onClick={onCerrar}>
          Volver al inicio
        </button>
      </div>
    </section>
  );
}
