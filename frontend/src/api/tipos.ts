/** Tipos compartidos con el backend (fase 3). */

export type NombrePlan = "Inicial" | "Independiente" | "Emprendedor" | "Empresario";

/** Funciones que el plan puede habilitar. El servidor decide; el panel refleja. */
export type FuncionPlan = "stock" | "tienda" | "voz" | "masivo" | "archivos";

export interface EstadoPlan {
  nombre: NombrePlan;
  precio: string;
  cupo: number;
  usados: number;
  restantes: number;
  pct_uso: number;
  pocos: boolean;
  acumula: boolean;
  nota_cupo: string;
  clientes: { usados: number; tope: number };
  productos: { usados: number; tope: number };
  /** Cupo mensual de análisis con IA (0 = el plan no lo incluye). */
  analisis_ia: number;
  numeros_whatsapp: number;
  funciones: Record<FuncionPlan, boolean>;
  planes_para_desbloquear: Record<FuncionPlan, NombrePlan | null>;
}

export type EstadoComprobante =
  | "PENDIENTE"
  | "FIRMADO"
  | "ENVIADO_SRI"
  | "AUTORIZADO"
  | "RECHAZADO"
  | "DEVUELTO";

export interface Comprobante {
  id: string;
  tipo: string;
  estado: EstadoComprobante;
  ambiente: string;
  numero: string | null;
  clave_acceso: string | null;
  numero_autorizacion: string | null;
  fecha_emision: string;
  subtotal: string;
  iva: string;
  total: string;
  mensajes: string[];
  intentos: number;
}

export type TipoIdentificacion =
  | "RUC"
  | "CEDULA"
  | "PASAPORTE"
  | "CONSUMIDOR_FINAL"
  | "ID_EXTERIOR";

export interface ClienteFinal {
  id: string;
  tipo_identificacion: TipoIdentificacion;
  identificacion: string;
  razon_social: string;
  email: string | null;
  telefono: string | null;
  direccion: string | null;
}

export interface Producto {
  id: string;
  codigo: string;
  nombre: string;
  descripcion: string | null;
  tipo: "BIEN" | "SERVICIO";
  precio_sin_iva: string;
  codigo_iva: string;
  porcentaje_iva: string;
  maneja_inventario: boolean;
  stock: string;
  stock_minimo: string | null;
  mostrar_en_tienda: boolean;
  activo: boolean;
}

export interface ProximaDeclaracion {
  noveno_digito: string;
  dia_maximo: number;
  fecha_limite: string;
  dias_restantes: number;
  periodo_declarado: string;
}

export interface DatosInicio {
  periodo: { desde: string; hasta: string };
  ventas_del_mes: string;
  iva_cobrado: string;
  comprobantes_emitidos: number;
  proxima_declaracion: ProximaDeclaracion;
  ranking: Array<{ cliente: string; total: string; comprobantes: number }>;
  ventas_por_dia: Array<{ fecha: string; total: string }>;
}

export interface ResumenFiscal {
  desde: string;
  hasta: string;
  ventas_sin_iva: string;
  iva_cobrado: string;
  notas_credito: string;
  total_facturado: string;
  retenciones_recibidas: string;
  a_pagar: string;
  comprobantes_emitidos: number;
}

/** Respuesta 402 cuando el plan no alcanza. */
export interface LimitePlan {
  mensaje: string;
  funcion: string;
  plan_sugerido: NombrePlan | null;
}

export interface FilaCargaMasiva {
  numero: number;
  identificacion: string;
  razon_social: string;
  email: string | null;
  telefono: string | null;
  tipo_identificacion: string;
  errores: string[];
  ya_guardado: boolean;
}

export interface VistaPreviaCarga {
  total: number;
  validas: number;
  con_error: number;
  ya_guardados: number;
  cabe_en_el_plan: boolean;
  disponibles_en_el_plan: number | null;
  filas: FilaCargaMasiva[];
}
