// Viaje: hub con lo que sirve fuera de las charlas (dónde comer, etc.). Cada sección es una línea de SECCIONES:
// { href, icono, titulo, bajada }, con icono como función que devuelve el ícono (así tests/test_diseno.py verifica el nombre). Para sumar una pantalla, agregá una línea acá.
import { icon } from "./icons.js";
import { h } from "./ui.js";

export const SECCIONES = [
  { href: "#/comer", icono: () => icon("ubicacion", 20), titulo: "Dónde comer barato", bajada: "Cerca de tu próxima charla, con precio y reseñas" },
  { href: "#/gastos", icono: () => icon("listo", 20), titulo: "Gastos", bajada: "Cuánto llevás gastado y qué se reintegra" },
  { href: "#/ofertas", icono: () => icon("eventos", 20), titulo: "Ofertas", bajada: "Bajas de precio en shows y promos de comida y compras, con aviso" },
  { href: "#/viajes", icono: () => icon("viaje", 20), titulo: "Vuelos y hoteles", bajada: "Check-in, demoras y puerta de embarque" },
];

const Tarjeta = (s) => h("a", { class: "ra-card", href: s.href, style: { textDecoration: "none" } },
  h("div", { class: "ra-card-top" }, h("h2", { class: "ra-card-title ra-icotext" }, s.icono(), h("span", {}, s.titulo)), icon("llevar", 16)),
  h("p", { class: "caption" }, s.bajada));

export function viewViaje(view) {
  view.append(h("div", { class: "stack-lg" },
    h("h1", { class: "title" }, "Viaje"),
    h("div", { class: "stack" }, SECCIONES.map(Tarjeta))));
}
