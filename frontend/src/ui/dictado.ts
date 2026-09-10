/** Dictado que escribe MIENTRAS hablas, no después.
 *
 *  La diferencia con grabar-y-transcribir no es de velocidad, es de confianza:
 *  quien dicta ve aparecer las palabras y corrige sobre la marcha. Con una
 *  grabación hay que esperar, leer lo que salió y volver a empezar si se
 *  entendió mal.
 *
 *  Se apoya en el reconocimiento de voz del propio navegador
 *  (`SpeechRecognition`), que entrega resultados PARCIALES según habla la
 *  persona. No hace falta grabar, ni subir nada, ni un proveedor externo.
 *
 *  LO QUE HAY QUE SABER ANTES DE USARLO:
 *
 *  · Chrome, Edge y Chrome de Android sí. **Firefox no lo implementa** y Safari
 *    va a rachas. El componente lo detecta y lo dice, en vez de quedarse mudo.
 *  · En Chrome el audio viaja a los servidores de Google para reconocerlo. Para
 *    dictar la descripción de un producto es razonable; para leer en voz alta
 *    datos de un cliente, conviene saberlo.
 *  · Necesita HTTPS (o localhost), igual que la cámara.
 */

import { useCallback, useEffect, useRef, useState } from "react";

// El navegador no lo trae en sus tipos estándar: se declara lo que se usa.
interface ResultadoVoz {
  readonly isFinal: boolean;
  readonly length: number;
  [i: number]: { readonly transcript: string };
}
interface EventoVoz extends Event {
  readonly resultIndex: number;
  readonly results: { readonly length: number; [i: number]: ResultadoVoz };
}
interface EventoErrorVoz extends Event {
  readonly error: string;
}
interface Reconocedor extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: EventoVoz) => void) | null;
  onerror: ((e: EventoErrorVoz) => void) | null;
  onend: (() => void) | null;
}
type ConstructorReconocedor = new () => Reconocedor;

function fabrica(): ConstructorReconocedor | null {
  const w = window as unknown as {
    SpeechRecognition?: ConstructorReconocedor;
    webkitSpeechRecognition?: ConstructorReconocedor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export interface Dictado {
  /** false ⇒ el navegador no sabe hacerlo; hay que ofrecer teclado y ya está. */
  soportado: boolean;
  escuchando: boolean;
  /** Lo que se está oyendo AHORA, todavía sin confirmar. Se pinta en gris. */
  parcial: string;
  error: string | null;
  alternar: () => void;
  parar: () => void;
}

/** `onTexto` recibe cada trozo YA confirmado, listo para añadir al campo. */
export function useDictado(onTexto: (texto: string) => void, idioma = "es-EC"): Dictado {
  const [soportado] = useState(() => fabrica() !== null);
  const [escuchando, setEscuchando] = useState(false);
  const [parcial, setParcial] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reconocedor = useRef<Reconocedor | null>(null);
  // Si sigue queriendo dictar. Chrome corta solo tras un silencio; sin esta
  // marca, callarse dos segundos para pensar terminaría el dictado.
  const deseado = useRef(false);
  // En un ref y no en el estado: el manejador `onresult` se registra una vez y
  // se quedaría con la primera versión de la función.
  const entregar = useRef(onTexto);
  entregar.current = onTexto;

  const parar = useCallback(() => {
    deseado.current = false;
    reconocedor.current?.stop();
    setEscuchando(false);
    setParcial("");
  }, []);

  useEffect(() => parar, [parar]); // al desmontar, el micrófono se suelta

  const alternar = useCallback(() => {
    if (deseado.current) {
      parar();
      return;
    }
    const Fabrica = fabrica();
    if (!Fabrica) return;

    const r = new Fabrica();
    r.lang = idioma;
    r.continuous = true;
    r.interimResults = true; // ← esto es lo que hace que aparezcan las letras
    r.maxAlternatives = 1;

    r.onresult = (e) => {
      let confirmado = "";
      let enCurso = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const trozo = e.results[i][0].transcript;
        if (e.results[i].isFinal) confirmado += trozo;
        else enCurso += trozo;
      }
      setParcial(enCurso);
      if (confirmado) {
        setParcial("");
        entregar.current(confirmado);
      }
    };

    r.onerror = (e) => {
      // «no-speech» y «aborted» son ruido normal: callarse un rato o parar a
      // mano no son fallos que haya que enseñar.
      if (e.error === "no-speech" || e.error === "aborted") return;
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        setError("No nos diste permiso para usar el micrófono.");
      } else if (e.error === "network") {
        setError("Sin conexión no se puede dictar.");
      } else {
        setError("No pudimos escuchar. Inténtalo otra vez.");
      }
      deseado.current = false;
      setEscuchando(false);
    };

    // Chrome termina la sesión tras un silencio aunque `continuous` sea true:
    // se vuelve a arrancar mientras la persona no haya pulsado parar.
    r.onend = () => {
      if (deseado.current) {
        try {
          r.start();
          return;
        } catch {
          /* ya estaba arrancando: no pasa nada */
        }
      }
      setEscuchando(false);
      setParcial("");
    };

    reconocedor.current = r;
    deseado.current = true;
    setError(null);
    try {
      r.start();
      setEscuchando(true);
    } catch {
      setError("No pudimos encender el micrófono.");
      deseado.current = false;
    }
  }, [idioma, parar]);

  return { soportado, escuchando, parcial, error, alternar, parar };
}
