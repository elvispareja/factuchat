/** Entrada al panel, en dos pasos y sin contraseña.
 *
 *  1. El correo. El servidor manda un código de seis dígitos a esa dirección.
 *  2. El código.
 *
 *  El personal interno no recibe correo: su código sale de la app de
 *  autenticación que ya tiene. La pantalla NO distingue los dos casos ni el
 *  servidor lo cuenta: decir «a esta cuenta no le mandamos correo» revelaría
 *  quién trabaja aquí a cualquiera que pruebe direcciones.
 *
 *  Por lo mismo, el paso 1 responde igual exista la cuenta o no.
 */

import { useEffect, useRef, useState } from "react";
import { api, sesion } from "./api/cliente";

interface Respuesta {
  access_token: string;
  refresh_token: string;
}

const REENVIO_S = 30;

export function Login({ onEntrar, onVolver }: { onEntrar: () => void; onVolver?: () => void }) {
  const [paso, setPaso] = useState<1 | 2>(1);
  const [email, setEmail] = useState("");
  const [codigo, setCodigo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [espera, setEspera] = useState(0);
  const campoCodigo = useRef<HTMLInputElement>(null);

  // Cuenta atrás para poder pedir otro código sin machacar el botón
  useEffect(() => {
    if (espera <= 0) return;
    const t = window.setTimeout(() => setEspera(espera - 1), 1000);
    return () => window.clearTimeout(t);
  }, [espera]);

  useEffect(() => {
    if (paso === 2) campoCodigo.current?.focus();
  }, [paso]);

  async function pedirCodigo(e?: React.FormEvent) {
    e?.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const r = await api.autenticar<{ detail: string }>("/auth/codigo", { email: email.trim() });
      setAviso(r.detail);
      setPaso(2);
      setEspera(REENVIO_S);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos enviar el código");
    } finally {
      setEnviando(false);
    }
  }

  async function entrar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const datos = await api.autenticar<Respuesta>("/auth/login", {
        email: email.trim(),
        codigo: codigo.trim(),
      });
      sesion.guardar(datos.access_token, datos.refresh_token);
      onEntrar();
    } catch (err) {
      const mensaje = err instanceof Error ? err.message : "No pudimos entrar";
      setError(mensaje);
      setCodigo("");
      campoCodigo.current?.focus();
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
      <form
        className="fc-tarjeta"
        style={{ width: "100%", maxWidth: 400 }}
        onSubmit={paso === 1 ? pedirCodigo : entrar}
      >
        <p
          style={{
            fontFamily: "var(--fuente-mano)",
            fontSize: 32,
            color: "var(--verde-medio)",
            margin: "0 0 4px",
          }}
        >
          Factuchat
        </p>
        <p style={{ fontSize: 13.5, color: "var(--texto-tenue)", margin: "0 0 22px" }}>
          {paso === 1 ? "Entra con tu correo. Sin contraseña." : "Escribe el código de 6 dígitos."}
        </p>

        {onVolver && paso === 1 && (
          <button
            type="button"
            onClick={onVolver}
            className="fc-btn fc-btn--texto"
            style={{ padding: 0, marginBottom: 18 }}
          >
            ← Volver a la web
          </button>
        )}

        {paso === 1 && (
          <>
            <label className="fc-label" htmlFor="email">
              Correo
            </label>
            <input
              id="email"
              className="fc-campo"
              type="email"
              autoComplete="username"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{ marginBottom: 20 }}
            />
          </>
        )}

        {paso === 2 && (
          <>
            <p style={{ fontSize: 13, color: "var(--texto-suave)", margin: "0 0 16px" }}>
              {aviso} Si tu cuenta usa app de autenticación, ábrela.
            </p>

            <label className="fc-label" htmlFor="codigo">
              Código
            </label>
            <input
              id="codigo"
              ref={campoCodigo}
              className="fc-campo fc-mono"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={8}
              required
              value={codigo}
              onChange={(e) => setCodigo(e.target.value.replace(/\D/g, ""))}
              style={{ marginBottom: 14, fontSize: 20, letterSpacing: "0.24em" }}
            />

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 10,
                alignItems: "center",
                marginBottom: 20,
              }}
            >
              <button
                type="button"
                className="fc-btn fc-btn--texto"
                style={{ padding: 0, fontSize: 12.5 }}
                onClick={() => {
                  setPaso(1);
                  setCodigo("");
                  setError(null);
                }}
              >
                ← Otro correo
              </button>
              <button
                type="button"
                className="fc-btn fc-btn--texto"
                style={{ padding: 0, fontSize: 12.5 }}
                disabled={espera > 0 || enviando}
                onClick={() => void pedirCodigo()}
              >
                {espera > 0 ? `Reenviar en ${espera}s` : "Reenviar código"}
              </button>
            </div>
          </>
        )}

        {error && (
          <p className="fc-error" role="alert" style={{ marginBottom: 14 }}>
            {error}
          </p>
        )}

        <button
          type="submit"
          className="fc-btn fc-btn--primario"
          style={{ width: "100%", padding: 12 }}
          disabled={enviando}
        >
          {enviando ? "Un momento…" : paso === 1 ? "Enviarme el código" : "Entrar"}
        </button>
      </form>
    </main>
  );
}
