/** Estado del plan, cargado del servidor.
 *
 * El panel NO decide permisos: solo refleja lo que el servidor respondió en
 * /panel/estado. Cualquier bloqueo pintado aquí tiene su guarda equivalente en
 * el backend (services/planes.py), que es la que realmente protege.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api/cliente";
import type { EstadoPlan, FuncionPlan, NombrePlan } from "../api/tipos";

export interface EstadoFirma {
  cargada: boolean;
  vence: string | null;
}

/** Cabecera del negocio tal y como la imprime el RIDE. Viaja en /panel/estado
 *  —el mismo viaje que ya se hace al montar— y la usa «Revisa tu factura» para
 *  leerse como el documento que va a salir. `nombre_comercial` y
 *  `direccion_matriz` llegan en null si el perfil está incompleto: la pantalla
 *  esconde la línea, no inventa un «S/D» (eso es cosa del XML). */
export interface Emisor {
  razon_social: string;
  nombre_comercial: string | null;
  ruc: string;
  direccion_matriz: string | null;
  obligado_contabilidad: boolean;
}

interface ValorContexto {
  plan: EstadoPlan | null;
  /** null mientras no se sabe. Sin firma cargada el negocio no puede operar:
   *  el servidor rechaza sus peticiones con FIRMA_REQUERIDA. */
  firma: EstadoFirma | null;
  /** null mientras no se sabe: la revisión pinta un hueco, no un dato falso. */
  emisor: Emisor | null;
  cargando: boolean;
  error: string | null;
  permite: (funcion: FuncionPlan) => boolean;
  planPara: (funcion: FuncionPlan) => NombrePlan | null;
  recargar: () => Promise<void>;
}

const Contexto = createContext<ValorContexto | null>(null);

export function ProveedorPlan({ children }: { children: ReactNode }) {
  const [plan, setPlan] = useState<EstadoPlan | null>(null);
  const [firma, setFirma] = useState<EstadoFirma | null>(null);
  const [emisor, setEmisor] = useState<Emisor | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const recargar = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const datos = await api.get<{ plan: EstadoPlan; firma: EstadoFirma; emisor: Emisor }>(
        "/panel/estado",
      );
      setPlan(datos.plan);
      setFirma(datos.firma);
      setEmisor(datos.emisor);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos cargar tu plan");
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void recargar();
  }, [recargar]);

  const valor = useMemo<ValorContexto>(
    () => ({
      plan,
      firma,
      emisor,
      cargando,
      error,
      // Sin datos del servidor no se concede nada (deny by default)
      permite: (funcion) => Boolean(plan?.funciones?.[funcion]),
      planPara: (funcion) => plan?.planes_para_desbloquear?.[funcion] ?? null,
      recargar,
    }),
    [plan, firma, emisor, cargando, error, recargar],
  );

  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function usePlan(): ValorContexto {
  const valor = useContext(Contexto);
  if (!valor) throw new Error("usePlan debe usarse dentro de ProveedorPlan");
  return valor;
}
