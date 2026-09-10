/** «Números que pueden facturar» de Mi cuenta (maqueta líneas 1028-1046).
 *
 *  Cada teléfono de esta lista puede emitir por WhatsApp en nombre de la
 *  empresa. El bot resuelve de quién es un mensaje mirando precisamente aquí,
 *  así que quitar una fila deja a ese teléfono fuera al instante.
 *
 *  EL NÚMERO SE ESCRIBE COMO SALGA. Da igual `0993053670`, `+593 99 305 3670`
 *  o con espacios: el servidor lo normaliza al formato que entiende Meta y
 *  devuelve `mostrar` ya compuesto. Aquí no se formatea nada, para que no haya
 *  dos sitios donde vive la misma regla.
 *
 *  La maqueta pinta las filas sin botón de quitar —es un prototipo estático—,
 *  así que el botón reutiliza el mismo estilo que «Editar» de la lista de
 *  establecimientos, que sí está en la maqueta.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api/cliente";

export interface NumeroAutorizado {
  id: string;
  numero: string;
  mostrar: string;
  etiqueta: string;
  principal: boolean;
  created_at: string;
}

/** El icono de WhatsApp de la maqueta, tal cual. */
function IconoWhatsApp() {
  return (
    <span
      style={{
        width: 32,
        height: 32,
        borderRadius: 10,
        background: "#FBFCFA",
        border: "1px solid #E4E9E2",
        display: "grid",
        placeItems: "center",
        flexShrink: 0,
      }}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="#16794A" aria-hidden="true">
        <path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.46 1.32 4.96L2 22l5.25-1.38a9.9 9.9 0 004.79 1.22h.01c5.46 0 9.91-4.45 9.91-9.91S17.5 2 12.04 2zm5.8 14.06c-.24.68-1.4 1.3-1.93 1.35-.53.05-1.03.24-2.9-.62-2.23-1.02-3.63-3.36-3.74-3.51-.11-.16-.9-1.24-.9-2.37 0-1.13.58-1.68.79-1.91.2-.23.44-.29.59-.29.15 0 .3 0 .43.01.14.01.32-.5.5.39.18.44.6 1.51.65 1.62.05.11.08.24.01.38-.7.15-.13.24-.26.38-.13.14-.25.25-.36.4-.12.14-.26.3-.11.57.15.27.63 1.05 1.36 1.7.93.83 1.67 1.09 1.94 1.21.27.12.42.1.58-.6.16-.16.7-.79.89-1.06.19-.27.38-.22.63-.13.25.9 1.6.78 1.87.92.28.14.46.21.53.32.7.11.7.64-.17 1.32z" />
      </svg>
    </span>
  );
}

interface Props {
  /** Cuántos permite el plan. Lo trae `plan.numeros_whatsapp`. */
  tope: number;
}

export function NumerosQueFacturan({ tope }: Props) {
  const [numeros, setNumeros] = useState<NumeroAutorizado[] | null>(null);
  const [abierto, setAbierto] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quitando, setQuitando] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<NumeroAutorizado[]>("/numeros-whatsapp")
      .then(setNumeros)
      .catch(() => setNumeros([]));
  }, []);

  const cabenMas = numeros !== null && numeros.length < tope;

  async function quitar(n: NumeroAutorizado) {
    setQuitando(n.id);
    setError(null);
    try {
      setNumeros(await api.delete<NumeroAutorizado[]>(`/numeros-whatsapp/${n.id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos quitar el número");
    } finally {
      setQuitando(null);
    }
  }

  return (
    <section className="fc-tarjeta">
      <p className="fc-kicker">Números que pueden facturar</p>
      <p style={{ fontSize: 13, lineHeight: 1.5, color: "var(--texto-suave)", margin: "0 0 16px" }}>
        Cada número emite sobre esta misma cuenta, con tus clientes y tu numeración.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
        {numeros === null && (
          <p style={{ fontSize: 13, color: "var(--texto-tenue)", margin: 0 }}>Consultando…</p>
        )}

        {numeros?.length === 0 && (
          <p style={{ fontSize: 13, lineHeight: 1.55, color: "var(--texto-suave)", margin: 0 }}>
            Todavía no hay ninguno. Autoriza tu WhatsApp y podrás facturar escribiéndole al bot.
          </p>
        )}

        {numeros?.map((n) => (
          <div
            key={n.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              border: "1px solid #E4E9E2",
              background: "#FFFFFF",
              borderRadius: 13,
              padding: "13px 15px",
            }}
          >
            <IconoWhatsApp />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: "var(--texto)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {n.mostrar}
              </div>
              <div style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>{n.etiqueta}</div>
            </div>
            <span
              style={{
                fontSize: 11.5,
                fontWeight: 600,
                color: "#16794A",
                whiteSpace: "nowrap",
                flexShrink: 0,
              }}
            >
              {n.principal ? "Principal" : "Autorizado"}
            </span>
            <button
              type="button"
              className="fc-btn fc-btn--contorno"
              style={{ flexShrink: 0, padding: "8px 15px", fontSize: 13 }}
              disabled={quitando !== null}
              onClick={() => void quitar(n)}
            >
              {quitando === n.id ? "Quitando…" : "Quitar"}
            </button>
          </div>
        ))}
      </div>

      {error && (
        <p className="fc-error" role="alert" style={{ marginBottom: 10 }}>
          {error}
        </p>
      )}

      <button
        type="button"
        className={cabenMas ? "fc-btn fc-btn--contorno" : "fc-btn fc-btn--bloqueado"}
        style={{ width: "100%" }}
        disabled={!cabenMas}
        title={cabenMas ? undefined : "Un segundo número viene con el plan Empresario"}
        onClick={() => setAbierto(true)}
      >
        {cabenMas ? "Autorizar otro número" : "Un segundo número viene con Empresario"}
      </button>

      {numeros !== null && tope > 1 && (
        <p style={{ fontSize: 12, color: "var(--texto-tenue)", margin: "10px 0 0", textAlign: "center" }}>
          {numeros.length} de {tope} según tu plan
        </p>
      )}

      {abierto && (
        <ModalAutorizar
          onCerrar={() => setAbierto(false)}
          onGuardado={(lista) => {
            setNumeros(lista);
            setAbierto(false);
          }}
        />
      )}
    </section>
  );
}

function ModalAutorizar({
  onCerrar,
  onGuardado,
}: {
  onCerrar: () => void;
  onGuardado: (lista: NumeroAutorizado[]) => void;
}) {
  const [numero, setNumero] = useState("");
  const [etiqueta, setEtiqueta] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panel.current?.focus();
    function alPulsar(e: KeyboardEvent) {
      if (e.key === "Escape") onCerrar();
    }
    document.addEventListener("keydown", alPulsar);
    return () => document.removeEventListener("keydown", alPulsar);
  }, [onCerrar]);

  const puedeGuardar = numero.trim().length >= 7 && etiqueta.trim().length >= 2;

  async function guardar() {
    if (!puedeGuardar) return;
    setGuardando(true);
    setError(null);
    try {
      onGuardado(
        await api.post<NumeroAutorizado[]>("/numeros-whatsapp", {
          numero: numero.trim(),
          etiqueta: etiqueta.trim(),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos autorizar el número");
    } finally {
      setGuardando(false);
    }
  }

  return createPortal(
    <div
      className="fc-modal"
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
        aria-label="Autorizar un número"
        tabIndex={-1}
      >
        <div className="fc-modal__cabecera">
          <div>
            <p className="fc-kicker">Números que pueden facturar</p>
            <h2
              style={{
                fontFamily: "var(--fuente-titulo)",
                fontSize: 19,
                letterSpacing: "-0.025em",
                fontWeight: 700,
                margin: "2px 0 0",
                color: "var(--texto)",
              }}
            >
              Autorizar otro número
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
          <label className="fc-label" htmlFor="na-numero">
            Número de WhatsApp
          </label>
          <input
            id="na-numero"
            className="fc-campo"
            value={numero}
            inputMode="tel"
            autoComplete="tel"
            onChange={(e) => setNumero(e.target.value)}
            placeholder="0993053670"
            disabled={guardando}
          />
          <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: "6px 0 16px", lineHeight: 1.5 }}>
            Escríbelo como quieras. Si es de otro país, ponle el signo + y su código.
          </p>

          <label className="fc-label" htmlFor="na-etiqueta">
            De quién es
          </label>
          <input
            id="na-etiqueta"
            className="fc-campo"
            value={etiqueta}
            maxLength={60}
            onChange={(e) => setEtiqueta(e.target.value)}
            placeholder="Karina, mostrador"
            disabled={guardando}
          />
          <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: "6px 0 0", lineHeight: 1.5 }}>
            Solo para que reconozcas la fila. No sale en ninguna factura.
          </p>

          {error && (
            <p className="fc-error" role="alert" style={{ marginTop: 12 }}>
              {error}
            </p>
          )}
        </div>

        <div className="fc-modal__pie">
          <button type="button" className="fc-btn fc-btn--contorno" onClick={onCerrar}>
            Cancelar
          </button>
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            disabled={!puedeGuardar || guardando}
            onClick={() => void guardar()}
          >
            {guardando ? "Autorizando…" : "Autorizar"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
