/** Simulador de WhatsApp del hero — chrome y copy portados literalmente de
 * diseno/Facturas IA.dc.html (líneas 805-882) y del bundle ejecutable
 * diseno/Factuchat - pagina web.html. Es una demo animada en bucle, no un
 * chat real: reproduce la secuencia de bienvenida tal como la muestra la
 * maqueta, con indicador de "escribiendo…" entre mensajes. */
import { useEffect, useState } from "react";

type Mensaje = {
  lines: { t: string; w?: number }[];
  footer?: string;
  hasButton?: boolean;
  time: string;
};

const GUION: Mensaje[] = [
  {
    lines: [{ t: "¡Hola, Andrea! 👋 Soy Factuchat®, tu asistente virtual contable." }],
    time: "10:06 a.m.",
  },
  {
    lines: [
      { t: "Escríbeme con texto, así de simple. Mientras más concreto seas, más rápido lo resuelvo." },
    ],
    time: "10:06 a.m.",
  },
  {
    lines: [
      { t: "Toca el botón de abajo y elige qué necesitas hacer. También puedes escribirme con tus palabras." },
    ],
    footer: "Mensajes concisos · voz desde Emprendedor",
    hasButton: true,
    time: "10:06 a.m.",
  },
];

const PAUSA_ENTRE_MENSAJES = 1400;
const PAUSA_ESCRIBIENDO = 900;
const PAUSA_FINAL = 3200;

export function PhoneHero() {
  const [visibles, setVisibles] = useState(0);
  const [escribiendo, setEscribiendo] = useState(false);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setVisibles(GUION.length);
      return;
    }
    let vivo = true;
    let t: ReturnType<typeof setTimeout>;

    async function ciclo() {
      while (vivo) {
        setVisibles(0);
        setEscribiendo(false);
        for (let i = 0; i < GUION.length; i++) {
          await esperar(i === 0 ? 500 : PAUSA_ENTRE_MENSAJES);
          if (!vivo) return;
          setEscribiendo(true);
          await esperar(PAUSA_ESCRIBIENDO);
          if (!vivo) return;
          setEscribiendo(false);
          setVisibles(i + 1);
        }
        await esperar(PAUSA_FINAL);
      }
    }
    function esperar(ms: number) {
      return new Promise<void>((resolve) => {
        t = setTimeout(resolve, ms);
      });
    }
    ciclo();
    return () => {
      vivo = false;
      clearTimeout(t);
    };
  }, []);

  const presencia = escribiendo ? "escribiendo…" : "en línea";

  return (
    <div className="lp-phone-wrap">
      <div className="lp-phone-halo" aria-hidden="true" />
      <div className="lp-phone">
        <div className="lp-phone__screen">
          <div className="lp-phone__statusbar">
            <span>9:41</span>
            <span className="lp-phone__statusicons">
              <svg width="17" height="11" viewBox="0 0 17 11" fill="#000000" aria-hidden="true">
                <rect x="0" y="7.5" width="3" height="3.5" rx="1" />
                <rect x="4.6" y="5.3" width="3" height="5.7" rx="1" />
                <rect x="9.2" y="3" width="3" height="8" rx="1" />
                <rect x="13.8" y="0.6" width="3" height="10.4" rx="1" />
              </svg>
              <svg width="15" height="11" viewBox="0 0 16 12" fill="none" stroke="#000000" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
                <path d="M1.4 4.2a9.6 9.6 0 0113.2 0" />
                <path d="M4.1 7a5.8 5.8 0 017.8 0" />
                <circle cx="8" cy="10" r=".9" fill="#000000" stroke="none" />
              </svg>
            </span>
          </div>

          <div className="lp-phone__header">
            <span className="lp-phone__back">‹</span>
            <span className="lp-phone__avatar">F</span>
            <span className="lp-phone__titulo">
              <span className="lp-phone__nombre">Factuchat®</span>
              <span className="lp-phone__presencia">{presencia}</span>
            </span>
          </div>

          <div className="lp-phone__cuerpo fc-scroll">
            <div className="lp-phone__fecha">
              <span>HOY</span>
            </div>
            <div className="lp-phone__cifrado">
              <span>🔒 Los mensajes están cifrados de extremo a extremo.</span>
            </div>

            {GUION.slice(0, visibles).map((m, i) => (
              <div className="lp-phone__burbuja" key={i}>
                {m.lines.map((ln, j) => (
                  <div className="lp-phone__linea" key={j} style={ln.w ? { fontWeight: ln.w } : undefined}>
                    {ln.t}
                  </div>
                ))}
                {m.footer && <div className="lp-phone__footer">{m.footer}</div>}
                <div className="lp-phone__hora">{m.time}</div>
                {m.hasButton && (
                  <div className="lp-phone__boton">
                    <button type="button" tabIndex={-1}>
                      ☰ Ver opciones
                    </button>
                  </div>
                )}
              </div>
            ))}

            {escribiendo && (
              <div className="lp-phone__burbuja lp-phone__burbuja--typing">
                <span />
                <span />
                <span />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
