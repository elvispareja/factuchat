/** Clientes: libreta con tope por plan y carga masiva con vista previa
 *  (maqueta líneas 527-604). El tope bloquea el ALTA, nunca la facturación:
 *  ese matiz es explícito en el copy de la maqueta. */

import { useEffect, useMemo, useState } from "react";
import { ErrorLimitePlan, api } from "../api/cliente";
import type { ClienteFinal, VistaPreviaCarga } from "../api/tipos";
import { usePlan } from "../plan/PlanContexto";
import { FranjaTope } from "../plan/Bloqueos";
import { Cargando, ErrorSeccion, Vacio } from "../ui/Estados";
import { ETIQUETA_ID, dinero, inicial, telefonoLimpio } from "../util/formato";
import { NOMBRES_PROVINCIAS, PROVINCIAS } from "../util/ecuador";
import { CargaMasiva } from "./CargaMasiva";

export function Clientes({ onVerPlanes }: { onVerPlanes: () => void }) {
  const { plan, recargar } = usePlan();
  const [clientes, setClientes] = useState<ClienteFinal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busqueda, setBusqueda] = useState("");
  const [importando, setImportando] = useState(false);
  const [editando, setEditando] = useState<ClienteFinal | "nuevo" | null>(null);

  const cargar = () =>
    api
      .get<ClienteFinal[]>("/clientes")
      .then(setClientes)
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visibles = useMemo(() => {
    const t = busqueda.trim().toLowerCase();
    if (!t) return clientes ?? [];
    return (clientes ?? []).filter(
      (c) => c.razon_social.toLowerCase().includes(t) || c.identificacion.includes(t),
    );
  }, [clientes, busqueda]);

  const tope = plan?.clientes.tope ?? 0;
  const usados = plan?.clientes.usados ?? 0;
  const topeLleno = tope > 0 && usados >= tope;
  const pct = tope > 0 ? Math.min(100, Math.round((usados / tope) * 100)) : 34;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <section className="fc-tarjeta">
        <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <p className="fc-kicker">Tu libreta</p>
            <p className="fc-cifra" style={{ fontSize: 24, margin: "0 0 4px" }}>
              {tope > 0 ? `${usados} de ${tope} guardados` : `${usados} clientes, sin límite`}
            </p>
            <div
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Clientes guardados"
              style={{
                height: 5,
                borderRadius: 999,
                background: "var(--superficie-tenue)",
                overflow: "hidden",
                marginTop: 10,
                maxWidth: 320,
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${pct}%`,
                  borderRadius: 999,
                  background: topeLleno ? "var(--aviso-punto)" : "var(--verde-acento)",
                  animation: "dbBar .8s cubic-bezier(.16,1,.3,1) both",
                }}
              />
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button
              type="button"
              className="fc-btn fc-btn--contorno"
              onClick={() => setImportando(true)}
            >
              Importar desde Excel
            </button>
            <button
              type="button"
              className="fc-btn fc-btn--primario"
              disabled={topeLleno}
              onClick={() => setEditando("nuevo")}
            >
              Nuevo cliente
            </button>
          </div>
        </div>

        {topeLleno && (
          <FranjaTope
            texto="Llegaste al límite de tu plan. Tus clientes siguen aquí y puedes seguir facturándoles, pero para guardar nuevos necesitas subir de plan."
            onSubirPlan={onVerPlanes}
          />
        )}
      </section>

      {importando && (
        <CargaMasiva
          onCerrar={() => setImportando(false)}
          onListo={async () => {
            setImportando(false);
            await cargar();
            await recargar();
          }}
          onVerPlanes={onVerPlanes}
        />
      )}

      {error && <ErrorSeccion mensaje={error} />}
      {!error && !clientes && <Cargando />}
      {clientes && (
        <section className="fc-tarjeta fc-tarjeta--tabla">
          <div style={{ padding: "16px 18px", borderBottom: "1px solid var(--borde)" }}>
            <label>
              <span className="fc-label" style={{ position: "absolute", left: -9999 }}>
                Buscar cliente
              </span>
              <input
                className="fc-campo"
                type="search"
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
                placeholder="Buscar por nombre o identificación"
                style={{ maxWidth: 340 }}
              />
            </label>
          </div>
          {visibles.length === 0 ? (
            <Vacio
              titulo={
                busqueda ? "Sin resultados para esa búsqueda." : "Tu libreta está vacía."
              }
              ayuda={
                busqueda
                  ? "Prueba con el nombre o la identificación del cliente."
                  : "Guarda un cliente y lo tendrás listo para facturarle en un toque."
              }
            />
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="fc-tabla">
                <thead>
                  {/* Las cabeceras ya salen en mayúsculas pequeñas y tenues:
                      lo hace `.fc-tabla th` en design/componentes.css. */}
                  <tr>
                    <th scope="col">Nombre</th>
                    <th scope="col">Identificación</th>
                    <th scope="col">Contacto</th>
                    <th scope="col" className="fc-num">
                      Facturado
                    </th>
                    <th scope="col">Editar</th>
                  </tr>
                </thead>
                <tbody>
                  {visibles.map((c, i) => (
                    <tr
                      key={c.id}
                      // Los que exceden el tope se atenúan pero siguen usables
                      style={{
                        cursor: "pointer",
                        ...(tope > 0 && i >= tope ? { opacity: 0.45 } : undefined),
                      }}
                      onClick={() => setEditando(c)}
                    >
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                          <span aria-hidden="true" className="fc-avatar">
                            {inicial(c.razon_social)}
                          </span>
                          <span>
                            {/* Quien abre el modal con el teclado es este botón,
                                no la fila: el onClick del <tr> es solo comodidad
                                de ratón (mismo criterio que ClientesInternos). */}
                            <button
                              type="button"
                              className="fc-btn fc-btn--texto"
                              style={{
                                fontWeight: 600,
                                fontSize: 13.5,
                                color: "var(--texto)",
                                textAlign: "left",
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                setEditando(c);
                              }}
                            >
                              {c.razon_social}
                            </button>
                            <span
                              style={{
                                display: "block",
                                fontSize: 11.5,
                                color: "var(--texto-tenue)",
                                marginTop: 1,
                              }}
                            >
                              {ETIQUETA_ID[c.tipo_identificacion] ?? c.tipo_identificacion}
                            </span>
                          </span>
                        </div>
                      </td>
                      <td className="fc-mono" style={{ color: "var(--texto-tenue)" }}>
                        {c.identificacion}
                      </td>
                      <td style={{ color: "var(--texto-tenue)", fontSize: 12.5 }}>
                        {c.email || c.telefono ? (
                          <>
                            {c.email && <span style={{ display: "block" }}>{c.email}</span>}
                            {c.telefono && <span style={{ display: "block" }}>{c.telefono}</span>}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="fc-num">
                        <span style={{ fontWeight: 600 }}>{dinero(c.facturado ?? 0)}</span>
                        <span
                          style={{
                            display: "block",
                            fontSize: 11.5,
                            fontWeight: 400,
                            color: "var(--texto-tenue)",
                            marginTop: 1,
                          }}
                        >
                          {c.comprobantes ?? 0}{" "}
                          {(c.comprobantes ?? 0) === 1 ? "comprobante" : "comprobantes"}
                        </span>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          className="fc-btn-icono"
                          aria-label={`Editar a ${c.razon_social}`}
                          onClick={(e) => {
                            // Sin esto se dispararía también el onClick de la fila
                            e.stopPropagation();
                            setEditando(c);
                          }}
                        >
                          <svg
                            width="14"
                            height="14"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden="true"
                          >
                            <path d="M12 20h9" />
                            <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                          </svg>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {editando && (
        <FormularioCliente
          cliente={editando === "nuevo" ? null : editando}
          onCerrar={() => setEditando(null)}
          onGuardado={async () => {
            setEditando(null);
            await cargar();
            await recargar();
          }}
        />
      )}
    </div>
  );
}

/** Los tres con los que se factura a una persona o empresa concreta.
 *
 *  «Consumidor final» no está a propósito: no es alguien a quien se guarde en la
 *  libreta, es la venta sin cliente identificado (hasta $200), y la emisión ya la
 *  resuelve sola cuando la factura no lleva cliente. */
const TIPOS_ID: Array<{ id: ClienteFinal["tipo_identificacion"]; label: string }> = [
  { id: "RUC", label: "RUC" },
  { id: "CEDULA", label: "Cédula de ciudadanía" },
  { id: "PASAPORTE", label: "Pasaporte" },
];

/** Reglas por tipo, calcadas de las del servidor (schemas/clientes.py) para que
 *  el formulario avise antes de mandar algo que va a rebotar con un 422. */
const REGLAS_ID = {
  RUC: {
    digitos: 13,
    etiquetaNombre: "Razón social",
    placeholderNombre: "Comercial Andina S.A.",
    placeholderNumero: "1790012345001",
    ayuda: "13 dígitos, termina en 001",
  },
  CEDULA: {
    digitos: 10,
    etiquetaNombre: "Nombres y apellidos",
    placeholderNombre: "María Fernanda Pérez",
    placeholderNumero: "1712345678",
    ayuda: "10 dígitos",
  },
  PASAPORTE: {
    digitos: null,
    etiquetaNombre: "Nombres y apellidos",
    placeholderNombre: "María Fernanda Pérez",
    placeholderNumero: "AB123456",
    ayuda: "Sin formato fijo",
  },
} as const;

function FormularioCliente({
  cliente,
  onCerrar,
  onGuardado,
}: {
  cliente: ClienteFinal | null;
  onCerrar: () => void;
  onGuardado: () => void;
}) {
  // Un cliente puede tener un tipo que ya no está en el selector (los dados de
  // alta cuando había 5 opciones). Se CONSERVA el suyo: caer a «Cédula» sin
  // avisar hacía que abrir su ficha para corregirle el teléfono le cambiara el
  // tipo de identificación al guardar, porque el PUT reemplaza el registro
  // entero. El tipo antiguo se añade al desplegable solo para ese cliente.
  const tipoGuardado = cliente?.tipo_identificacion;
  const tipoFueraDeCatalogo = tipoGuardado != null && !(tipoGuardado in REGLAS_ID);
  const [tipoId, setTipoId] = useState<ClienteFinal["tipo_identificacion"]>(
    tipoGuardado ?? "CEDULA",
  );
  const [identificacion, setIdentificacion] = useState(cliente?.identificacion ?? "");
  const [razonSocial, setRazonSocial] = useState(cliente?.razon_social ?? "");
  const [email, setEmail] = useState(cliente?.email ?? "");
  const [telefono, setTelefono] = useState(cliente?.telefono ?? "");
  const [direccion, setDireccion] = useState(cliente?.direccion ?? "");
  const [provincia, setProvincia] = useState(cliente?.provincia ?? "");
  const [ciudad, setCiudad] = useState(cliente?.ciudad ?? "");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function guardar() {
    setGuardando(true);
    setError(null);
    const cuerpo = {
      tipo_identificacion: tipoId,
      identificacion: identificacion.trim(),
      razon_social: razonSocial.trim(),
      email: email.trim() || null,
      telefono: telefono.trim() || null,
      direccion: direccion.trim() || null,
      provincia: provincia || null,
      ciudad: ciudad || null,
    };
    try {
      if (cliente) {
        await api.put(`/clientes/${cliente.id}`, cuerpo);
      } else {
        await api.post("/clientes", cuerpo);
      }
      onGuardado();
    } catch (e) {
      setError(
        e instanceof ErrorLimitePlan
          ? e.message
          : e instanceof Error
            ? e.message
            : "No pudimos guardar el cliente",
      );
    } finally {
      setGuardando(false);
    }
  }

  const regla = REGLAS_ID[tipoId as keyof typeof REGLAS_ID] ?? REGLAS_ID.CEDULA;
  // hasOwn y no PROVINCIAS[x]: la provincia llega como texto libre desde la API,
  // y un valor como "constructor" devolvería una función del prototipo en vez de
  // undefined — el ?? no saltaría y el .map() de abajo tumbaría el modal.
  const cantones = Object.hasOwn(PROVINCIAS, provincia) ? PROVINCIAS[provincia] : [];
  const numeroOk =
    regla.digitos === null
      ? identificacion.trim().length >= 3
      : identificacion.length === regla.digitos;
  const valido = numeroOk && razonSocial.trim().length >= 2;

  return (
    <div className="fc-modal" role="dialog" aria-modal="true" aria-label="Cliente">
      <div className="fc-modal__panel" style={{ maxWidth: 720 }}>
        <p className="fc-kicker">{cliente ? "Editar cliente" : "Nuevo cliente"}</p>
        <h2 className="fc-titulo" style={{ fontSize: 20, marginBottom: 18 }}>
          {cliente ? cliente.razon_social : "Agregar a tu libreta"}
        </h2>

        <div style={{ display: "grid", gap: 14 }}>
          {/* El tipo es un desplegable de tres opciones; el número es lo que se
              teclea y se relee, así que se lleva el espacio. minmax(0,…) evita
              que el texto largo de una opción ensanche la columna. */}
          <div
            style={{ display: "grid", gridTemplateColumns: "minmax(0, 0.7fr) 1fr", gap: 12 }}
          >
            <div>
              <label className="fc-label" htmlFor="cf-tipo">
                Tipo de identificación
              </label>
              <select
                id="cf-tipo"
                className="fc-campo"
                value={tipoId}
                onChange={(e) => {
                  const nuevo = e.target.value as ClienteFinal["tipo_identificacion"];
                  setTipoId(nuevo);
                  // El número deja de encajar al cambiar de tipo: una cédula de
                  // 10 dígitos no es un RUC. Se recorta a lo que quepa en vez de
                  // borrarlo, porque el RUC suele ser la cédula más «001».
                  const limite = REGLAS_ID[nuevo as keyof typeof REGLAS_ID]?.digitos;
                  if (limite != null) {
                    setIdentificacion((n) => n.replace(/\D/g, "").slice(0, limite));
                  }
                }}
              >
                {tipoFueraDeCatalogo && tipoGuardado && (
                  // El tipo con el que se guardó, para no cambiárselo sin querer
                  <option value={tipoGuardado}>{ETIQUETA_ID[tipoGuardado] ?? tipoGuardado}</option>
                )}
                {TIPOS_ID.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="fc-label" htmlFor="cf-id">
                Número
              </label>
              <input
                id="cf-id"
                className="fc-campo fc-mono"
                value={identificacion}
                placeholder={regla.placeholderNumero}
                inputMode={regla.digitos === null ? "text" : "numeric"}
                maxLength={regla.digitos ?? 20}
                onChange={(e) =>
                  setIdentificacion(
                    // El pasaporte lleva letras; RUC y cédula, solo dígitos.
                    regla.digitos === null
                      ? e.target.value.trim()
                      : e.target.value.replace(/\D/g, "").slice(0, regla.digitos),
                  )
                }
              />
              <p style={{ fontSize: 11.5, color: "var(--texto-tenue)", margin: "4px 0 0" }}>
                {regla.ayuda}
              </p>
            </div>
          </div>

          {/* Nombre, correo y teléfono en una línea. Es flex y no grid a
              propósito: con `flex-wrap` los tres caen a varias líneas en una
              pantalla estrecha en vez de encogerse hasta ser ilegibles. El
              nombre pesa el doble porque es el campo largo. */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <div style={{ flex: "2 1 220px", minWidth: 0 }}>
              <label className="fc-label" htmlFor="cf-nombre">
                {regla.etiquetaNombre}
              </label>
              <input
                id="cf-nombre"
                className="fc-campo"
                value={razonSocial}
                placeholder={regla.placeholderNombre}
                onChange={(e) => setRazonSocial(e.target.value)}
              />
            </div>
            <div style={{ flex: "1 1 170px", minWidth: 0 }}>
              <label className="fc-label" htmlFor="cf-email">
                Correo
              </label>
              <input
                id="cf-email"
                type="email"
                className="fc-campo"
                value={email}
                placeholder="cliente@correo.com"
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div style={{ flex: "1 1 170px", minWidth: 0 }}>
              <label className="fc-label" htmlFor="cf-telefono">
                Teléfono
              </label>
              <input
                id="cf-telefono"
                className="fc-campo"
                value={telefono}
                placeholder="+593 99 000 0000"
                onChange={(e) => setTelefono(telefonoLimpio(e.target.value))}
              />
            </div>
          </div>

          <div>
            <label className="fc-label" htmlFor="cf-direccion">
              Dirección
            </label>
            <textarea
              id="cf-direccion"
              className="fc-campo"
              rows={3}
              value={direccion}
              placeholder="Av. Amazonas N34-56 y Av. República, Quito"
              style={{ resize: "vertical", minHeight: 72 }}
              onChange={(e) => setDireccion(e.target.value)}
            />
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <div style={{ flex: "1 1 200px", minWidth: 0 }}>
              <label className="fc-label" htmlFor="cf-provincia">
                Provincia
              </label>
              <select
                id="cf-provincia"
                className="fc-campo"
                value={provincia}
                onChange={(e) => {
                  setProvincia(e.target.value);
                  // Un cantón del Guayas no vale si ahora la provincia es
                  // Pichincha: la ciudad se vuelve a elegir siempre.
                  setCiudad("");
                }}
              >
                <option value="">Selecciona</option>
                {/* Un cliente importado puede traer una provincia escrita a
                    mano que no está en el catálogo; se muestra en vez de dejar
                    el desplegable en blanco sobre un dato que sí existe. */}
                {provincia && !Object.hasOwn(PROVINCIAS, provincia) && (
                  <option value={provincia}>{provincia}</option>
                )}
                {NOMBRES_PROVINCIAS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ flex: "1 1 200px", minWidth: 0 }}>
              {/* «Cantón» y no «Ciudad»: el catálogo son cantones, y en varios
                  no coinciden — quien es de Macas elige «Morona», y quien es de
                  Puyo, «Pastaza». Con la etiqueta anterior no encontraban su
                  ciudad y acababan eligiendo cualquiera o dejándolo vacío. */}
              <label className="fc-label" htmlFor="cf-ciudad">
                Cantón
              </label>
              <select
                id="cf-ciudad"
                className="fc-campo"
                value={ciudad}
                // Con la provincia fuera del catálogo no hay cantones, pero si
                // el cliente YA tiene uno guardado hay que poder corregirlo.
                disabled={cantones.length === 0 && !ciudad}
                onChange={(e) => setCiudad(e.target.value)}
              >
                <option value="">
                  {cantones.length === 0 ? "Elige la provincia primero" : "Selecciona"}
                </option>
                {ciudad && !cantones.includes(ciudad) && (
                  <option value={ciudad}>{ciudad}</option>
                )}
                {cantones.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
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
              {guardando ? "Guardando…" : cliente ? "Guardar cambios" : "Agregar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export { ErrorLimitePlan };
export type { VistaPreviaCarga };
