/** Avisos automáticos (Superadmin.dc.html, dentro de `esConfig`).
 *
 *  Los tres textos que el sistema envía por su cuenta: pre-declaración de IVA,
 *  cupo agotado y pago vencido. Antes vivían fijos en el código y cambiar una
 *  frase exigía un despliegue.
 *
 *  Las variables entre llaves NO son decorativas: Meta registra cada plantilla
 *  con un número fijo de parámetros posicionales. Si se borra una, el mensaje
 *  sale con los datos descolocados o Meta lo rechaza —y cobra igual el
 *  intento—. Por eso el servidor valida antes de guardar y aquí se avisa antes
 *  de enviar.
 */

import { useCallback, useEffect, useState } from "react";
import { sa, type AvisoAutomatico, type Operador } from "../api";

export function AvisosAutomaticos({ operador }: { operador: Operador }) {
  const [avisos, setAvisos] = useState<AvisoAutomatico[] | null>(null);
  const [textos, setTextos] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);

  const cargar = useCallback(async () => {
    try {
      const lista = await sa.avisos();
      setAvisos(lista);
      setTextos(Object.fromEntries(lista.map((a) => [a.aviso, a.texto])));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos cargar los avisos");
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  if (!avisos) return null;

  const cambiados = avisos.filter((a) => textos[a.aviso] !== a.texto);

  async function guardar() {
    if (cambiados.length === 0) {
      setAviso("No cambiaste ningún texto.");
      window.setTimeout(() => setAviso(null), 4000);
      return;
    }
    setGuardando(true);
    setError(null);
    try {
      await sa.guardarAvisos(Object.fromEntries(cambiados.map((a) => [a.aviso, textos[a.aviso]])));
      setAviso(
        cambiados.length === 1 ? "Texto guardado." : `${cambiados.length} textos guardados.`,
      );
      await cargar();
      window.setTimeout(() => setAviso(null), 5000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos guardar los textos");
    } finally {
      setGuardando(false);
    }
  }

  return (
    <section className="fc-sa-panel">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 14,
        }}
      >
        <h2 className="fc-sa-panel__titulo">Avisos automáticos</h2>
        {operador.es_superadmin && (
          <button
            type="button"
            className="fc-btn fc-btn--oscuro"
            onClick={() => void guardar()}
            disabled={guardando}
          >
            {guardando ? "Guardando…" : "Guardar textos"}
          </button>
        )}
      </div>

      <div className="fc-avisos">
        {avisos.map((a) => (
          <div key={a.aviso}>
            <label className="fc-alta-rotulo" htmlFor={`aviso-${a.aviso}`}>
              {a.etiqueta}
              {a.editado && (
                <span style={{ fontWeight: 500, color: "var(--verde-medio)" }}> · editado</span>
              )}
            </label>
            <textarea
              id={`aviso-${a.aviso}`}
              className="fc-avisos__texto"
              rows={5}
              value={textos[a.aviso] ?? ""}
              readOnly={!operador.es_superadmin}
              onChange={(e) => setTextos((t) => ({ ...t, [a.aviso]: e.target.value }))}
            />
            <div className="fc-avisos__pie">
              <span title={`Plantilla registrada en Meta: ${a.plantilla_meta}`}>
                {a.variables.map((v) => `{${v}}`).join(" ")}
              </span>
              {a.editado && operador.es_superadmin && (
                <button
                  type="button"
                  onClick={() => setTextos((t) => ({ ...t, [a.aviso]: a.texto_original }))}
                >
                  Volver al original
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <p style={{ fontSize: 11.5, color: "#8A9A91", margin: "10px 0 0", lineHeight: 1.5 }}>
        Las variables entre llaves son obligatorias: cada plantilla está aprobada por Meta con esos
        parámetros exactos. Si falta una, el aviso no se envía.
      </p>
      {aviso && (
        <p style={{ fontSize: 12.5, color: "var(--verde-medio)", margin: "8px 0 0" }}>{aviso}</p>
      )}
      {error && (
        <p className="fc-error" role="alert" style={{ marginTop: 8 }}>
          {error}
        </p>
      )}
    </section>
  );
}
