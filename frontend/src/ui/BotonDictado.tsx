/** Botón de dictado que escribe MIENTRAS hablas.
 *
 *  Se acopla a un campo que ya existe en vez de sustituirlo: así el campo
 *  conserva su longitud máxima, su validación y su estado deshabilitado, y el
 *  teclado sigue siendo el camino principal. En un navegador que no sabe
 *  reconocer voz, el botón no se pinta y no pasa nada más.
 *
 *  Lo que se está oyendo aparece en gris debajo del campo y se sustituye por el
 *  texto definitivo en cuanto el reconocedor lo confirma. Esa es la diferencia
 *  con grabar y transcribir después: se ve avanzar y se corrige sobre la marcha.
 */

import { useDictado } from "./dictado";

interface Props {
  /** Cada trozo YA confirmado. Normalmente se añade al final del campo. */
  onTexto: (trozo: string) => void;
  disabled?: boolean;
  idioma?: string;
  /** Qué se dicta, para el lector de pantalla: «Dictar el motivo». */
  etiqueta?: string;
}

export function BotonDictado({ onTexto, disabled, idioma, etiqueta = "" }: Props) {
  const d = useDictado(onTexto, idioma);
  if (!d.soportado) return null;

  const que = etiqueta ? ` ${etiqueta}` : "";
  return (
    <div className="fc-dictado">
      <button
        type="button"
        className="fc-dictado__micro"
        data-escuchando={d.escuchando ? "1" : "0"}
        onClick={d.alternar}
        disabled={disabled}
        aria-pressed={d.escuchando}
        aria-label={d.escuchando ? `Dejar de dictar${que}` : `Dictar${que}`}
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect x="9" y="2" width="6" height="11" rx="3" />
          <path d="M5 10a7 7 0 0 0 14 0M12 17v5" />
        </svg>
        {d.escuchando ? "Escuchando…" : "Dictar"}
      </button>

      {/* aria-live para que un lector de pantalla vaya cantando lo que se oye */}
      {d.escuchando && (
        <span className="fc-dictado__eco" aria-live="polite">
          {d.parcial || "habla y aparecerá aquí"}
        </span>
      )}

      {d.error && (
        <span className="fc-dictado__error" role="alert">
          {d.error}
        </span>
      )}
    </div>
  );
}
