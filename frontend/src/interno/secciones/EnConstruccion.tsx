/** Secciones cuyo backend llega en fases posteriores del plan. */

export function EnConstruccion({ seccion }: { seccion: string }) {
  return (
    <section className="fc-tarjeta fc-vacio">
      <p className="fc-vacio__titulo">{seccion} llega con su fase</p>
      <p className="fc-vacio__ayuda">
        Esta sección depende de trabajo que el plan sitúa más adelante: WhatsApp y su presupuesto
        en la fase 5, pagos y morosos en la fase 6, y el buzón SRI en la fase 7 tras su feature
        flag. La pantalla ya está reservada en el menú.
      </p>
    </section>
  );
}
