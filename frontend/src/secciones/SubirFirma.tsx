/** Primer ingreso: subir la firma electrónica.
 *
 *  Hasta que el negocio no tiene su certificado cargado no puede operar, y esa
 *  regla la impone el SERVIDOR (`exigir_firma`): las rutas de operación
 *  responden 403 con el código FIRMA_REQUERIDA. Esta pantalla es la cara de esa
 *  regla, no la regla; por eso ocupa el panel entero en vez de ser un aviso
 *  que se pueda cerrar.
 *
 *  El .p12 y su clave NUNCA se piden fuera de aquí. No los recoge el alta
 *  interna, no los ve el personal de Factuchat y no viajan a ninguna otra
 *  pantalla: el certificado es la identidad de firma del contribuyente. Del
 *  navegador salen una sola vez, por HTTPS, hacia el endpoint que los cifra.
 */

import { useState } from "react";
import { api } from "../api/cliente";
import { usePlan } from "../plan/PlanContexto";

interface Certificado {
  subject: string | null;
  emisor: string | null;
  valido_hasta: string | null;
}

export function SubirFirma() {
  const { recargar } = usePlan();
  const [archivo, setArchivo] = useState<File | null>(null);
  const [clave, setClave] = useState("");
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listo, setListo] = useState<Certificado | null>(null);

  async function subir(e: React.FormEvent) {
    e.preventDefault();
    if (!archivo) return setError("Elige tu archivo .p12");
    if (!clave) return setError("Escribe la clave del certificado");
    setSubiendo(true);
    setError(null);
    try {
      const cert = await api.subir<Certificado>("/certificados", archivo, { password: clave });
      // La clave no se queda en memoria más de lo necesario
      setClave("");
      setListo(cert);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos leer el certificado");
    } finally {
      setSubiendo(false);
    }
  }

  if (listo) {
    return (
      <main className="fc-firma">
        <section className="fc-tarjeta fc-firma__caja">
          <p className="fc-kicker">Firma cargada</p>
          <h1 className="fc-titulo" style={{ fontSize: 24, margin: "4px 0 10px" }}>
            Ya puedes emitir
          </h1>
          <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--texto-suave)" }}>
            {listo.subject}
            {listo.emisor && (
              <>
                <br />
                Emitida por {listo.emisor}
              </>
            )}
          </p>
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            style={{ marginTop: 18 }}
            onClick={() => void recargar()}
          >
            Entrar a mi panel
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="fc-firma">
      <form className="fc-tarjeta fc-firma__caja" onSubmit={subir}>
        <p
          style={{
            fontFamily: "var(--fuente-mano)",
            fontSize: 30,
            color: "var(--verde-medio)",
            margin: "0 0 2px",
          }}
        >
          Factuchat
        </p>
        <h1 className="fc-titulo" style={{ fontSize: 24, margin: "0 0 8px" }}>
          Sube tu firma electrónica
        </h1>
        <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--texto-suave)", margin: 0 }}>
          Es el archivo <strong>.p12</strong> que te entregó tu entidad certificadora (Banco
          Central, Security Data, UANATACA o ANF). Con él firmamos tus comprobantes ante el SRI, así
          que sin él no podemos emitir nada todavía.
        </p>
        <p
          style={{
            fontSize: 12.5,
            lineHeight: 1.55,
            color: "var(--texto-tenue)",
            margin: "10px 0 20px",
          }}
        >
          Se sube una sola vez. El archivo y su clave se guardan con encriptación de grado bancario
          y nadie de Factuchat puede verlos: por eso no te los pedimos al crear tu cuenta.
        </p>

        <label className="fc-p12" style={{ marginBottom: 14 }}>
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
            <path d="M12 16V4M7 9l5-5 5 5M4 20h16" />
          </svg>
          <span style={{ fontSize: 13.5, fontWeight: 600, color: "var(--verde-marca)" }}>
            {archivo ? archivo.name : "Seleccionar archivo .p12"}
          </span>
          {!archivo && <span style={{ fontSize: 12, color: "#8A9A91" }}>o .pfx</span>}
          <input
            type="file"
            accept=".p12,.pfx"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) {
                setArchivo(f);
                setError(null);
              }
            }}
          />
        </label>

        <label className="fc-alta-campo">
          <span>Clave del certificado</span>
          <input
            type="password"
            value={clave}
            autoComplete="off"
            placeholder="La que te dio la entidad certificadora"
            onChange={(e) => setClave(e.target.value)}
          />
        </label>

        {error && (
          <p className="fc-error" role="alert" style={{ marginTop: 4 }}>
            {error}
          </p>
        )}

        <button
          type="submit"
          className="fc-btn fc-btn--primario"
          style={{ width: "100%", padding: 12, marginTop: 16 }}
          disabled={subiendo}
        >
          {subiendo ? "Comprobando…" : "Subir mi firma"}
        </button>

        <p
          style={{
            fontSize: 12,
            lineHeight: 1.55,
            color: "var(--texto-tenue)",
            margin: "16px 0 0",
          }}
        >
          ¿Todavía no la tienes? Se saca en línea y suele estar lista en horas. Escríbenos por
          WhatsApp y te acompañamos en el trámite.
        </p>
      </form>
    </main>
  );
}
