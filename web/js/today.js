// Pantalla Hoy: la charla que está pasando, la que sigue y el resto del día, con "Grabar esta charla".
import { Sessions, Today } from "./api.js";
import { CountdownBadge } from "./countdown.js";
import { GoThere, startsAt } from "./location.js";
import { icon } from "./icons.js";
import { Button, Hint, IconText, h, toast } from "./ui.js";

const LATER_LIMIT = 4;

const dayLabel = (iso) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "short" });

const place = (s) => [s.venue?.hotel, s.venue?.detail].filter(Boolean).join(" · ");

/** Crea la sesión de grabación con los datos de la charla y abre el grabador. */
export async function recordTalk(s, btn) {
  btn.disabled = true;
  try {
    const rec = await Sessions.create({
      title: s.title.slice(0, 200), kind: s.recording_kind, code: s.code,
      venue: place(s).slice(0, 120) || null,
      speaker: ((s.people || []).map((p) => p.name).join(", ") || s.speakers || "").slice(0, 200) || null,
    });
    location.hash = `#/grabar/${rec.id}`;
  } catch (err) { toast(err.message); btn.disabled = false; }
}

// A dónde lleva tocar un ítem: la charla, el evento, o el itinerario (los eventos propios no tienen ficha).
const itemHref = (s) => ({ event: `#/evento/${encodeURIComponent(s.code)}`, mine: "#/itinerario" }[s.kind] || `#/charla/${s.base}`);
// Eventos y eventos propios llevan su ícono; las charlas, el código en mono.
const KIND_ICON = { event: ["eventos", "Evento"], mine: ["fijar", "Mi evento"] };
const itemLabel = (s) => (KIND_ICON[s.kind] ? IconText(...KIND_ICON[s.kind]) : h("span", { class: "ra-mono" }, s.code));
const itemTitle = (s) => (KIND_ICON[s.kind] ? [icon(KIND_ICON[s.kind][0], 16), h("span", {}, s.title)] : s.title);

/** Acción de la charla: si ya hay una grabación con ese código, abrirla; si no, grabar. */
function TalkAction(s, recorded, variant) {
  if (s.kind === "mine") return s.note ? h("p", { class: "caption" }, s.note) : null;
  if (s.kind === "event") return Button("Ver evento", { variant, onclick: () => (location.hash = `#/evento/${encodeURIComponent(s.code)}`) });
  const mine = recorded.get(s.code);
  if (mine) {
    const live = mine.status === "recording" || mine.status === "uploading";
    return Button(live ? "Seguir grabando" : "Ver grabación", { onclick: () => (location.hash = live ? `#/grabar/${mine.id}` : `#/s/${mine.id}`) });
  }
  const btn = Button(variant === "primary" ? "Grabar esta charla" : "Grabar", { variant, onclick: () => recordTalk(s, btn) });
  return btn;
}

const destination = (s) => (s.venue?.lat != null
  ? { lat: s.venue.lat, lng: s.venue.lng, name: s.venue.hotel, placeId: s.venue.place_id, approx: s.venue.exact === false } : null);

// "Ahora" es un estado con punto (y la tarjeta lleva borde de marca); "Después"/"Próxima", texto de marca.
const WhenLabel = (label, highlight) => (highlight
  ? h("span", { class: "ra-status is-now" }, h("span", { class: "ra-status-dot", "aria-hidden": "true" }), label)
  : h("span", { class: "ra-soon" }, label));

function TalkCard(s, { label, recorded, variant, highlight }) {
  return h("article", { class: `ra-today${highlight ? " is-now" : ""}` },
    h("div", { class: "ra-today-when" }, WhenLabel(label, highlight), h("span", { class: "ra-time" }, `${s.start}–${s.end}`)),
    !highlight && s.day && s.start ? CountdownBadge(startsAt(s.day, s.start)) : null,
    h("h3", { class: "ra-card-title" }, h("a", { class: "ra-link", href: itemHref(s) }, s.title)),
    h("div", { class: "ra-card-meta" }, place(s) ? IconText("ubicacion", place(s)) : null, itemLabel(s)),
    // Tiempo a pie (Routes API, paga) solo en estas dos tarjetas: lo que está pasando y lo que sigue.
    s.cola_desde ? Hint(`Sin reserva: hacé la cola desde las ${s.cola_desde}.`, { tone: "info" }) : null,
    s.salis_a ? Hint(`Salí a las ${s.salis_a}, antes de que termine, para llegar a la siguiente.`, { tone: "warn" }) : null,
    GoThere(destination(s), { start: s.day && s.start ? startsAt(s.day, s.cola_desde || s.start) : null, eta: true }),
    h("div", { class: "actions" }, TalkAction(s, recorded, variant)));
}

const LaterList = (items) => items.length ? h("ul", { class: "ra-today-later" },
  items.slice(0, LATER_LIMIT).map((s) => h("li", {}, h("span", { class: "ra-mono" }, s.start),
    h("a", { class: "ra-link", href: itemHref(s) }, itemTitle(s)))),
  items.length > LATER_LIMIT ? h("li", { class: "caption" }, h("a", { class: "ra-link", href: "#/itinerario" }, `y ${items.length - LATER_LIMIT} más en tu itinerario`)) : null) : null;

const Empty = (text, action) => h("div", { class: "ra-today-empty" }, h("p", { class: "caption" }, text), action);

/**
 * Panel Hoy para el inicio. `sessions` son las grabaciones del usuario (para no duplicar una charla ya grabada).
 * Devuelve { el, hasTalk }: con una charla para grabar, el inicio baja "Nueva sesión" a secundario (un solo primario).
 */
export async function TodayPanel(sessions) {
  const data = await Today.get();
  const recorded = new Map(sessions.filter((s) => s.code).map((s) => [s.code, s]));
  const body = [];

  if (data.now) body.push(TalkCard(data.now, { label: "Ahora", recorded, variant: "primary", highlight: true }));
  if (data.next) body.push(TalkCard(data.next, { label: data.now ? "Después" : "Próxima", recorded, variant: data.now ? "secondary" : "primary" }));
  body.push(LaterList(data.later));

  if (!data.now && !data.next) {
    const up = data.upcoming;
    body.push(up
      ? Empty(`No tenés más charlas hoy. La próxima es el ${dayLabel(up.day)} a las ${up.first.start}: ${up.first.title}.`,
        Button("Ver itinerario", { onclick: () => (location.hash = "#/itinerario") }))
      : Empty("No tenés charlas en el itinerario para hoy.",
        Button("Armar itinerario", { onclick: () => (location.hash = "#/itinerario") })));
  }

  const el = h("section", { class: "stack", "aria-labelledby": "hoy-title" },
    h("div", { class: "ra-sec-head" }, h("h2", { class: "label", id: "hoy-title" }, "Hoy"), h("span", { class: "caption" }, dayLabel(data.date))), body);
  return { el, hasTalk: Boolean(data.now || data.next) };
}
