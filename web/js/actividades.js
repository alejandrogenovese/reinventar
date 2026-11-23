// Actividades: dos pestañas para lo que no es re:Invent.
// - Excursiones: Viator (app/viator.py), agrupadas por categoría si el servidor pudo; «Reservar en Viator» abre el link
//   de afiliado tal cual. Sin clave en el servidor la pestaña no aparece. «Ver más» pide la página siguiente.
// - Cerca: atracciones de Google Places ordenadas por distancia a donde estás (o a la sede de tu próxima sesión).
import { api } from "./api.js";
import { icon } from "./icons.js";
import { GoThereParts, currentPosition } from "./location.js";
import { Hint, h, mensajeError } from "./ui.js";

const TABS = [["excursiones", "Excursiones", "#/actividades"], ["cerca", "Cerca", "#/actividades/cerca"]];
const ANCHO_FOTO = 480;

const safeUrl = (url) => (typeof url === "string" && url.startsWith("https://") ? url : null);
const puntaje = (n) => Number(n).toLocaleString("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const entero = (n) => Number(n || 0).toLocaleString("es-AR");

/** 90 → «1 h 30 min», 45 → «45 min», 120 → «2 h». */
export function minutosTexto(min) {
  const horas = Math.floor(min / 60);
  const resto = min % 60;
  if (!horas) return `${resto} min`;
  return resto ? `${horas} h ${resto} min` : `${horas} h`;
}

/** Duración de Viator: fija («12 h»), variable («30 min a 1 h») o sin dato (null). */
export function duracionTexto(desde, hasta) {
  if (!desde && !hasta) return null;
  if (!desde || !hasta || desde === hasta) return minutosTexto(desde || hasta);
  return `${minutosTexto(desde)} a ${minutosTexto(hasta)}`;
}

/** «desde US$ 189,99» (o «desde US$ 25» si es redondo); sin precio, null. */
export function precioTexto(monto, moneda = "USD") {
  if (monto == null || !Number.isFinite(Number(monto))) return null;
  const n = Number(monto);
  const cifra = Number.isInteger(n) ? String(n) : n.toFixed(2).replace(".", ",");
  return `desde ${moneda === "USD" ? "US$" : moneda} ${cifra}`;
}

/** «a 650 m» o «a 2,3 km». */
export function distanciaTexto(metros) {
  return metros < 1000 ? `a ${Math.round(metros / 10) * 10} m` : `a ${(metros / 1000).toLocaleString("es-AR", { maximumFractionDigits: 1 })} km`;
}

/** Querystring de Cerca: con ubicación del teléfono manda lat/lng; sin ella el servidor usa la próxima sesión. */
export function consultaCerca(pos) {
  if (!pos) return "/api/actividades/cerca";
  return `/api/actividades/cerca?${new URLSearchParams({ lat: pos.lat, lng: pos.lng })}`;
}

const SegTabs = (current, visibles) => h("div", { class: "ra-segtabs", role: "tablist", "aria-label": "Qué actividades ver" },
  visibles.map(([value, label, href]) => h("button", { type: "button", class: "ra-segtab", role: "tab", "aria-selected": String(value === current),
    onclick: () => { if (value !== current) location.hash = href; } }, label)));

// ---- Excursiones --------------------------------------------------------------------------------------------------
export function ExcursionCard(p) {
  const foto = safeUrl(p.foto)
    ? h("img", { class: "ra-event-cover", src: p.foto, alt: "", width: ANCHO_FOTO, loading: "lazy", decoding: "async", referrerpolicy: "no-referrer" }) : null;
  const rating = p.rating ? `${puntaje(p.rating)} ★ (${entero(p.resenas)} reseñas)` : null;
  const duracion = duracionTexto(p.minutos_desde, p.minutos_hasta);
  const link = safeUrl(p.url);
  return h("article", { class: "ra-card", style: { cursor: "default" } },
    foto,
    h("h3", { class: "ra-card-title" }, p.titulo),
    h("div", { class: "ra-card-meta" },
      precioTexto(p.precio_desde, p.moneda) ? h("span", {}, precioTexto(p.precio_desde, p.moneda)) : null,
      rating ? h("span", {}, rating) : null,
      duracion ? h("span", { class: "ra-icotext" }, icon("reloj", 16), duracion) : null),
    link ? h("div", { class: "actions" },
      h("a", { class: "ra-btn ra-btn-primary", href: link, target: "_blank", rel: "noopener" }, "Reservar en Viator", icon("externo", 16))) : null);
}

function pintarExcursiones(r, acumulados) {
  const productos = [...acumulados, ...r.productos];
  if (!productos.length) return { productos, nodos: [Hint("No encontramos excursiones para tus días en Las Vegas. Probá más tarde.")] };
  // Con «Ver más» las páginas se suman: los grupos de la primera página quedan y lo nuevo va abajo, sin agrupar.
  const nodos = r.grupos && !acumulados.length
    ? r.grupos.flatMap((g) => [h("h2", { class: "label" }, `${g.titulo} · ${g.productos.length}`), ...g.productos.map(ExcursionCard)])
    : r.productos.map(ExcursionCard);
  return { productos, nodos };
}

async function panelExcursiones(cont) {
  const lista = h("div", { class: "stack", "aria-live": "polite" });
  const pie = h("div", { class: "actions" });
  cont.append(h("p", { class: "caption" }, "Excursiones y entradas para tus días en Las Vegas. Se reservan y pagan en Viator."),
    lista, pie,
    h("p", { class: "caption" }, "Puntajes de reseñas de Viator y Tripadvisor."));
  let acumulados = [];
  async function cargar(pagina) {
    pie.replaceChildren(h("p", { class: "caption", role: "status" }, "Buscando excursiones…"));
    try {
      const r = await api(`/api/actividades/excursiones?pagina=${pagina}`);
      const { productos, nodos } = pintarExcursiones(r, acumulados);
      if (pagina === 1) lista.replaceChildren(...nodos); else lista.append(...nodos);
      acumulados = productos;
      pie.replaceChildren(r.hay_mas ? h("button", { type: "button", class: "ra-btn ra-btn-secondary", onclick: () => void cargar(pagina + 1) }, "Ver más") : "");
    } catch (e) {
      pie.replaceChildren(Hint(mensajeError(e, "No pudimos traer las excursiones."), { tone: "error" }));
    }
  }
  await cargar(1);
}

// ---- Cerca --------------------------------------------------------------------------------------------------------
export function AtraccionCard(l) {
  const ir = GoThereParts({ lat: l.lat, lng: l.lng, name: l.nombre, placeId: l.place_id }, { iconOnly: true })?.link;
  return h("article", { class: "ra-card", style: { cursor: "default" } },
    h("div", { class: "ra-card-top" }, h("h3", { class: "ra-card-title" }, l.nombre), ir),
    h("div", { class: "ra-card-meta" },
      l.tipo ? h("span", { class: "ra-tag" }, l.tipo) : null,
      h("span", {}, distanciaTexto(l.metros)),
      h("span", { class: "ra-icotext" }, icon("caminar", 16), `${l.minutos} min caminando`)),
    h("p", { class: "caption" }, l.direccion));
}

async function panelCerca(cont) {
  const origenEl = h("p", { class: "caption" });
  const lista = h("div", { class: "stack", "aria-live": "polite" }, h("p", { class: "caption", role: "status" }, "Buscando atracciones…"));
  cont.append(origenEl, lista);
  try {
    const r = await api(consultaCerca(await currentPosition()));
    origenEl.textContent = r.origen.fuente === "sesion" ? `Cerca de ${r.origen.nombre}, tu próxima sesión` : "Cerca de donde estás";
    lista.replaceChildren(...(r.lugares.length ? r.lugares.map(AtraccionCard) : [Hint("No encontramos atracciones cerca.")]));
  } catch (e) {
    lista.replaceChildren(Hint(mensajeError(e, "No pudimos buscar atracciones cercanas."), { tone: "error" }));
  }
}

/** Actividades: Excursiones (si el servidor tiene la clave de Viator) y Cerca. Sin Viator, solo Cerca y sin pestañas. */
export async function viewActividades(view, tab = "excursiones") {
  const estado = await api("/api/actividades/excursiones").catch(() => ({ habilitado: true }));
  const conViator = estado.habilitado !== false;
  const actual = conViator ? tab : "cerca";
  const cont = h("div", { class: "stack" });
  view.append(h("div", { class: "stack-lg" },
    h("header", { class: "stack" },
      h("a", { class: "ra-btn ra-btn-ghost ra-back", href: "#/viaje" }, icon("volver", 16), h("span", {}, "Viaje")),
      h("h1", { class: "title" }, "Actividades"),
      conViator ? SegTabs(actual, TABS) : null),
    cont));
  await (actual === "excursiones" ? panelExcursiones(cont) : panelCerca(cont));
}
