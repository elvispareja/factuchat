/** Tutoriales (maqueta líneas 1103-1158), con los cinco temas de subTut. */

import { useState } from "react";

type Tema = "empezar" | "comprobantes" | "declarar" | "inventario" | "plan";

const TEMAS: Array<{ id: Tema; label: string; titulo: string }> = [
  { id: "empezar", label: "Empezar", titulo: "Cómo usar el sistema" },
  { id: "comprobantes", label: "Comprobantes", titulo: "Entender los comprobantes" },
  { id: "declarar", label: "Declarar", titulo: "Mis pagos tributarios" },
  { id: "inventario", label: "Inventario", titulo: "Inventario y tienda" },
  { id: "plan", label: "Tu plan", titulo: "Tu plan" },
];

export function Tutoriales() {
  const [tema, setTema] = useState<Tema>("empezar");
  const activo = TEMAS.find((t) => t.id === tema)!;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <section className="fc-tarjeta--oscura">
        <div className="fc-halo" />
        <div style={{ position: "relative", zIndex: 1 }}>
          <p className="fc-kicker" style={{ color: "var(--texto-tenue-oscuro)" }}>
            Empieza por aquí
          </p>
          <p
            style={{
              fontFamily: "var(--fuente-mano)",
              fontSize: 26,
              color: "var(--verde-claro)",
              margin: "6px 0 0",
            }}
          >
            Aprende sin apuro
          </p>
        </div>
      </section>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {TEMAS.map((t) => (
          <button
            key={t.id}
            type="button"
            className="fc-chip"
            aria-pressed={tema === t.id}
            onClick={() => setTema(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <section className="fc-tarjeta">
        <h2 className="fc-titulo" style={{ fontSize: 20, marginBottom: 10 }}>
          {activo.titulo}
        </h2>
        <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--texto-suave)" }}>
          Los tutoriales de este tema llegan en la próxima entrega. Mientras tanto, el asistente
          responde tus dudas en tus propias palabras desde el chat.
        </p>
      </section>
    </div>
  );
}
