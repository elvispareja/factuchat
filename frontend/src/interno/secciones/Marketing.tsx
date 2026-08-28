/** Marketing: códigos promocionales con su columna Retenido (Superadmin, esMkt).
 *
 *  "Retenido" es el ingreso que la promoción NO cobró. Se congela al aplicarse:
 *  un cambio de precio posterior no lo reescribe. */

import { useCallback, useEffect, useState } from "react";
import { sa, type Operador, type Promo, type Solicitud, type UsoPromo } from "../api";
import { Cargando, ErrorSeccion, Vacio } from "../../ui/Estados";
import { dinero, fechaCorta } from "../../util/formato";

export function Marketing({ operador }: { operador: Operador }) {
  const [promos, setPromos] = useState<Promo[] | null>(null);
  const [origenes, setOrigenes] = useState<Array<{ origen: string; altas: number; retenido: string }>>([]);
  const [error, setError] = useState<string | null>(null);
  const [abierta, setAbierta] = useState<Promo | null>(null);
  const [creando, setCreando] = useState(false);

  const cargar = async () => {
    setError(null);
    try {
      const [p, o] = await Promise.all([sa.promos(), sa.origenes()]);
      setPromos(p);
      setOrigenes(o);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  };

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  if (!promos) return <Cargando />;

  if (abierta) return <Usos promo={abierta} onVolver={() => setAbierta(null)} />;

  const retenidoTotal = promos.reduce((s, p) => s + Number(p.retenido_total), 0);

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div className="fc-kpi">
        <Tarjeta etiqueta="Códigos activos" valor={String(promos.filter((p) => p.activo).length)} />
        <Tarjeta etiqueta="Altas con código" valor={String(promos.reduce((s, p) => s + p.usos, 0))} />
        <Tarjeta etiqueta="Retenido total" valor={dinero(retenidoTotal)} />
        <Tarjeta
          etiqueta="Sin código"
          valor={String(origenes.find((o) => o.origen === "Sin código")?.altas ?? 0)}
        />
      </div>

      <Bandeja operador={operador} />

      {operador.es_superadmin && (
        <div>
          <button
            type="button"
            className="fc-btn fc-btn--primario"
            onClick={() => setCreando((v) => !v)}
          >
            {creando ? "Cancelar" : "Nuevo código"}
          </button>
        </div>
      )}

      {creando && (
        <NuevoCodigo
          onListo={async () => {
            setCreando(false);
            await cargar();
          }}
        />
      )}

      <section className="fc-tarjeta fc-tarjeta--tabla">
        {promos.length === 0 ? (
          <Vacio
            titulo="Todavía no hay códigos promocionales."
            ayuda="Crea uno para medir de dónde vienen tus altas y cuánto te cuesta cada campaña."
          />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="fc-tabla">
              <thead>
                <tr>
                  <th scope="col">Código</th>
                  <th scope="col">Beneficio</th>
                  <th scope="col">Vigencia</th>
                  <th scope="col" className="fc-num">Usos</th>
                  <th scope="col" className="fc-num">Retenido</th>
                  <th scope="col"> </th>
                </tr>
              </thead>
              <tbody>
                {promos.map((p) => (
                  <tr key={p.id}>
                    <td className="fc-mono" style={{ fontWeight: 600 }}>
                      {p.codigo}
                    </td>
                    <td>
                      {p.tipo === "PRECIO_FIJO" && `${dinero(p.valor)} por ${p.meses} mes(es)`}
                      {p.tipo === "PORCENTAJE" && `${p.valor}% por ${p.meses} mes(es)`}
                      {p.tipo === "MONTO_FIJO" && `−${dinero(p.valor)} por ${p.meses} mes(es)`}
                    </td>
                    <td style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>
                      {fechaCorta(p.vigente_desde)}
                      {p.vigente_hasta ? ` → ${fechaCorta(p.vigente_hasta)}` : " → sin fin"}
                    </td>
                    <td className="fc-num">
                      {p.usos}
                      {p.max_usos ? ` / ${p.max_usos}` : ""}
                    </td>
                    <td className="fc-num">{dinero(p.retenido_total)}</td>
                    <td>
                      <button
                        type="button"
                        className="fc-btn fc-btn--texto"
                        onClick={() => setAbierta(p)}
                      >
                        Ver usos
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="fc-tarjeta">
        <p className="fc-kicker">Origen de las altas</p>
        <table className="fc-tabla" style={{ marginTop: 10 }}>
          <thead>
            <tr>
              <th scope="col">Origen</th>
              <th scope="col" className="fc-num">Altas</th>
              <th scope="col" className="fc-num">Retenido</th>
            </tr>
          </thead>
          <tbody>
            {origenes.map((o) => (
              <tr key={o.origen}>
                <td>{o.origen}</td>
                <td className="fc-num">{o.altas}</td>
                <td className="fc-num">{dinero(o.retenido)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

/** Lo que entra por la landing: pedidos del checkout y consultas de contacto.
 *
 *  El correo avisa al equipo; esta es la bandeja donde se trabaja. Sin ella el
 *  aviso se pierde en una bandeja de entrada y el pedido queda sin atender. */
function Bandeja({ operador }: { operador: Operador }) {
  const [solicitudes, setSolicitudes] = useState<Solicitud[] | null>(null);
  const [pendientes, setPendientes] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [trabajando, setTrabajando] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setError(null);
    try {
      setSolicitudes(await sa.solicitudes(pendientes));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }, [pendientes]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function atender(id: string) {
    setTrabajando(id);
    try {
      await sa.atenderSolicitud(id);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos cerrarla");
    } finally {
      setTrabajando(null);
    }
  }

  return (
    <section className="fc-tarjeta fc-tarjeta--tabla">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 12,
        }}
      >
        <p className="fc-kicker" style={{ margin: 0 }}>
          Llegó por la web
        </p>
        <button
          type="button"
          className="fc-btn fc-btn--contorno"
          style={{ padding: "6px 14px", fontSize: 12.5 }}
          onClick={() => setPendientes((v) => !v)}
        >
          {pendientes ? "Ver todas" : "Ver solo pendientes"}
        </button>
      </div>

      {error && (
        <p className="fc-error" role="alert">
          {error}
        </p>
      )}

      {!solicitudes ? (
        <Cargando />
      ) : solicitudes.length === 0 ? (
        <Vacio
          titulo={pendientes ? "Nada pendiente por atender." : "Todavía no llegó nada por la web."}
          ayuda="Aquí caen los pedidos del checkout y las consultas del formulario de contacto."
        />
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="fc-tabla">
            <thead>
              <tr>
                <th scope="col">Quién</th>
                <th scope="col">Qué pide</th>
                <th scope="col">Cómo paga</th>
                <th scope="col">Entró</th>
                <th scope="col"> </th>
              </tr>
            </thead>
            <tbody>
              {solicitudes.map((s) => (
                <tr key={s.id}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{s.nombre}</div>
                    <div style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                      {s.email}
                      {s.telefono ? ` · ${s.telefono}` : ""}
                    </div>
                  </td>
                  <td>
                    {s.plan ? `Plan ${s.plan}` : "Consulta"}
                    {s.agenda && (
                      <div style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                        Llamada: {s.agenda}
                      </div>
                    )}
                    {s.mensaje && (
                      <div
                        style={{
                          fontSize: 11.5,
                          color: "var(--texto-tenue)",
                          maxWidth: 320,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {s.mensaje}
                      </div>
                    )}
                  </td>
                  <td>
                    {s.metodo_pago ?? "—"}
                    {s.tiene_comprobante && (
                      <div style={{ fontSize: 11.5, color: "var(--exito-texto)" }}>
                        Con comprobante
                      </div>
                    )}
                  </td>
                  <td style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>
                    {fechaCorta(s.creada.slice(0, 10))}
                    {!s.avisado && (
                      <div style={{ fontSize: 11.5, color: "var(--aviso-texto)" }}>
                        Aviso en cola
                      </div>
                    )}
                  </td>
                  <td>
                    {s.atendida ? (
                      <span style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>Atendida</span>
                    ) : operador.puede_actuar ? (
                      <button
                        type="button"
                        className="fc-btn fc-btn--contorno"
                        style={{ padding: "6px 14px", fontSize: 12.5 }}
                        disabled={trabajando === s.id}
                        onClick={() => void atender(s.id)}
                      >
                        Marcar atendida
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Usos({ promo, onVolver }: { promo: Promo; onVolver: () => void }) {
  const [usos, setUsos] = useState<UsoPromo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    sa.usosPromo(promo.id)
      .then((d) => setUsos(d.usos))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));
  }, [promo.id]);

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <button
        type="button"
        className="fc-btn fc-btn--texto"
        style={{ justifySelf: "start" }}
        onClick={onVolver}
      >
        ← Volver a marketing
      </button>
      <section className="fc-tarjeta fc-tarjeta--tabla">
        <div style={{ padding: "18px 20px", borderBottom: "1px solid var(--borde)" }}>
          <p className="fc-kicker">Usos del código</p>
          <h2 className="fc-titulo" style={{ fontSize: 20 }}>
            {promo.codigo}
          </h2>
          <p style={{ fontSize: 13, color: "var(--texto-tenue)", margin: "6px 0 0" }}>
            Retenido total: <strong>{dinero(promo.retenido_total)}</strong> · lo que la promoción
            dejó de cobrar.
          </p>
        </div>
        {error && <ErrorSeccion mensaje={error} />}
        {!error && !usos && <Cargando />}
        {usos &&
          (usos.length === 0 ? (
            <Vacio titulo="Nadie ha usado este código todavía." />
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="fc-tabla">
                <thead>
                  <tr>
                    <th scope="col">Cliente</th>
                    <th scope="col">RUC</th>
                    <th scope="col">Fecha</th>
                    <th scope="col" className="fc-num">Lista</th>
                    <th scope="col" className="fc-num">Cobrado</th>
                    <th scope="col" className="fc-num">Retenido</th>
                  </tr>
                </thead>
                <tbody>
                  {usos.map((u) => (
                    <tr key={u.id}>
                      <td style={{ fontWeight: 600 }}>{u.cliente}</td>
                      <td className="fc-mono">{u.ruc}</td>
                      <td>{fechaCorta(u.usado_at.slice(0, 10))}</td>
                      <td className="fc-num">{u.precio_lista ? dinero(u.precio_lista) : "—"}</td>
                      <td className="fc-num">
                        {u.precio_cobrado ? dinero(u.precio_cobrado) : "—"}
                      </td>
                      <td className="fc-num" style={{ fontWeight: 600 }}>
                        {dinero(u.retenido)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
      </section>
    </div>
  );
}

function NuevoCodigo({ onListo }: { onListo: () => void }) {
  const [codigo, setCodigo] = useState("");
  const [tipo, setTipo] = useState("PRECIO_FIJO");
  const [valor, setValor] = useState("0.99");
  const [meses, setMeses] = useState("1");
  const [maxUsos, setMaxUsos] = useState("200");
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);

  async function guardar() {
    setGuardando(true);
    setError(null);
    try {
      await sa.crearPromo({
        codigo: codigo.trim().toUpperCase(),
        tipo,
        valor,
        meses: Number(meses),
        max_usos: maxUsos ? Number(maxUsos) : null,
        vigente_desde: new Date().toISOString().slice(0, 10),
      });
      onListo();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos crear el código");
    } finally {
      setGuardando(false);
    }
  }

  return (
    <section className="fc-tarjeta">
      <p className="fc-kicker">Nuevo código promocional</p>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 14,
          marginTop: 14,
        }}
      >
        <div>
          <label className="fc-label" htmlFor="pc-codigo">
            Código
          </label>
          <input
            id="pc-codigo"
            className="fc-campo"
            value={codigo}
            onChange={(e) => setCodigo(e.target.value.toUpperCase())}
            placeholder="LANZA99"
          />
        </div>
        <div>
          <label className="fc-label" htmlFor="pc-tipo">
            Tipo
          </label>
          <select
            id="pc-tipo"
            className="fc-campo"
            value={tipo}
            onChange={(e) => setTipo(e.target.value)}
          >
            <option value="PRECIO_FIJO">Precio fijo</option>
            <option value="PORCENTAJE">Porcentaje</option>
            <option value="MONTO_FIJO">Monto fijo</option>
          </select>
        </div>
        <div>
          <label className="fc-label" htmlFor="pc-valor">
            Valor
          </label>
          <input
            id="pc-valor"
            className="fc-campo"
            value={valor}
            onChange={(e) => setValor(e.target.value)}
          />
        </div>
        <div>
          <label className="fc-label" htmlFor="pc-meses">
            Meses
          </label>
          <input
            id="pc-meses"
            className="fc-campo"
            inputMode="numeric"
            value={meses}
            onChange={(e) => setMeses(e.target.value)}
          />
        </div>
        <div>
          <label className="fc-label" htmlFor="pc-cupo">
            Cupos
          </label>
          <input
            id="pc-cupo"
            className="fc-campo"
            inputMode="numeric"
            value={maxUsos}
            onChange={(e) => setMaxUsos(e.target.value)}
          />
        </div>
      </div>
      {error && (
        <p className="fc-error" role="alert">
          {error}
        </p>
      )}
      <button
        type="button"
        className="fc-btn fc-btn--primario"
        style={{ marginTop: 16 }}
        disabled={guardando || codigo.trim().length < 3}
        onClick={() => void guardar()}
      >
        {guardando ? "Creando…" : "Crear código"}
      </button>
    </section>
  );
}

function Tarjeta({ etiqueta, valor }: { etiqueta: string; valor: string }) {
  return (
    <div className="fc-tarjeta" style={{ padding: "18px 20px 20px" }}>
      <div className="fc-kicker" style={{ marginBottom: 8 }}>
        {etiqueta}
      </div>
      <div className="fc-cifra" style={{ fontSize: 24 }}>
        {valor}
      </div>
    </div>
  );
}
