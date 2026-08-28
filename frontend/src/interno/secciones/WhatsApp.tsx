/** WhatsApp: consumo, presupuesto y alerta de proyección (Superadmin, esWa).
 *
 *  El costo sale de la tarifa vigente en la fecha de cada conversación, así que
 *  el alza de Meta de octubre de 2026 no reescribe lo ya consumido. */

import { useEffect, useState } from "react";
import { api } from "../../api/cliente";
import { Cargando, ErrorSeccion, Vacio } from "../../ui/Estados";
import { dinero } from "../../util/formato";

interface Consumo {
  desde: string;
  mensajes: number;
  conversaciones_cobradas: number;
  costo_total: string;
  empresa: { mensajes: number; costo: string };
  usuario: { mensajes: number; costo: string };
  presupuesto: string;
  gastado: string;
  proyectado: string;
  pct_presupuesto: number;
  sobre_presupuesto: boolean;
  alerta: boolean;
  umbral_alerta_pct: number;
  dias_transcurridos: number;
  dias_del_mes: number;
  por_cliente: Array<{ tenant_id: string; mensajes: number; costo: string }>;
}

export function WhatsApp() {
  const [datos, setDatos] = useState<Consumo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Consumo>("/sa/whatsapp/consumo")
      .then(setDatos)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));
  }, []);

  if (error) return <ErrorSeccion mensaje={error} />;
  if (!datos) return <Cargando />;

  const sinPresupuesto = Number(datos.presupuesto) === 0;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      {datos.alerta && !sinPresupuesto && (
        <section
          role="alert"
          style={{
            background: datos.sobre_presupuesto ? "var(--error-bg)" : "var(--aviso-bg)",
            border: `1px solid ${datos.sobre_presupuesto ? "var(--error-borde)" : "var(--aviso-borde)"}`,
            borderRadius: "var(--radio-panel)",
            padding: "16px 20px",
          }}
        >
          <p
            style={{
              margin: 0,
              fontSize: 13.5,
              color: datos.sobre_presupuesto ? "var(--error-texto)" : "var(--aviso-texto-fuerte)",
            }}
          >
            {datos.sobre_presupuesto
              ? `A este ritmo el mes cerrará en ${dinero(datos.proyectado)}, por encima del presupuesto de ${dinero(datos.presupuesto)}.`
              : `La proyección del mes va en el ${datos.pct_presupuesto}% del presupuesto (umbral de aviso: ${datos.umbral_alerta_pct}%).`}
          </p>
        </section>
      )}

      <div className="fc-kpi">
        <Tarjeta etiqueta="Mensajes del mes" valor={String(datos.mensajes)} />
        <Tarjeta
          etiqueta="Conversaciones cobradas"
          valor={String(datos.conversaciones_cobradas)}
          nota="Meta cobra por ventana de 24 h"
        />
        <Tarjeta etiqueta="Gastado" valor={dinero(datos.gastado)} />
        <Tarjeta
          etiqueta="Proyección del mes"
          valor={dinero(datos.proyectado)}
          nota={`día ${datos.dias_transcurridos} de ${datos.dias_del_mes}`}
        />
      </div>

      <section className="fc-tarjeta">
        <p className="fc-kicker">Quién abre la conversación</p>
        <p style={{ fontSize: 13, color: "var(--texto-tenue)", margin: "6px 0 14px" }}>
          Las que abre el usuario no se cobran. Las que abrimos nosotros con una plantilla, sí.
        </p>
        <Fila
          etiqueta="Iniciadas por la empresa"
          mensajes={datos.empresa.mensajes}
          costo={datos.empresa.costo}
        />
        <Fila
          etiqueta="Iniciadas por el usuario"
          mensajes={datos.usuario.mensajes}
          costo={datos.usuario.costo}
        />
      </section>

      <section className="fc-tarjeta fc-tarjeta--tabla">
        <div style={{ padding: "18px 20px", borderBottom: "1px solid var(--borde)" }}>
          <p className="fc-kicker">Consumo por cliente</p>
        </div>
        {datos.por_cliente.length === 0 ? (
          <Vacio titulo="Todavía no hay consumo este mes." />
        ) : (
          <table className="fc-tabla">
            <thead>
              <tr>
                <th scope="col">Inquilino</th>
                <th scope="col" className="fc-num">Mensajes</th>
                <th scope="col" className="fc-num">Costo</th>
              </tr>
            </thead>
            <tbody>
              {datos.por_cliente.map((c) => (
                <tr key={c.tenant_id}>
                  <td className="fc-mono" style={{ fontSize: 11.5 }}>
                    {c.tenant_id.slice(0, 8)}…
                  </td>
                  <td className="fc-num">{c.mensajes}</td>
                  <td className="fc-num">{dinero(c.costo)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Tarjeta({ etiqueta, valor, nota }: { etiqueta: string; valor: string; nota?: string }) {
  return (
    <div className="fc-tarjeta" style={{ padding: "18px 20px 20px" }}>
      <div className="fc-kicker" style={{ marginBottom: 8 }}>
        {etiqueta}
      </div>
      <div className="fc-cifra" style={{ fontSize: 24 }}>
        {valor}
      </div>
      {nota && (
        <div style={{ fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 4 }}>{nota}</div>
      )}
    </div>
  );
}

function Fila({
  etiqueta,
  mensajes,
  costo,
}: {
  etiqueta: string;
  mensajes: number;
  costo: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 12,
        padding: "11px 0",
        borderBottom: "1px solid var(--borde)",
      }}
    >
      <span style={{ fontSize: 13.5 }}>{etiqueta}</span>
      <span style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>{mensajes} mensajes</span>
      <span className="fc-cifra" style={{ fontSize: 15 }}>
        {dinero(costo)}
      </span>
    </div>
  );
}
