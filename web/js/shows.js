// Shows de Ticketmaster (pestaña Shows de Eventos): conciertos, espectáculos, deportes y actividades en Las Vegas.
// Una tarjeta por show (sus funciones de ese día); la ficha deja elegir la función que va al itinerario. Las entradas
// se compran en Ticketmaster: acá solo el link (texto, sin logo). Las imágenes vienen de su CDN (no pasan por el sw).
import { Itinerary, Shows } from "./api.js";
import { CountdownBadge, refreshCountdown } from "./countdown.js";
import { GoThere, currentPosition, distanceMeters, formatDistance, startsAt } from "./location.js";
import { sandboxNow } from "./sandbox.js";
import { icon } from "./icons.js";
import { Button, Hint, IconText, h, toast } from "./ui.js";

const ALL = "todos";
const TIPOS = [["musica", "música"], ["teatro", "teatro y shows"], ["comedia", "comedia"], ["deportes", "deportes"], ["actividades", "actividades"]];
const NEAR_MAX_M = 3000; // "a 600 m de Venetian" solo si la sede de re:Invent está cerca
const dayLabel = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("es-AR", { weekday: "short", day: "numeric", month: "numeric" }).replaceAll(".", "");
const shortDay = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("es-AR", { weekday: "short", day: "numeric" }).replaceAll(".", "");
const safeUrl = (url) => (typeof url === "string" && url.startsWith("https://") ? url : null);
const money = (n) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(".", ","));
const priceText = (p) => (p != null ? `desde US$ ${money(p)}` : null);
const listJoin = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(", ")} y ${xs.at(-1)}` : xs[0] || "");
const destination = (s) => (s.venue?.lat != null ? { lat: s.venue.lat, lng: s.venue.lng, name: s.venue.hotel } : null);
const nearText = (s) => (s.near && s.near.meters <= NEAR_MAX_M ? `${formatDistance(s.near.meters)} de ${s.near.name}` : null);

// Estados de Ticketmaster: el aviso de la tarjeta y la fila «Estado» de la ficha.
const STATUS = {
  onsale: { label: "En venta" },
  offsale: { label: "Sin venta", hint: "Sin venta en Ticketmaster por ahora.", tone: "info" },
  canceled: { label: "Cancelado", hint: "Cancelado por el organizador. Revisalo antes de ir.", tone: "error" },
  postponed: { label: "Postergado", hint: "Postergado: Ticketmaster todavía no tiene la fecha nueva.", tone: "warn", icon: "alerta" },
  rescheduled: { label: "Cambió de horario", hint: "Cambió de horario: ya ves el nuevo.", tone: "info" },
};
const StatusHint = (status) => (STATUS[status]?.hint ? Hint(STATUS[status].hint, { tone: STATUS[status].tone, iconName: STATUS[status].icon }) : null);

const Cover = (s, cls) => (safeUrl(s.image)
  ? h("img", { class: cls, src: s.image, alt: "", loading: "lazy", decoding: "async", referrerpolicy: "no-referrer" }) : null);

/** «Entradas en Ticketmaster ↗»: link de texto (en la tarjeta) o botón naranja (en la ficha). */
const TicketLink = (url, { button = false } = {}) => (safeUrl(url)
  ? h("a", { class: button ? "ra-btn ra-btn-primary" : "ra-link ra-tm-link", href: url, target: "_blank", rel: "noopener noreferrer" },
    "Entradas en Ticketmaster", icon("externo", 16)) : null);

/** «+ Itinerario» de una función (naranja) o «En tu itinerario». */
export function AddFunctionButton(f, onAdded) {
  if (f.in_itinerary) return IconText("fijar", "En tu itinerario", { className: "ra-tag is-new ra-icotext", size: 14 });
  const btn = Button("+ Itinerario", { variant: "primary", onclick: async () => {
    btn.disabled = true;
    try {
      const r = await Itinerary.add(f.code);
      const mine = r.days.flatMap((d) => d.sessions).find((s) => s.code === f.code);
      toast(mine?.overlaps?.length ? `Agregado. Ojo: se superpone con ${mine.overlaps.join(", ")}.` : "Agregado y fijado en tu itinerario.");
      void refreshCountdown({ force: true });
      onAdded?.();
    } catch (err) { toast(err.message); btn.disabled = false; }
  } });
  return btn;
}

/** Tarjeta de un show en la lista: sus funciones de ese día. Con varias, «+ Itinerario» lleva a elegir en la ficha. */
function ShowCard(s, day, onAdded) {
  const open = s.functions.filter((f) => !f.cancelled);
  const href = `#/show/${encodeURIComponent(s.id)}`;
  const single = s.functions.length === 1 ? s.functions[0] : null;
  let action;
  if (s.functions.some((f) => f.in_itinerary)) action = IconText("fijar", "En tu itinerario", { className: "ra-tag is-new ra-icotext", size: 14 });
  else if (single && !single.cancelled) action = AddFunctionButton(single, onAdded);
  else if (open.length) action = Button("+ Itinerario", { variant: "primary", onclick: () => (location.hash = `${href}?dia=${day}`) });
  const facts = [s.functions.length > 1 ? `${s.functions.length} funciones` : null, priceText(s.price_from)].filter(Boolean).join(" · ");
  return h("article", { class: `ra-event${s.cancelled ? " is-cancelled" : ""}` },
    Cover(s, "ra-event-cover"),
    h("div", { class: "ra-event-body" },
      h("span", { class: "ra-kind" }, [s.type.toUpperCase(), dayLabel(day), listJoin(s.functions.map((f) => f.start))].join(" · ")),
      h("h3", { class: "ra-card-title" }, h("a", { class: "ra-link", href }, s.title)),
      h("div", { class: "ra-card-meta" }, h("span", {}, [s.venue.hotel, nearText(s)].filter(Boolean).join(" · "))),
      facts ? h("p", { class: "caption" }, facts) : null,
      single ? StatusHint(single.status) : s.cancelled ? StatusHint("canceled") : null,
      action ? h("div", { class: "actions" }, action) : null,
      TicketLink(s.url)));
}

/** Una función en el itinerario (kind = "show"), con las acciones que le pase el itinerario (Fijar, Quitar). */
export function ShowFunctionCard(f, { actions = [] } = {}) {
  return h("article", { class: `ra-event${f.cancelled ? " is-cancelled" : ""}` },
    Cover(f, "ra-event-cover"),
    h("div", { class: "ra-event-body" },
      h("span", { class: "ra-kind" }, [f.type.toUpperCase(), dayLabel(f.day), f.start].join(" · ")),
      h("h3", { class: "ra-card-title" }, h("a", { class: "ra-link", href: `#/show/${encodeURIComponent(f.show)}` }, f.title)),
      h("div", { class: "ra-card-meta" }, h("span", {}, f.venue.hotel)),
      priceText(f.price_from) ? h("p", { class: "caption" }, priceText(f.price_from)) : null,
      StatusHint(f.status),
      f.overlaps?.length ? Hint(`Se superpone con ${f.overlaps.join(", ")}`, { tone: "error" }) : null,
      GoThere(destination(f)),
      h("div", { class: "actions" }, actions),
      TicketLink(f.url)));
}

// --- lista (dentro de Eventos) ---------------------------------------------------
export function ShowsPanel({ days }) {
  const box = h("div", { class: "stack-lg" });
  if (!days.length) {
    box.append(h("p", { class: "caption" }, "Todavía no hay shows cargados de Ticketmaster."));
    return box;
  }
  const today = sandboxNow().toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
  const state = { day: days.some((d) => d.day === today) ? today : days[0].day, type: ALL, near: false };
  let here = null;
  void currentPosition().then((p) => { here = p; });

  const dayTabs = h("div", { class: "ra-chips", role: "tablist", "aria-label": "Día" });
  const typeChips = h("div", { class: "ra-chips", "aria-label": "Tipo de show" });
  const list = h("div", { class: "daylist" });
  const chip = (label, on, onclick) => h("button", { type: "button", class: `ra-chip${on ? " ra-chip-on" : ""}`, "aria-pressed": String(on), onclick }, label);

  function paint() {
    dayTabs.replaceChildren(...days.map((d) => chip(`${dayLabel(d.day)} (${d.shows.length})`, d.day === state.day, () => { state.day = d.day; paint(); })));
    typeChips.replaceChildren(chip("Todos", state.type === ALL, () => { state.type = ALL; paint(); }),
      ...TIPOS.map(([t, label]) => chip(label, t === state.type, () => { state.type = t; paint(); })),
      chip("↕ Más cerca", state.near, async () => {
        state.near = !state.near;
        here = here || await currentPosition();
        if (state.near && !here) toast("Activá la ubicación para ordenar por cercanía.");
        paint();
      }));
    let shown = days.find((d) => d.day === state.day)?.shows || [];
    if (state.type !== ALL) shown = shown.filter((s) => s.tipo === state.type);
    if (state.near && here) {
      const dist = (s) => (s.venue?.lat != null ? distanceMeters(here, s.venue) : Infinity);
      shown = [...shown].sort((a, b) => Number(a.cancelled) - Number(b.cancelled) || dist(a) - dist(b));
    }
    list.replaceChildren(...(shown.length ? shown.map((s) => ShowCard(s, state.day, reload))
      : [h("p", { class: "caption" }, "No hay shows de ese tipo ese día.")]));
  }
  async function reload() {
    ({ days } = await Shows.list());
    paint();
  }
  paint();
  box.append(
    h("p", { class: "caption" }, "Shows, deportes y actividades en Las Vegas. Las entradas se compran en Ticketmaster."),
    dayTabs, typeChips, list,
    h("p", { class: "caption" }, "Datos de Ticketmaster."));
  return box;
}

// --- ficha -------------------------------------------------------------------------
const section = (title, ...children) => h("section", { class: "stack" }, h("h2", { class: "label" }, title), ...children);
const row = (label, value) => (value ? h("div", { class: "ra-event-row" }, h("span", { class: "label" }, label), h("span", {}, value)) : null);

/** La función que arranca elegida: la del día pedido (desde la tarjeta), o la primera que no está cancelada. */
function firstChoice(functions, day) {
  const usable = functions.filter((f) => !f.cancelled);
  return (day && usable.find((f) => f.day === day)) || usable.find((f) => f.in_itinerary) || usable[0] || functions[0];
}

export async function viewShow(view, id, query = "") {
  const s = await Shows.get(decodeURIComponent(id));
  const day = new URLSearchParams(query.replace(/^\?/, "")).get("dia");
  let chosen = firstChoice(s.functions, day);
  const picker = h("div", { class: "ra-funciones", role: "group", "aria-label": "Función" });
  const detail = h("div", { class: "stack-lg" });
  const reload = () => { view.replaceChildren(); void viewShow(view, id, query); };

  function paint() {
    picker.replaceChildren(...s.functions.map((f) => h("button", {
      type: "button", class: `ra-chip${f === chosen ? " ra-chip-on" : ""}`, "aria-pressed": String(f === chosen),
      onclick: () => { chosen = f; paint(); },
    }, `${shortDay(f.day)} · ${f.start}${f.cancelled ? " · cancelada" : ""}`)));
    const f = chosen;
    detail.replaceChildren(
      section("Cuándo y dónde",
        row("Cuándo", `${dayLabel(f.day)} · ${f.start}–${f.end}`),
        row("Dónde", [f.venue.hotel, f.venue.address].filter(Boolean).join(" · ")),
        f.near ? row("Cerca de", `${f.near.name} (${Math.round(f.near.meters / 100) / 10} km)`.replace(".", ",")) : null,
        GoThere(destination(f), { start: startsAt(f.day, f.start), eta: true })),
      section("Entradas",
        row("Desde", f.price_from != null ? `US$ ${money(f.price_from)}` : null),
        row("Estado", STATUS[f.status]?.label || STATUS.onsale.label),
        StatusHint(f.status)),
      h("div", { class: "actions" }, TicketLink(f.url, { button: true }), f.cancelled ? null : AddFunctionButton(f, reload)),
      h("p", { class: "caption" }, "Datos de Ticketmaster. La compra se hace en su página."));
  }
  paint();
  const kind = [s.type.toUpperCase(), s.artist && s.artist !== s.title ? s.artist.toUpperCase() : null].filter(Boolean).join(" · ");
  view.append(h("div", { class: "stack-lg" },
    h("a", { class: "ra-link", href: "#/eventos/shows" }, "← Shows"),
    Cover(s, "ra-event-hero"),
    h("header", { class: "stack" },
      h("span", { class: "ra-kind" }, kind),
      h("h1", { class: "title" }, s.title),
      CountdownBadge(startsAt(chosen.day, chosen.start))),
    section("Funciones esta semana", picker,
      h("p", { class: "caption" }, "Elegí la función y agregala: queda fijada en tu itinerario y te avisamos cuándo salir.")),
    detail));
}
