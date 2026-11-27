// «Apps de pedidos» en Dónde comer: las apps de delivery que andan en Las Vegas. No hay integración: Uber Eats, DoorDash
// y Grubhub no tienen API pública para pedir desde otra app (las suyas son para los restaurantes). Se abren con el link
// universal (https): con la app instalada la abre; si no, la web. No viaja ningún dato.
import { icon } from "./icons.js";
import { Hint, h } from "./ui.js";

export const APPS_PEDIDOS = Object.freeze([
  Object.freeze({ nombre: "Uber Eats", url: "https://www.ubereats.com/", detalle: "La más usada en el Strip. Usa la misma cuenta que Uber." }),
  Object.freeze({ nombre: "DoorDash", url: "https://www.doordash.com/", detalle: "Muchos restaurantes y farmacias (Walgreens, CVS)." }),
  Object.freeze({ nombre: "Grubhub", url: "https://www.grubhub.com/", detalle: "Otra opción si lo que buscás no está en las otras." }),
]);

export const AVISO_HOTEL = "En muchos hoteles del Strip el repartidor no sube a la habitación: fijate en la app dónde te lo "
  + "entregan (suele ser un punto de retiro o el lobby) y poné el nombre del hotel y tu número de habitación en las notas.";

function AppCard(app) {
  return h("article", { class: "ra-card", style: { cursor: "default" } },
    h("div", { class: "ra-card-top" }, h("h2", { class: "ra-card-title" }, app.nombre)),
    h("p", { class: "caption" }, app.detalle),
    h("a", { class: "ra-btn", href: app.url, target: "_blank", rel: "noopener noreferrer" },
      icon("externo", 16), h("span", {}, `Abrir ${app.nombre}`)));
}

/** La lista de apps con el aviso del hotel arriba. */
export function AppsPedidos() {
  return [Hint(AVISO_HOTEL, { tone: "info" }), ...APPS_PEDIDOS.map(AppCard)];
}
