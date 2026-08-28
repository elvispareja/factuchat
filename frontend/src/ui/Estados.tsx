/** Estados compartidos: cargando, error y vacío. */

export function Cargando({ texto = "Cargando…" }: { texto?: string }) {
  return (
    <div className="fc-tarjeta fc-vacio" role="status" aria-live="polite">
      <span
        style={{
          width: 22,
          height: 22,
          display: "inline-block",
          border: "2px solid var(--borde)",
          borderTopColor: "var(--verde-acento)",
          borderRadius: "50%",
          animation: "dbSpin .8s linear infinite",
          marginBottom: 12,
        }}
        aria-hidden="true"
      />
      <p className="fc-vacio__ayuda">{texto}</p>
    </div>
  );
}

export function ErrorSeccion({ mensaje, onReintentar }: { mensaje: string; onReintentar?: () => void }) {
  return (
    <div className="fc-tarjeta fc-vacio" role="alert">
      <p className="fc-vacio__titulo">No pudimos cargar esta sección</p>
      <p className="fc-vacio__ayuda">{mensaje}</p>
      {onReintentar && (
        <button
          type="button"
          className="fc-btn fc-btn--contorno"
          style={{ marginTop: 16 }}
          onClick={onReintentar}
        >
          Reintentar
        </button>
      )}
    </div>
  );
}

export function Vacio({ titulo, ayuda, accion }: { titulo: string; ayuda?: string; accion?: React.ReactNode }) {
  return (
    <div className="fc-vacio">
      <p className="fc-vacio__titulo">{titulo}</p>
      {ayuda && <p className="fc-vacio__ayuda">{ayuda}</p>}
      {accion && <div style={{ marginTop: 16 }}>{accion}</div>}
    </div>
  );
}
