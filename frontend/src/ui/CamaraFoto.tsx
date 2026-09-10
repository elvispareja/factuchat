/** Tomar la foto con la cámara, aquí y ahora. Nunca elegir un archivo.
 *
 *  POR QUÉ NO HAY SELECTOR DE ARCHIVOS. Una foto elegida del disco puede ser
 *  de cualquier sitio: del catálogo del proveedor, de una búsqueda en internet,
 *  de hace dos años. La foto del artículo tiene que ser del artículo que está
 *  delante, así que el único camino es la cámara. Ni siquiera se deja como
 *  respaldo: un respaldo cómodo se convierte en el camino normal.
 *
 *  `<input type="file" capture>` NO sirve para esto. En el escritorio abre el
 *  explorador de archivos, y en varios navegadores de móvil ofrece igualmente
 *  la galería. Solo `getUserMedia` garantiza que el píxel viene del sensor.
 *
 *  DOS COSAS QUE HAY QUE HACER BIEN, y son fáciles de olvidar:
 *
 *  1. APAGAR LA CÁMARA. Si no se paran las pistas del stream, el piloto del
 *     dispositivo se queda encendido después de cerrar el formulario. Aunque no
 *     se esté grabando nada, para quien lo ve es una cámara espiando.
 *  2. REDUCIR LA FOTO. Un móvil moderno saca 4-8 MB y el servidor acepta 2 MB:
 *     sin reescalar, todas las fotos se rechazarían. Se baja a 1280 px de lado
 *     mayor y JPEG de calidad 0.85, que para un catálogo sobra.
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** Lado mayor de la foto guardada. Más que esto no aporta nada en una ficha de
 *  catálogo y sí hace que la subida falle por tamaño. */
const LADO_MAXIMO = 1280;
const CALIDAD = 0.85;

type Estado = "iniciando" | "lista" | "sin-permiso" | "sin-camara" | "no-disponible";

export function CamaraFoto({ onTomada }: { onTomada: (foto: File) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [estado, setEstado] = useState<Estado>("iniciando");
  const [detalle, setDetalle] = useState<string | null>(null);
  const [frontal, setFrontal] = useState(false);
  const [tomando, setTomando] = useState(false);

  const apagar = useCallback(() => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  }, []);

  const encender = useCallback(
    async (usarFrontal: boolean) => {
      apagar();
      // En http:// (salvo localhost) el navegador ni siquiera expone la API.
      if (!navigator.mediaDevices?.getUserMedia) {
        setEstado("no-disponible");
        return;
      }
      setEstado("iniciando");
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          // La trasera es la que apunta al producto; en un portátil no existe y
          // el navegador entrega la que haya.
          video: { facingMode: usarFrontal ? "user" : "environment" },
          audio: false,
        });
        stream.current = s;
        if (video.current) {
          video.current.srcObject = s;
          await video.current.play().catch(() => undefined);
        }
        setEstado("lista");
      } catch (e) {
        const nombre = e instanceof DOMException ? e.name : "";
        if (nombre === "NotAllowedError" || nombre === "SecurityError") {
          setEstado("sin-permiso");
        } else if (nombre === "NotFoundError" || nombre === "OverconstrainedError") {
          setEstado("sin-camara");
        } else {
          setEstado("no-disponible");
          setDetalle(e instanceof Error ? e.message : null);
        }
      }
    },
    [apagar],
  );

  useEffect(() => {
    void encender(frontal);
    return apagar; // al desmontar, la cámara se apaga
  }, [encender, apagar, frontal]);

  function tomar() {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    setTomando(true);

    const escala = Math.min(1, LADO_MAXIMO / Math.max(v.videoWidth, v.videoHeight));
    const lienzo = document.createElement("canvas");
    lienzo.width = Math.round(v.videoWidth * escala);
    lienzo.height = Math.round(v.videoHeight * escala);
    const ctx = lienzo.getContext("2d");
    if (!ctx) {
      setTomando(false);
      return;
    }
    ctx.drawImage(v, 0, 0, lienzo.width, lienzo.height);

    lienzo.toBlob(
      (blob) => {
        setTomando(false);
        if (!blob) return;
        const sello = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "");
        onTomada(new File([blob], `foto-${sello}.jpg`, { type: "image/jpeg" }));
        apagar(); // la foto ya está: no hay motivo para seguir mirando
      },
      "image/jpeg",
      CALIDAD,
    );
  }

  if (estado !== "lista" && estado !== "iniciando") {
    return <SinCamara estado={estado} detalle={detalle} onReintentar={() => void encender(frontal)} />;
  }

  return (
    <div className="fc-camara">
      <div className="fc-camara__marco">
        <video ref={video} playsInline muted autoPlay />
        {estado === "iniciando" && <span className="fc-camara__aviso">Encendiendo la cámara…</span>}
      </div>
      <div className="fc-camara__botones">
        <button
          type="button"
          className="fc-btn fc-btn--primario"
          onClick={tomar}
          disabled={estado !== "lista" || tomando}
        >
          {tomando ? "Tomando…" : "Tomar foto"}
        </button>
        <button
          type="button"
          className="fc-btn fc-btn--texto"
          onClick={() => setFrontal(!frontal)}
          disabled={estado !== "lista"}
        >
          Cambiar de cámara
        </button>
      </div>
      <p className="fc-camara__nota">
        La foto se toma ahora y no se puede elegir del dispositivo: así la imagen del catálogo es
        siempre del artículo real.
      </p>
    </div>
  );
}

function SinCamara({
  estado,
  detalle,
  onReintentar,
}: {
  estado: Estado;
  detalle: string | null;
  onReintentar: () => void;
}) {
  const textos: Record<string, { titulo: string; ayuda: string }> = {
    "sin-permiso": {
      titulo: "No nos diste permiso para usar la cámara",
      ayuda:
        "Ábrelo en el candado de la barra de direcciones y vuelve a intentarlo. La foto se toma aquí y no se guarda en tu dispositivo.",
    },
    "sin-camara": {
      titulo: "No encontramos ninguna cámara",
      ayuda:
        "Conecta una o abre Factuchat desde el móvil. Las fotos del catálogo solo se pueden tomar, no subir.",
    },
    "no-disponible": {
      titulo: "El navegador no deja usar la cámara aquí",
      ayuda:
        "Suele pasar cuando la página no va por HTTPS. Ábrela con https:// y vuelve a intentarlo.",
    },
  };
  const t = textos[estado] ?? textos["no-disponible"];
  return (
    <div className="fc-camara__error">
      <p style={{ fontSize: 13.5, fontWeight: 600, margin: 0 }}>{t.titulo}</p>
      <p style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--texto-suave)", margin: "6px 0 0" }}>
        {t.ayuda}
      </p>
      {detalle && (
        <p style={{ fontSize: 11.5, color: "#8A9A91", margin: "6px 0 0" }}>{detalle}</p>
      )}
      <button
        type="button"
        className="fc-btn fc-btn--contorno"
        style={{ marginTop: 12 }}
        onClick={onReintentar}
      >
        Reintentar
      </button>
    </div>
  );
}
