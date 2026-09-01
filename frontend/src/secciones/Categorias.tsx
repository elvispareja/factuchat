/** Categorías y atributos: catálogo simple para organizar el catálogo, sin tope
 *  de plan (patrón calcado de Clientes.tsx). Cada categoría tiene atributos
 *  genéricos (Marca, Color, Talla…) y cada atributo sus valores posibles. */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/cliente";
import type { Atributo, AtributoValor, Categoria } from "../api/tipos";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";

/** El backend tiene UNIQUE (atributo_id, valor) y UNIQUE (categoria_id, nombre):
 *  se compara sin mayúsculas ni espacios sobrantes para no mandar duplicados que
 *  el servidor rechazaría con un error feo. */
const normalizar = (s: string) => s.trim().toLowerCase();

/** Nombres que se repiten en cualquier catálogo real; ahorran escribirlos. */
const SUGERENCIAS = ["Marca", "Talla", "Color", "Material", "Tamaño", "Peso", "Modelo", "Presentación"];

const mensaje = (e: unknown, respaldo: string) => (e instanceof Error ? e.message : respaldo);

export function Categorias() {
  const [categorias, setCategorias] = useState<Categoria[] | null>(null);
  const [atributos, setAtributos] = useState<Atributo[] | null>(null);
  const [valores, setValores] = useState<AtributoValor[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seleccionada, setSeleccionada] = useState<Categoria | null>(null);
  const [atributoAbierto, setAtributoAbierto] = useState<string | null>(null);
  const [editandoCategoria, setEditandoCategoria] = useState<Categoria | "nueva" | null>(null);
  const [editandoAtributo, setEditandoAtributo] = useState<Atributo | "nueva" | null>(null);
  const [editandoValor, setEditandoValor] = useState<AtributoValor | null>(null);
  const [copiando, setCopiando] = useState(false);

  const cargar = () =>
    Promise.all([
      api.get<Categoria[]>("/categorias"),
      api.get<Atributo[]>("/atributos"),
      api.get<AtributoValor[]>("/atributo-valores"),
    ])
      .then(([c, a, v]) => {
        setCategorias(c);
        setAtributos(a);
        setValores(v);
        setError(null); // hay una recarga por cada alta: un fallo de red suelto
      }) //              no debe dejar el cartel rojo clavado el resto de la sesión
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const atributosPorCategoria = useMemo(() => {
    const mapa = new Map<string, number>();
    for (const a of atributos ?? []) mapa.set(a.categoria_id, (mapa.get(a.categoria_id) ?? 0) + 1);
    return mapa;
  }, [atributos]);

  const atributosDeSeleccionada = useMemo(
    () => (atributos ?? []).filter((a) => a.categoria_id === seleccionada?.id),
    [atributos, seleccionada],
  );

  const valoresPorAtributo = useMemo(() => {
    const mapa = new Map<string, AtributoValor[]>();
    for (const v of valores ?? []) {
      const lista = mapa.get(v.atributo_id) ?? [];
      lista.push(v);
      mapa.set(v.atributo_id, lista);
    }
    return mapa;
  }, [valores]);

  async function eliminarCategoria(c: Categoria) {
    if (!window.confirm(`¿Eliminar la categoría "${c.nombre}"?`)) return;
    try {
      await api.delete(`/categorias/${c.id}`);
      if (seleccionada?.id === c.id) setSeleccionada(null);
      await cargar();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "No pudimos eliminar la categoría");
    }
  }

  async function eliminarAtributo(a: Atributo) {
    if (
      !window.confirm(
        `¿Eliminar el atributo "${a.nombre}"? También se eliminarán todos sus valores.`,
      )
    )
      return;
    try {
      await api.delete(`/atributos/${a.id}`);
      if (atributoAbierto === a.id) setAtributoAbierto(null);
      await cargar();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "No pudimos eliminar el atributo");
    }
  }

  async function eliminarValor(v: AtributoValor) {
    if (!window.confirm(`¿Eliminar el valor "${v.valor}"?`)) return;
    try {
      await api.delete(`/atributo-valores/${v.id}`);
      await cargar();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "No pudimos eliminar el valor");
    }
  }

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <section className="fc-tarjeta">
        <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <p className="fc-kicker">Cómo vendes</p>
            <p className="fc-cifra" style={{ fontSize: 24, margin: 0 }}>
              {categorias?.length ?? 0} categorías
            </p>
          </div>
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            onClick={() => setEditandoCategoria("nueva")}
          >
            Nueva categoría
          </button>
        </div>
      </section>

      {error && <ErrorSeccion mensaje={error} />}
      {!error && (!categorias || !atributos || !valores) && <Cargando />}

      {categorias && atributos && valores && (
        <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 18 }}>
          <section className="fc-tarjeta fc-tarjeta--tabla">
            {categorias.length === 0 ? (
              <Vacio
                titulo="Aún no tienes categorías."
                ayuda="Crea la primera para empezar a organizar tu catálogo."
              />
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="fc-tabla">
                  <thead>
                    <tr>
                      <th scope="col">Categoría</th>
                      <th scope="col"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {categorias.map((c) => (
                      <tr
                        key={c.id}
                        style={{
                          cursor: "pointer",
                          ...(seleccionada?.id === c.id
                            ? { background: "var(--superficie-suave)" }
                            : undefined),
                        }}
                        onClick={() => setSeleccionada(c)}
                      >
                        <td>
                          <div style={{ fontWeight: 600 }}>{c.nombre}</div>
                          <div style={{ fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 2 }}>
                            {atributosPorCategoria.get(c.id) ?? 0} atributos
                          </div>
                        </td>
                        <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          <button
                            type="button"
                            className="fc-btn fc-btn--texto"
                            onClick={(e) => {
                              e.stopPropagation();
                              setEditandoCategoria(c);
                            }}
                          >
                            Editar
                          </button>
                          <button
                            type="button"
                            className="fc-btn fc-btn--texto"
                            style={{ marginLeft: 12 }}
                            onClick={(e) => {
                              e.stopPropagation();
                              void eliminarCategoria(c);
                            }}
                          >
                            Eliminar
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="fc-tarjeta fc-tarjeta--tabla">
            {!seleccionada ? (
              <Vacio
                titulo="Elige una categoría"
                ayuda="Selecciona una de la izquierda para ver y administrar sus atributos."
              />
            ) : (
              <>
                <div
                  style={{
                    display: "flex",
                    gap: 14,
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "16px 18px",
                    borderBottom: "1px solid var(--borde)",
                  }}
                >
                  <p style={{ fontWeight: 700, margin: 0 }}>{seleccionada.nombre}</p>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="fc-btn fc-btn--contorno"
                      onClick={() => setCopiando(true)}
                    >
                      Copiar de otra categoría
                    </button>
                    <button
                      type="button"
                      className="fc-btn fc-btn--contorno"
                      onClick={() => setEditandoAtributo("nueva")}
                    >
                      Nuevo atributo
                    </button>
                  </div>
                </div>
                {atributosDeSeleccionada.length === 0 ? (
                  <Vacio
                    titulo="Sin atributos todavía"
                    ayuda="Agrega uno, por ejemplo Marca, Color o Talla, y luego sus valores posibles."
                  />
                ) : (
                  <div>
                    {atributosDeSeleccionada.map((a) => {
                      const valoresDelAtributo = valoresPorAtributo.get(a.id) ?? [];
                      const abierto = atributoAbierto === a.id;
                      return (
                        <div key={a.id} style={{ borderBottom: "1px solid var(--borde)" }}>
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              padding: "12px 18px",
                              cursor: "pointer",
                            }}
                            onClick={() => setAtributoAbierto(abierto ? null : a.id)}
                          >
                            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                              <span style={{ fontSize: 12, color: "var(--texto-tenue)" }}>
                                {abierto ? "▾" : "▸"}
                              </span>
                              <span style={{ fontWeight: 600 }}>{a.nombre}</span>
                              <span style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                                {valoresDelAtributo.length} valores
                              </span>
                            </div>
                            <div style={{ whiteSpace: "nowrap" }}>
                              <button
                                type="button"
                                className="fc-btn fc-btn--texto"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setEditandoAtributo(a);
                                }}
                              >
                                Editar
                              </button>
                              <button
                                type="button"
                                className="fc-btn fc-btn--texto"
                                style={{ marginLeft: 12 }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  void eliminarAtributo(a);
                                }}
                              >
                                Eliminar
                              </button>
                            </div>
                          </div>

                          {abierto && (
                            <div
                              style={{
                                padding: "4px 18px 14px 42px",
                                display: "grid",
                                gap: 8,
                              }}
                            >
                              {valoresDelAtributo.length === 0 ? (
                                <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: "6px 0" }}>
                                  Todavía no tiene valores.
                                </p>
                              ) : (
                                valoresDelAtributo.map((v) => (
                                  <div
                                    key={v.id}
                                    style={{
                                      display: "flex",
                                      alignItems: "center",
                                      justifyContent: "space-between",
                                    }}
                                  >
                                    <span>{v.valor}</span>
                                    <span style={{ whiteSpace: "nowrap" }}>
                                      <button
                                        type="button"
                                        className="fc-btn fc-btn--texto"
                                        onClick={() => setEditandoValor(v)}
                                      >
                                        Editar
                                      </button>
                                      <button
                                        type="button"
                                        className="fc-btn fc-btn--texto"
                                        style={{ marginLeft: 12 }}
                                        onClick={() => void eliminarValor(v)}
                                      >
                                        Eliminar
                                      </button>
                                    </span>
                                  </div>
                                ))
                              )}
                              <AltaValores
                                atributoId={a.id}
                                existentes={valoresDelAtributo}
                                recargar={cargar}
                              />
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      )}

      {editandoCategoria && (
        <FormularioCategoria
          categoria={editandoCategoria === "nueva" ? null : editandoCategoria}
          onCerrar={() => setEditandoCategoria(null)}
          onGuardado={async () => {
            setEditandoCategoria(null);
            await cargar();
          }}
        />
      )}

      {editandoAtributo && seleccionada && (
        <FormularioAtributo
          atributo={editandoAtributo === "nueva" ? null : editandoAtributo}
          categoriaId={seleccionada.id}
          nombresUsados={atributosDeSeleccionada.map((a) => a.nombre)}
          onCerrar={() => setEditandoAtributo(null)}
          onGuardado={async () => {
            setEditandoAtributo(null);
            await cargar();
          }}
        />
      )}

      {editandoValor && (
        <FormularioValor
          valor={editandoValor}
          onCerrar={() => setEditandoValor(null)}
          onGuardado={async () => {
            setEditandoValor(null);
            await cargar();
          }}
        />
      )}

      {copiando && seleccionada && categorias && atributos && valores && (
        <CopiarAtributos
          destino={seleccionada}
          categorias={categorias}
          atributos={atributos}
          valores={valores}
          recargar={cargar}
          onCerrar={() => setCopiando(false)}
        />
      )}
    </div>
  );
}

/** Alta de valores en línea: sin modal, con el foco siempre en el input, para
 *  cargar diez tallas escribiendo "35 Enter 36 Enter…" sin tocar el ratón.
 *  Acepta varios separados por coma (o salto de línea, para pegar de una hoja). */
function AltaValores({
  atributoId,
  existentes,
  recargar,
}: {
  atributoId: string;
  existentes: AtributoValor[];
  recargar: () => Promise<void>;
}) {
  const [texto, setTexto] = useState("");
  // Contador, no booleano: al encadenar altas rápidas hay varias en vuelo a la
  // vez y un booleano se apagaría con la primera que vuelva.
  const [enviando, setEnviando] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const entrada = useRef<HTMLInputElement>(null);
  const enVuelo = useRef<Set<string>>(new Set());

  async function anadir() {
    const enviado = texto;
    // `existentes` solo refleja lo que ya volvió del servidor; lo que sigue en
    // vuelo se lleva aparte para que teclear «35 Enter 35 Enter» rápido no
    // mande el mismo valor dos veces mientras la primera alta viaja.
    const vistos = new Set([...existentes.map((v) => normalizar(v.valor)), ...enVuelo.current]);
    const nuevos: string[] = [];
    for (const bruto of enviado.split(/[,\n]/)) {
      const valor = bruto.trim();
      if (!valor || vistos.has(normalizar(valor))) continue;
      vistos.add(normalizar(valor));
      nuevos.push(valor);
    }

    if (nuevos.length === 0) {
      setError(enviado.trim() ? "Esos valores ya están en el atributo." : null);
      setTexto("");
      entrada.current?.focus();
      return;
    }

    // El campo se vacía AQUÍ, no al volver la respuesta. Entre el POST y las
    // recargas hay dos viajes al servidor: con latencia de verdad, quien teclea
    // «35 Enter 36 Enter» seguía escribiendo sobre el «35» todavía en pantalla y
    // acababa guardando «3536». Limpiar al enviar es lo que hace que se puedan
    // encadenar diez tallas de corrido.
    setTexto("");
    setError(null);
    for (const valor of nuevos) enVuelo.current.add(normalizar(valor));
    setEnviando((n) => n + 1);

    const resultados = await Promise.allSettled(
      nuevos.map((valor) => api.post("/atributo-valores", { atributo_id: atributoId, valor })),
    );
    for (const valor of nuevos) enVuelo.current.delete(normalizar(valor));

    const fallidos = nuevos.filter((_, i) => resultados[i].status === "rejected");
    const primerFallo = resultados.find((r) => r.status === "rejected");
    if (primerFallo) {
      // Devolver lo fallido al campo solo si sigue vacío: si ya está tecleando
      // el siguiente valor, pisárselo sería peor que nombrarlo en el error.
      setTexto((actual) => (actual ? actual : fallidos.join(", ")));
      setError(
        `${mensaje(
          (primerFallo as PromiseRejectedResult).reason,
          "No pudimos guardar algunos valores",
        )} (${fallidos.join(", ")})`,
      );
    }

    await recargar();
    setEnviando((n) => n - 1);
    entrada.current?.focus(); // la clave: el foco vuelve al input tras recargar
  }

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          ref={entrada}
          className="fc-campo"
          style={{ maxWidth: 280 }}
          placeholder="35, 36, 37…"
          aria-label="Añadir valor"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            void anadir();
          }}
        />
        <button
          type="button"
          className="fc-btn fc-btn--contorno"
          disabled={!texto.trim()}
          onClick={() => void anadir()}
        >
          {enviando > 0 ? "Añadiendo…" : "Añadir"}
        </button>
      </div>
      <p style={{ fontSize: 11.5, color: "var(--texto-tenue)", margin: "6px 0 0" }}>
        Separa con comas para añadir varios de una vez.
      </p>
      {error && (
        <p className="fc-error" role="alert" style={{ marginTop: 6 }}>
          {error}
        </p>
      )}
    </div>
  );
}

/** Copia atributos (y sus valores) de otra categoría: montar "Zapatos" después
 *  de "Botas" no debería obligar a recrear Marca, Talla y Color a mano. */
function CopiarAtributos({
  destino,
  categorias,
  atributos,
  valores,
  recargar,
  onCerrar,
}: {
  destino: Categoria;
  categorias: Categoria[];
  atributos: Atributo[];
  valores: AtributoValor[];
  recargar: () => Promise<void>;
  onCerrar: () => void;
}) {
  const [origenId, setOrigenId] = useState("");
  const [marcados, setMarcados] = useState<string[]>([]);
  const [copiando, setCopiando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  const origenes = useMemo(
    () => categorias.filter((c) => c.id !== destino.id && atributos.some((a) => a.categoria_id === c.id)),
    [categorias, atributos, destino.id],
  );
  const delOrigen = useMemo(
    () => atributos.filter((a) => a.categoria_id === origenId),
    [atributos, origenId],
  );
  const yaEnDestino = useMemo(
    () =>
      new Set(
        atributos.filter((a) => a.categoria_id === destino.id).map((a) => normalizar(a.nombre)),
      ),
    [atributos, destino.id],
  );

  function elegirOrigen(id: string) {
    setOrigenId(id);
    setMarcados(
      atributos
        .filter((a) => a.categoria_id === id && !yaEnDestino.has(normalizar(a.nombre)))
        .map((a) => a.id),
    );
    setError(null);
    setAviso(null);
  }

  async function copiar() {
    setCopiando(true);
    setError(null);
    setAviso(null);
    const saltados: string[] = [];
    const fallos: string[] = [];

    for (const a of delOrigen.filter((a) => marcados.includes(a.id))) {
      if (yaEnDestino.has(normalizar(a.nombre))) {
        saltados.push(a.nombre); // el backend lo rechazaría por el UNIQUE
        continue;
      }
      try {
        // Primero el atributo: sus valores necesitan el id nuevo del padre.
        const nuevo = await api.post<Atributo>("/atributos", {
          categoria_id: destino.id,
          nombre: a.nombre,
        });
        // Ya con el id, los valores sí pueden ir en paralelo entre sí.
        const resultados = await Promise.allSettled(
          valores
            .filter((v) => v.atributo_id === a.id)
            .map((v) => api.post("/atributo-valores", { atributo_id: nuevo.id, valor: v.valor })),
        );
        const malos = resultados.filter((r) => r.status === "rejected").length;
        if (malos) fallos.push(`${a.nombre}: ${malos} valor(es) no se copiaron`);
      } catch (e) {
        fallos.push(`${a.nombre}: ${mensaje(e, "no se pudo crear")}`);
      }
    }

    await recargar();
    setCopiando(false);
    if (fallos.length) setError(fallos.join(" · "));
    if (saltados.length) setAviso(`Ya existían en ${destino.nombre} y se saltaron: ${saltados.join(", ")}.`);
    if (!fallos.length && !saltados.length) onCerrar();
  }

  return (
    <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Copiar atributos">
      <div className="fc-modal__panel" style={{ maxWidth: 480 }}>
        <p className="fc-kicker">Copiar de otra categoría</p>
        <h2 className="fc-titulo" style={{ fontSize: 20, marginBottom: 18 }}>
          Hacia {destino.nombre}
        </h2>

        <div style={{ display: "grid", gap: 14 }}>
          {origenes.length === 0 ? (
            <Vacio
              titulo="No hay de dónde copiar"
              ayuda="Ninguna otra categoría tiene atributos todavía."
            />
          ) : (
            <>
              <div>
                <label className="fc-label" htmlFor="copiar-origen">
                  Categoría de origen
                </label>
                <select
                  id="copiar-origen"
                  className="fc-campo"
                  value={origenId}
                  onChange={(e) => elegirOrigen(e.target.value)}
                >
                  <option value="">Elige una…</option>
                  {origenes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nombre}
                    </option>
                  ))}
                </select>
              </div>

              {origenId && (
                // fc-scroll solo pinta la barra: sin overflowY la lista se
                // derrama por encima de los botones del pie del modal.
                <div
                  className="fc-scroll"
                  style={{ display: "grid", gap: 8, maxHeight: 240, overflowY: "auto" }}
                >
                  {delOrigen.map((a) => {
                    const repetido = yaEnDestino.has(normalizar(a.nombre));
                    return (
                      <label
                        key={a.id}
                        style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 13.5 }}
                      >
                        <input
                          type="checkbox"
                          checked={marcados.includes(a.id) && !repetido}
                          disabled={repetido}
                          onChange={(e) =>
                            setMarcados((prev) =>
                              e.target.checked ? [...prev, a.id] : prev.filter((id) => id !== a.id),
                            )
                          }
                        />
                        <span style={{ fontWeight: 600 }}>{a.nombre}</span>
                        <span style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                          {repetido
                            ? "ya existe aquí"
                            : `${valores.filter((v) => v.atributo_id === a.id).length} valores`}
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {aviso && <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0 }}>{aviso}</p>}
          {error && (
            <p className="fc-error" role="alert">
              {error}
            </p>
          )}

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="fc-btn fc-btn--contorno" onClick={onCerrar}>
              Cerrar
            </button>
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              disabled={copiando || marcados.length === 0 || !origenId}
              onClick={() => void copiar()}
            >
              {copiando ? "Copiando…" : "Copiar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function FormularioCategoria({
  categoria,
  onCerrar,
  onGuardado,
}: {
  categoria: Categoria | null;
  onCerrar: () => void;
  onGuardado: () => void;
}) {
  const [nombre, setNombre] = useState(categoria?.nombre ?? "");
  const [descripcion, setDescripcion] = useState(categoria?.descripcion ?? "");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function guardar() {
    setGuardando(true);
    setError(null);
    const cuerpo = { nombre: nombre.trim(), descripcion: descripcion.trim() || null };
    try {
      if (categoria) {
        await api.put(`/categorias/${categoria.id}`, cuerpo);
      } else {
        await api.post("/categorias", cuerpo);
      }
      onGuardado();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos guardar la categoría");
    } finally {
      setGuardando(false);
    }
  }

  const valido = nombre.trim().length >= 2;

  return (
    <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Categoría">
      <div className="fc-modal__panel" style={{ maxWidth: 480 }}>
        <p className="fc-kicker">{categoria ? "Editar categoría" : "Nueva categoría"}</p>
        <h2 className="fc-titulo" style={{ fontSize: 20, marginBottom: 18 }}>
          {categoria ? categoria.nombre : "Agregar categoría"}
        </h2>

        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <label className="fc-label" htmlFor="cat-nombre">
              Nombre
            </label>
            <input
              id="cat-nombre"
              className="fc-campo"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </div>
          <div>
            <label className="fc-label" htmlFor="cat-descripcion">
              Descripción (opcional)
            </label>
            <input
              id="cat-descripcion"
              className="fc-campo"
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
            />
          </div>

          {error && (
            <p className="fc-error" role="alert">
              {error}
            </p>
          )}

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="fc-btn fc-btn--contorno" onClick={onCerrar}>
              Cancelar
            </button>
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              disabled={!valido || guardando}
              onClick={() => void guardar()}
            >
              {guardando ? "Guardando…" : categoria ? "Guardar cambios" : "Agregar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function FormularioAtributo({
  atributo,
  categoriaId,
  nombresUsados,
  onCerrar,
  onGuardado,
}: {
  atributo: Atributo | null;
  categoriaId: string;
  nombresUsados: string[];
  onCerrar: () => void;
  onGuardado: () => void;
}) {
  const [nombre, setNombre] = useState(atributo?.nombre ?? "");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function guardar() {
    setGuardando(true);
    setError(null);
    const cuerpo = { categoria_id: categoriaId, nombre: nombre.trim() };
    try {
      if (atributo) {
        await api.put(`/atributos/${atributo.id}`, cuerpo);
      } else {
        await api.post("/atributos", cuerpo);
      }
      onGuardado();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos guardar el atributo");
    } finally {
      setGuardando(false);
    }
  }

  // El backend acepta min_length=1 (AtributoIn); el panel exigía 2 sin motivo.
  const valido = nombre.trim().length >= 1;
  const usados = new Set(nombresUsados.map(normalizar));

  return (
    <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Atributo">
      <div className="fc-modal__panel" style={{ maxWidth: 420 }}>
        <p className="fc-kicker">{atributo ? "Editar atributo" : "Nuevo atributo"}</p>
        <h2 className="fc-titulo" style={{ fontSize: 20, marginBottom: 18 }}>
          {atributo ? atributo.nombre : "Agregar atributo"}
        </h2>

        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <label className="fc-label" htmlFor="atributo-nombre">
              Nombre
            </label>
            <input
              id="atributo-nombre"
              className="fc-campo"
              placeholder="Marca, Color, Talla…"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </div>

          {!atributo && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {SUGERENCIAS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="fc-chip"
                  disabled={usados.has(normalizar(s))}
                  aria-pressed={normalizar(nombre) === normalizar(s)}
                  onClick={() => setNombre(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {error && (
            <p className="fc-error" role="alert">
              {error}
            </p>
          )}

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="fc-btn fc-btn--contorno" onClick={onCerrar}>
              Cancelar
            </button>
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              disabled={!valido || guardando}
              onClick={() => void guardar()}
            >
              {guardando ? "Guardando…" : atributo ? "Guardar cambios" : "Agregar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Solo edición: las altas van por el input en línea del acordeón. */
function FormularioValor({
  valor,
  onCerrar,
  onGuardado,
}: {
  valor: AtributoValor;
  onCerrar: () => void;
  onGuardado: () => void;
}) {
  const [texto, setTexto] = useState(valor.valor);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function guardar() {
    setGuardando(true);
    setError(null);
    try {
      await api.put(`/atributo-valores/${valor.id}`, {
        atributo_id: valor.atributo_id,
        valor: texto.trim(),
      });
      onGuardado();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos guardar el valor");
    } finally {
      setGuardando(false);
    }
  }

  const valido = texto.trim().length >= 1;

  return (
    <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Valor">
      <div className="fc-modal__panel" style={{ maxWidth: 420 }}>
        <p className="fc-kicker">Editar valor</p>
        <h2 className="fc-titulo" style={{ fontSize: 20, marginBottom: 18 }}>
          {valor.valor}
        </h2>

        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <label className="fc-label" htmlFor="valor-texto">
              Valor
            </label>
            <input
              id="valor-texto"
              className="fc-campo"
              placeholder="Rojo, XL, Nike…"
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
            />
          </div>

          {error && (
            <p className="fc-error" role="alert">
              {error}
            </p>
          )}

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" className="fc-btn fc-btn--contorno" onClick={onCerrar}>
              Cancelar
            </button>
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              disabled={!valido || guardando}
              onClick={() => void guardar()}
            >
              {guardando ? "Guardando…" : "Guardar cambios"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
