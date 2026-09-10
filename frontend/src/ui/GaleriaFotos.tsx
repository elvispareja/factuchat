/** Galería de fotos de un artículo: varias, subidas o tomadas, libremente.
 *
 *  DOS CAMINOS QUE ACABAN IGUAL. «Subir» abre el selector del dispositivo —en
 *  el móvil eso ya ofrece cámara o galería— y «Tomar foto» enciende la cámara
 *  aquí mismo, que es lo que hace falta en el escritorio, donde el selector no
 *  ofrece la webcam. Al servidor le llegan los mismos bytes por el mismo sitio.
 *
 *  UN ARTÍCULO SIN GUARDAR NO TIENE ID, y las fotos se suben a
 *  /productos/{id}/imagenes. Por eso este componente distingue las fotos que ya
 *  están en el servidor de las que esperan: las pendientes se quedan en memoria
 *  y las sube quien guarda, con el id recién creado. Ver `subirPendientes`.
 *
 *  La PRIMERA es la principal: la del listado y la tienda. Se cambia pulsando
 *  «Principal» en cualquier otra.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../api/cliente";
import { CamaraFoto } from "./CamaraFoto";

export interface FotoGuardada {
  id: string;
  orden: number;
}

/** Sube las fotos que estaban esperando a que el artículo existiera. */
export async function subirPendientes(productoId: string, fotos: File[]): Promise<void> {
  for (const foto of fotos) {
    await api.subir(`/productos/${productoId}/imagenes`, foto);
  }
}

interface Props {
  /** null mientras el artículo no se ha guardado nunca. */
  productoId: string | null;
  /** Las que esperan a que el artículo exista. Las gestiona el formulario. */
  pendientes: File[];
  onPendientes: (fotos: File[]) => void;
  maximo?: number;
}

export function GaleriaFotos({ productoId, pendientes, onPendientes, maximo = 8 }: Props) {
  const [guardadas, setGuardadas] = useState<FotoGuardada[]>([]);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [conCamara, setConCamara] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const entrada = useRef<HTMLInputElement>(null);

  // Las miniaturas se piden con el token: un <img src> normal iría sin
  // cabecera y el servidor devolvería 401.
  useEffect(() => {
    if (!productoId) return;
    let vigente = true;
    const creadas: string[] = [];
    api
      .get<FotoGuardada[]>(`/productos/${productoId}/imagenes`)
      .then(async (lista) => {
        if (!vigente) return;
        setGuardadas(lista);
        const mapa: Record<string, string> = {};
        for (const f of lista) {
          try {
            const blob = await api.blob(`/productos/${productoId}/imagenes/${f.id}`);
            const url = URL.createObjectURL(blob);
            creadas.push(url);
            mapa[f.id] = url;
          } catch {
            /* una foto que no carga no debe tumbar la galería entera */
          }
        }
        if (vigente) setUrls(mapa);
      })
      .catch(() => undefined);
    return () => {
      vigente = false;
      creadas.forEach(URL.revokeObjectURL);
    };
  }, [productoId]);

  const total = guardadas.length + pendientes.length;
  const lleno = total >= maximo;

  function aceptar(archivos: FileList | File[] | null | undefined) {
    if (!archivos) return;
    const sitio = maximo - total;
    if (sitio <= 0) {
      setError(`Un artículo admite hasta ${maximo} fotos.`);
      return;
    }
    const nuevas = Array.from(archivos).slice(0, sitio);
    setError(nuevas.length < Array.from(archivos).length ? `Solo caben ${maximo} fotos.` : null);
    onPendientes([...pendientes, ...nuevas]);
  }

  async function borrarGuardada(id: string) {
    if (!productoId) return;
    setOcupado(true);
    try {
      await api.delete(`/productos/${productoId}/imagenes/${id}`);
      setGuardadas((g) => g.filter((f) => f.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos borrar la foto");
    } finally {
      setOcupado(false);
    }
  }

  async function hacerPrincipal(id: string) {
    if (!productoId) return;
    setOcupado(true);
    try {
      setGuardadas(await api.put<FotoGuardada[]>(`/productos/${productoId}/imagenes/${id}/principal`, {}));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos cambiar la principal");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <div>
      <div className="fc-galeria">
        {guardadas.map((f, i) => (
          <figure key={f.id} className="fc-galeria__foto" data-principal={i === 0 ? "1" : "0"}>
            {urls[f.id] ? <img src={urls[f.id]} alt="" /> : <span className="fc-galeria__hueco" />}
            {i === 0 && <span className="fc-galeria__marca">Principal</span>}
            <div className="fc-galeria__acciones">
              {i !== 0 && (
                <button type="button" onClick={() => void hacerPrincipal(f.id)} disabled={ocupado}>
                  Principal
                </button>
              )}
              <button type="button" onClick={() => void borrarGuardada(f.id)} disabled={ocupado}>
                Quitar
              </button>
            </div>
          </figure>
        ))}

        {pendientes.map((foto, i) => (
          <FotoPendiente
            key={`${foto.name}-${i}`}
            foto={foto}
            onQuitar={() => onPendientes(pendientes.filter((_, j) => j !== i))}
          />
        ))}
      </div>

      {conCamara ? (
        <div style={{ marginTop: 10 }}>
          <CamaraFoto
            onTomada={(foto) => {
              aceptar([foto]);
              setConCamara(false);
            }}
          />
          <button
            type="button"
            className="fc-btn fc-btn--texto"
            style={{ marginTop: 8 }}
            onClick={() => setConCamara(false)}
          >
            Cancelar
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 10 }}>
          <button
            type="button"
            className="fc-btn fc-btn--contorno"
            disabled={lleno}
            onClick={() => entrada.current?.click()}
          >
            Subir fotos
          </button>
          <button
            type="button"
            className="fc-btn fc-btn--contorno"
            disabled={lleno}
            onClick={() => setConCamara(true)}
          >
            Tomar foto
          </button>
          <input
            ref={entrada}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            hidden
            onChange={(e) => {
              aceptar(e.target.files);
              // Sin esto, volver a elegir el MISMO archivo no dispara el evento
              e.target.value = "";
            }}
          />
        </div>
      )}

      <p style={{ fontSize: 11.5, color: "#8A9A91", margin: "8px 0 0", lineHeight: 1.5 }}>
        {total} de {maximo} · JPG, PNG o WEBP, hasta 2 MB cada una. La primera es la que se ve en el
        listado.
        {pendientes.length > 0 && " Las nuevas se suben al guardar."}
      </p>

      {error && (
        <p className="fc-error" role="alert" style={{ marginTop: 6 }}>
          {error}
        </p>
      )}
    </div>
  );
}

function FotoPendiente({ foto, onQuitar }: { foto: File; onQuitar: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const u = URL.createObjectURL(foto);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [foto]);
  return (
    <figure className="fc-galeria__foto" data-pendiente="1">
      {url && <img src={url} alt="" />}
      <span className="fc-galeria__marca">Sin guardar</span>
      <div className="fc-galeria__acciones">
        <button type="button" onClick={onQuitar}>
          Quitar
        </button>
      </div>
    </figure>
  );
}
