/** Bloqueos por plan (requisito 3.2).
 *
 * Tres formas, tal como las define la maqueta:
 *  - Muro: sustituye la pantalla entera (tienda, retenciones, genérico).
 *  - Franja: aviso al pie sin ocultar el contenido (stock).
 *  - Franja de tope: límite alcanzado, en ámbar (clientes).
 *
 * Todos repiten la misma promesa: los datos siguen ahí y vuelven al activar el
 * plan. Ese tono es deliberado y se transcribe literalmente de la maqueta.
 */

import type { ReactNode } from "react";

export function IconoCandado({ tamano = 22 }: { tamano?: number }) {
  return (
    <svg width={tamano} height={tamano} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect
        x="4"
        y="10.5"
        width="16"
        height="11"
        rx="2.5"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path d="M8 10.5V7a4 4 0 018 0v3.5" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

interface MuroProps {
  titulo: string;
  texto: string;
  textoBoton?: string;
  onVerPlanes: () => void;
  extra?: ReactNode;
}

/** Muro de pantalla completa. */
export function MuroPlan({
  titulo,
  texto,
  textoBoton = "Ver los planes",
  onVerPlanes,
  extra,
}: MuroProps) {
  return (
    <section
      className="fc-tarjeta"
      style={{
        borderRadius: "var(--radio-tarjeta-grande)",
        padding: "42px 38px",
        textAlign: "center",
        animation: "dbIn .45s cubic-bezier(.16,1,.3,1) both",
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: 16,
          background: "var(--superficie-tenue)",
          border: "1px solid var(--borde)",
          color: "var(--texto-tenue)",
          display: "grid",
          placeItems: "center",
          margin: "0 auto 18px",
        }}
      >
        <IconoCandado />
      </div>
      <h2 className="fc-titulo" style={{ fontSize: 22, marginBottom: 12 }}>
        {titulo}
      </h2>
      <p
        style={{
          fontSize: 15.5,
          lineHeight: 1.6,
          color: "var(--texto-suave)",
          margin: "0 auto 24px",
          maxWidth: "48ch",
          textWrap: "pretty",
        }}
      >
        {texto}
      </p>
      {extra}
      <button type="button" className="fc-btn fc-btn--primario" onClick={onVerPlanes}>
        {textoBoton}
      </button>
    </section>
  );
}

/** Franja gris al pie: la función falta, pero el contenido sigue visible. */
export function FranjaPlan({
  texto,
  onVerPlanes,
  textoBoton = "Ver planes",
}: {
  texto: string;
  onVerPlanes: () => void;
  textoBoton?: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 13,
        flexWrap: "wrap",
        background: "var(--superficie-tenue)",
        border: "1px solid var(--borde)",
        borderRadius: "var(--radio-panel)",
        padding: "16px 20px",
        marginTop: 16,
      }}
    >
      <span style={{ color: "var(--texto-tenue)", display: "grid" }}>
        <IconoCandado tamano={18} />
      </span>
      <span
        style={{
          flex: 1,
          minWidth: 220,
          fontSize: 13.5,
          lineHeight: 1.5,
          color: "var(--texto-suave)",
          textWrap: "pretty",
        }}
      >
        {texto}
      </span>
      <button type="button" className="fc-btn fc-btn--contorno" onClick={onVerPlanes}>
        {textoBoton}
      </button>
    </div>
  );
}

/** Franja ámbar: el tope se alcanzó. No es una función ausente, es un límite. */
export function FranjaTope({
  texto,
  onSubirPlan,
  textoBoton = "Subir de plan",
}: {
  texto: string;
  onSubirPlan: () => void;
  textoBoton?: string;
}) {
  return (
    <div
      role="status"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 13,
        flexWrap: "wrap",
        background: "var(--aviso-bg)",
        border: "1px solid var(--aviso-borde)",
        borderRadius: "var(--radio-panel)",
        padding: "16px 20px",
        marginTop: 16,
      }}
    >
      <span
        style={{
          flex: 1,
          minWidth: 220,
          fontSize: 13.5,
          lineHeight: 1.5,
          color: "var(--aviso-texto-fuerte)",
          textWrap: "pretty",
        }}
      >
        {texto}
      </span>
      <button type="button" className="fc-btn fc-btn--oscuro" onClick={onSubirPlan}>
        {textoBoton}
      </button>
    </div>
  );
}

/** Chip gris que reemplaza al conteo real cuando el plan no lleva inventario. */
export function ChipSinConteo() {
  return (
    <span className="fc-estado fc-estado--neutro">
      <span className="fc-estado__punto" />
      Sin conteo
    </span>
  );
}
