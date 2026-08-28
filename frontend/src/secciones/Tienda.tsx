/** Tienda en línea del panel (maqueta líneas 687-886).
 *
 * VITRINA INTERNA: la usa el equipo del negocio, no el comprador. La doctrina
 * de la maqueta manda: "Solo tu equipo accede, con los precios y el stock de
 * Artículos/Servicios." */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api/cliente";
import { usePlan } from "../plan/PlanContexto";
import { MuroPlan } from "../plan/Bloqueos";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";
import { dinero } from "../util/formato";

type Pestana = "pedidos" | "vitrina" | "config";

const PESTANAS: Array<{ id: Pestana; label: string }> = [
  { id: "pedidos", label: "Pedidos" },
  { id: "vitrina", label: "Mi tienda" },
  { id: "config", label: "Configuración" },
];

const ETIQUETA_ESTADO: Record<string, { label: string; clase: string }> = {
  POR_REVISAR: { label: "Por revisar", clase: "fc-estado--aviso" },
  TRANSFERENCIA_POR_CONFIRMAR: { label: "Pago por revisar", clase: "fc-estado--aviso" },
  POR_ENTREGAR: { label: "Por entregar", clase: "fc-estado--exito" },
  PAGADO: { label: "Pagado", clase: "fc-estado--exito" },
  ANULADO: { label: "Anulado", clase: "fc-estado--neutro" },
};

interface Pedido {
  id: string;
  numero: string;
  estado: string;
  metodo_pago: string;
  comprador: string;
  identificado: boolean;
  items: Array<{ nombre: string; cantidad: string }>;
  subtotal: string;
  iva: string;
  total: string;
  tiene_comprobante_pago: boolean;
  comprobante_id: string | null;
  creado: string;
}

interface ArticuloVitrina {
  id: string;
  codigo: string;
  nombre: string;
  precio_sin_iva: string;
  porcentaje_iva: string;
  tipo: string;
  maneja_inventario: boolean;
  stock: string;
  agotado: boolean;
}

export function Tienda({ onVerPlanes }: { onVerPlanes: () => void }) {
  const { permite, planPara } = usePlan();
  const [pestana, setPestana] = useState<Pestana>("pedidos");

  if (!permite("tienda")) {
    const destino = planPara("tienda") ?? "Empresario";
    return (
      <MuroPlan
        titulo="Tu tienda existe. Está esperando."
        texto={`La tienda en línea viene con el plan ${destino}. Tu catálogo y tus fotos siguen guardados tal como los dejaste, y vuelve a funcionar el mismo día que actives el plan.`}
        textoBoton={`Activar el plan ${destino}`}
        onVerPlanes={onVerPlanes}
      />
    );
  }

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div className="fc-tabs" role="tablist" aria-label="Secciones de la tienda">
        {PESTANAS.map((p) => (
          <button
            key={p.id}
            type="button"
            role="tab"
            className="fc-tab"
            aria-selected={pestana === p.id}
            onClick={() => setPestana(p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {pestana === "pedidos" && <Pedidos />}
      {pestana === "vitrina" && <MiTienda />}
      {pestana === "config" && <ConfiguracionTienda />}
    </div>
  );
}

function Pedidos() {
  const [datos, setDatos] = useState<{ resumen: Record<string, number>; pedidos: Pedido[] } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [trabajando, setTrabajando] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setError(null);
    try {
      setDatos(await api.get("/tienda/pedidos"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function accion(id: string, ruta: string) {
    setTrabajando(id);
    setError(null);
    try {
      await api.post(`/tienda/pedidos/${id}/${ruta}`);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos completar la acción");
    } finally {
      setTrabajando(null);
    }
  }

  if (error && !datos) return <ErrorSeccion mensaje={error} onReintentar={() => void cargar()} />;
  if (!datos) return <Cargando />;

  const r = datos.resumen;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div className="fc-kpi">
        <Contador etiqueta="Por revisar" valor={r.POR_REVISAR ?? 0} />
        <Contador
          etiqueta="Transferencias por confirmar"
          valor={r.TRANSFERENCIA_POR_CONFIRMAR ?? 0}
        />
        <Contador etiqueta="Por entregar" valor={r.POR_ENTREGAR ?? 0} />
        <Contador etiqueta="Pagados" valor={r.PAGADO ?? 0} />
      </div>

      {error && (
        <p className="fc-error" role="alert">
          {error}
        </p>
      )}

      <section className="fc-tarjeta fc-tarjeta--tabla">
        {datos.pedidos.length === 0 ? (
          <Vacio
            titulo="Todavía no hay pedidos."
            ayuda="Cuando tu equipo cierre una venta desde la vitrina, el pedido aparecerá aquí con su estado."
          />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="fc-tabla">
              <thead>
                <tr>
                  <th scope="col">Pedido</th>
                  <th scope="col">Comprador</th>
                  <th scope="col">Artículos</th>
                  <th scope="col" className="fc-num">Total</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Acción</th>
                </tr>
              </thead>
              <tbody>
                {datos.pedidos.map((p) => {
                  const tono = ETIQUETA_ESTADO[p.estado] ?? {
                    label: p.estado,
                    clase: "fc-estado--neutro",
                  };
                  return (
                    <tr key={p.id}>
                      <td className="fc-mono" style={{ fontWeight: 600 }}>
                        {p.numero}
                      </td>
                      <td>
                        <div>{p.comprador}</div>
                        <div style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                          {p.identificado ? "Identificado" : "Consumidor final"}
                        </div>
                      </td>
                      <td>{p.items.length}</td>
                      <td className="fc-num">{dinero(p.total)}</td>
                      <td>
                        <span className={`fc-estado ${tono.clase}`}>
                          <span className="fc-estado__punto" />
                          {tono.label}
                        </span>
                        {p.tiene_comprobante_pago && (
                          <div style={{ fontSize: 11.5, color: "var(--texto-tenue)", marginTop: 4 }}>
                            Con comprobante adjunto
                          </div>
                        )}
                      </td>
                      <td>
                        {p.estado === "TRANSFERENCIA_POR_CONFIRMAR" && (
                          <button
                            type="button"
                            className="fc-btn fc-btn--contorno"
                            style={{ padding: "6px 14px", fontSize: 12.5 }}
                            disabled={trabajando === p.id}
                            onClick={() => void accion(p.id, "confirmar-pago")}
                          >
                            Revisar pago
                          </button>
                        )}
                        {p.estado === "POR_ENTREGAR" && !p.comprobante_id && (
                          <button
                            type="button"
                            className="fc-btn fc-btn--primario"
                            style={{ padding: "6px 14px", fontSize: 12.5 }}
                            disabled={trabajando === p.id}
                            onClick={() => void accion(p.id, "facturar")}
                          >
                            Facturar
                          </button>
                        )}
                        {p.comprobante_id && (
                          <span style={{ fontSize: 12.5, color: "var(--texto-tenue)" }}>
                            Ya está en Comprobantes
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function MiTienda() {
  const [articulos, setArticulos] = useState<ArticuloVitrina[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ArticuloVitrina[]>("/tienda/vitrina")
      .then(setArticulos)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));
  }, []);

  if (error) return <ErrorSeccion mensaje={error} />;
  if (!articulos) return <Cargando />;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <section className="fc-tarjeta">
        <p className="fc-kicker">Tu inventario en vista de tienda</p>
        <p style={{ fontSize: 13.5, color: "var(--texto-suave)", margin: "6px 0 0" }}>
          Selecciona productos y cierra la venta aquí mismo. La vitrina es tu herramienta de venta:
          tus clientes no necesitan entrar aquí.
        </p>
      </section>

      {articulos.length === 0 ? (
        <section className="fc-tarjeta">
          <Vacio
            titulo="Aún no has puesto productos en la vitrina."
            ayuda="Marca «Mostrar en tienda» en los artículos que quieras vender desde aquí."
          />
        </section>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: 14,
          }}
        >
          {articulos.map((a) => (
            <article
              key={a.id}
              className="fc-tarjeta"
              style={{ padding: "16px 18px 18px", opacity: a.agotado ? 0.55 : 1 }}
            >
              <div style={{ fontSize: 14.5, fontWeight: 600, marginBottom: 4 }}>{a.nombre}</div>
              <div className="fc-mono" style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                {a.codigo}
              </div>
              <div className="fc-cifra" style={{ fontSize: 20, margin: "10px 0 2px" }}>
                {dinero(a.precio_sin_iva)}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--texto-tenue)", marginBottom: 10 }}>
                sin impuesto · IVA {Number(a.porcentaje_iva)}%
              </div>
              {a.agotado ? (
                <span className="fc-estado fc-estado--error">
                  <span className="fc-estado__punto" />
                  Agotado
                </span>
              ) : a.maneja_inventario ? (
                <span className="fc-estado fc-estado--exito">
                  <span className="fc-estado__punto" />
                  {Number(a.stock)} disponibles
                </span>
              ) : (
                <span className="fc-estado fc-estado--neutro">
                  <span className="fc-estado__punto" />
                  Servicio
                </span>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function ConfiguracionTienda() {
  const [metodos, setMetodos] = useState<
    Array<{ id: string; label: string; nota: string; activo: boolean }> | null
  >(null);

  useEffect(() => {
    api
      .get<Array<{ id: string; label: string; nota: string; activo: boolean }>>("/tienda/metodos")
      .then(setMetodos)
      .catch(() => setMetodos([]));
  }, []);

  return (
    <div className="fc-split">
      <div style={{ display: "grid", gap: 18 }}>
        <section className="fc-tarjeta--oscura">
          <div className="fc-halo" />
          <div style={{ position: "relative", zIndex: 1 }}>
            <p className="fc-kicker" style={{ color: "var(--verde-claro)" }}>
              Tu tienda es interna
            </p>
            <p
              style={{
                fontSize: 13.5,
                lineHeight: 1.55,
                color: "#A6BFB2",
                margin: "8px 0 14px",
                maxWidth: "46ch",
              }}
            >
              La vitrina es tu herramienta de venta: tú o tu equipo seleccionan los productos del
              inventario, cierran la venta y el comprobante sale al instante. Tus clientes no
              necesitan entrar aquí.
            </p>
            <div
              style={{
                background: "rgba(255,255,255,.06)",
                border: "1px solid rgba(92,230,143,.28)",
                borderRadius: 13,
                padding: "12px 14px",
                fontSize: 12.5,
                color: "#DDF3E6",
              }}
            >
              Solo tu equipo accede, con los precios y el stock de Artículos/Servicios.
            </div>
          </div>
        </section>

        <section className="fc-tarjeta">
          <h3 className="fc-titulo" style={{ fontSize: 18, marginBottom: 8 }}>
            Tus precios se cargan sin IVA
          </h3>
          <p style={{ fontSize: 13, lineHeight: 1.5, color: "var(--texto-suave)", margin: 0 }}>
            En Artículos/Servicios cada producto lleva su precio sin impuesto y su tarifa de IVA por
            separado. La tienda calcula el impuesto al facturar — así nunca hay dobles cobros ni
            descuadres.
          </p>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              background: "var(--superficie-suave)",
              border: "1px solid #EFF2EE",
              borderRadius: 14,
              padding: "13px 16px",
              marginTop: 14,
            }}
          >
            <span className="fc-mono" style={{ fontSize: 12, color: "var(--texto-suave)" }}>
              $100.00 + IVA 15%
            </span>
            <span style={{ color: "#8A9A91" }}>→</span>
            <span className="fc-mono" style={{ fontSize: 12, fontWeight: 700 }}>
              $115.00 en la factura
            </span>
          </div>
        </section>

        <section className="fc-tarjeta">
          <h3 className="fc-titulo" style={{ fontSize: 18, marginBottom: 8 }}>
            Si el comprador no quiere dar sus datos
          </h3>
          <p style={{ fontSize: 13, lineHeight: 1.5, color: "var(--texto-suave)", margin: 0 }}>
            Se emite igual, a consumidor final, y le llega su comprobante sin que entregue nada. Así
            tu venta queda declarada. Por norma del SRI, sin datos del comprador se puede facturar
            hasta $200: por encima de ese monto la vitrina te pedirá su cédula o RUC.
          </p>
          <div
            style={{
              display: "flex",
              gap: 10,
              alignItems: "center",
              background: "rgba(34,197,94,.07)",
              border: "1px solid rgba(22,121,74,.2)",
              borderRadius: 14,
              padding: "14px 16px",
              marginTop: 14,
              fontSize: 13.5,
              color: "var(--texto)",
            }}
          >
            <strong style={{ fontWeight: 600 }}>Activo siempre.</strong> Tu tienda nunca vende sin
            comprobante.
          </div>
        </section>
      </div>

      <section className="fc-tarjeta">
        <p className="fc-kicker">Cómo cobras</p>
        <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
          {(metodos ?? []).map((m) => (
            <div
              key={m.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                borderRadius: 13,
                padding: "13px 15px",
                background: m.activo ? "var(--superficie)" : "var(--superficie-suave)",
                border: `1px solid ${m.activo ? "var(--borde)" : "#EFF2EE"}`,
              }}
            >
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: "block", fontSize: 14, fontWeight: 600 }}>{m.label}</span>
                <span style={{ display: "block", fontSize: 12.5, color: "var(--texto-tenue)" }}>
                  {m.nota}
                </span>
              </span>
              <span
                style={{
                  fontSize: 11.5,
                  fontWeight: 600,
                  color: m.activo ? "var(--exito-texto)" : "var(--texto-tenue)",
                }}
              >
                {m.activo ? "Activo" : "Sin conectar"}
              </span>
            </div>
          ))}
        </div>
        <p style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--texto-tenue)", marginTop: 14 }}>
          El dinero entra directo a tu cuenta Payphone, no pasa por Factuchat. Si no la conectas, tu
          tienda cobra por transferencia y por WhatsApp.
        </p>
      </section>
    </div>
  );
}

function Contador({ etiqueta, valor }: { etiqueta: string; valor: number }) {
  return (
    <div className="fc-tarjeta" style={{ padding: "16px 18px 18px" }}>
      <div className="fc-cifra" style={{ fontSize: 24 }}>
        {valor}
      </div>
      <div style={{ fontSize: 12.5, color: "var(--texto-tenue)", marginTop: 4 }}>{etiqueta}</div>
    </div>
  );
}
