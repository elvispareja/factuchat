/** Dashboard general del panel interno.
 *
 *  Estructura tomada de `diseno/Superadmin.dc.html` (bloque `esDash`): cuatro
 *  KPI con el MRR en tarjeta oscura, el panel de comprobantes emitidos con sus
 *  tres contadores y las 30 barras, y abajo «Salud de servicios» y «Alertas
 *  críticas».
 *
 *  Los textos que en la maqueta son datos de ejemplo —«+12% vs julio», «4 con
 *  código LANZA99», «142 ms»— se calculan aquí con lo que devuelve el servidor.
 *  Ninguna cifra se inventa en el navegador.
 */

import { useCallback, useEffect, useState } from "react";
import { sa, type AlertaCritica, type Metricas, type ServicioSalud } from "../api";
import { MENU_INTERNO, type IdSeccionInterna } from "../navegacion";
import { Cargando, ErrorSeccion } from "../../ui/Estados";
import { dinero } from "../../util/formato";

/** Cada cuánto se vuelve a pedir el panel. La salud de servicios envejece
 *  rápido: media hora de retraso haría inútil el semáforo. */
const REFRESCO_MS = 60_000;
/** Cada cuánto se repinta el «hace N min» sin pedir nada al servidor. */
const RELOJ_MS = 15_000;

const MESES = [
  "enero",
  "febrero",
  "marzo",
  "abril",
  "mayo",
  "junio",
  "julio",
  "agosto",
  "septiembre",
  "octubre",
  "noviembre",
  "diciembre",
];

function mesAnterior(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return MESES[d.getMonth()];
}

function plural(n: number, uno: string, varios: string): string {
  return `${n} ${n === 1 ? uno : varios}`;
}

function haceCuanto(desde: number, ahora: number): string {
  const min = Math.floor((ahora - desde) / 60_000);
  return min < 1 ? "ahora mismo" : `hace ${min} min`;
}

const ROTULO_ESTADO: Record<string, string> = {
  ok: "operativo",
  aviso: "con avisos",
  mal: "caído",
  apagado: "sin configurar",
};

export function DashboardInterno({ onIr }: { onIr?: (s: IdSeccionInterna) => void }) {
  const [datos, setDatos] = useState<Metricas | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [medido, setMedido] = useState(0);
  const [ahora, setAhora] = useState(() => Date.now());

  const cargar = useCallback(async (vivo: () => boolean) => {
    try {
      const d = await sa.metricas();
      if (!vivo()) return;
      setDatos(d);
      setMedido(Date.now());
      setError(null);
    } catch (e) {
      if (!vivo()) return;
      // Con datos ya en pantalla, un fallo del refresco no los borra: se
      // quedan, y el «hace N min» delata que están envejeciendo.
      setDatos((previos) => {
        if (!previos) setError(e instanceof Error ? e.message : "Error");
        return previos;
      });
    }
  }, []);

  useEffect(() => {
    let vigente = true;
    const vivo = () => vigente;
    void cargar(vivo);
    const t = setInterval(() => void cargar(vivo), REFRESCO_MS);
    return () => {
      vigente = false;
      clearInterval(t);
    };
  }, [cargar]);

  useEffect(() => {
    const t = setInterval(() => setAhora(Date.now()), RELOJ_MS);
    return () => clearInterval(t);
  }, []);

  if (error && !datos) return <ErrorSeccion mensaje={error} />;
  if (!datos) return <Cargando />;

  // Un inquilino activo sin suscripción activa está en periodo de prueba;
  // la maqueta lo muestra como «1 en prueba» al final del desglose.
  const enPrueba =
    datos.activos_total - datos.activos_por_plan.reduce((a, p) => a + p.clientes, 0);
  const desglose = [
    ...datos.activos_por_plan.map((p) => `${p.clientes} ${p.plan}`),
    ...(enPrueba > 0 ? [`${enPrueba} en prueba`] : []),
  ].join(" · ");

  const variacion = datos.mrr_variacion_pct;
  const edad = haceCuanto(medido, ahora);

  return (
    <div style={{ animation: "dbIn .35s ease-out both" }}>
      <div className="fc-sa-kpis">
        <div className="fc-sa-kpi fc-sa-kpi--oscura">
          <div className="fc-sa-kpi__rotulo">MRR</div>
          <div className="fc-sa-kpi__cifra">{dinero(datos.mrr)}</div>
          <div className="fc-sa-kpi__pie">
            {variacion === null ? (
              "Primer mes: aún no hay con qué comparar"
            ) : (
              <>
                <strong
                  style={{
                    fontWeight: 700,
                    color: variacion >= 0 ? "var(--verde-claro)" : "var(--dorado)",
                  }}
                >
                  {variacion >= 0 ? "+" : ""}
                  {variacion}%
                </strong>{" "}
                vs {mesAnterior()}
              </>
            )}
          </div>
        </div>

        <div className="fc-sa-kpi">
          <div className="fc-sa-kpi__rotulo">Altas del mes</div>
          <div className="fc-sa-kpi__cifra">{datos.altas_mes}</div>
          <div className="fc-sa-kpi__pie">
            {datos.altas_con_promo > 0
              ? `${datos.altas_con_promo} con código promocional`
              : "sin códigos promocionales"}
          </div>
        </div>

        <div className="fc-sa-kpi">
          <div className="fc-sa-kpi__rotulo">Bajas del mes</div>
          <div className="fc-sa-kpi__cifra">{datos.bajas_mes}</div>
          <div className="fc-sa-kpi__pie">
            {plural(datos.cancelaciones, "cancelación", "cancelaciones")} ·{" "}
            {plural(datos.suspensiones, "suspensión", "suspensiones")}
          </div>
        </div>

        <div className="fc-sa-kpi">
          <div className="fc-sa-kpi__rotulo">Clientes activos</div>
          <div className="fc-sa-kpi__cifra">{datos.activos_total}</div>
          <div className="fc-sa-kpi__pie" style={{ fontSize: 11.5 }}>
            {desglose || "todavía sin clientes activos"}
          </div>
        </div>
      </div>

      <section className="fc-sa-panel" style={{ marginBottom: 14 }}>
        <div className="fc-sa-emision">
          <h2 className="fc-sa-panel__titulo">Comprobantes emitidos</h2>
          <div className="fc-sa-emision__dato">
            Hoy <strong>{datos.emision.hoy}</strong>
          </div>
          <div className="fc-sa-emision__dato">
            Semana <strong>{datos.emision.semana}</strong>
          </div>
          <div className="fc-sa-emision__dato">
            Mes <strong>{datos.emision.mes}</strong>
          </div>
          <span style={{ marginLeft: "auto", fontSize: 11.5, color: "#8A9A91" }}>
            Últimos 30 días
          </span>
        </div>
        <Barras barras={datos.emision.barras} maximo={datos.emision.maximo} />
      </section>

      <div className="fc-sa-abajo">
        <section className="fc-sa-panel">
          <h2 className="fc-sa-panel__titulo" style={{ marginBottom: 14 }}>
            Salud de servicios
          </h2>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {datos.servicios.map((s) => (
              <Servicio key={s.nombre} servicio={s} edad={edad} />
            ))}
          </div>
        </section>

        <section className="fc-sa-panel">
          <h2 className="fc-sa-panel__titulo" style={{ marginBottom: 14 }}>
            Alertas críticas
          </h2>
          {datos.alertas.length === 0 ? (
            <p style={{ fontSize: 13, color: "var(--texto-tenue)", margin: 0 }}>
              Nada que atender ahora mismo.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
              {datos.alertas.map((a, i) => (
                <Alerta key={`${a.seccion}-${i}`} alerta={a} onIr={onIr} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/** Las 30 barras. La altura es relativa al día más alto del periodo, igual que
 *  en la maqueta; un día sin emisión deja una marca gris para que el hueco se
 *  distinga de un día que no existe. */
function Barras({ barras, maximo }: { barras: { dia: string; n: number }[]; maximo: number }) {
  return (
    <div
      className="fc-sa-barras"
      role="img"
      aria-label={`Comprobantes emitidos por día, últimos ${barras.length} días`}
    >
      {barras.map((b) => (
        <div
          key={b.dia}
          className="fc-sa-barras__b"
          data-cero={b.n === 0 ? "1" : "0"}
          style={{
            height: maximo > 0 ? `${Math.max(2, Math.round((b.n / maximo) * 100))}%` : 2,
          }}
          title={`${b.dia}: ${plural(b.n, "comprobante", "comprobantes")}`}
        />
      ))}
    </div>
  );
}

function Servicio({ servicio, edad }: { servicio: ServicioSalud; edad: string }) {
  return (
    <div className="fc-sa-servicio">
      <span
        className="fc-sa-servicio__punto"
        data-estado={servicio.estado}
        role="img"
        aria-label={ROTULO_ESTADO[servicio.estado] ?? servicio.estado}
      />
      <span className="fc-sa-servicio__nombre">{servicio.nombre}</span>
      <span className="fc-sa-servicio__detalle">{servicio.detalle}</span>
      <span className="fc-sa-servicio__hace">{edad}</span>
    </div>
  );
}

function Alerta({ alerta, onIr }: { alerta: AlertaCritica; onIr?: (s: IdSeccionInterna) => void }) {
  // La sección llega del servidor: se comprueba contra el menú antes de
  // navegar, para que un valor inesperado no rompa la pantalla.
  const destino = MENU_INTERNO.find((m) => m.id === alerta.seccion)?.id;
  return (
    <div className="fc-sa-alerta">
      <span className="fc-sa-alerta__punto" data-sev={alerta.severidad} />
      <span className="fc-sa-alerta__texto">{alerta.texto}</span>
      {destino && onIr && (
        <button type="button" className="fc-sa-alerta__ver" onClick={() => onIr(destino)}>
          Ver
        </button>
      )}
    </div>
  );
}
