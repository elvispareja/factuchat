/** Cliente HTTP del panel.
 *
 * Renueva el access token con el refresh cuando expira (sesiones de 30 min) y
 * traduce el 402 del servidor en un error tipado de límite de plan, para que la
 * interfaz muestre el bloqueo que corresponde SIN decidir permisos por su cuenta.
 */

import type { LimitePlan } from "./tipos";

const BASE = "/api/v1";
const CLAVE_ACCESS = "fc_access";
const CLAVE_REFRESH = "fc_refresh";

export class ErrorApi extends Error {
  constructor(
    readonly status: number,
    mensaje: string,
  ) {
    super(mensaje);
    this.name = "ErrorApi";
  }
}

export class ErrorLimitePlan extends ErrorApi {
  constructor(readonly limite: LimitePlan) {
    super(402, limite.mensaje);
    this.name = "ErrorLimitePlan";
  }
}

/** El negocio no ha subido su firma electrónica y el servidor le cierra las
 *  rutas de operación. La pantalla lo lleva a subirla. */
export class ErrorFirmaRequerida extends ErrorApi {
  constructor(mensaje: string) {
    super(403, mensaje);
    this.name = "ErrorFirmaRequerida";
  }
}

export class SesionExpirada extends ErrorApi {
  constructor() {
    super(401, "Tu sesión expiró. Vuelve a entrar.");
    this.name = "SesionExpirada";
  }
}

function leer(clave: string): string | null {
  try {
    return window.localStorage.getItem(clave);
  } catch {
    return null; // navegación privada o almacenamiento bloqueado
  }
}

function guardar(clave: string, valor: string | null): void {
  try {
    if (valor === null) window.localStorage.removeItem(clave);
    else window.localStorage.setItem(clave, valor);
  } catch {
    /* sin almacenamiento: la sesión dura lo que dure la pestaña */
  }
}

export const sesion = {
  get access() {
    return leer(CLAVE_ACCESS);
  },
  get refresh() {
    return leer(CLAVE_REFRESH);
  },
  guardar(access: string, refresh: string) {
    guardar(CLAVE_ACCESS, access);
    guardar(CLAVE_REFRESH, refresh);
  },
  limpiar() {
    guardar(CLAVE_ACCESS, null);
    guardar(CLAVE_REFRESH, null);
  },
  get activa() {
    return Boolean(leer(CLAVE_ACCESS));
  },
};

/** Una sola renovación en vuelo: varias peticiones que caducan a la vez no
 *  disparan varios refresh (el servidor revoca la familia si detecta reúso). */
let renovacionEnVuelo: Promise<boolean> | null = null;

async function renovar(): Promise<boolean> {
  const refresh = sesion.refresh;
  if (!refresh) return false;
  if (!renovacionEnVuelo) {
    renovacionEnVuelo = (async () => {
      try {
        const r = await fetch(`${BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!r.ok) {
          sesion.limpiar();
          return false;
        }
        const datos = await r.json();
        sesion.guardar(datos.access_token, datos.refresh_token);
        return true;
      } catch {
        return false;
      } finally {
        renovacionEnVuelo = null;
      }
    })();
  }
  return renovacionEnVuelo;
}

async function extraerError(r: Response): Promise<never> {
  let detalle: unknown = null;
  try {
    detalle = (await r.json())?.detail;
  } catch {
    /* respuesta sin cuerpo JSON */
  }
  if (r.status === 402 && detalle && typeof detalle === "object") {
    throw new ErrorLimitePlan(detalle as LimitePlan);
  }
  if (
    r.status === 403 &&
    detalle &&
    typeof detalle === "object" &&
    (detalle as { codigo?: string }).codigo === "FIRMA_REQUERIDA"
  ) {
    throw new ErrorFirmaRequerida(
      (detalle as { mensaje?: string }).mensaje ?? "Sube tu firma electrónica para continuar.",
    );
  }
  const mensaje =
    typeof detalle === "string"
      ? detalle
      : "No pudimos completar la acción. Inténtalo de nuevo.";
  throw new ErrorApi(r.status, mensaje);
}

async function peticion<T>(
  ruta: string,
  opciones: RequestInit = {},
  reintentado = false,
): Promise<T> {
  const cabeceras = new Headers(opciones.headers);
  const access = sesion.access;
  if (access) cabeceras.set("Authorization", `Bearer ${access}`);
  if (opciones.body && !(opciones.body instanceof FormData)) {
    cabeceras.set("Content-Type", "application/json");
  }

  const r = await fetch(`${BASE}${ruta}`, { ...opciones, headers: cabeceras });

  if (r.status === 401 && !reintentado && sesion.refresh) {
    if (await renovar()) return peticion<T>(ruta, opciones, true);
    throw new SesionExpirada();
  }
  if (r.status === 401) throw new SesionExpirada();
  if (!r.ok) await extraerError(r);
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

/** Intercambio de credenciales: login y 2FA.
 *
 *  NO pasa por `peticion` a propósito. Ahí un 401 significa "tu sesión expiró"
 *  y dispara la renovación con el refresh token; aquí significa "esas
 *  credenciales no valen" o "falta el código de verificación", que es un
 *  mensaje que el usuario TIENE que ver. Mezclar los dos casos dejaba al
 *  superadmin sin poder entrar nunca: el servidor pedía su código de 2FA y la
 *  pantalla respondía "Tu sesión expiró".
 */
async function autenticar<T>(ruta: string, cuerpo: unknown): Promise<T> {
  const r = await fetch(`${BASE}${ruta}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  });
  if (!r.ok) await extraerError(r);
  return (await r.json()) as T;
}

/** Descarga un archivo que el servidor entrega con Authorization.
 *
 *  Un `<a href>` normal no sirve: el navegador no adjunta el token, así que la
 *  descarga volvería 401. Se pide con `peticion` para heredar la renovación de
 *  sesión y se entrega como blob.
 */
async function descargar(ruta: string, nombrePorDefecto: string): Promise<void> {
  const r = await peticionCruda(ruta);
  const blob = await r.blob();
  // El servidor manda el nombre en Content-Disposition; si un proxy lo quita,
  // se usa el de reserva en vez de dejar el archivo sin nombre.
  const cd = r.headers.get("Content-Disposition") ?? "";
  const nombre = /filename="([^"]+)"/.exec(cd)?.[1] ?? nombrePorDefecto;

  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = nombre;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Sin esto el blob se queda en memoria hasta recargar la pestaña
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

/** Como `peticion`, pero devuelve la respuesta sin interpretarla como JSON. */
async function peticionCruda(ruta: string, reintentado = false): Promise<Response> {
  const cabeceras = new Headers();
  const access = sesion.access;
  if (access) cabeceras.set("Authorization", `Bearer ${access}`);

  const r = await fetch(`${BASE}${ruta}`, { headers: cabeceras });

  if (r.status === 401 && !reintentado && sesion.refresh) {
    if (await renovar()) return peticionCruda(ruta, true);
    throw new SesionExpirada();
  }
  if (r.status === 401) throw new SesionExpirada();
  if (!r.ok) await extraerError(r);
  return r;
}

export const api = {
  autenticar,
  descargar,
  get: <T>(ruta: string) => peticion<T>(ruta),
  post: <T>(ruta: string, cuerpo?: unknown) =>
    peticion<T>(ruta, { method: "POST", body: cuerpo ? JSON.stringify(cuerpo) : undefined }),
  put: <T>(ruta: string, cuerpo: unknown) =>
    peticion<T>(ruta, { method: "PUT", body: JSON.stringify(cuerpo) }),
  delete: <T>(ruta: string) => peticion<T>(ruta, { method: "DELETE" }),
  subir: <T>(ruta: string, archivo: File, campos: Record<string, string> = {}) => {
    const datos = new FormData();
    datos.append("archivo", archivo);
    for (const [k, v] of Object.entries(campos)) datos.append(k, v);
    return peticion<T>(ruta, { method: "POST", body: datos });
  },
};
