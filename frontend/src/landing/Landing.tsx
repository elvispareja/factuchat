/** Landing pública (diseno/Facturas IA.dc.html).
 *
 * Los precios, los cupos y los países salen del servidor: /publico/planes y
 * /publico/paises. Así la web no puede quedar mintiendo si el superadmin
 * programa un cambio de precio o habilita otro país.
 *
 * El dominio y los datos de contacto vienen de /publico/config porque el
 * dominio definitivo sigue sin confirmarse: cambiarlo es una variable de
 * entorno, no un despliegue de frontend.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import "./landing.css";
import { Checkout, ModalLegal } from "./Checkout";
import {
  ACUMULACION,
  ASUNTOS_CONTACTO,
  BENEFICIOS,
  CAPACIDADES,
  DOCUMENTOS,
  FAQS,
  NAV,
  NOTAS_PLANES,
  NOTA_PAISES,
  ONBOARDING,
  PAISES,
  PLANES_COPY,
  REDES,
  REPORTE_ITEMS,
} from "./datos";
import type { ConfigPublica, PlanPublico } from "./datos";

const BASE = "/api/v1";
const ORDEN = ["INICIAL", "INDEPENDIENTE", "EMPRENDEDOR", "EMPRESARIO"];

export function Landing({ onEntrar }: { onEntrar: () => void }) {
  const [config, setConfig] = useState<ConfigPublica | null>(null);
  const [planes, setPlanes] = useState<PlanPublico[]>([]);
  const [elegido, setElegido] = useState<PlanPublico | null>(null);
  const [modalPais, setModalPais] = useState(true);
  const [progreso, setProgreso] = useState(0);
  const [sticky, setSticky] = useState(false);
  const ultimoY = useRef(0);

  useEffect(() => {
    fetch(`${BASE}/publico/config`)
      .then((r) => r.json())
      .then(setConfig)
      .catch(() => setConfig(null));
    fetch(`${BASE}/publico/planes`)
      .then((r) => r.json())
      .then((p: PlanPublico[]) =>
        setPlanes([...p].sort((a, b) => ORDEN.indexOf(a.codigo) - ORDEN.indexOf(b.codigo))),
      )
      .catch(() => setPlanes([]));
  }, []);

  useEffect(() => {
    function alDesplazar() {
      const alto = document.documentElement.scrollHeight - window.innerHeight;
      const y = window.scrollY;
      setProgreso(alto > 0 ? (y / alto) * 100 : 0);
      setSticky(y > 420 && y < ultimoY.current);
      ultimoY.current = y;
    }
    window.addEventListener("scroll", alDesplazar, { passive: true });
    return () => window.removeEventListener("scroll", alDesplazar);
  }, []);

  const wa = config?.whatsapp ?? null;

  if (elegido) {
    return <Checkout plan={elegido} config={config} onCerrar={() => setElegido(null)} />;
  }

  return (
    <div className="lp">
      <div className="lp-progreso" style={{ width: `${progreso}%` }} aria-hidden="true" />

      <div className="lp-sticky" data-visible={sticky}>
        <div className="lp-ancho lp-nav">
          <span className="lp-logo">Factuchat®</span>
          <nav className="lp-nav__enlaces">
            {NAV.map((n) => (
              <a key={n.id} href={`#${n.id}`}>
                {n.sticky}
              </a>
            ))}
          </nav>
          <BotonEntrar onEntrar={onEntrar} />
          {wa && (
            <a className="lp-btn lp-btn--verde lp-btn--pequeno" href={wa} target="_blank" rel="noreferrer noopener">
              Empezar
            </a>
          )}
        </div>
      </div>

      {/* ------------------------------------------------------------ hero */}
      <header className="lp-oscuro">
        <div className="lp-ancho lp-nav">
          <span className="lp-logo">Factuchat®</span>
          <nav className="lp-nav__enlaces">
            {NAV.map((n) => (
              <a key={n.id} href={`#${n.id}`}>
                {n.hero}
              </a>
            ))}
          </nav>
          <button type="button" className="lp-btn lp-btn--fantasma lp-btn--pequeno" onClick={() => setModalPais(true)}>
            Ecuador
          </button>
          <BotonEntrar onEntrar={onEntrar} />
          {wa && (
            <a className="lp-btn lp-btn--verde lp-btn--pequeno" href={wa} target="_blank" rel="noreferrer noopener">
              Empieza Ahora!
            </a>
          )}
        </div>

        <div className="lp-ancho lp-hero">
          <span className="lp-hero__badge">Comprobantes válidos ante el SRI · Ecuador</span>
          <h1 className="lp-hero__h1">
            Crea tus facturas desde
            <span className="lp-hero__wa">WHATSAPP</span>
            en menos de un minuto.
          </h1>
          <p className="lp-hero__sub">
            No necesitas aprender un sistema nuevo.
            <br />
            Realiza tus comprobantes sin depender de nadie!
          </p>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {wa && (
              <a className="lp-btn lp-btn--verde" href={wa} target="_blank" rel="noreferrer noopener">
                Empezar por WhatsApp
              </a>
            )}
            <a className="lp-btn lp-btn--fantasma" href="#planes">
              Ver planes desde ${planes[0]?.precio ? Number(planes[0].precio).toFixed(2) : "2.99"}
            </a>
          </div>
        </div>
      </header>

      {/* ------------------------------------------------------ para quién */}
      <section id="para-quien" className="lp-seccion">
        <div className="lp-ancho lp-dos">
          <div>
            <p className="lp-firma">Factuchat®</p>
            <h2 className="lp-h2">
              El primer sistema de facturación electrónica que funciona en{" "}
              <em style={{ color: "var(--verde-medio)" }}>WhatsApp</em>.
            </h2>
            <p className="lp-bajada">
              Olvídate de plataformas complejas y manuales de usuario. Escribe lo que vendiste por
              WhatsApp y nuestra IA genera el comprobante electrónico validado por el SRI en
              segundos.
            </p>
          </div>
          <div style={{ display: "grid", gap: 16 }}>
            {BENEFICIOS.map((b) => (
              <article key={b.titulo} className="lp-tarjeta">
                <h3 style={{ fontFamily: "var(--fuente-titulo)", fontSize: 18, margin: "0 0 6px" }}>
                  {b.titulo}
                </h3>
                <p style={{ fontSize: 14.5, lineHeight: 1.55, color: "var(--texto-suave)", margin: 0 }}>
                  {b.texto}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------- documentos */}
      <section id="documentos" className="lp-oscuro lp-seccion">
        <div className="lp-ancho">
          <p className="lp-eyebrow" style={{ color: "var(--verde-claro)" }}>
            Esquema de comprobantes electrónicos
          </p>
          <h2 className="lp-h2">Los seis documentos del SRI. Todos, con su código.</h2>
          <p className="lp-bajada" style={{ marginBottom: 34 }}>
            Cada uno se firma con tu certificado, se transmite al SRI y vuelve autorizado, con su
            XML y su RIDE en PDF.
          </p>
          <div style={{ display: "grid", gap: 10 }}>
            {DOCUMENTOS.map((d) => (
              <article key={d.codigo} className="lp-doc">
                <span className="lp-doc__cod">
                  {d.codigo}
                  <small>Cód. SRI</small>
                </span>
                <span>
                  <strong style={{ fontFamily: "var(--fuente-titulo)", fontSize: 17, display: "block" }}>
                    {d.nombre}
                  </strong>
                  <span style={{ fontSize: 14, lineHeight: 1.5, color: "var(--texto-suave)" }}>
                    {d.texto}
                  </span>
                  {d.nota && (
                    <span
                      style={{
                        display: "block",
                        marginTop: 8,
                        fontSize: 13,
                        color: "var(--aviso-texto-fuerte)",
                        background: "var(--aviso-bg)",
                        border: "1px solid var(--aviso-borde)",
                        borderRadius: 12,
                        padding: "8px 11px",
                      }}
                    >
                      {d.nota}
                    </span>
                  )}
                </span>
                <span className="lp-doc__etq">{d.etiqueta}</span>
              </article>
            ))}
          </div>
          <p className="lp-bajada" style={{ marginTop: 24 }}>
            El código es el que usa el SRI para identificar cada tipo de comprobante. Factuchat lo
            elige por ti.
          </p>
          <p style={{ fontSize: 13.5, color: "var(--verde-claro)", marginTop: 6 }}>
            ✓ Firma con tu certificado · ✓ Transmisión al SRI · ✓ XML y RIDE en segundos
          </p>
        </div>
      </section>

      {/* --------------------------------------------------------- qué hace */}
      <section className="lp-seccion">
        <div className="lp-ancho">
          <p className="lp-firma">Navegación intuitiva</p>
          <h2 className="lp-h2">
            Un menú. <span style={{ color: "var(--verde-medio)" }}>4 opciones.</span> Cero laberintos.
          </h2>
          <p className="lp-bajada" style={{ marginBottom: 30 }}>
            Diseñado para humanos. Escribe un “Hola”, elige lo que necesitas y deja que la IA
            trabaje. Olvídate de los portales enredados.
          </p>
          <div className="lp-cuatro">
            {CAPACIDADES.map((c) => (
              <article key={c.titulo} className="lp-tarjeta">
                <h3 style={{ fontFamily: "var(--fuente-titulo)", fontSize: 17, margin: "0 0 6px" }}>
                  {c.titulo}
                </h3>
                <p style={{ fontSize: 14, lineHeight: 1.55, color: "var(--texto-suave)", margin: 0 }}>
                  {c.texto}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------- reportes */}
      <section id="reporte" className="lp-oscuro lp-seccion">
        <div className="lp-ancho lp-dos">
          <div>
            <p className="lp-firma">El reporte que sí importa</p>
            <h2 className="lp-h2">
              Otros te dicen cuánto vendiste.{" "}
              <span style={{ color: "var(--verde-whatsapp)" }}>Nosotros, cuánto debes declarar.</span>
            </h2>
            <p className="lp-bajada">
              Saber tus ventas no basta. Te damos el número final exacto a pagar, la fecha límite
              según tu RUC y el respaldo en Excel. Sin cálculos enredados.
            </p>
            <ul style={{ listStyle: "none", padding: 0, margin: "22px 0 0", display: "grid", gap: 10 }}>
              {REPORTE_ITEMS.map((i) => (
                <li key={i} style={{ fontSize: 14.5, color: "#CFE3D8" }}>
                  ✓ {i}
                </li>
              ))}
            </ul>
          </div>
          <div className="lp-vidrio">
            <p className="lp-eyebrow" style={{ color: "var(--verde-claro)" }}>
              Resumen fiscal
            </p>
            <p style={{ fontSize: 13, color: "#A6BFB2", margin: "0 0 16px" }}>Ene – Jun 2026</p>
            {[
              ["Ingresos facturados", "$8,420.00"],
              ["IVA cobrado", "$1,263.00"],
              ["Ret. de Renta recibida", "$673.60"],
              ["Ret. de IVA recibida", "$883.10"],
            ].map(([k, v]) => (
              <div key={k} className="lp-resumen__fila">
                <span>{k}</span>
                <strong style={{ color: "var(--texto-sobre-oscuro)" }}>{v}</strong>
              </div>
            ))}
            <div
              style={{
                marginTop: 16,
                background: "rgba(34,197,94,.12)",
                border: "1px solid rgba(92,230,143,.28)",
                borderRadius: 14,
                padding: "13px 15px",
              }}
            >
              <p style={{ fontSize: 12.5, color: "#A6BFB2", margin: "0 0 4px" }}>
                Tu declaración vence
              </p>
              <strong style={{ fontFamily: "var(--fuente-titulo)", fontSize: 19 }}>
                20 de julio de 2026
              </strong>
              <p style={{ fontSize: 12.5, color: "#A6BFB2", margin: "4px 0 0" }}>
                Noveno dígito de tu RUC: 4
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <span className="lp-chip">PDF Resumen</span>
              <span className="lp-chip">XLS Detalle</span>
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------ retenciones */}
      <section className="lp-seccion">
        <div className="lp-ancho lp-dos">
          <div>
            <p className="lp-firma">No regales tu dinero</p>
            <h2 className="lp-h2">
              Cada retención es efectivo.{" "}
              <span style={{ color: "var(--verde-medio)" }}>
                Nosotros evitamos que la pierdas en el correo.
              </span>
            </h2>
            <p className="lp-bajada" style={{ marginBottom: 14 }}>
              Cuando una empresa te paga, te retiene una parte. Ese documento baja lo que pagas de
              Impuesto a la Renta, pero siempre termina sepultado entre miles de emails.
            </p>
            <p className="lp-bajada">
              Cero estrés: Solo reenvía el archivo a tu chat de WhatsApp. Nuestra IA lee el XML, lo
              clasifica automáticamente y te entrega tu saldo consolidado justo a tiempo para
              declarar.
            </p>
          </div>
          <article
            style={{
              background: "rgba(255,251,240,.72)",
              border: "1px solid rgba(233,168,42,.3)",
              borderRadius: "var(--radio-tarjeta-grande)",
              padding: "22px 24px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 14 }}>
              <p className="lp-eyebrow" style={{ margin: 0, color: "var(--aviso-texto)" }}>
                Comprobante de retención
              </p>
              <span className="fc-estado fc-estado--aviso">
                <span className="fc-estado__punto" />
                Leyendo XML
              </span>
            </div>
            <h3 style={{ fontFamily: "var(--fuente-titulo)", fontSize: 22, margin: "0 0 6px" }}>
              Lo lee, lo clasifica
              <br />y lo guarda.
            </h3>
            <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--texto-suave)", margin: "0 0 16px" }}>
              Tú solo reenvías el archivo al chat. Estos son los datos que Factuchat extrae de un
              comprobante:
            </p>
            {[
              ["Agente de retención", "RUC 0992...001"],
              ["Documento", "001-001-000001428"],
              ["Base imponible", "$450.00"],
              ["Impuesto", "Renta · 10%"],
              ["Valor retenido", "$45.00"],
            ].map(([k, v]) => (
              <div
                key={k}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  fontSize: 13.5,
                  padding: "8px 0",
                  borderBottom: "1px solid rgba(233,168,42,.22)",
                  color: "var(--texto-suave)",
                }}
              >
                <span>{k}</span>
                <strong style={{ color: "var(--texto)" }}>{v}</strong>
              </div>
            ))}
            <p style={{ fontSize: 13, color: "var(--exito-texto)", marginTop: 14, marginBottom: 0 }}>
              Archivado y sumado a tu saldo del periodo.
            </p>
          </article>
        </div>
      </section>

      {/* ------------------------------------------------------- onboarding */}
      <section className="lp-oscuro lp-oscuro--hondo lp-seccion">
        <div className="lp-ancho">
          <p className="lp-firma">Onboarding invisible</p>
          <h2 className="lp-h2">
            De hoy en adelante…{" "}
            <span style={{ color: "var(--verde-whatsapp)" }}>factura sin enredos.</span>
          </h2>
          <p className="lp-bajada" style={{ marginBottom: 32 }}>
            Sin instalaciones largas. Conectas tu firma, le enseñas a la IA quiénes son tus clientes
            y empiezas a facturar desde WhatsApp.
          </p>
          <div className="lp-tres">
            {ONBOARDING.map((p) => (
              <article key={p.paso} className="lp-vidrio">
                <span
                  style={{
                    fontFamily: "var(--fuente-titulo)",
                    fontSize: 30,
                    fontWeight: 700,
                    color: "var(--verde-claro)",
                  }}
                >
                  {p.paso}
                </span>
                <h3 style={{ fontFamily: "var(--fuente-titulo)", fontSize: 18, margin: "8px 0 6px" }}>
                  {p.titulo}
                </h3>
                <p style={{ fontSize: 14, lineHeight: 1.55, color: "#A6BFB2", margin: 0 }}>{p.texto}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------ planes */}
      <section id="planes" className="lp-seccion">
        <div className="lp-ancho">
          <p className="lp-eyebrow">Planes</p>
          <h2 className="lp-h2">Pagas por lo que emites.</h2>
          <p className="lp-bajada" style={{ marginBottom: 34 }}>
            Consultar, pedir reportes, guardar clientes y crear servicios no consume nada. Solo
            cuentan los comprobantes que van al SRI.
          </p>

          {planes.length === 0 ? (
            <p className="lp-bajada">Cargando los planes…</p>
          ) : (
            <div className="lp-cuatro">
              {planes.map((p) => {
                const copy = PLANES_COPY[p.codigo];
                if (!copy) return null;
                return (
                  <article
                    key={p.codigo}
                    className={`lp-plan${copy.destacado ? " lp-plan--destacado" : ""}`}
                  >
                    {copy.destacado && <span className="lp-plan__badge">{copy.destacado}</span>}
                    <h3 style={{ fontFamily: "var(--fuente-titulo)", fontSize: 21, margin: 0 }}>
                      {p.nombre}
                    </h3>
                    <p style={{ fontSize: 13.5, margin: "4px 0 0", opacity: 0.8 }}>{copy.tagline}</p>
                    <div className="lp-plan__precio">${Number(p.precio).toFixed(2)}</div>
                    <p style={{ fontSize: 12.5, margin: 0, opacity: 0.75 }}>{copy.periodicidad}</p>
                    <ul className="lp-plan__feats">
                      {copy.features.map((f) => (
                        <li key={f}>
                          <span className="lp-plan__check">✓</span>
                          <span>{f}</span>
                        </li>
                      ))}
                    </ul>
                    {copy.nota && (
                      <p
                        style={{
                          fontSize: 12.5,
                          lineHeight: 1.5,
                          color: "var(--texto-suave)",
                          background: "var(--superficie-tenue)",
                          borderRadius: 12,
                          padding: "10px 12px",
                          margin: "0 0 14px",
                        }}
                      >
                        {copy.nota}
                      </p>
                    )}
                    <button
                      type="button"
                      className={copy.destacado ? "lp-btn lp-btn--verde" : "lp-btn lp-btn--claro"}
                      aria-label={copy.ariaLabel}
                      onClick={() => setElegido(p)}
                    >
                      {copy.boton}
                    </button>
                  </article>
                );
              })}
            </div>
          )}

          <div style={{ display: "grid", gap: 10, margin: "26px 0 34px" }}>
            {NOTAS_PLANES.map((n) => (
              <p key={n} style={{ fontSize: 13, lineHeight: 1.55, color: "var(--texto-tenue)", margin: 0 }}>
                {n}
              </p>
            ))}
          </div>

          <div
            style={{
              border: "1px solid var(--borde)",
              borderRadius: 20,
              padding: "26px 28px",
              background: "var(--superficie)",
            }}
          >
            <p className="lp-eyebrow">Tus comprobantes no se queman</p>
            <div className="lp-tres" style={{ marginTop: 16 }}>
              {ACUMULACION.map((a) => (
                <div key={a.n}>
                  <span
                    style={{
                      fontFamily: "var(--fuente-titulo)",
                      fontSize: 26,
                      fontWeight: 700,
                      color: "var(--verde-medio)",
                    }}
                  >
                    {a.n}
                  </span>
                  <h3 style={{ fontFamily: "var(--fuente-titulo)", fontSize: 16, margin: "4px 0 6px" }}>
                    {a.titulo}
                  </h3>
                  <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--texto-suave)", margin: 0 }}>
                    {a.texto}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------------- FAQ */}
      <Faq />

      {/* ---------------------------------------------------------- contacto */}
      <Contacto config={config} />

      {/* --------------------------------------------------------- CTA final */}
      <section className="lp-oscuro lp-oscuro--hondo lp-seccion" style={{ textAlign: "center" }}>
        <div className="lp-ancho">
          <span className="lp-hero__badge">Factuchat está en línea</span>
          <h2 className="lp-h2" style={{ maxWidth: "17ch", margin: "18px auto 14px" }}>
            Tu próxima factura empieza en un chat.
          </h2>
          <p className="lp-bajada" style={{ margin: "0 auto 26px" }}>
            Escríbenos hoy. Te ayudamos con la firma digital
            <br />y dejamos todo listo para que empieces a facturar.
          </p>
          <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
            {wa && (
              <a className="lp-btn lp-btn--verde" href={wa} target="_blank" rel="noreferrer noopener">
                Empezar por WhatsApp
              </a>
            )}
            <a className="lp-btn lp-btn--fantasma" href="#planes">
              Ver los planes
            </a>
          </div>
          <p className="lp-logo" style={{ fontSize: 66, marginTop: 34 }}>
            Factuchat®
          </p>
          <p className="lp-firma" style={{ fontSize: 34, color: "var(--verde-claro)" }}>
            ¡ Facturar nunca fue tan fácil !
          </p>
        </div>
      </section>

      <Pie config={config} onEntrar={onEntrar} />

      {wa && (
        <a className="lp-fab" href={wa} target="_blank" rel="noreferrer noopener" title="Escribir por WhatsApp">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="#062B18" aria-hidden="true">
            <path d="M12 2a10 10 0 00-8.6 15.05L2 22l5.1-1.34A10 10 0 1012 2zm0 1.9a8.1 8.1 0 016.9 12.3l-.3.5.8 2.9-3-.78-.45.26A8.1 8.1 0 1112 3.9z" />
            <path d="M8.4 7.3c.2-.5.4-.5.6-.5h.5c.2 0 .4 0 .6.5l.8 1.9c.1.3 0 .5-.1.7l-.4.5c-.2.2-.3.4-.1.7a7 7 0 003.3 2.9c.3.1.5.1.7-.1l.6-.7c.2-.2.4-.2.6-.1l1.8.9c.3.1.4.3.4.5 0 .9-.7 1.7-1.6 1.8-.4 0-.9.1-3-1a11 11 0 01-4.5-4.4c-.9-1.6-.9-2.3-.9-2.7a2 2 0 01.8-1.8z" />
          </svg>
        </a>
      )}

      {modalPais && <ModalPais onCerrar={() => setModalPais(false)} />}
    </div>
  );
}

function BotonEntrar({ onEntrar }: { onEntrar: () => void }) {
  return (
    <button type="button" className="lp-btn lp-btn--fantasma lp-btn--pequeno" onClick={onEntrar}>
      Entrar a mi panel
    </button>
  );
}

function Faq() {
  const [abierta, setAbierta] = useState(0);
  return (
    <section id="faq" className="lp-seccion">
      <div className="lp-ancho">
        <p className="lp-firma">Cero letra pequeña</p>
        <h2 className="lp-h2" style={{ color: "#3E5A4E", marginBottom: 30 }}>
          Respuestas claras para que empieces hoy.
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(340px,1fr))", gap: "0 40px" }}>
          {FAQS.map((f, i) => (
            <div key={f.p} className="lp-faq">
              <button
                type="button"
                className="lp-faq__btn"
                aria-expanded={abierta === i}
                onClick={() => setAbierta(abierta === i ? -1 : i)}
              >
                <span className="lp-faq__n">Q{String(i + 1).padStart(2, "0")}</span>
                <span>{f.p}</span>
                <span aria-hidden="true" style={{ textAlign: "right", color: "var(--texto-tenue)" }}>
                  {abierta === i ? "−" : "+"}
                </span>
              </button>
              {abierta === i && (
                <div className="lp-faq__cuerpo">
                  {f.r.map((p, j) => (
                    <p key={j}>{p}</p>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Contacto({ config }: { config: ConfigPublica | null }) {
  const [nombre, setNombre] = useState("");
  const [email, setEmail] = useState("");
  const [telefono, setTelefono] = useState("");
  const [asunto, setAsunto] = useState(ASUNTOS_CONTACTO[0]);
  const [mensaje, setMensaje] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setAviso(null);
    try {
      const r = await fetch(`${BASE}/publico/contacto`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre, email, telefono: telefono || null, asunto, mensaje }),
      });
      const datos = await r.json();
      if (!r.ok) throw new Error(datos?.detail ?? "No pudimos enviar tu mensaje.");
      if (datos.wa_link) window.open(datos.wa_link, "_blank", "noopener");
      setAviso(datos.mensaje);
      setMensaje("");
    } catch (err) {
      setAviso(err instanceof Error ? err.message : "No pudimos enviar tu mensaje.");
    } finally {
      setEnviando(false);
    }
  }

  const tarjetas = useMemo(
    () => [
      { titulo: "Email", valor: config?.email ?? "—", href: config ? `mailto:${config.email}` : undefined },
      {
        titulo: "Teléfono",
        valor: config?.telefono ?? "—",
        href: config ? `tel:${config.telefono_e164}` : undefined,
      },
      { titulo: "Ubicación", valor: config?.direccion ?? "—" },
    ],
    [config],
  );

  return (
    <section id="contacto" className="lp-seccion" style={{ background: "var(--superficie)" }}>
      <div className="lp-ancho lp-dos">
        <div>
          <p className="lp-firma">Hablemos</p>
          <h2 className="lp-h2">Contáctanos</h2>
          <p className="lp-bajada" style={{ marginBottom: 24 }}>
            ¿Qué podemos hacer por ti? Escríbenos y te respondemos el mismo día.
          </p>
          <div style={{ display: "grid", gap: 12, marginBottom: 22 }}>
            {tarjetas.map((t) => (
              <div key={t.titulo} className="lp-tarjeta" style={{ padding: "16px 18px" }}>
                <p className="lp-eyebrow" style={{ margin: 0 }}>
                  {t.titulo}
                </p>
                {t.href ? (
                  <a href={t.href} style={{ fontSize: 15, color: "var(--verde-medio)" }}>
                    {t.valor}
                  </a>
                ) : (
                  <span style={{ fontSize: 15 }}>{t.valor}</span>
                )}
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {REDES.map((r) => (
              <a key={r.nombre} href={r.url} target="_blank" rel="noreferrer noopener" style={{ fontSize: 13.5 }}>
                {r.nombre}
              </a>
            ))}
          </div>
          {config && (
            <p style={{ fontSize: 13, marginTop: 18 }}>
              <a href={config.maps_url} target="_blank" rel="noreferrer noopener">
                Abrir en Maps → Quito - Ecuador
              </a>
            </p>
          )}
        </div>

        <form onSubmit={enviar} className="lp-tarjeta">
          <label className="lp-campo">
            <span>Nombres y Apellidos</span>
            <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="María Andrade" required />
          </label>
          <label className="lp-campo">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="maria@correo.com"
              required
            />
          </label>
          <label className="lp-campo">
            <span>Teléfono</span>
            <input value={telefono} onChange={(e) => setTelefono(e.target.value)} placeholder="099 000 0000" />
          </label>
          <label className="lp-campo">
            <span>Asunto</span>
            <select value={asunto} onChange={(e) => setAsunto(e.target.value)}>
              {ASUNTOS_CONTACTO.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </label>
          <label className="lp-campo">
            <span>Mensaje</span>
            <textarea
              value={mensaje}
              onChange={(e) => setMensaje(e.target.value)}
              rows={5}
              maxLength={2000}
              placeholder="Cuéntanos en pocas líneas qué necesitas."
              required
            />
          </label>
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <button type="submit" className="lp-btn lp-btn--verde" disabled={enviando}>
              {enviando ? "Enviando…" : "Enviar"}
            </button>
            <span style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>
              Se abre WhatsApp con tu mensaje listo para enviar.
            </span>
          </div>
          {aviso && (
            <p role="status" style={{ fontSize: 13, color: "var(--exito-texto)", marginBottom: 0 }}>
              {aviso}
            </p>
          )}
        </form>
      </div>
    </section>
  );
}

function Pie({ config, onEntrar }: { config: ConfigPublica | null; onEntrar: () => void }) {
  const [legal, setLegal] = useState(false);
  return (
    <footer className="lp-pie">
      <div className="lp-ancho lp-tres">
        <div>
          <p className="lp-logo" style={{ marginTop: 0 }}>
            Factuchat®
          </p>
          <p style={{ fontSize: 14, lineHeight: 1.6, maxWidth: "40ch" }}>
            Comprobantes electrónicos válidos ante el SRI, emitidos desde WhatsApp con Factuchat®, tu
            asistente virtual contable.
          </p>
        </div>
        <div style={{ display: "flex", gap: 40 }}>
          <div>
            <p className="lp-eyebrow" style={{ color: "var(--verde-claro)" }}>
              Producto
            </p>
            <div style={{ display: "grid", gap: 8 }}>
              {NAV.map((n) => (
                <a key={n.id} href={`#${n.id}`}>
                  {n.hero}
                </a>
              ))}
            </div>
          </div>
          <div>
            <p className="lp-eyebrow" style={{ color: "var(--verde-claro)" }}>
              Legal
            </p>
            <div style={{ display: "grid", gap: 8 }}>
              <button
                type="button"
                onClick={() => setLegal(true)}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  font: "inherit",
                  fontSize: 14,
                  color: "#A6BFB2",
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                Términos y privacidad
              </button>
              <a href="https://www.sri.gob.ec" target="_blank" rel="noreferrer noopener">
                SRI Ecuador
              </a>
              <button
                type="button"
                onClick={onEntrar}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  font: "inherit",
                  fontSize: 14,
                  color: "#A6BFB2",
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                Entrar a mi panel
              </button>
            </div>
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <p style={{ fontSize: 15, color: "var(--verde-claro)", margin: "0 0 4px" }}>
            {config?.dominio ?? ""}
          </p>
          <p style={{ fontSize: 13, margin: 0 }}>© 2026 Factuchat® · Ecuador</p>
        </div>
      </div>
      {legal && <ModalLegal onCerrar={() => setLegal(false)} />}
    </footer>
  );
}

function ModalPais({ onCerrar }: { onCerrar: () => void }) {
  return (
    <div className="lp-modal" role="dialog" aria-modal="true" aria-label="¿En qué país facturas?">
      <div className="lp-modal__panel" style={{ maxWidth: 460 }}>
        <p className="lp-logo" style={{ color: "var(--verde-medio)", marginTop: 0 }}>
          Factuchat®
        </p>
        <h2 className="lp-h2" style={{ fontSize: 24, marginBottom: 6 }}>
          ¿En qué país facturas?
        </h2>
        <p style={{ fontSize: 13.5, color: "var(--texto-suave)", margin: "0 0 20px" }}>
          Así te mostramos los documentos y los datos que pide tu entidad tributaria.
        </p>
        <div style={{ display: "grid", gap: 8 }}>
          {PAISES.map((p) =>
            p.disponible ? (
              <button
                key={p.nombre}
                type="button"
                className="lp-cuenta"
                style={{ gridTemplateColumns: "1fr auto" }}
                onClick={onCerrar}
              >
                <span style={{ fontSize: 15, fontWeight: 600 }}>{p.nombre}</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--verde-medio)" }}>
                  {p.badge}
                </span>
              </button>
            ) : (
              <div
                key={p.nombre}
                className="lp-cuenta"
                style={{ gridTemplateColumns: "1fr auto", opacity: 0.5, cursor: "not-allowed" }}
                aria-disabled="true"
              >
                <span style={{ fontSize: 15, fontWeight: 600 }}>{p.nombre}</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--texto-tenue)" }}>
                  {p.badge}
                </span>
              </div>
            ),
          )}
        </div>
        <p style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--texto-tenue)", margin: "18px 0 0" }}>
          {NOTA_PAISES}
        </p>
      </div>
    </div>
  );
}
