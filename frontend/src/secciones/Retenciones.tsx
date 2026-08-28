/** Bandeja de retenciones recibidas (Dashboard.dc.html, líneas 380-449).
 *
 * Tres tarjetas de resumen, la banda de custodia de siete años y la tabla de
 * seis columnas con descarga de XML por fila.
 *
 * El inquilino NUNCA emite una retención: solo la recibe. Por eso la primera
 * columna es «Quién te retuvo» y no «Cliente».
 *
 * Las cifras vienen calculadas del servidor. La maqueta las traía escritas a
 * mano y no cuadraban entre sí (14 documentos y $1,556.70 de saldo frente a 6
 * filas que suman $710.77): aquí todo sale de la misma consulta, así que el
 * conteo, el saldo y la tabla hablan siempre del mismo período.
 */

import { useEffect, useState } from "react";
import { api, sesion } from "../api/cliente";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";
import { dinero, fechaCorta } from "../util/formato";

interface RetencionFila {
  id: string;
  quien: string;
  ruc: string | null;
  numero: string;
  fecha: string | null;
  concepto: string | null;
  renta: string;
  iva: string;
  origen: string;
  verificada: boolean;
  verificacion: string | null;
  tiene_xml: boolean;
  tiene_pdf: boolean;
}

interface Bandeja {
  activo: boolean;
  buzon: string | null;
  periodo: { desde: string; hasta: string };
  saldo: string;
  saldo_renta: string;
  saldo_iva: string;
  documentos: number;
  agentes: number;
  retenciones: RetencionFila[];
}

export function Retenciones() {
  const [datos, setDatos] = useState<Bandeja | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Bandeja>("/retenciones")
      .then(setDatos)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));
  }, []);

  if (error) return <ErrorSeccion mensaje={error} />;
  if (!datos) return <Cargando />;

  const pendientes = datos.retenciones.filter((r) => !r.verificada).length;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="fc-kpi">
        <section className="fc-tarjeta--oscura" style={{ padding: "20px 22px" }}>
          <div className="fc-halo" />
          <div style={{ position: "relative", zIndex: 1 }}>
            <p className="fc-kicker" style={{ color: "var(--verde-claro)", margin: 0 }}>
              Saldo a tu favor
            </p>
            <div
              className="fc-cifra"
              style={{ fontSize: 30, margin: "8px 0 6px", color: "var(--texto-sobre-oscuro)" }}
            >
              {dinero(datos.saldo)}
            </div>
            <p style={{ fontSize: 12.5, color: "#A6BFB2", margin: 0, lineHeight: 1.5 }}>
              Crédito acumulado del semestre, listo para descontar.
            </p>
            {/* La maqueta mostraba una sola cifra; renta e IVA son impuestos
                distintos y el desglose evita que alguien reste lo que no debe. */}
            <p style={{ fontSize: 11.5, color: "#8FB3A0", margin: "8px 0 0", lineHeight: 1.5 }}>
              {dinero(datos.saldo_iva)} de IVA (baja tu declaración mensual) ·{" "}
              {dinero(datos.saldo_renta)} de renta (crédito de la anual)
            </p>
            {pendientes > 0 && (
              <p style={{ fontSize: 11.5, color: "#E8C766", margin: "6px 0 0", lineHeight: 1.5 }}>
                {pendientes === 1
                  ? "1 comprobante está comprobándose con el SRI y todavía no suma."
                  : `${pendientes} comprobantes se están comprobando con el SRI y todavía no suman.`}
              </p>
            )}
          </div>
        </section>

        <section className="fc-tarjeta" style={{ padding: "20px 22px" }}>
          <p className="fc-kicker" style={{ margin: 0 }}>
            Retenciones recibidas
          </p>
          <div className="fc-cifra" style={{ fontSize: 30, margin: "8px 0 6px" }}>
            {datos.documentos}
          </div>
          <p style={{ fontSize: 12.5, color: "var(--texto-tenue)", margin: 0, lineHeight: 1.5 }}>
            {datos.agentes === 1
              ? "De 1 empresa este semestre."
              : `De ${datos.agentes} empresas distintas este semestre.`}
          </p>
        </section>

        <section className="fc-tarjeta" style={{ padding: "20px 22px" }}>
          <p className="fc-kicker" style={{ margin: 0 }}>
            Reenvía y listo
          </p>
          <p
            style={{
              fontSize: 13,
              lineHeight: 1.55,
              color: "var(--texto-suave)",
              margin: "8px 0 12px",
            }}
          >
            Manda el XML al chat y el asistente lo lee, lo clasifica y lo suma solo.
          </p>
          {datos.buzon && (
            <p
              className="fc-mono"
              style={{
                fontSize: 12,
                background: "var(--superficie-tenue)",
                border: "1px solid var(--borde)",
                borderRadius: "var(--radio-campo)",
                padding: "9px 11px",
                margin: 0,
                wordBreak: "break-all",
              }}
            >
              {datos.buzon}
            </p>
          )}
        </section>
      </div>

      <section
        className="fc-tarjeta"
        style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}
      >
        <div
          style={{
            flex: 1,
            minWidth: 260,
            fontSize: 13.5,
            lineHeight: 1.55,
            color: "var(--texto-suave)",
            textWrap: "pretty",
          }}
        >
          Guardamos el XML y el PDF de cada comprobante de retención, con su detalle de renta y de
          IVA, por siete años. Baja uno o todos cuando los necesites.
        </div>
      </section>

      <section className="fc-tarjeta fc-tarjeta--tabla">
        {datos.retenciones.length === 0 ? (
          <Vacio
            titulo="Todavía no ha llegado ninguna retención."
            ayuda={
              datos.buzon
                ? `Cuando una empresa te retenga, reenvía su XML a ${datos.buzon} o al chat y aparecerá aquí.`
                : "Cuando una empresa te retenga, reenvía su XML al chat y aparecerá aquí."
            }
          />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="fc-tabla" style={{ minWidth: 860 }}>
              <thead>
                <tr>
                  <th scope="col">Quién te retuvo</th>
                  <th scope="col">Fecha</th>
                  <th scope="col">Concepto</th>
                  <th scope="col" className="fc-num">
                    Ret. renta
                  </th>
                  <th scope="col" className="fc-num">
                    Ret. IVA
                  </th>
                  <th scope="col" className="fc-num">
                    Archivo
                  </th>
                </tr>
              </thead>
              <tbody>
                {datos.retenciones.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{r.quien}</div>
                      <div className="fc-mono" style={{ fontSize: 11.5, color: "var(--texto-tenue)" }}>
                        {r.numero}
                        {r.ruc ? ` · ${r.ruc}` : ""}
                      </div>
                      {/* Copia nueva, no está en la maqueta: una retención solo
                          suma cuando el SRI confirma que existe. */}
                      {!r.verificada && (
                        <div
                          className="fc-estado fc-estado--aviso"
                          style={{ marginTop: 6, fontSize: 11 }}
                          title={r.verificacion ?? undefined}
                        >
                          <span className="fc-estado__punto" />
                          Comprobando con el SRI
                        </div>
                      )}
                    </td>
                    <td style={{ fontSize: 13 }}>{r.fecha ? fechaCorta(r.fecha) : "—"}</td>
                    <td style={{ fontSize: 13, color: "var(--texto-suave)" }}>
                      {r.concepto ?? "—"}
                    </td>
                    <td className="fc-num">{dinero(r.renta)}</td>
                    <td className="fc-num">{dinero(r.iva)}</td>
                    <td className="fc-num">
                      {r.tiene_xml ? (
                        <button
                          type="button"
                          className="fc-btn fc-btn--contorno"
                          style={{ padding: "5px 13px", fontSize: 12 }}
                          title="Descargar XML"
                          onClick={() => void bajarXml(r)}
                        >
                          XML
                        </button>
                      ) : (
                        <span style={{ fontSize: 12, color: "var(--texto-tenue)" }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/** Descarga el XML con el token de sesión: la ruta está autenticada, así que no
 *  sirve un enlace directo. El servidor lo descifra al vuelo. */
async function bajarXml(r: RetencionFila) {
  const respuesta = await fetch(`/api/v1/retenciones/${r.id}/xml`, {
    headers: sesion.access ? { Authorization: `Bearer ${sesion.access}` } : {},
  });
  if (!respuesta.ok) return;
  const blob = await respuesta.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `retencion-${r.numero}.xml`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
