/** Las 11 secciones del panel interno, con los rótulos exactos de la maqueta
 *  (Superadmin.dc.html líneas 1239-1249). */

export type IdSeccionInterna =
  | "dash"
  | "clientes"
  | "consumo"
  | "pagos"
  | "comp"
  | "wa"
  | "buzon"
  | "soporte"
  | "mkt"
  | "config"
  | "audit";

export interface ItemInterno {
  id: IdSeccionInterna;
  label: string;
  titulo: string;
  subtitulo: string;
  /** Solo SUPERADMIN entra. */
  soloSuperadmin?: boolean;
}

export const MENU_INTERNO: ItemInterno[] = [
  {
    id: "dash",
    label: "Dashboard general",
    titulo: "Dashboard general",
    subtitulo: "KPIs, actividad, salud de servicios y alertas",
  },
  {
    id: "clientes",
    label: "Clientes",
    titulo: "Clientes",
    subtitulo: "búsqueda, filtros y ficha con acciones de soporte",
  },
  {
    id: "consumo",
    label: "Consumo y costos",
    titulo: "Consumo y costos",
    subtitulo: "Costo real por cliente contra lo que paga su plan · tarifas editables",
  },
  {
    id: "pagos",
    label: "Facturación y pagos",
    titulo: "Facturación y pagos",
    subtitulo: "Vencimientos, morosos, recargas e ingresos",
  },
  {
    id: "comp",
    label: "Comprobantes",
    titulo: "Comprobantes del sistema",
    subtitulo: "Cola de emisión en tiempo real · los rechazados del SRI piden acción",
  },
  {
    id: "wa",
    label: "WhatsApp",
    titulo: "WhatsApp",
    subtitulo: "Estado de la línea, plantillas, consumo y mensajes fallidos",
  },
  {
    id: "buzon",
    label: "Buzón SRI",
    titulo: "Buzón SRI",
    subtitulo: "Correos recibidos por inquilino y estado del parseo de XML",
  },
  {
    id: "soporte",
    label: "Soporte",
    titulo: "Soporte",
    subtitulo: "Conversaciones que piden humano y señales de abandono",
  },
  {
    id: "mkt",
    label: "Marketing",
    titulo: "Marketing",
    subtitulo: "Códigos promocionales, origen de altas y embudo del mes",
  },
  {
    id: "config",
    label: "Configuración",
    titulo: "Configuración",
    subtitulo: "Planes, avisos automáticos, administradores y parámetros SRI",
    soloSuperadmin: true,
  },
  {
    id: "audit",
    label: "Auditoría",
    titulo: "Auditoría",
    subtitulo: "Registro inmutable de acciones · solo lectura · cumplimiento LOPDP",
  },
];
