/** Las 8 secciones del panel, con los rótulos exactos de la maqueta
 *  (Dashboard.dc.html líneas 3315-3322). */

import type { FuncionPlan } from "../api/tipos";

export type IdSeccion =
  | "inicio"
  | "comprobantes"
  | "clientes"
  | "catalogo"
  | "tienda"
  | "reportes"
  | "tutoriales"
  | "cuenta";

export interface SubitemMenu {
  id: string;
  label: string;
}

export interface ItemMenu {
  id: IdSeccion;
  label: string;
  /** Función del plan que habilita la sección; sin ella, va con candado. */
  requiere?: FuncionPlan;
  /** Trazado del icono (24x24), tal cual la maqueta. */
  icono: string;
  /** Submenú que se despliega cuando la sección está activa (maqueta:
   *  Comprobantes y Artículos/Servicios reflejan ahí el filtro elegido). */
  submenu?: SubitemMenu[];
}

/** Los filtros de Comprobantes (Comprobantes.tsx) espejados aquí para que la
 *  barra lateral y la sección compartan el mismo id. */
export const SUBMENU_COMPROBANTES: SubitemMenu[] = [
  { id: "todos", label: "Todos" },
  { id: "factura", label: "Facturas" },
  { id: "credito", label: "Notas de crédito" },
  { id: "debito", label: "Notas de débito" },
  { id: "retencion", label: "Retenciones" },
  { id: "guia", label: "Guías de remisión" },
];

/** Los filtros de Artículos/Servicios (Catalogo.tsx), mismo criterio.
 *  "categorias" vive DENTRO de este menú (no es una sección propia): abre la
 *  administración de categorías y marcas sin salir de Artículos/Servicios. */
export const SUBMENU_CATALOGO: SubitemMenu[] = [
  { id: "todos", label: "Todos" },
  { id: "articulo", label: "Artículos" },
  { id: "servicio", label: "Servicios" },
  { id: "categorias", label: "Categorías" },
];

/** Los cinco temas de Tutoriales.tsx, mismo criterio. */
export const SUBMENU_TUTORIALES: SubitemMenu[] = [
  { id: "empezar", label: "Cómo usar el sistema" },
  { id: "comprobantes", label: "Entender los comprobantes" },
  { id: "declarar", label: "Mis pagos tributarios" },
  { id: "inventario", label: "Inventario y tienda" },
  { id: "plan", label: "Tu plan" },
];

export const MENU: ItemMenu[] = [
  { id: "inicio", label: "Inicio", icono: "M4 11.2L12 4l8 7.2V20a1 1 0 01-1 1h-4.5v-6h-5v6H5a1 1 0 01-1-1z" },
  {
    id: "comprobantes",
    label: "Comprobantes",
    icono: "M7 3h7l5 5v13a1 1 0 01-1 1H7a1 1 0 01-1-1V4a1 1 0 011-1zM14 3v5h5M9 13h6M9 17h4",
    submenu: SUBMENU_COMPROBANTES,
  },
  {
    id: "clientes",
    label: "Clientes",
    icono:
      "M16 20v-1.5a4 4 0 00-4-4H7a4 4 0 00-4 4V20M9.5 10.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7M21 20v-1.5a4 4 0 00-3-3.87M16.5 3.75a4 4 0 010 7.5",
  },
  {
    id: "catalogo",
    label: "Artículos/Servicios",
    icono: "M21 8.5l-9-5-9 5v7l9 5 9-5zM3 8.5l9 5 9-5M12 13.5V20",
    submenu: SUBMENU_CATALOGO,
  },
  {
    id: "tienda",
    label: "Tienda en línea",
    requiere: "tienda",
    icono: "M4 9.5V20a1 1 0 001 1h14a1 1 0 001-1V9.5M2.5 9.5h19L19 3.5H5zM9 21v-6h6v6",
  },
  { id: "reportes", label: "Reportes", icono: "M4 20V10M10 20V4M16 20v-7M22 20H2" },
  {
    id: "tutoriales",
    label: "Tutoriales",
    icono:
      "M4 5.5A2.5 2.5 0 016.5 3H12v17H6.5A2.5 2.5 0 004 22.5zM20 5.5A2.5 2.5 0 0017.5 3H12v17h5.5a2.5 2.5 0 012.5 2.5z",
    submenu: SUBMENU_TUTORIALES,
  },
  {
    id: "cuenta",
    label: "Mi cuenta",
    icono:
      "M12 15.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7M19.4 15a1.7 1.7 0 00.34 1.87l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.7 1.7 0 00-2.87 1.2V21a2 2 0 11-4 0v-.11A1.7 1.7 0 006 19.4l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.7 1.7 0 003 13.7H2.9a2 2 0 110-4H3a1.7 1.7 0 001.2-2.87L4.14 6.8A2 2 0 116.97 3.97l.06.06A1.7 1.7 0 009.9 2.83V2.9a2 2 0 114 0V3a1.7 1.7 0 002.87 1.2l.06-.06a2 2 0 112.83 2.83l-.06.06A1.7 1.7 0 0021.1 10H21a2 2 0 110 4h.1",
  },
];

/** Kicker y título de la cabecera por sección (maqueta ~línea 3371). */
export const ENCABEZADOS: Record<IdSeccion, { kicker: string; titulo: string }> = {
  inicio: { kicker: "Tu negocio hoy", titulo: "Todo al día" },
  comprobantes: { kicker: "Historial", titulo: "Tus comprobantes emitidos" },
  clientes: { kicker: "Tu libreta", titulo: "Clientes guardados" },
  catalogo: { kicker: "Lo que vendes", titulo: "Artículos y servicios" },
  tienda: { kicker: "Tu vitrina", titulo: "Tienda en línea" },
  reportes: { kicker: "Cifras", titulo: "Reportes y declaración" },
  tutoriales: { kicker: "Aprende sin apuro", titulo: "Tutoriales" },
  cuenta: { kicker: "Configuración", titulo: "Mi cuenta" },
};
