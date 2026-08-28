/** Mi cuenta (maqueta líneas 959-1102): establecimientos, firma electrónica,
 *  números de WhatsApp autorizados y el resumen del plan. */

import { useEffect, useState } from "react";
import { api } from "../api/cliente";
import { usePlan } from "../plan/PlanContexto";
import { Cargando } from "../ui/Estados";
import { fechaCorta } from "../util/formato";

interface Certificado {
  subject: string | null;
  emisor: string | null;
  valido_desde: string | null;
  valido_hasta: string | null;
  activo: boolean;
}

export function MiCuenta({ onVerPlanes }: { onVerPlanes: () => void }) {
  const { plan } = usePlan();
  const [cert, setCert] = useState<Certificado | null | "sin">(null);

  useEffect(() => {
    api
      .get<Certificado>("/certificados")
      .then(setCert)
      .catch(() => setCert("sin"));
  }, []);

  if (!plan) return <Cargando />;

  const puedeSegundoNumero = plan.numeros_whatsapp > 1;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div className="fc-split">
        <section className="fc-tarjeta">
          <p className="fc-kicker">Firma electrónica</p>
          {cert === null && <p style={{ fontSize: 13.5 }}>Consultando…</p>}
          {cert === "sin" && (
            <>
              {/* Este caso ya casi no se ve: sin certificado el panel no se
                  abre y el cliente aterriza directamente en la pantalla de
                  subida. Queda por si el certificado se retira estando dentro. */}
              <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--texto-suave)" }}>
                Tu certificado ya no está activo. Sin él no podemos firmar tus comprobantes ante el
                SRI: vuelve a entrar para subirlo.
              </p>
            </>
          )}
          {cert && cert !== "sin" && (
            <>
              <p style={{ fontSize: 13.5, margin: "8px 0 4px", fontWeight: 600 }}>{cert.subject}</p>
              <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0 }}>
                Emitido por {cert.emisor}
              </p>
              {cert.valido_hasta && (
                <p style={{ fontSize: 13, marginTop: 12 }}>
                  <span className="fc-estado fc-estado--exito">
                    <span className="fc-estado__punto" />
                    Vigente hasta {fechaCorta(cert.valido_hasta.slice(0, 10))}
                  </span>
                </p>
              )}
            </>
          )}
        </section>

        <section className="fc-tarjeta">
          <p className="fc-kicker">Números de WhatsApp</p>
          <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--texto-suave)" }}>
            Desde estos números tu equipo puede emitir comprobantes por chat.
          </p>
          <button
            type="button"
            className={puedeSegundoNumero ? "fc-btn fc-btn--contorno" : "fc-btn fc-btn--bloqueado"}
            style={{ marginTop: 14, width: "100%" }}
            disabled={!puedeSegundoNumero}
            title={
              puedeSegundoNumero ? undefined : "Un segundo número viene con el plan Emprendedor"
            }
          >
            {puedeSegundoNumero
              ? "Autorizar otro número"
              : "Un segundo número viene con Empresario"}
          </button>
        </section>
      </div>

      <section className="fc-tarjeta--oscura">
        <div className="fc-halo" />
        <div style={{ position: "relative", zIndex: 1 }}>
          <p
            className="fc-kicker"
            style={{ color: "var(--texto-tenue-oscuro)", marginBottom: 10 }}
          >
            Tu plan
          </p>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 18 }}>
            <span className="fc-cifra" style={{ fontSize: 28, color: "var(--verde-claro)" }}>
              {plan.nombre}
            </span>
            <span style={{ fontSize: 13, color: "var(--texto-tenue-oscuro)" }}>
              ${plan.precio} al mes
            </span>
          </div>

          <FilaPlan etiqueta="Comprobantes al mes" valor={String(plan.cupo)} />
          <FilaPlan
            etiqueta="Clientes guardados"
            valor={plan.clientes.tope ? `hasta ${plan.clientes.tope}` : "ilimitados"}
          />
          <FilaPlan
            etiqueta="Productos en catálogo"
            valor={plan.productos.tope ? `hasta ${plan.productos.tope}` : "ilimitados"}
          />
          <FilaPlan
            etiqueta="Lo que no uses"
            valor={plan.acumula ? "se acumula" : "es del período"}
            color={plan.acumula ? "var(--verde-claro)" : "#A6BFB2"}
          />

          <button
            type="button"
            className="fc-btn fc-btn--primario"
            style={{ marginTop: 20 }}
            onClick={onVerPlanes}
          >
            Cambiar de plan
          </button>
        </div>
      </section>
    </div>
  );
}

function FilaPlan({
  etiqueta,
  valor,
  color = "#FFFFFF",
}: {
  etiqueta: string;
  valor: string;
  color?: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 12,
        padding: "10px 0",
        borderBottom: "1px solid rgba(92,230,143,.16)",
      }}
    >
      <span style={{ fontSize: 13, color: "var(--texto-tenue-oscuro)" }}>{etiqueta}</span>
      <span style={{ fontSize: 13.5, fontWeight: 600, color }}>{valor}</span>
    </div>
  );
}
