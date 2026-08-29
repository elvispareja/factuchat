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
import { HeroWebgl } from "./HeroWebgl";
import { PhoneHero } from "./PhoneHero";
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

/** Iconos de redes sociales — colores de marca e íconos SVG literales de la
 * maqueta (líneas 1598-1612 y 1741-1744). REDES solo trae nombre/url. */
const ICONOS_REDES: Record<string, { color: string; path: string }> = {
  Instagram: {
    color: "#E4405F",
    path: "M12 2.16c3.2 0 3.58.01 4.85.07 1.17.05 1.96.24 2.65.5.72.28 1.3.66 1.87 1.23a5 5 0 011.23 1.87c.27.7.46 1.49.51 2.65.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.05 1.17-.24 1.96-.5 2.65a5.6 5.6 0 01-3.1 3.1c-.7.27-1.49.46-2.66.51-1.27.06-1.65.07-4.85.07s-3.58-.01-4.85-.07c-1.17-.05-1.96-.24-2.65-.5a5.6 5.6 0 01-3.1-3.1c-.27-.7-.46-1.49-.51-2.66C2.17 15.58 2.16 15.2 2.16 12s.01-3.58.07-4.85c.05-1.17.24-1.96.5-2.65a5 5 0 011.23-1.87A5 5 0 015.84 2.2c.7-.27 1.49-.46 2.65-.51C9.76 2.17 10.14 2.16 12 2.16zm0 2.32c-3.14 0-3.5.01-4.73.07-.94.04-1.5.2-1.9.35-.47.19-.8.4-1.14.75-.35.34-.56.68-.75 1.15-.15.4-.31.95-.35 1.89-.06 1.24-.07 1.6-.07 4.74s.01 3.5.07 4.73c.4.94.2 1.5.35 1.9.19.47.4.8.75 1.14.34.35.68.56 1.15.75.4.15.95.31 1.89.35 1.24.06 1.6.07 4.73.07s3.5-.01 4.73-.07c.94-.04 1.5-.2 1.9-.35.47-.19.8-.4 1.14-.75.35-.34.56-.67.75-1.15.15-.4.31-.95.35-1.89.06-1.24.07-1.6.07-4.73s-.01-3.5-.07-4.73c-.04-.94-.2-1.5-.35-1.9-.19-.47-.4-.8-.75-1.14a3.1 3.1 0 00-1.15-.75c-.4-.15-.95-.31-1.89-.35-1.24-.06-1.6-.07-4.73-.07zm0 3.94a5.58 5.58 0 110 11.16 5.58 5.58 0 010-11.16zm0 9.2a3.62 3.62 0 100-7.24 3.62 3.62 0 000 7.24zm7.1-9.44a1.3 1.3 0 11-2.6 0 1.3 1.3 0 012.6 0z",
  },
  Facebook: {
    color: "#1877F2",
    path: "M22 12.06C22 6.5 17.52 2 12 2S2 6.5 2 12.06c0 5.02 3.66 9.18 8.44 9.94v-7.03H7.9v-2.9h2.54V9.85c0-2.51 1.49-3.9 3.77-3.9 1.1 0 2.24.2 2.24.2v2.46h-1.26c-1.24 0-1.63.78-1.63 1.57v1.88h2.78l-.45 2.9h-2.33V22c4.78-.76 8.44-4.92 8.44-9.94z",
  },
  LinkedIn: {
    color: "#0A66C2",
    path: "M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.85 0-2.13 1.45-2.13 2.94v5.67H9.35V9h3.41v1.56h.05c.47-.9 1.63-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 110-4.12 2.06 2.06 0 010 4.12zM7.12 20.45H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.22.79 24 1.77 24h20.45c.98 0 1.78-.78 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z",
  },
  YouTube: {
    color: "#FF0000",
    path: "M23.5 6.19a3.02 3.02 0 00-2.12-2.14C19.5 3.55 12 3.55 12 3.55s-7.5 0-9.38.5A3.02 3.02 0 00.5 6.19C0 8.07 0 12 0 12s0 3.93.5 5.81a3.02 3.02 0 002.12 2.14c1.88.5 9.38.5 9.38.5s7.5 0 9.38-.5a3.02 3.02 0 002.12-2.14C24 15.93 24 12 24 12s0-3.93-.5-5.81zM9.55 15.57V8.43L15.82 12l-6.27 3.57z",
  },
  TikTok: {
    color: "#010101",
    path: "M21 8.3a6.9 6.9 0 01-4.03-1.29v5.87a5.35 5.35 0 11-4.62-5.3v2.7a2.66 2.66 0 101.87 2.54V2h2.75a4.15 4.15 0 004.03 3.71V8.3",
  },
};

/* Línea de tiempo "Para quién es" (diseno/Facturas IA.dc.html líneas 1050-1094):
   3 puntos escalonados conectados a una línea vertical, cada uno con su ícono. */
const TIMELINE_LAYOUT = [
  { ml: 0, dot: -34, seg: -25 },
  { ml: 44, dot: -78, seg: -69 },
  { ml: 16, dot: -50, seg: -41 },
];
const TIMELINE_ICONO = [
  <svg key="0" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#16794A" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 11.5a8.4 8.4 0 01-9 8.4 9.3 9.3 0 01-3.9-.8L3 21l1.9-4.8A8.2 8.2 0 013.5 11.5a8.4 8.4 0 019-8.4 8.4 8.4 0 018.5 8.4z" />
  </svg>,
  <svg key="1" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#16794A" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2.6l7.5 3.2v5.4c0 4.7-3.2 9-7.5 10.2-4.3-1.2-7.5-5.5-7.5-10.2V5.8z" />
    <path d="M9 12l2.2 2.2L15.5 10" />
  </svg>,
  <svg key="2" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#16794A" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 20V10" />
    <path d="M10 20V4" />
    <path d="M16 20v-7" />
    <path d="M22 20H2" />
  </svg>,
];

/* "Navegación intuitiva" (diseno/Facturas IA.dc.html líneas 1167-1210):
   grid de 2 columnas, cada tarjeta con su propio desnivel y flotación. */
const CAPACIDAD_LAYOUT = [
  { mt: 0, anim: "fiFloatA", delay: "0s" },
  { mt: 46, anim: "fiFloatB", delay: "-0.6s" },
  { mt: 14, anim: "fiFloatC", delay: "-1.2s" },
  { mt: 58, anim: "fiFloatD", delay: "-1.9s" },
];
const CAPACIDAD_ICONO = [
  <svg key="0" width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="#16794A" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 11.5L21 3l-8.5 18-2.2-7.3z" />
    <path d="M10.3 13.7L21 3" />
  </svg>,
  <svg key="1" width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="#16794A" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="10.5" cy="10.5" r="7" />
    <path d="M20.5 20.5l-5-5" />
  </svg>,
  <svg key="2" width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="#16794A" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 20V11" />
    <path d="M10 20V4" />
    <path d="M16 20v-6" />
    <path d="M22 20H2" />
  </svg>,
  <svg key="3" width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="#16794A" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <ellipse cx="12" cy="5.5" rx="8" ry="3.2" />
    <path d="M4 5.5v6c0 1.8 3.6 3.2 8 3.2s8-1.4 8-3.2v-6" />
    <path d="M4 11.5v6c0 1.8 3.6 3.2 8 3.2s8-1.4 8-3.2v-6" />
  </svg>,
];

/* "Onboarding invisible" (diseno/Facturas IA.dc.html líneas 1358-1408):
   3 filas de 2 columnas, tarjeta izquierda/derecha/izquierda, cada una con
   su propia flotación y retraso para que no se sincronicen. */
const ONBOARDING_LAYOUT = [
  { col: 1, anim: "fiFloatA", delay: "0s" },
  { col: 2, anim: "fiFloatB", delay: "-0.8s" },
  { col: 1, anim: "fiFloatC", delay: "-1.5s" },
];

function IconoRed({ nombre, footer }: { nombre: string; footer?: boolean }) {
  const icono = ICONOS_REDES[nombre];
  if (!icono) return null;
  return (
    <svg width={footer ? 17 : 18} height={footer ? 17 : 18} viewBox="0 0 24 24" fill={footer ? "#9BA8A2" : icono.color}>
      <path d={icono.path} />
    </svg>
  );
}

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
          <button type="button" className="lp-nav__pais" onClick={() => setModalPais(true)} title="Cambiar de país" aria-label="Cambiar de país">
            <svg width="20" height="14" viewBox="0 0 20 14" style={{ display: "block", borderRadius: 2.5, flexShrink: 0, boxShadow: "0 0 0 1px rgba(0,0,0,.18)" }} aria-hidden="true">
              <rect width="20" height="7" fill="#FFDD00" />
              <rect y="7" width="20" height="3.5" fill="#0047A0" />
              <rect y="10.5" width="20" height="3.5" fill="#EC1C24" />
            </svg>
            <span>Ecuador</span>
            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#5CE68F" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
          <BotonEntrar onEntrar={onEntrar} />
          {wa && (
            <a className="lp-btn lp-btn--verde lp-btn--pequeno" href={wa} target="_blank" rel="noreferrer noopener">
              Empieza Ahora!
            </a>
          )}
        </div>

        <HeroWebgl />
        <span className="lp-hero__vineta" aria-hidden="true" />
        <span className="lp-hero__desvanece" aria-hidden="true" />

        <div className="lp-ancho lp-hero-grid">
          <div className="lp-hero">
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

          <PhoneHero />
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
          <div className="lp-timeline">
            <span className="lp-timeline__linea" />
            {BENEFICIOS.map((b, i) => {
              const t = TIMELINE_LAYOUT[i];
              return (
                <div key={b.titulo} className="lp-timeline__item" style={{ marginLeft: t.ml, animationDelay: `${i * 0.7}s` }}>
                  <span className="lp-timeline__punto" style={{ left: t.dot }} />
                  <span className="lp-timeline__segmento" style={{ left: t.seg, width: -t.seg }} />
                  <article className="lp-timeline__card">
                    <span className="lp-timeline__icono">{TIMELINE_ICONO[i]}</span>
                    <div style={{ minWidth: 0 }}>
                      <h3>{b.titulo}</h3>
                      <p>{b.texto}</p>
                    </div>
                  </article>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------- documentos */}
      <section id="documentos" className="lp-oscuro lp-seccion">
        <HeroWebgl />
        <span className="lp-doc__vineta" aria-hidden="true" />
        <span className="lp-sweep" aria-hidden="true" />
        <div className="lp-ancho">
          <div className="lp-doc-encabezado">
            <div>
              <p className="lp-eyebrow" style={{ color: "var(--verde-claro)" }}>
                Esquema de comprobantes electrónicos
              </p>
              <h2 className="lp-h2" style={{ margin: 0, maxWidth: "22ch" }}>
                Los seis documentos del SRI. Todos, con su código.
              </h2>
            </div>
            <p className="lp-bajada" style={{ margin: 0, maxWidth: "34ch" }}>
              Cada uno se firma con tu certificado, se transmite al SRI y vuelve autorizado, con su
              XML y su RIDE en PDF.
            </p>
          </div>
          <div className="lp-doc-lista">
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
                  <span style={{ fontSize: 15, lineHeight: 1.55, color: "#a9c7b6" }}>{d.texto}</span>
                  {d.nota && (
                    <span className="lp-doc__nota">
                      <i />
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
      <section className="lp-seccion lp-seccion--respira">
        <span className="lp-respira lp-respira--a" aria-hidden="true" />
        <span className="lp-respira lp-respira--b" aria-hidden="true" />
        <div className="lp-ancho">
          <p className="lp-firma">Navegación intuitiva</p>
          <h2 className="lp-h2">
            Un menú. <span style={{ color: "var(--verde-medio)" }}>4 opciones.</span> Cero laberintos.
          </h2>
          <p className="lp-bajada" style={{ marginBottom: 30 }}>
            Diseñado para humanos. Escribe un “Hola”, elige lo que necesitas y deja que la IA
            trabaje. Olvídate de los portales enredados.
          </p>
          <div className="lp-capacidades">
            {CAPACIDADES.map((c, i) => {
              const l = CAPACIDAD_LAYOUT[i];
              return (
                <div key={c.titulo} className="lp-capacidades__item" style={{ marginTop: l.mt, animationName: l.anim, animationDelay: l.delay }}>
                  <article className="lp-capacidades__card">
                    <span className="lp-capacidades__icono">{CAPACIDAD_ICONO[i]}</span>
                    <div style={{ minWidth: 0 }}>
                      <h3>{c.titulo}</h3>
                      <p>{c.texto}</p>
                    </div>
                  </article>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------- reportes */}
      <section id="reporte" className="lp-oscuro lp-oscuro--hondo lp-oscuro--grid lp-seccion">
        <span className="lp-sweep" aria-hidden="true" />
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
      <section className="lp-seccion lp-retenciones">
        <span className="lp-respira lp-respira--ambar" aria-hidden="true" />
        <span className="lp-respira lp-respira--b" aria-hidden="true" />
        <div className="lp-ancho lp-retenciones__grid">
          <article className="lp-xml">
            <span className="lp-xml__scan" aria-hidden="true" />
            <div className="lp-xml__header">
              <p className="lp-xml__eyebrow">Comprobante de retención</p>
              <span className="lp-xml__estado">
                <i />
                Leyendo XML
              </span>
            </div>
            <h3 className="lp-xml__titulo">
              Lo lee, lo clasifica
              <br />y lo guarda.
            </h3>
            <p className="lp-xml__sub">
              Tú solo reenvías el archivo al chat. Estos son los datos que Factuchat extrae de un
              comprobante:
            </p>
            {[
              ["Agente de retención", "RUC 0992...001"],
              ["Documento", "001-001-000001428"],
              ["Base imponible", "$450.00"],
              ["Impuesto", "Renta · 10%"],
              ["Valor retenido", "$45.00"],
            ].map(([k, v], i) => (
              <div key={k} className={`lp-xml__fila${i === 4 ? " lp-xml__fila--total" : ""}`} style={{ animationDelay: `${400 + i * 150}ms` }}>
                <span>{k}</span>
                <strong>{v}</strong>
              </div>
            ))}
            <div className="lp-xml__pie">
              <span className="lp-xml__check">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#8A6410" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 12.5l5.5 5.5L20 7" />
                </svg>
              </span>
              Archivado y sumado a tu saldo del periodo.
            </div>
          </article>

          <div>
            <p className="lp-firma">No regales tu dinero</p>
            <h2 className="lp-h2">
              Cada retención es efectivo.{" "}
              <span style={{ color: "var(--verde-medio)" }}>
                Nosotros evitamos que la pierdas en el correo.
              </span>
            </h2>
            <div className="lp-retenciones__item">
              <span className="lp-retenciones__icono">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#16794A" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="2.5" y="4.5" width="19" height="15" rx="2.4" />
                  <path d="M3 6l9 6.5L21 6" />
                </svg>
              </span>
              <p>
                Cuando una empresa te paga, te retiene una parte. Ese documento baja lo que pagas
                de Impuesto a la Renta, pero siempre termina sepultado entre miles de emails.
              </p>
            </div>
            <div className="lp-retenciones__item">
              <span className="lp-retenciones__icono">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#16794A" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 11.5a8.4 8.4 0 01-9 8.4 9.3 9.3 0 01-3.9-.8L3 21l1.9-4.8A8.2 8.2 0 013.5 11.5a8.4 8.4 0 019-8.4 8.4 8.4 0 018.5 8.4z" />
                </svg>
              </span>
              <p>
                <strong>Cero estrés:</strong> Solo reenvía el archivo a tu chat de WhatsApp.
                Nuestra IA lee el XML, lo clasifica automáticamente y te entrega tu saldo
                consolidado justo a tiempo para declarar.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------- onboarding */}
      <section className="lp-onboarding">
        <span className="lp-respira lp-respira--onb-a" aria-hidden="true" />
        <span className="lp-respira lp-respira--onb-b" aria-hidden="true" />
        <span className="lp-sweep" aria-hidden="true" />
        <div className="lp-ancho">
          <div className="lp-onboarding__cabecera">
            <p className="lp-firma">Onboarding invisible</p>
            <h2 className="lp-h2">
              De hoy en adelante…{" "}
              <span style={{ color: "var(--verde-whatsapp)" }}>factura sin enredos.</span>
            </h2>
            <p className="lp-bajada">
              Sin instalaciones largas. Conectas tu firma, le enseñas a la IA quiénes son tus
              clientes y empiezas a facturar desde WhatsApp.
            </p>
          </div>

          <div className="lp-flujo">
            <span className="lp-flujo__linea" aria-hidden="true">
              <span className="lp-flujo__pulso" aria-hidden="true" />
            </span>
            {ONBOARDING.map((p, i) => {
              const l = ONBOARDING_LAYOUT[i];
              return (
                <div key={p.paso} className="lp-flujo__fila">
                  <span className="lp-flujo__punto" aria-hidden="true" />
                  <div
                    className="lp-flujo__col"
                    style={{ gridColumn: l.col, animationName: l.anim, animationDelay: l.delay }}
                  >
                    <article className="lp-flujo__card">
                      <div className="lp-flujo__num">{p.paso}</div>
                      <h3>{p.titulo}</h3>
                      <p>{p.texto}</p>
                    </article>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------ planes */}
      <section id="planes" className="lp-seccion">
        <div className="lp-ancho">
          <div style={{ textAlign: "center", maxWidth: "50ch", margin: "0 auto 46px" }}>
            <p className="lp-eyebrow" style={{ justifyContent: "center" }}>
              Planes
            </p>
            <h2 className="lp-h2" style={{ margin: "0 0 16px" }}>
              Pagas por lo que emites.
            </h2>
            <p className="lp-bajada" style={{ margin: 0 }}>
              Consultar, pedir reportes, guardar clientes y crear servicios no consume nada. Solo
              cuentan los comprobantes que van al SRI.
            </p>
          </div>

          {planes.length === 0 ? (
            <p className="lp-bajada">Cargando los planes…</p>
          ) : (
            <div className="lp-planes">
              {planes.map((p) => {
                const copy = PLANES_COPY[p.codigo];
                if (!copy) return null;
                const oscuro = Boolean(copy.destacado);
                return (
                  <article
                    key={p.codigo}
                    className={`lp-plan${oscuro ? " lp-plan--destacado" : ""}`}
                  >
                    {copy.destacado && <span className="lp-plan__badge">{copy.destacado}</span>}
                    <h3
                      style={{
                        fontFamily: "var(--fuente-titulo)",
                        fontSize: 17.5,
                        fontWeight: 700,
                        letterSpacing: "-.025em",
                        margin: "0 0 4px",
                        color: oscuro ? "#FFFFFF" : undefined,
                      }}
                    >
                      {p.nombre}
                    </h3>
                    <p
                      style={{
                        fontSize: 13.5,
                        lineHeight: 1.45,
                        margin: "0 0 16px",
                        color: oscuro ? "#A6BFB2" : "#3E5A4E",
                      }}
                    >
                      {copy.tagline}
                    </p>
                    <div className="lp-plan__precio" style={{ color: oscuro ? "#FFFFFF" : undefined }}>
                      ${Number(p.precio).toFixed(2)}
                    </div>
                    <p style={{ fontSize: 13, margin: "0 0 18px", color: oscuro ? "#A6BFB2" : "#3E5A4E" }}>
                      {copy.periodicidad}
                    </p>
                    <ul
                      className="lp-plan__feats"
                      style={{
                        borderTop: `1px solid ${oscuro ? "#2A5344" : "#EFF2EE"}`,
                        paddingTop: 16,
                      }}
                    >
                      {copy.features.map((f) => (
                        <li key={f}>
                          <span className="lp-plan__check" style={{ color: oscuro ? "#5CE68F" : "#16794A" }}>
                            ✓
                          </span>
                          <span>{f}</span>
                        </li>
                      ))}
                    </ul>
                    {copy.nota && (
                      <p
                        style={{
                          fontSize: 12.5,
                          lineHeight: 1.45,
                          color: "#3E5A4E",
                          background: "rgba(34,197,94,.07)",
                          border: "1px solid rgba(22,121,74,.18)",
                          borderRadius: 12,
                          padding: "10px 13px",
                          margin: "auto 0 14px",
                        }}
                      >
                        <strong style={{ color: "#123D2F" }}>Ideal para probar Factuchat.</strong>{" "}
                        {copy.nota}
                      </p>
                    )}
                    <button
                      type="button"
                      className={`lp-btn ${oscuro ? "lp-btn--verde" : "lp-btn--contorno"}`}
                      style={{ width: "100%", marginTop: copy.nota ? 0 : "auto" }}
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
              border: "1px solid #E4E9E2",
              borderRadius: 20,
              background: "#FFFFFF",
              padding: "26px 28px 28px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 20 }}>
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: "#22C55E",
                  display: "inline-block",
                  flexShrink: 0,
                }}
              />
              <div
                style={{
                  fontFamily: "var(--fuente-mono)",
                  fontSize: 10.5,
                  fontWeight: 700,
                  letterSpacing: ".14em",
                  textTransform: "uppercase",
                  color: "#3E5A4E",
                }}
              >
                Tus comprobantes no se queman
              </div>
            </div>
            <div className="lp-acumula">
              {ACUMULACION.map((a, i) => (
                <div key={a.n} style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 9 }}>
                    <span className={`lp-acumula__n${i === 1 ? " lp-acumula__n--dark" : ""}`}>{a.n}</span>
                    <div
                      style={{
                        fontFamily: "var(--fuente-titulo)",
                        fontSize: 15.5,
                        fontWeight: 700,
                        letterSpacing: "-.02em",
                        color: "#123D2F",
                      }}
                    >
                      {a.titulo}
                    </div>
                  </div>
                  <p style={{ fontSize: 14, lineHeight: 1.55, color: "#3E5A4E", margin: 0 }}>
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
        <HeroWebgl accent="#7A8A84" background="#08090A" />
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
        <div className="lp-faq-grid">
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
    <section id="contacto" className="lp-seccion" style={{ background: "#FFFFFF" }}>
      <div className="lp-ancho lp-contacto-grid">
        <div>
          <p className="lp-firma" style={{ fontSize: 30, color: "#16794A" }}>
            Hablemos
          </p>
          <h2 className="lp-h2" style={{ fontSize: 38 }}>
            Contáctanos
          </h2>
          <p className="lp-bajada" style={{ marginBottom: 22, fontSize: 15.5 }}>
            ¿Qué podemos hacer por ti? Escríbenos y te respondemos el mismo día.
          </p>

          <div style={{ display: "flex", gap: 9, marginBottom: 26 }}>
            {REDES.map((r) => (
              <a
                key={r.nombre}
                href={r.url}
                title={r.nombre}
                target="_blank"
                rel="noreferrer noopener"
                className="lp-social"
                style={{ "--marca": ICONOS_REDES[r.nombre]?.color } as React.CSSProperties}
              >
                <IconoRed nombre={r.nombre} />
              </a>
            ))}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
            {tarjetas.map((t) => (
              <a
                key={t.titulo}
                href={t.href}
                className="lp-contacto-item"
                style={{ textDecoration: "none", cursor: t.href ? "pointer" : "default" }}
              >
                <span className="lp-contacto-item__icono">
                  <IconoContacto titulo={t.titulo} />
                </span>
                <span style={{ minWidth: 0 }}>
                  <span className="lp-contacto-item__etq">{t.titulo}</span>
                  <span className="lp-contacto-item__valor">{t.valor}</span>
                </span>
              </a>
            ))}
          </div>
        </div>

        <form onSubmit={enviar} className="lp-contacto-form">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginBottom: 18 }}>
            <label className="lp-campo" style={{ margin: 0 }}>
              <span>Nombres y Apellidos</span>
              <input
                value={nombre}
                onChange={(e) => setNombre(e.target.value)}
                placeholder="María Andrade"
                required
              />
            </label>
            <label className="lp-campo" style={{ margin: 0 }}>
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="maria@correo.com"
                required
              />
            </label>
            <label className="lp-campo" style={{ margin: 0 }}>
              <span>Teléfono</span>
              <input value={telefono} onChange={(e) => setTelefono(e.target.value)} placeholder="099 000 0000" />
            </label>
            <label className="lp-campo" style={{ margin: 0 }}>
              <span>Asunto</span>
              <select value={asunto} onChange={(e) => setAsunto(e.target.value)}>
                {ASUNTOS_CONTACTO.map((a) => (
                  <option key={a}>{a}</option>
                ))}
              </select>
            </label>
          </div>
          <label className="lp-campo" style={{ marginBottom: 22 }}>
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

        <div style={{ alignSelf: "stretch", display: "flex", flexDirection: "column" }}>
          <div
            style={{
              fontFamily: "var(--fuente-titulo)",
              fontSize: 16,
              fontWeight: 700,
              letterSpacing: "-.02em",
              color: "#123D2F",
              marginBottom: 12,
            }}
          >
            Quito - Ecuador
          </div>
          <div className="lp-mapa">
            {config && (
              <iframe
                src={`https://maps.google.com/maps?q=${encodeURIComponent(config.direccion)}&z=16&hl=es&output=embed`}
                title="Ubicación de Factuchat"
                loading="lazy"
                referrerPolicy="no-referrer-when-downgrade"
              />
            )}
            {config && (
              <a href={config.maps_url} target="_blank" rel="noreferrer noopener" className="lp-mapa__abrir">
                Abrir en Maps
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M8 5h11v11" />
                  <path d="M19 5L6 18" />
                </svg>
              </a>
            )}
            <div className="lp-mapa__pie">{config?.direccion ?? ""}</div>
          </div>
        </div>
      </div>
    </section>
  );
}

function IconoContacto({ titulo }: { titulo: string }) {
  if (titulo === "Email") {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5CE68F" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2.5" y="4.5" width="19" height="15" rx="2.5" />
        <path d="M3 6.5l9 6 9-6" />
      </svg>
    );
  }
  if (titulo === "Teléfono") {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5CE68F" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6.5 3h3l1.8 4.5-2.3 1.6a11.5 11.5 0 005.9 5.9l1.6-2.3L21 14.5v3a3 3 0 01-3.3 3A17.5 17.5 0 013.5 6.3 3 3 0 016.5 3z" />
      </svg>
    );
  }
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5CE68F" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 21.5s7-5.6 7-11a7 7 0 10-14 0c0 5.4 7 11 7 11z" />
      <circle cx="12" cy="10.3" r="2.6" />
    </svg>
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
          <p style={{ fontSize: 14, lineHeight: 1.55, maxWidth: "36ch", marginBottom: 22 }}>
            Comprobantes electrónicos válidos ante el SRI, emitidos desde WhatsApp con Factuchat®, tu
            asistente virtual contable.
          </p>
          <div style={{ display: "flex", gap: 9 }}>
            {REDES.map((r) => (
              <a key={r.nombre} href={r.url} title={r.nombre} target="_blank" rel="noreferrer noopener" className="lp-social lp-social--footer">
                <IconoRed nombre={r.nombre} footer />
              </a>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", gap: 56 }}>
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
                  color: "#8B9993",
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
                  color: "#8B9993",
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

const BANDERAS_PAIS: Record<string, JSX.Element> = {
  Ecuador: (
    <svg width="30" height="21" viewBox="0 0 20 14" className="lp-pais-op__bandera">
      <rect width="20" height="7" fill="#FFDD00" />
      <rect y="7" width="20" height="3.5" fill="#0047A0" />
      <rect y="10.5" width="20" height="3.5" fill="#EC1C24" />
    </svg>
  ),
  Panamá: (
    <svg width="30" height="21" viewBox="0 0 20 14" className="lp-pais-op__bandera">
      <rect width="20" height="14" fill="#FFFFFF" />
      <rect x="10" width="10" height="7" fill="#D21034" />
      <rect y="7" width="10" height="7" fill="#005293" />
      <path d="M5 1.8l.6 1.7h1.8L5.9 4.6l.6 1.8L5 5.3 3.5 6.4l.6-1.8L2.6 3.5h1.8z" fill="#005293" />
      <path d="M15 8.8l.6 1.7h1.8l-1.5 1.1.6 1.8-1.5-1.1-1.5 1.1.6-1.8-1.5-1.1h1.8z" fill="#D21034" />
    </svg>
  ),
  Perú: (
    <svg width="30" height="21" viewBox="0 0 20 14" className="lp-pais-op__bandera">
      <rect width="20" height="14" fill="#FFFFFF" />
      <rect width="6.67" height="14" fill="#D91023" />
      <rect x="13.33" width="6.67" height="14" fill="#D91023" />
    </svg>
  ),
  Colombia: (
    <svg width="30" height="21" viewBox="0 0 20 14" className="lp-pais-op__bandera">
      <rect width="20" height="7" fill="#FCD116" />
      <rect y="7" width="20" height="3.5" fill="#003893" />
      <rect y="10.5" width="20" height="3.5" fill="#CE1126" />
    </svg>
  ),
  Chile: (
    <svg width="30" height="21" viewBox="0 0 20 14" className="lp-pais-op__bandera">
      <rect width="20" height="7" fill="#FFFFFF" />
      <rect y="7" width="20" height="7" fill="#D52B1E" />
      <rect width="7" height="7" fill="#0039A6" />
      <path d="M3.5 1.6l.62 1.9h2l-1.62 1.18.62 1.9L3.5 5.4 1.88 6.58l.62-1.9L.88 3.5h2z" fill="#FFFFFF" />
    </svg>
  ),
};

function ModalPais({ onCerrar }: { onCerrar: () => void }) {
  return (
    <div
      className="lp-modal lp-modal--pais"
      role="dialog"
      aria-modal="true"
      aria-label="¿En qué país facturas?"
    >
      <div className="lp-modal__panel lp-modal__panel--pais">
        <p className="lp-logo">Factuchat®</p>
        <h2 className="lp-h2" style={{ fontSize: 28, marginBottom: 9 }}>
          ¿En qué país facturas?
        </h2>
        <p style={{ fontSize: 14.5, margin: "0 0 24px" }}>
          Así te mostramos los documentos y los datos que pide tu entidad tributaria.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {PAISES.map((p) =>
            p.disponible ? (
              <button
                key={p.nombre}
                type="button"
                className="lp-pais-op"
                onClick={onCerrar}
              >
                {BANDERAS_PAIS[p.nombre]}
                <span className="lp-pais-op__nombre">{p.nombre}</span>
                <span className="lp-pais-op__badge">{p.badge}</span>
              </button>
            ) : (
              <div key={p.nombre} className="lp-pais-op lp-pais-op--pronto" aria-disabled="true">
                {BANDERAS_PAIS[p.nombre]}
                <span className="lp-pais-op__nombre">{p.nombre}</span>
                <span className="lp-pais-op__badge lp-pais-op__badge--tenue">{p.badge}</span>
              </div>
            ),
          )}
        </div>
        <p className="lp-pais-nota">{NOTA_PAISES}</p>
      </div>
    </div>
  );
}
