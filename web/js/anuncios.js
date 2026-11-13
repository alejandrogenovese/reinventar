// Inicio › Anuncios sin reserva: keynotes, mainstage y lanzamientos walk-up del día, en una fila que se desliza con el
// dedo (scroll-snap). No se mueve sola: nada de autoplay. La regla vive en app/anuncios.py.
import { Anuncios, Itinerary } from "./api.js";
import { refreshCountdown } from "./countdown.js";
import { icon } from "./icons.js";
import { AddButton } from "./itinerary.js";
import { GoThereParts, startsAt } from "./location.js";
import { sandboxNow } from "./sandbox.js";
import { TalkAction, destination, place } from "./today.js";
import { Button, IconText, h, toast } from "./ui.js";

const NIVEL = { 1: "Keynote", 2: "Mainstage", 3: "Lanzamiento", 4: "Novedades" };
const NIVELES_HERO = new Set([1, 2]);   // Keynote y Mainstage van en la tarjeta oscura (el «banner»)
const NIVEL_KEYNOTE = 1;
const FILTRO_BUSCAR = "Anuncios sin reserva"; // mismo valor que anuncios.FILTRO_BUSCAR en el backend
const MIN_MS = 60_000;

const dayLabel = (iso) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "short" });

/** "En 20 min", "En 1 h 50 min", "Empezó hace 4 min" o "Empieza ya", contra el reloj (simulado en modo prueba). */
function relativeStart(s) {
  const min = Math.round((startsAt(s.day, s.start) - sandboxNow()) / MIN_MS);
  if (min < 0) return `Empezó hace ${-min} min`;
  if (min === 0) return "Empieza ya";
  const hours = Math.floor(min / 60), rest = min % 60;
  return `En ${hours ? `${hours} h${rest ? ` ${rest} min` : ""}` : `${min} min`}`;
}

function typeTag(s) {
  if (s.nivel === NIVEL_KEYNOTE) return null;
  if (s.type === "Mainstage") return s.seats ? `${s.seats} lugares` : null;
  return s.type === "Lightning talk" ? "Lightning · 20 min" : "Breakout";
}

function queueText(s, isToday) {
  const started = isToday && startsAt(s.day, s.cola_desde) <= sandboxNow();
  return `Cola desde ${s.cola_desde}${started ? " · ya empezó la fila" : ""}`;
}

/** Agregar al itinerario con el botón que confirma (itinerary.js): queda «Agregada» y otro toque la quita. */
const addToItinerary = (code) => async () => {
  try {
    await Itinerary.add(code);
    toast("Agregada al itinerario.");
    void refreshCountdown({ force: true });
  } catch (e) { toast(e.message); return false; }
};

function AnnCard(s, { isToday, recorded }) {
  const hero = NIVELES_HERO.has(s.nivel);
  const go = GoThereParts(destination(s), { iconOnly: true });
  const tag = typeTag(s);
  const summary = s.abstract_es || s.abstract;
  // Grabar solo tiene sentido con la charla en curso; antes, lo útil es agregarla.
  const action = s.en_curso ? TalkAction(s, recorded, "primary") : AddButton(s.code, addToItinerary(s.code));
  action.classList.add("ra-ann-grow");

  return h("article", { class: `ra-ann${hero ? " is-hero" : ""}` },
    h("div", { class: "ra-ann-row" }, h("span", { class: "ra-ann-tags" },
      h("span", { class: `ra-tag${s.nivel === 4 ? "" : " is-new"}` }, NIVEL[s.nivel]), tag ? h("span", { class: "ra-tag" }, tag) : null)),
    h("div", { class: "ra-ann-row" },
      h("span", { class: "ra-soon" }, isToday ? relativeStart(s) : dayLabel(s.day)),
      h("span", { class: "ra-time" }, s.start)),
    h("h3", { class: "ra-card-title" }, h("a", { class: "ra-link", href: `#/charla/${s.base}` }, s.title)),
    summary ? h("p", { class: "ra-ann-es" }, summary) : null,
    h("div", { class: "ra-card-meta" }, place(s) ? IconText("ubicacion", place(s)) : null, h("span", { class: "ra-mono" }, s.code)),
    h("div", { class: "ra-card-meta" }, IconText("reloj", queueText(s, isToday))),
    s.nivel === NIVEL_KEYNOTE ? h("div", { class: "ra-card-meta" }, IconText("pantalla", "También por streaming y en overflow")) : null,
    h("div", { class: "ra-ann-space" }),
    h("div", { class: "ra-ann-acts" }, action, go ? go.link : null));
}

function MoreCard(data) {
  const rest = data.total - data.items.length;
  const when = data.is_today ? "que quedan hoy" : `del ${dayLabel(data.day)}`;
  const params = new URLSearchParams({ anuncio: FILTRO_BUSCAR, dia: data.day });
  return h("a", { class: "ra-ann is-more", href: `#/buscar?${params}` },
    h("span", { class: "ra-ann-big" }, `+${rest}`),
    h("span", { class: "ra-card-title" }, `Ver los ${data.total} ${when}`),
    h("span", { class: "caption" }, "Buscar con el filtro «Anuncios»"),
    h("span", { class: "ra-ann-cta" }, "Ver todos", icon("seguir", 16)));
}

/** Flechas ← → (mouse y teclado) y contador «2 de 6» que acompaña el deslizamiento. */
function railControls(rail, total) {
  const counter = h("span", { class: "ra-ann-counter", "aria-live": "polite" }, `1 de ${total}`);
  const current = () => {
    const items = rail.children;
    const step = items.length > 1 ? items[1].offsetLeft - items[0].offsetLeft : 1;
    return Math.min(items.length - 1, Math.max(0, Math.round(rail.scrollLeft / step)));
  };
  const go = (dir) => {
    const items = rail.children;
    const next = Math.min(items.length - 1, Math.max(0, current() + dir));
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    rail.scrollTo({ left: items[next].offsetLeft - items[0].offsetLeft, behavior: smooth ? "smooth" : "auto" });
  };
  rail.addEventListener("scroll", () => { counter.textContent = `${current() + 1} de ${total}`; }, { passive: true });
  const arrow = (dir, name, label) => h("button", { type: "button", class: "ra-ann-ctl", "aria-label": label,
    "aria-controls": "anuncios-fila", onclick: () => go(dir) }, icon(name, 16));
  return { arrows: h("div", { class: "ra-ann-ctls" }, arrow(-1, "volver", "Anterior"), arrow(1, "seguir", "Siguiente")), counter };
}

/**
 * Fila «Anuncios sin reserva» para Inicio. `sessions` son las grabaciones (para no grabar dos veces la misma charla).
 * Devuelve null si no queda ningún anuncio: la sección no se dibuja (sin estado vacío en Inicio).
 */
export async function AnunciosRail(sessions) {
  const data = await Anuncios.get();
  if (!data.items.length) return null;
  const recorded = new Map(sessions.filter((s) => s.code).map((s) => [s.code, s]));
  const cards = data.items.map((s) => h("li", {}, AnnCard(s, { isToday: data.is_today, recorded })));
  if (data.total > data.items.length) cards.push(h("li", {}, MoreCard(data)));
  const rail = h("ul", { class: "ra-ann-rail", id: "anuncios-fila", "aria-label": `Anuncios sin reserva ${data.is_today ? "de hoy" : `del ${dayLabel(data.day)}`}` }, cards);
  const { arrows, counter } = railControls(rail, cards.length);
  const sub = data.is_today
    ? "Keynotes, mainstage y lanzamientos de hoy. Sin reserva posible: se entra por la cola."
    : `Keynotes, mainstage y lanzamientos del ${dayLabel(data.day)}. Sin reserva posible: se entra por la cola.`;
  return h("section", { class: "stack ra-ann-section", "aria-labelledby": "anuncios-title" },
    h("div", { class: "ra-sec-head ra-ann-head" }, h("h2", { class: "label", id: "anuncios-title" }, "Anuncios sin reserva"),
      cards.length > 1 ? arrows : null),
    h("p", { class: "caption" }, sub),
    rail,
    cards.length > 1 ? counter : null);
}
