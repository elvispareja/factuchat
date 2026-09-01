/** Asistente «Nuevo cliente» del panel interno.
 *
 *  Modal de 640 px sobre velo oscuro, con el raíl de pasos, los campos, los
 *  chips y el pie de la maqueta (Superadmin.dc.html, bloque `altaOn`).
 *
 *  DIFERENCIA DELIBERADA CON LA MAQUETA: son DOS pasos, no tres. La maqueta
 *  pide aquí el .p12 y su contraseña, y eso no debe pasar por manos de
 *  Factuchat: el certificado es la identidad de firma del contribuyente y su
 *  clave se la entrega la entidad certificadora solo a él. Quien da de alta no
 *  lo ve, no lo escribe y no lo guarda.
 *
 *  El cliente sube su firma él mismo, desde su panel, la primera vez que entra.
 *  Hasta que lo haga no puede operar: el bloqueo está en el SERVIDOR
 *  (`exigir_firma`, montado sobre los routers de operación), no en la pantalla.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import { sa, type PlanInterno } from "../api";
import { telefonoLimpio } from "../../util/formato";

const PASOS = ["Datos del contribuyente", "Confirmación"];

/** El «origen del alta» de la maqueta, en su mismo orden. */
const ORIGENES = ["Campaña Meta", "Referido", "Orgánico", "TikTok"];

/** Orden de los chips de Plan, fijado como en la maqueta. Ordenarlos por el
 *  precio que devuelve el servidor parecía equivalente —hoy coincide— pero
 *  bastaría una promoción o un cambio de tarifa para que la fila se reordenara
 *  sola delante de quien está dando de alta. */
const ORDEN_PLANES = ["INICIAL", "INDEPENDIENTE", "EMPRENDEDOR", "EMPRESARIO"];

interface Props {
  onCerrar: () => void;
  onCreado: (mensaje: string) => void;
}

export function NuevoCliente({ onCerrar, onCreado }: Props) {
  const [paso, setPaso] = useState(1);
  const [planes, setPlanes] = useState<PlanInterno[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const [ruc, setRuc] = useState("");
  const [telefono, setTelefono] = useState("");
  const [razon, setRazon] = useState("");
  const [comercial, setComercial] = useState("");
  const [correo, setCorreo] = useState("");
  const [plan, setPlan] = useState("INDEPENDIENTE");
  const [origen, setOrigen] = useState("Orgánico");

  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    sa.planes()
      .then((p) =>
        setPlanes(
          p
            .filter((x) => x.vigente_ahora)
            .sort((a, b) => ORDEN_PLANES.indexOf(a.codigo) - ORDEN_PLANES.indexOf(b.codigo)),
        ),
      )
      // Sin planes no hay alta posible: hay que decirlo, no dejar «Cargando…»
      // para siempre y que el operador crea que tarda.
      .catch(() =>
        setError("No pudimos cargar los planes. Cierra y vuelve a abrir el asistente."),
      );
  }, []);

  useEffect(() => {
    panel.current?.focus();
    const alPulsar = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCerrar();
    };
    document.addEventListener("keydown", alPulsar);
    // La página de detrás no debe moverse: si se desplaza, el modal parece
    // flotar sobre un fondo que se escapa.
    const scrollPrevio = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", alPulsar);
      document.body.style.overflow = scrollPrevio;
    };
  }, [onCerrar]);

  const planElegido = planes.find((p) => p.codigo === plan);

  function seguir() {
    setError(null);
    if (paso === 1) {
      if (!/^\d{13}$/.test(ruc.trim())) return setError("El RUC debe tener 13 dígitos");
      if (!ruc.trim().endsWith("001")) return setError("El RUC debe terminar en 001");
      if (!razon.trim()) return setError("Falta la razón social");
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(correo.trim())) return setError("Revisa el correo");
      if (!telefono.trim()) return setError("Falta el número de WhatsApp");
      return setPaso(2);
    }
    void crear();
  }

  async function crear() {
    setEnviando(true);
    setError(null);
    try {
      const r = (await sa.altaCliente({
        ruc: ruc.trim(),
        razon_social: razon.trim(),
        nombre_comercial: comercial.trim() || null,
        email: correo.trim(),
        telefono: telefono.trim() || null,
        plan,
        origen,
      })) as { id: string; plan?: string };
      onCreado(`Alta de cliente: ${razon.trim()} · plan ${r.plan ?? plan}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos crear el cliente");
      setPaso(1);
    } finally {
      setEnviando(false);
    }
  }

  const resumen: Array<[string, string]> = [
    ["RUC", ruc || "—"],
    ["Razón social", razon || "—"],
    ["Nombre comercial", comercial || razon || "—"],
    ["Correo · WhatsApp", `${correo || "—"} · ${telefono || "—"}`],
    [
      "Plan",
      planElegido
        ? `${planElegido.nombre} · $${planElegido.precio}${
            plan === "INICIAL" ? " pago único" : "/mes"
          }`
        : plan,
    ],
    ["Origen del alta", origen],
    ["Firma electrónica", "La sube el propio cliente la primera vez que entra"],
    ["Establecimiento", "001 Matriz · secuencial propio (se crea automático)"],
    // La maqueta cierra el resumen con el ambiente. Aquí no es un parámetro
    // de Configuración sino un hecho: el alta nace siempre en PRUEBAS y pasa a
    // producción cuando el cliente lo pide con su firma ya cargada.
    ["Ambiente SRI", "PRUEBAS · se pasa a producción desde su ficha"],
  ];

  return createPortal(
    <div
      className="fc-modal fc-modal--interno"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCerrar();
      }}
    >
      <div
        ref={panel}
        className="fc-modal__panel"
        role="dialog"
        aria-modal="true"
        aria-label="Nuevo cliente"
        tabIndex={-1}
      >
        <div className="fc-modal__cabecera">
          <h2 className="fc-modal__titulo">Nuevo cliente</h2>
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

        <div className="fc-pasos">
          {PASOS.map((titulo, i) => (
            <div
              key={titulo}
              className="fc-pasos__item"
              data-alcanzado={paso > i ? "1" : "0"}
              data-actual={paso === i + 1 ? "1" : "0"}
            >
              <span className="fc-pasos__num">{i + 1}</span>
              <span className="fc-pasos__label">{titulo}</span>
            </div>
          ))}
        </div>

        <div className="fc-modal__cuerpo fc-scroll">
          {error && (
            <p className="fc-error" role="alert" style={{ marginBottom: 12 }}>
              {error}
            </p>
          )}

          {paso === 1 && (
            <>
              <div className="fc-alta-rejilla">
                <Campo
                  etiqueta="RUC (13 dígitos)"
                  valor={ruc}
                  onCambio={(v) => setRuc(v.replace(/\D/g, "").slice(0, 13))}
                  placeholder="1712345678001"
                  mono
                />
                <Campo
                  etiqueta="WhatsApp"
                  valor={telefono}
                  onCambio={(v) => setTelefono(telefonoLimpio(v))}
                  placeholder="+593 99 000 0000"
                />
              </div>
              <Campo
                etiqueta="Razón social"
                valor={razon}
                onCambio={setRazon}
                placeholder="Como consta en el RUC"
              />
              <div className="fc-alta-rejilla">
                <Campo
                  etiqueta="Nombre comercial"
                  opcional
                  valor={comercial}
                  onCambio={setComercial}
                />
                <Campo
                  etiqueta="Correo"
                  valor={correo}
                  onCambio={setCorreo}
                  tipo="email"
                  placeholder="correo@negocio.ec"
                />
              </div>

              <Grupo titulo="Plan">
                {planes.length === 0 ? (
                  <span style={{ fontSize: 13, color: "var(--texto-tenue)" }}>
                    {error ? "Sin planes disponibles" : "Cargando planes…"}
                  </span>
                ) : (
                  planes.map((p) => (
                    <Chip key={p.codigo} activo={plan === p.codigo} onClick={() => setPlan(p.codigo)}>
                      {p.nombre}
                    </Chip>
                  ))
                )}
              </Grupo>

              <Grupo titulo="Origen del alta">
                {ORIGENES.map((o) => (
                  <Chip key={o} activo={origen === o} onClick={() => setOrigen(o)}>
                    {o}
                  </Chip>
                ))}
              </Grupo>
            </>
          )}

          {paso === 2 && (
            <>
              <div className="fc-resumen">
                {resumen.map(([k, v]) => (
                  <div key={k} className="fc-resumen__fila">
                    <div className="fc-resumen__k">{k}</div>
                    <div className="fc-resumen__v">{v}</div>
                  </div>
                ))}
              </div>
              <p style={{ fontSize: 12.5, lineHeight: 1.55, color: "#8A9A91", margin: 0 }}>
                Su firma electrónica no se pide aquí: el .p12 y su clave son privados del
                contribuyente. Al entrar por primera vez el cliente la sube desde su propio panel, y
                hasta entonces no puede emitir. El alta queda registrada en auditoría con tu nombre
                y la hora.
              </p>
            </>
          )}
        </div>

        <div className="fc-modal__pie">
          <span style={{ fontSize: 12, color: "#8A9A91" }}>Paso {paso} de 2</span>
          <div style={{ display: "flex", gap: 9 }}>
            {paso > 1 && (
              <button
                type="button"
                className="fc-btn fc-btn--contorno"
                onClick={() => {
                  setError(null);
                  setPaso(paso - 1);
                }}
                disabled={enviando}
              >
                Atrás
              </button>
            )}
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              onClick={seguir}
              disabled={enviando}
            >
              {enviando ? "Creando…" : paso === 2 ? "Crear cliente" : "Continuar"}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function Campo({
  etiqueta,
  valor,
  onCambio,
  tipo = "text",
  mono,
  placeholder,
  opcional,
}: {
  etiqueta: string;
  valor: string;
  onCambio: (v: string) => void;
  tipo?: string;
  mono?: boolean;
  placeholder?: string;
  opcional?: boolean;
}) {
  return (
    <label className="fc-alta-campo">
      <span>
        {etiqueta} {opcional && <em>(opcional)</em>}
      </span>
      <input
        type={tipo}
        value={valor}
        placeholder={placeholder}
        autoComplete="off"
        data-mono={mono ? "1" : "0"}
        onChange={(e) => onCambio(e.target.value)}
      />
    </label>
  );
}

function Grupo({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="fc-alta-rotulo">{titulo}</div>
      <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>{children}</div>
    </div>
  );
}

function Chip({
  activo,
  onClick,
  children,
}: {
  activo: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className="fc-sa-chip" aria-pressed={activo} onClick={onClick}>
      {children}
    </button>
  );
}
