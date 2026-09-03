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
  /** Columnas CLIENTE y DETALLE del historial. Salen del snapshot del payload
   *  (lo que se le mandó al SRI), no de un JOIN: por eso siguen siendo fieles
   *  aunque el cliente se renombre o se borre. `cliente` en null = la venta se
   *  hizo a consumidor final. */
  cliente: string | null;
  cliente_identificacion: string | null;
  cliente_tipo_id: string | null;
  detalle: string | null;
}

/** Una línea de la factura que la nota de crédito modifica. Todo viaja como
 *  cadena (Decimal del servidor): parsear, nunca concatenar. */
export interface ItemAcreditable {
  codigo: string;
  descripcion: string;
  cantidad: string;
  precio_unitario: string;
  /** Lo REBAJADO en esa línea al facturar. La nota de crédito se precarga con
   *  él: sin eso reflejaría el precio de tarifa y no lo que el cliente pagó. */
  descuento: string;
  codigo_iva: string;
  /** Tarifa del `codigo_iva`, en porcentaje («15»). */
  tarifa_iva: string;
}

/** Una factura que TODAVÍA admite nota de crédito (GET /comprobantes/acreditables).
 *
 *  El servidor solo devuelve las autorizadas con saldo, así que elegir una de
 *  aquí nunca acaba en un rechazo por «ya está anulada». `pendiente` es el tope
 *  del importe de la nueva nota: el total menos lo que ya se le devolvió. */
export interface FacturaAcreditable {
  id: string;
  numero: string;
  fecha_emision: string;
  /** Razón social del snapshot; `cliente_final_id` en null = consumidor final. */
  cliente: string | null;
  cliente_identificacion: string | null;
  cliente_final_id: string | null;
  total: string;
  acreditado: string;
  pendiente: string;
  items: ItemAcreditable[];
}

/** Una opción del panel de pago.
 *
 *  OJO: `codigo` NO es clave única. Un plazo (una venta a crédito) no es una
 *  forma de pago de la tabla 24, así que se expresa repitiendo el mismo código
 *  con un plazo_dias distinto. Hoy todas las opciones son al contado, pero la
 *  identidad de un chip sigue siendo el par (codigo, plazo_dias) —que es lo que
 *  se manda al crear la factura—, no el código suelto. */
export interface OpcionPago {
  codigo: string;
  etiqueta: string;
  plazo_dias: number | null;
}

/** Vista PREVIA del número que le tocaría al próximo comprobante. El servidor
 *  no lo reserva (reservar dejaría huecos cada vez que alguien abre el modal y
 *  lo cierra), así que si alguien emite entre medias el definitivo será otro:
 *  el de verdad lo devuelve `emitir`. */
export interface SiguienteNumero {
  numero: string;
  establecimiento: string;
  punto_emision: string;
  secuencial: number;
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
  provincia: string | null;
  ciudad: string | null;
  /** Solo los trae GET /clientes (`ClienteFinalListado`), no la ficha ni el
   *  POST/PUT: ahí devolver 0 sería mentir sobre un dato de dinero. `facturado`
   *  viaja como string (Decimal de Pydantic) — parsear, nunca concatenar. */
  facturado?: string;
  comprobantes?: number;
}

/** Una combinación concreta a la venta (talla 38 roja) con su SKU y su stock.
 *  `precio_sin_iva` en null = hereda el precio del producto. */
export interface ProductoVariante {
  id: string;
  codigo: string;
  precio_sin_iva: string | null;
  stock: string;
  activo: boolean;
  valores: Array<{ atributo_id: string; atributo_valor_id: string }>;
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
  /** El servidor NO manda la ruta del archivo, solo si lo hay: la imagen se
   *  pide aparte con GET /productos/{id}/imagen. */
  tiene_imagen: boolean;
  activo: boolean;
  categoria_id: string | null;
  /** Qué valores tiene disponibles el producto (puede repetir atributo_id). */
  atributos: Array<{ atributo_id: string; atributo_valor_id: string }>;
  variantes: ProductoVariante[];
}

export interface Categoria {
  id: string;
  nombre: string;
  descripcion: string | null;
  activo: boolean;
}

export interface Atributo {
  id: string;
  categoria_id: string;
  nombre: string;
  activo: boolean;
}

export interface AtributoValor {
  id: string;
  atributo_id: string;
  valor: string;
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
