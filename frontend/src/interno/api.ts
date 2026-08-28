/** Tipos y llamadas del panel interno (fase 4). */

import { api } from "../api/cliente";

export type RolInterno = "SUPERADMIN" | "SOPORTE" | "LECTURA";

export interface Operador {
  nombre: string;
  rol: RolInterno;
  puede_actuar: boolean;
  es_superadmin: boolean;
  hoy: string;
  zona: string;
}

/** Una fila del semáforo «Salud de servicios». */
export interface ServicioSalud {
  nombre: string;
  detalle: string;
  /** ok | aviso | mal | apagado */
  estado: string;
}

export interface AlertaCritica {
  /** alta | media */
  severidad: string;
  texto: string;
  /** Sección del panel a la que lleva el botón «Ver». */
  seccion: string;
}

export interface Metricas {
  /** --- Los cuatro KPI de la cabecera --- */
  mrr: string;
  /** null cuando no hay mes anterior con qué comparar. */
  mrr_variacion_pct: number | null;
  altas_mes: number;
  altas_con_promo: number;
  bajas_mes: number;
  cancelaciones: number;
  suspensiones: number;
  activos_total: number;
  activos_por_plan: { plan: string; clientes: number }[];

  /** --- Comprobantes emitidos: 30 barras y tres contadores --- */
  emision: {
    barras: { dia: string; n: number }[];
    hoy: number;
    semana: number;
    mes: number;
    maximo: number;
  };

  servicios: ServicioSalud[];
  alertas: AlertaCritica[];

  /** --- Contadores heredados, los usan otros paneles --- */
  tenants: { total: number; activos: number; morosos: number };
  comprobantes_mes: { total: number; autorizados: number; rechazados: number };
  ingresos_mes: string;
  pagos_pendientes: number;
}

/* El panel interno NO maneja certificados: el .p12 y su clave son privados
   del contribuyente y se suben desde su propio panel. Aquí no hay tipos ni
   llamadas para ellos a propósito. */

export interface ClienteInterno {
  id: string;
  ruc: string;
  razon_social: string;
  email: string;
  /** Estado del inquilino en la tabla: ACTIVO | SUSPENDIDO | BAJA. */
  estado: string;
  /** El que muestra y filtra la maqueta, derivado en la base cruzando el
   *  inquilino con su suscripcion:
   *  ACTIVO | EN_PRUEBA | SUSPENDIDO | MOROSO | CANCELADO. */
  estado_cartera: string;
  plan: string | null;
  cupo: number;
  usados: number;
  suscripcion: string | null;
  /** ISO del ultimo comprobante que llego al SRI, o null si aun no emitio. */
  ultimo_comp: string | null;
  alta: string;
}

export interface FichaCliente {
  id: string;
  ruc: string;
  razon_social: string;
  nombre_comercial: string | null;
  email: string;
  telefono: string | null;
  estado: string;
  ambiente_sri: string;
  alta: string;
  plan: { nombre: string | null; precio: string };
  suscripcion: string | null;
  consumo: { comprobantes_mes: number; clientes: number; productos: number };
  certificado: { subject: string | null; vence: string | null };
}

export interface ComprobanteInterno {
  id: string;
  tenant_id: string;
  cliente: string;
  ruc: string;
  tipo: string;
  estado: string;
  numero: string | null;
  clave_acceso: string | null;
  total: string;
  mensajes: Record<string, Array<{ legible?: string }>> | null;
  intentos: number;
  actualizado: string;
}

export interface Promo {
  id: string;
  codigo: string;
  descripcion: string | null;
  tipo: string;
  valor: string;
  meses: number;
  planes: string[] | null;
  max_usos: number | null;
  usos: number;
  vigente_desde: string;
  vigente_hasta: string | null;
  activo: boolean;
  retenido_total: string;
  descuento_total: string;
}

export interface UsoPromo {
  id: string;
  usado_at: string;
  cliente: string;
  ruc: string;
  precio_lista: string | null;
  precio_cobrado: string | null;
  descuento: string;
  retenido: string;
  meses: number | null;
}

/** Buzón SRI del panel interno (fase 7). */
export interface CorreoBuzon {
  id: string;
  recibido: string;
  inquilino: string;
  buzon: string | null;
  remitente: string | null;
  tipo: string;
  estado: string;
  es_error: boolean;
  motivo_error: string | null;
}

export interface RespuestaBuzon {
  activo: boolean;
  dominio: string;
  correos: CorreoBuzon[];
  callados: Array<{ inquilino: string; dias: number; umbral: number }>;
}

/** Una solicitud de la landing: pedido del checkout o consulta de contacto. */
export interface Solicitud {
  id: string;
  tipo: "PEDIDO" | "CONSULTA";
  nombre: string;
  email: string;
  telefono: string | null;
  identificacion: string | null;
  ciudad: string | null;
  provincia: string | null;
  pais: string;
  plan: string | null;
  metodo_pago: string | null;
  agenda: string | null;
  mensaje: string | null;
  tiene_comprobante: boolean;
  avisado: boolean;
  atendida: boolean;
  creada: string;
}

export interface PlanInterno {
  id: string;
  codigo: string;
  nombre: string;
  precio: string;
  limites: Record<string, unknown>;
  vigente_desde: string;
  vigente_hasta: string | null;
  vigente_ahora: boolean;
  suscripciones: number;
}

/** Una fila de la tabla de costo por cliente (sección Consumo y costos). */
export interface FilaConsumo {
  tenant_id: string;
  cliente: string;
  plan: string;
  cupo: number;
  usados: number;
  /** null cuando el cliente aún no ha emitido nada este mes. */
  canal: { whatsapp_pct: number | null; panel_pct: number | null };
  ia_usados: number;
  ia_cupo: number;
  costo: string;
  costo_detalle: { whatsapp: string; ia: string; infra: string };
  /** A este ritmo, lo que costará el mes entero. */
  costo_proyectado: string;
  paga: string;
  margen: string;
  /** null si todavía no paga: sin ingreso no hay porcentaje que calcular. */
  margen_pct: number | null;
  /** El que decide la alerta: compara la mensualidad con el costo proyectado. */
  margen_proyectado_pct: number | null;
  /** ACTIVA | MOROSA | sin suscripción */
  suscripcion: string;
}

export interface Consumo {
  clientes: FilaConsumo[];
  periodo: { dias_transcurridos: number; dias_mes: number; hasta: string };
  totales: { ingreso: string; costo: string; margen: string; margen_pct: number | null };
  margen_bajo: FilaConsumo[];
}

/** Uno de los tres avisos automáticos editables desde Configuración. */
export interface AvisoAutomatico {
  aviso: string;
  etiqueta: string;
  texto: string;
  /** El de fábrica, para poder volver atrás sin buscarlo en el código. */
  texto_original: string;
  editado: boolean;
  /** Las variables que la plantilla aprobada por Meta exige, en su orden. */
  variables: string[];
  plantilla_meta: string;
}

export interface Tarifa {
  id: string;
  proveedor: string;
  concepto: string;
  costo_unitario: string;
  unidad: string;
  moneda: string;
  vigente_desde: string;
  vigente_hasta: string | null;
  vigente_ahora: boolean;
  notas: string | null;
}

export interface EntradaAuditoria {
  id: string;
  fecha: string;
  actor: string | null;
  rol: string | null;
  cliente: string | null;
  accion: string;
  tabla: string | null;
  registro_id: string | null;
  antes: Record<string, unknown> | null;
  despues: Record<string, unknown> | null;
  ip: string | null;
}

export interface SesionImpersonacion {
  token: string;
  expira_en: number;
  impersonacion_id: string;
  tenant: { id: string; razon_social: string };
  aviso: string;
}

export const sa = {
  yo: () => api.get<Operador>("/sa/yo"),
  metricas: () => api.get<Metricas>("/sa/metricas"),
  clientes: () => api.get<ClienteInterno[]>("/sa/clientes"),
  exportarClientes: () => api.descargar("/sa/clientes.csv", "clientes.csv"),
  ficha: (id: string, motivo: string) =>
    api.get<FichaCliente>(`/sa/clientes/${id}?motivo=${encodeURIComponent(motivo)}`),
  cambiarEstado: (id: string, estado: string, motivo: string) =>
    api.post<void>(`/sa/clientes/${id}/estado`, { estado, motivo }),
  impersonar: (id: string, motivo: string) =>
    api.post<SesionImpersonacion>(`/sa/clientes/${id}/impersonar`, { motivo }),
  salirImpersonacion: (id: string) => api.post<void>(`/sa/impersonaciones/${id}/salir`),
  comprobantes: (limite = 100) =>
    api.get<ComprobanteInterno[]>(`/sa/comprobantes?limite=${limite}`),
  promos: () => api.get<Promo[]>("/sa/promos"),
  crearPromo: (cuerpo: unknown) => api.post<{ id: string }>("/sa/promos", cuerpo),
  usosPromo: (id: string) =>
    api.get<{ codigo: string; resumen: Record<string, string>; usos: UsoPromo[] }>(
      `/sa/promos/${id}/usos`,
    ),
  origenes: () =>
    api.get<Array<{ origen: string; altas: number; retenido: string }>>(
      "/sa/marketing/origenes",
    ),
  planes: () => api.get<PlanInterno[]>("/sa/planes"),
  cambiarPrecio: (codigo: string, precio: string, vigente_desde: string) =>
    api.post<{ aviso: string }>(`/sa/planes/${codigo}/precio`, { precio, vigente_desde }),
  tarifas: () => api.get<Tarifa[]>("/sa/tarifas"),
  consumo: () => api.get<Consumo>("/sa/consumo"),
  avisos: () => api.get<AvisoAutomatico[]>("/sa/avisos"),
  guardarAvisos: (textos: Record<string, string>) =>
    api.put<void>("/sa/avisos", { textos }),
  programarTarifa: (cuerpo: {
    proveedor: string;
    concepto: string;
    costo_unitario: string;
    unidad: string;
    vigente_desde: string;
  }) => api.post<{ id: string; vigente_desde: string }>("/sa/tarifas", cuerpo),
  auditoria: (limite = 200) => api.get<EntradaAuditoria[]>(`/sa/auditoria?limite=${limite}`),
  altaCliente: (cuerpo: unknown) =>
    api.post<{ id: string; precio_cobrado: string; promo: unknown }>("/sa/clientes", cuerpo),
  buzon: () => api.get<RespuestaBuzon>("/sa/buzon"),
  buzonCrudo: (id: string) =>
    api.get<{ id: string; estado: string; motivo_error: string | null; xml: string }>(
      `/sa/buzon/${id}/crudo`,
    ),
  alternarBuzon: (activo: boolean) =>
    api.post<{ activo: boolean; etiqueta: string; mensaje: string }>(
      `/sa/buzon/flag?activo=${activo}`,
    ),
  solicitudes: (pendientes = true) =>
    api.get<Solicitud[]>(`/sa/solicitudes?pendientes=${pendientes}`),
  atenderSolicitud: (id: string) =>
    api.post<{ atendida: boolean }>(`/sa/solicitudes/${id}/atendida`),
};
