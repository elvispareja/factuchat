/** Consumo y costos (Superadmin.dc.html, bloque `esConsumo`).
 *
 *  Cuatro piezas, como la maqueta: las tarifas editables con vigencia, la
 *  tarjeta oscura de totales del mes, la tabla de costo real por cliente y el
 *  aviso de márgenes bajos.
 *
 *  Ninguna cifra se calcula aquí. El costo, el margen y los totales vienen de
 *  `/sa/consumo`, que los saca de la base: si el panel y un informe dieran
 *  márgenes distintos no habría forma de saber cuál creer. Esta pantalla solo
 *  los pinta.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { sa, type Consumo, type FilaConsumo, type Operador, type Tarifa } from "../api";
import { Cargando, ErrorSeccion } from "../../ui/Estados";
import { dinero, fechaCorta } from "../../util/formato";

/** Las tres tarifas que la maqueta deja editar, con el par
 *  (proveedor, concepto) exacto con el que viven en `cost_rates`. */
const EDITABLES = [
  {
    clave: "wa",
    etiqueta: "Meta $/conversación",
    proveedor: "META_WHATSAPP",
    concepto: "Conversación iniciada por la empresa",
    unidad: "conversacion",
  },
  {
    clave: "ia",
    etiqueta: "IA $/análisis",
    proveedor: "IA",
    concepto: "Análisis de comprobante",
    unidad: "análisis",
  },
  {
    clave: "infra",
    etiqueta: "Infra $/comprobante",
    proveedor: "INFRA",
    concepto: "Emisión de comprobante",
    unidad: "comprobante",
  },
] as const;

const HOY = new Date().toISOString().slice(0, 10);

function manana(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}

/** Verde si el margen es sano, ámbar si aprieta, rojo si pierde dinero. */
function tonoMargen(pct: number | null): string {
  if (pct === null) return "var(--error-texto)"; // no paga: es costo puro
  if (pct < 0) return "var(--error-texto)";
  if (pct < 20) return "var(--aviso-texto)";
  return "var(--verde-medio)";
}

export function ConsumoYCostos({ operador }: { operador: Operador }) {
  const [tarifas, setTarifas] = useState<Tarifa[] | null>(null);
  const [datos, setDatos] = useState<Consumo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [desde, setDesde] = useState(manana);
  const [valores, setValores] = useState<Record<string, string>>({});

  const cargar = useCallback(async () => {
    try {
      const [t, c] = await Promise.all([sa.tarifas(), sa.consumo()]);
      setTarifas(t);
      setDatos(c);
      // Los campos arrancan con lo que rige HOY, no vacíos: editar una tarifa
      // es casi siempre retocar la que hay.
      const iniciales: Record<string, string> = {};
      for (const e of EDITABLES) {
        const vig = t.find(
          (x) => x.proveedor === e.proveedor && x.concepto === e.concepto && x.vigente_ahora,
        );
        iniciales[e.clave] = vig ? String(Number(vig.costo_unitario)) : "";
      }
      setValores(iniciales);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  const futuras = useMemo(
    () => (tarifas ?? []).filter((t) => !t.vigente_ahora && t.vigente_desde > HOY),
    [tarifas],
  );

  async function guardar() {
    setGuardando(true);
    setError(null);
    try {
      // Solo se programa lo que de verdad cambió: guardar las tres siempre
      // llenaría el histórico de filas idénticas y haría ilegible la vigencia.
      const cambiadas = EDITABLES.filter((e) => {
        const vig = (tarifas ?? []).find(
          (x) => x.proveedor === e.proveedor && x.concepto === e.concepto && x.vigente_ahora,
        );
        const actual = vig ? Number(vig.costo_unitario) : NaN;
        const nuevo = Number(valores[e.clave]);
        return Number.isFinite(nuevo) && nuevo >= 0 && nuevo !== actual;
      });
      if (cambiadas.length === 0) {
        setAviso("No cambiaste ninguna tarifa.");
        return;
      }
      for (const e of cambiadas) {
        await sa.programarTarifa({
          proveedor: e.proveedor,
          concepto: e.concepto,
          costo_unitario: valores[e.clave],
          unidad: e.unidad,
          vigente_desde: desde,
        });
      }
      setAviso(
        `${cambiadas.length === 1 ? "1 tarifa programada" : `${cambiadas.length} tarifas programadas`} desde el ${fechaCorta(desde)}`,
      );
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos guardar las tarifas");
    } finally {
      setGuardando(false);
      window.setTimeout(() => setAviso(null), 6000);
    }
  }

  if (error && !datos) return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  if (!datos || !tarifas) return <Cargando />;

  const t = datos.totales;

  return (
    <div style={{ animation: "dbIn .35s ease-out both" }}>
      <div className="fc-consumo-cabecera">
        <section className="fc-sa-panel">
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
            <h2 className="fc-sa-panel__titulo">Tarifas de costo</h2>
            {/* Cambiar lo que cuesta el negocio es configuración: solo el
                superadmin. El servidor lo exige otra vez en POST /sa/tarifas. */}
            {operador.es_superadmin && (
              <button
                type="button"
                className="fc-btn fc-btn--oscuro"
                onClick={() => void guardar()}
                disabled={guardando}
              >
                {guardando ? "Guardando…" : "Guardar con vigencia"}
              </button>
            )}
          </div>

          <div className="fc-consumo-tarifas">
            {EDITABLES.map((e) => (
              <label key={e.clave} className="fc-alta-campo" style={{ marginBottom: 0 }}>
                <span>{e.etiqueta}</span>
                <input
                  type="number"
                  step="0.001"
                  min="0"
                  value={valores[e.clave] ?? ""}
                  readOnly={!operador.es_superadmin}
                  onChange={(ev) =>
                    setValores((v) => ({ ...v, [e.clave]: ev.target.value }))
                  }
                />
              </label>
            ))}
            <label className="fc-alta-campo" style={{ marginBottom: 0 }}>
              <span>Vigente desde</span>
              <input
                type="date"
                value={desde}
                min={manana()}
                readOnly={!operador.es_superadmin}
                onChange={(ev) => setDesde(ev.target.value)}
              />
            </label>
          </div>

          <p style={{ fontSize: 12, color: "#8A9A91", lineHeight: 1.5, margin: "12px 0 0" }}>
            {/* El histórico se arma con lo que hay de verdad en la base, no con
                un texto fijo: si alguien programa un alza, aquí sale. */}
            {historico(tarifas, futuras)}
          </p>
          {aviso && (
            <p style={{ fontSize: 12.5, color: "var(--verde-medio)", margin: "8px 0 0" }}>
              {aviso}
            </p>
          )}
          {error && (
            <p className="fc-error" role="alert" style={{ marginTop: 8 }}>
              {error}
            </p>
          )}
        </section>

        <section className="fc-consumo-total">
          <div className="fc-sa-kpi__rotulo" style={{ color: "#7FC7A4" }}>
            Total de {mesActual()}
          </div>
          <div className="fc-consumo-total__filas">
            <div>
              <span>Ingreso</span>
              <strong>{dinero(t.ingreso)}</strong>
            </div>
            <div>
              {/* El ingreso es del mes entero y el costo es lo que va del mes:
                  decirlo evita leer un margen que parece mejor de lo que es. */}
              <span>
                Costo real{" "}
                <em style={{ fontStyle: "normal", opacity: 0.75 }}>
                  ({datos.periodo.dias_transcurridos} de {datos.periodo.dias_mes} días)
                </em>
              </span>
              <strong>{dinero(t.costo)}</strong>
            </div>
            <div data-borde="1">
              <span>Margen global</span>
              <strong style={{ color: Number(t.margen) >= 0 ? "#5CE68F" : "#F2B8B2" }}>
                {dinero(t.margen)}
                {t.margen_pct !== null && ` · ${t.margen_pct}%`}
              </strong>
            </div>
          </div>
        </section>
      </div>

      <div className="fc-sa-tabla" style={{ marginBottom: 14 }}>
        <div className="fc-sa-tabla__scroll">
          <div style={{ minWidth: 940 }}>
            <div className="fc-consumo-fila fc-sa-fila--cabecera">
              <div>Cliente</div>
              <div>Cupo</div>
              <div>Canal</div>
              <div>IA</div>
              <div style={{ textAlign: "right" }}>Costo</div>
              <div style={{ textAlign: "right" }}>Paga</div>
              <div style={{ textAlign: "right" }}>Margen</div>
            </div>
            {datos.clientes.map((c) => (
              <Fila key={c.tenant_id} c={c} />
            ))}
            {datos.clientes.length === 0 && (
              <div
                style={{
                  padding: 36,
                  textAlign: "center",
                  fontSize: 13.5,
                  color: "var(--texto-tenue)",
                }}
              >
                Todavía no hay clientes activos que medir.
              </div>
            )}
          </div>
        </div>
      </div>

      {datos.margen_bajo.length > 0 && (
        <section className="fc-consumo-rojo">
          <h2 className="fc-sa-panel__titulo" style={{ color: "var(--error-texto)", marginBottom: 4 }}>
            Margen bajo o negativo
          </h2>
          <p style={{ fontSize: 12, color: "#8A9A91", margin: "0 0 12px", lineHeight: 1.5 }}>
            Clientes que, al ritmo de este mes, acabarán costando más del 80% de lo que pagan. Se
            mira la proyección a fin de mes y no lo que llevan gastado: si no, la lista se vaciaría
            sola cada día 1. Los que todavía no pagan están en prueba: ahí el costo es la inversión
            en captarlos.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            {datos.margen_bajo.map((c) => (
              <div key={c.tenant_id} className="fc-consumo-rojo__fila">
                <span className="fc-sa-fila__nombre" style={{ flex: 1 }}>
                  {c.cliente}
                </span>
                <span style={{ fontSize: 11.5, color: "#8A9A91", whiteSpace: "nowrap" }}>
                  {c.plan}
                </span>
                <strong
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    whiteSpace: "nowrap",
                    fontVariantNumeric: "tabular-nums",
                    color: tonoMargen(c.margen_proyectado_pct),
                  }}
                  title={`Costo proyectado a fin de mes: ${dinero(c.costo_proyectado)}`}
                >
                  {c.margen_proyectado_pct !== null
                    ? `${c.margen_proyectado_pct}% a fin de mes`
                    : c.suscripcion === "MOROSA"
                      ? "pago pendiente"
                      : "aún no paga"}
                </strong>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Fila({ c }: { c: FilaConsumo }) {
  const pct = c.cupo > 0 ? Math.round((c.usados / c.cupo) * 100) : 0;
  const tono = pct >= 100 ? "lleno" : pct >= 85 ? "aviso" : "normal";
  return (
    <div className="fc-consumo-fila fc-consumo-fila--dato">
      <div style={{ minWidth: 0 }}>
        <div className="fc-sa-fila__nombre">{c.cliente}</div>
        <div style={{ fontSize: 11, color: "#8A9A91" }}>{c.plan}</div>
      </div>
      <div>
        <div className="fc-sa-cupo__cifra">
          {c.usados} / {c.cupo > 0 ? c.cupo : "—"}
        </div>
        <div className="fc-sa-cupo__carril">
          <div
            className="fc-sa-cupo__lleno"
            data-tono={tono}
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
      </div>
      <div
        className="fc-sa-fila__dato"
        title={
          c.canal.whatsapp_pct === null
            ? undefined
            : `${c.canal.whatsapp_pct}% WhatsApp · ${c.canal.panel_pct}% panel`
        }
      >
        {c.canal.whatsapp_pct === null ? "sin emitir" : `${c.canal.whatsapp_pct}% WhatsApp`}
      </div>
      <div className="fc-sa-fila__dato">
        {c.ia_usados} de {c.ia_cupo}
      </div>
      <div
        className="fc-consumo-num"
        title={`WhatsApp ${dinero(c.costo_detalle.whatsapp)} · IA ${dinero(
          c.costo_detalle.ia,
        )} · Infra ${dinero(c.costo_detalle.infra)}`}
      >
        {dinero(c.costo)}
      </div>
      <div className="fc-consumo-num">{dinero(c.paga)}</div>
      <div className="fc-consumo-num" style={{ fontWeight: 700, color: tonoMargen(c.margen_pct) }}>
        {dinero(c.margen)}
        {c.margen_pct !== null ? ` · ${c.margen_pct}%` : ""}
      </div>
    </div>
  );
}

function mesActual(): string {
  return new Intl.DateTimeFormat("es-EC", { month: "long" }).format(new Date());
}

/** Una línea de histórico armada con las tarifas reales. */
function historico(tarifas: Tarifa[], futuras: Tarifa[]): string {
  const vigentes = tarifas.filter((t) => t.vigente_ahora);
  const partes = vigentes.map(
    (t) => `${t.proveedor} $${Number(t.costo_unitario)} desde ${fechaCorta(t.vigente_desde)}`,
  );
  const cola = futuras.length
    ? ` · ${futuras.length === 1 ? "1 alza programada" : `${futuras.length} alzas programadas`}: ${futuras
        .map((f) => `${f.proveedor} pasa a $${Number(f.costo_unitario)} el ${fechaCorta(f.vigente_desde)}`)
        .join(", ")}`
    : " · sin cambios programados";
  return `Vigente: ${partes.join(" · ") || "sin tarifas cargadas"}${cola}. La tabla se recalcula con la tarifa que regía en la fecha de cada consumo.`;
}
