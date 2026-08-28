/** Copy de la landing, transcrito de diseno/Facturas IA.dc.html.
 *
 * La maqueta es la única fuente de verdad visual y textual. Las únicas
 * diferencias frente al HTML original son las correcciones obligatorias:
 *   · "Pacalina" → "Factuchat"        (paso 02 del onboarding)
 *   · "wathsapp" → "WhatsApp"         (bajada del onboarding)
 *   · "fué" → "fue"                   (remate del CTA final)
 *   · "Whatsapp" → "WhatsApp"         (h2 de "para quién es")
 *   · Panamá: "Disponible" → "Muy pronto"; solo Ecuador está en operación
 *   · FAQ 13: "quince comprobantes" → "diez", que es lo que da el plan Inicial
 *
 * Los precios y los cupos NO se copian de aquí: los pinta /publico/planes con
 * lo que hay en la base. Estas listas son solo el texto de venta.
 */

export const PAISES = [
  { nombre: "Ecuador", disponible: true, badge: "Disponible" },
  { nombre: "Panamá", disponible: false, badge: "Muy pronto" },
  { nombre: "Perú", disponible: false, badge: "Muy pronto" },
  { nombre: "Colombia", disponible: false, badge: "Muy pronto" },
  { nombre: "Chile", disponible: false, badge: "Muy pronto" },
];

export const NOTA_PAISES =
  "Ecuador ya está en operación. Los demás se habilitan en cuanto cerremos la integración con su entidad tributaria.";

export const PROVINCIAS_EC = [
  "Azuay",
  "Bolívar",
  "Cañar",
  "Carchi",
  "Chimborazo",
  "Cotopaxi",
  "El Oro",
  "Esmeraldas",
  "Galápagos",
  "Guayas",
  "Imbabura",
  "Loja",
  "Los Ríos",
  "Manabí",
  "Morona Santiago",
  "Napo",
  "Orellana",
  "Pastaza",
  "Pichincha",
  "Santa Elena",
  "Santo Domingo de los Tsáchilas",
  "Sucumbíos",
  "Tungurahua",
  "Zamora Chinchipe",
];

export const NAV = [
  { id: "para-quien", hero: "Para quién es", sticky: "Cómo funciona" },
  { id: "documentos", hero: "Documentos", sticky: "Qué emite" },
  { id: "reporte", hero: "Reportes", sticky: "Reportes" },
  { id: "planes", hero: "Planes", sticky: "Planes" },
  { id: "faq", hero: "Preguntas", sticky: "Preguntas" },
];

export const BENEFICIOS = [
  {
    titulo: "Intuitivo desde el primer mensaje",
    texto:
      "Pides tu factura como si le escribieras a un asistente humano: “Factura a Juan Pérez por $50”.",
  },
  {
    titulo: "Autorización Oficial",
    texto:
      "La IA estructura los códigos, calcula los impuestos y obtiene el XML y PDF del SRI al instante.",
  },
  {
    titulo: "Control sin esfuerzo",
    texto:
      "Tus documentos se archivan automáticamente y recibes reportes exactos para tu declaración.",
  },
];

export const DOCUMENTOS = [
  {
    codigo: "01",
    nombre: "Factura",
    etiqueta: "El de siempre",
    texto: "Le cobras a un cliente por un producto o un servicio. Traslada crédito tributario.",
  },
  {
    codigo: "03",
    nombre: "Liquidación de compra",
    etiqueta: "Cuidado",
    texto: "Cuando le compras a alguien que no puede facturarte, como un agricultor sin RUC.",
    nota: "Al emitirla tú retienes el 100% del IVA. Factuchat te lo advierte antes.",
  },
  {
    codigo: "04",
    nombre: "Nota de crédito",
    etiqueta: "Corrige",
    texto: "Anula o corrige una factura ya autorizada, o registra una devolución.",
  },
  {
    codigo: "05",
    nombre: "Nota de débito",
    etiqueta: "Suma",
    texto: "Cobra de más sobre una factura ya emitida: intereses por mora o un recargo.",
  },
  {
    codigo: "06",
    nombre: "Guía de remisión",
    etiqueta: "Traslado",
    texto: "Respalda el movimiento de mercadería de un lugar a otro.",
    nota: "Solo la necesitas si mueves productos físicos.",
  },
  {
    codigo: "07",
    nombre: "Comprobante de retención",
    etiqueta: "Dos vías",
    texto:
      "Se la emites a tu proveedor si eres agente de retención. Y si te retienen a ti, Factuchat la archiva.",
  },
];

export const CAPACIDADES = [
  {
    titulo: "Emitir al instante",
    texto: "Facturas, notas o guías. La IA valida el RUC y nada se envía al SRI sin tu OK final.",
  },
  {
    titulo: "Consultar y reenviar",
    texto:
      "Busca cualquier comprobante y reenvía el PDF por chat. Guardamos todo por 7 años por ley.",
  },
  {
    titulo: "Reportes listos",
    texto: "Descarga tus resúmenes en PDF o Excel (mensual o anual). Tu contador te amará.",
  },
  {
    titulo: "Tu base de datos",
    texto: "Guarda clientes y servicios gratis. Tu próxima factura saldrá con solo 3 toques.",
  },
];

export const REPORTE_ITEMS = [
  "Mensual: Tu IVA cuadrado y sin sorpresas.",
  "Semestral: El resumen RIMPE exacto para julio y enero.",
  "Anual: Renta y retenciones consolidadas en un clic.",
];

export const ONBOARDING = [
  {
    paso: "01",
    titulo: "Enlaza tu firma",
    texto:
      "Conecta tu firma digital. Si aún no la tienes, nuestro equipo te acompaña de principio a fin.",
  },
  {
    paso: "02",
    titulo: "La IA memoriza",
    texto:
      "Factuchat recuerda tus clientes, servicios y productos. Nunca volverás a escribir los mismos datos dos veces.",
  },
  {
    paso: "03",
    titulo: "Factura en 30 segundos",
    texto:
      "Abre WhatsApp, pide tu factura por chat y confirma. El XML autorizado y el PDF llegan al instante a tu cliente. Así de simple.",
  },
];

/** Texto de venta por plan. El precio y el cupo vienen del servidor. */
export const PLANES_COPY: Record<
  string,
  {
    tagline: string;
    periodicidad: string;
    features: string[];
    nota?: string;
    boton: string;
    ariaLabel: string;
    destacado?: string;
  }
> = {
  INICIAL: {
    tagline: "Pruébalo sin compromiso.",
    periodicidad: "pago único · IVA incluido",
    features: [
      "10 comprobantes electrónicos",
      "Válidos por 20 días",
      "Hasta 50 clientes y 50 productos",
      "Emite desde el chat, con botones y listas",
      "Envío de la factura al correo de tu cliente",
      "Avisos antes de tus fechas de declaración",
      "1 usuario · sin cobros automáticos",
    ],
    nota: "Ideal para probar Factuchat. Al terminar tus comprobantes, eliges tu plan mensual.",
    boton: "Probar por $2.99",
    ariaLabel: "Probar Factuchat por 2.99 dólares",
  },
  INDEPENDIENTE: {
    tagline: "Para quien vende servicios.",
    periodicidad: "al mes · IVA incluido",
    features: [
      "30 comprobantes al mes",
      "Hasta 100 clientes y 100 productos",
      "Respaldo de todos tus XML en la nube",
      "Buzón SRI: tus documentos recibidos entran solos",
      "Documentos recibidos ilimitados, sin gastar tu cupo",
      "Resumen semanal de documentos por WhatsApp",
      "20 análisis de documentos con IA al mes",
      "Tu logotipo en las facturas · 1 usuario",
      "Todo lo del plan Inicial, y más",
    ],
    boton: "Empezar ahora",
    ariaLabel: "Empezar con el plan Independiente",
  },
  EMPRENDEDOR: {
    tagline: "El negocio en crecimiento.",
    periodicidad: "al mes · IVA incluido",
    destacado: "Más elegido",
    features: [
      "80 comprobantes acumulables al mes siguiente",
      "Hasta 200 clientes y 200 productos",
      "Control de inventario y consulta de stock",
      "Tienda online integrada",
      "Factura por WhatsApp o desde tu panel",
      "Acceso directo al panel, sin contraseña",
      "Archivo de retenciones listo para declarar",
      "40 análisis de documentos con IA · 2 usuarios",
      "Todo lo del plan Independiente",
    ],
    boton: "Empezar ahora",
    ariaLabel: "Empezar con el plan Emprendedor",
  },
  EMPRESARIO: {
    tagline: "Volumen y equipo de trabajo.",
    periodicidad: "al mes · IVA incluido",
    features: [
      "250 comprobantes acumulables al mes siguiente",
      "Clientes y catálogo ilimitados",
      "Facturación masiva subiendo un Excel",
      "Reportes avanzados desde tu panel",
      "100 análisis de documentos con IA al mes",
      "Asesoría por videollamada incluida",
      "Soporte prioritario",
      "3 usuarios para tu equipo",
      "Todo lo del plan Emprendedor",
    ],
    boton: "Empezar ahora",
    ariaLabel: "Empezar con el plan Empresario",
  },
};

export const NOTAS_PLANES = [
  "Ningún plan se cobra automáticamente. Al agotar tus comprobantes te avisamos por WhatsApp y tú decides: renovar, recargar o subir de plan pagando solo la diferencia.",
  "Recargas: 10 comprobantes por $2.99 en cualquier plan, o 100 por $10 en el Empresario. Nunca pierdes las funciones de tu plan.",
  "Los XML de tu buzón SRI no consumen tus análisis con IA; las fotos de documentos sí. Precios en dólares, IVA incluido.",
];

export const ACUMULACION = [
  {
    n: "1",
    titulo: "Lo que no usas, se acumula",
    texto:
      "Desde Emprendedor en adelante, los comprobantes que te sobran pasan al mes siguiente y se suman a los nuevos.",
  },
  {
    n: "2",
    titulo: "Diez días de gracia",
    texto:
      "Si tu plan vence, tus comprobantes acumulados siguen vigentes diez días más. Renuevas dentro de ese plazo y los conservas todos.",
  },
  {
    n: "3",
    titulo: "Empiezas con un paquete",
    texto:
      "El paquete Inicial vale veinte días o hasta que uses los diez comprobantes, con pago único. Es la forma de probar Factuchat sin comprometerte a una suscripción.",
  },
];

export const FAQS: Array<{ p: string; r: string[] }> = [
  {
    p: "¿Puede facturar más de una persona desde mi cuenta?",
    r: [
      "Desde el plan Emprendedor puedes autorizar un segundo número de WhatsApp además del tuyo. Los dos emiten sobre la misma cuenta, con tus clientes, tus servicios y tu numeración.",
      "Sirve para que tu socio, tu asistente o quien atiende el local facture sin pasarte los datos por otro lado. Los comprobantes se descuentan del mismo plan y quedan en un solo historial.",
    ],
  },
  {
    p: "¿Se me pierden los comprobantes que no uso?",
    r: [
      "Depende del plan. Desde Emprendedor en adelante, si un mes emites menos de lo que incluye tu plan, los comprobantes que te sobran pasan al mes siguiente y se suman a los nuevos.",
      "En los planes de entrada tienen fecha: los 10 de Inicial valen 20 días o hasta que se agoten, y los 30 de Independiente son del mes en curso.",
    ],
  },
  {
    p: "¿Qué pasa con mis comprobantes si dejo vencer el plan?",
    r: [
      "Tienes diez días de gracia. Al terminar tu ciclo, los comprobantes que traías acumulados siguen vigentes ese plazo.",
      "Si renuevas dentro de los diez días, los conservas y se suman a los del nuevo mes. Pasado ese plazo sin renovar, lo acumulado se cierra.",
      "Tus comprobantes ya emitidos no se tocan: siguen guardados y los puedes consultar o reenviar cuando quieras.",
    ],
  },
  {
    p: "¿Necesito WhatsApp Business?",
    r: [
      "No. Usas tu WhatsApp de siempre, el mismo con el que le escribes a tu familia. El menú y los botones aparecen solos dentro del chat porque los enviamos nosotros desde la plataforma oficial de WhatsApp Business.",
      "Tú no instalas ni configuras nada.",
    ],
  },
  {
    p: "¿Esto es válido ante el SRI?",
    r: [
      "Sí. Cada comprobante se firma con tu certificado digital y se envía al SRI para su autorización, bajo el esquema de facturación electrónica vigente. Recibes el XML autorizado y el RIDE en PDF, que es el respaldo que le entregas a tu cliente.",
    ],
  },
  {
    p: "No sé nada de contabilidad. ¿Igual me sirve?",
    r: [
      "Está hecho justamente para eso. Eliges del menú, respondes en tus palabras y Factuchat arma el documento con los códigos correctos. Antes de enviar nada al SRI te muestra un resumen en español simple para que confirmes.",
    ],
  },
  {
    p: "¿Qué es la firma electrónica y dónde la consigo?",
    r: [
      "Es un archivo .p12 que te identifica ante el SRI y sin el cual no se puede emitir nada electrónico. Lo emite el Banco Central o Security Data, entre otros, y se tramita en línea.",
      "Si no lo tienes, te acompañamos paso a paso a sacarlo. Es un trámite de una sola vez.",
    ],
  },
  {
    p: "Estoy en RIMPE Emprendedor. ¿Me sirve?",
    r: [
      "Sí, es el perfil para el que está pensado. RIMPE no obliga a llevar contabilidad, así que estás en el mismo grupo que una persona natural no obligada.",
      "Emites factura, declaras IVA cada semestre y tus clientes grandes te retienen: Factuchat guarda esas retenciones porque son crédito en tu declaración anual.",
    ],
  },
  {
    p: "¿Puedo mandarle notas de voz?",
    r: [
      "Por ahora no: Factuchat funciona con texto para garantizar precisión. Desde el plan Independiente puedes enviarle PDF y fotos de facturas: los lee y los analiza.",
      "En cualquier plan el texto sigue siendo la vía más precisa: un RUC tiene trece dígitos y un monto lleva centavos, y escritos no hay margen de duda. Antes de enviar nada al SRI te muestra el resumen para que confirmes.",
    ],
  },
  {
    p: "¿Hay un límite de texto por mensaje?",
    r: [
      "Sí, aunque en la práctica casi nadie lo alcanza. Si le escribes un mensaje muy largo, Factuchat te pide que lo resumas en unas cuatro líneas.",
      "No es un capricho: un mensaje concreto se resuelve en un paso. Con “factura a Andrade por consultoría, 450” ya tiene todo lo que necesita.",
    ],
  },
  {
    p: "¿Pedirle reportes o guardar clientes gasta mi plan?",
    r: [
      "No. Solo cuentan los comprobantes que se envían al SRI. Consultar, buscar, reenviar, pedir reportes, crear clientes y crear servicios es ilimitado en todos los planes.",
    ],
  },
  {
    p: "¿Y si un mes emito más de lo que incluye mi plan?",
    r: [
      "Te aviso antes de que llegues al límite, por el mismo chat. Desde ahí puedes hacer una recarga de comprobantes para ese mismo mes, sin cambiar tu fecha de renovación, o subir al plan que te alcance.",
      "Si estabas en Independiente o Emprendedor, lo que traías acumulado se conserva.",
    ],
  },
  {
    p: "¿Puedo probarlo sin suscribirme?",
    r: [
      "Sí, con el paquete Inicial: pagas $2.99 una sola vez y tienes diez comprobantes por veinte días, o hasta que los uses. No se renueva solo.",
      "Lo que emitas ahí es real: firmado con tu certificado y autorizado por el SRI. Si te sirve, pasas a un plan mensual y tus documentos quedan donde están.",
    ],
  },
  {
    p: "¿Puedo cancelar cuando quiera?",
    r: [
      "Sí, sin plazos forzosos ni penalidad. Tus comprobantes quedan disponibles para que los descargues, y el respaldo se conserva por los siete años que exige la normativa tributaria.",
    ],
  },
];

export const ASUNTOS_CONTACTO = [
  "Quiero contratar un plan",
  "Dudas sobre los planes",
  "Firma electrónica",
  "Soporte técnico",
  "Facturación y pagos",
  "Otro",
];

export const REDES = [
  { nombre: "Instagram", url: "https://instagram.com/" },
  { nombre: "Facebook", url: "https://facebook.com/" },
  { nombre: "LinkedIn", url: "https://linkedin.com/" },
  { nombre: "YouTube", url: "https://youtube.com/" },
  { nombre: "TikTok", url: "https://tiktok.com/" },
];

/** Configuración pública que sirve el backend (dominio, contacto, cuentas). */
export interface ConfigPublica {
  dominio: string;
  email: string;
  email_ventas: string;
  telefono: string;
  telefono_e164: string;
  direccion: string;
  maps_url: string;
  horario: string;
  whatsapp: string | null;
  cobro: {
    titular: string;
    identificacion: string;
    email: string;
    cuentas: Array<{ banco: string; numero: string }>;
  };
}

export interface PlanPublico {
  codigo: string;
  nombre: string;
  precio: string;
  cupo: number | null;
  analisis_ia: number | null;
  tienda: boolean;
  stock: boolean;
  acumula: boolean;
}
