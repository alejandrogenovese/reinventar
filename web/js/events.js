// Eventos de networking (desayunos, happy hours, fiestas, meetups): lista por día con filtros y ficha.
// Se agregan al itinerario (fijados) y se manejan desde ahí, igual que las charlas.
import { Events, Itinerary } from "./api.js";
import { CountdownBadge, refreshCountdown } from "./countdown.js";
import { GoThere, currentPosition, distanceMeters, startsAt } from "./location.js";
import { MyEventsSection } from "./myEvents.js";
import { sandboxNow } from "./sandbox.js";
import { Button, Hint, IconText, Tag, h, toast } from "./ui.js";

const ALL = "todos";
const dayLabel = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("es-AR", { weekday: "short", day: "numeric", month: "numeric" }).replaceAll(".", "");
const when = (e) => [e.start, e.end].filter(Boolean).join("–");
const destination = (e) => (e.venue?.lat != null
  ? { lat: e.venue.lat, lng: e.venue.lng, name: e.venue.hotel, placeId: e.venue.place_id, approx: e.venue.exact === false } : null);
const place = (e) => (e.venue?.exact ? e.venue.hotel : "Las Vegas · dirección al anotarte");

// Imagen y link vienen de la fuente externa (Luma): solo https.
const safeUrl = (url) => (typeof url === "string" && url.startsWith("https://") ? url : null);

const Cover = (e, cls) => (safeUrl(e.image)
  ? h("img", { class: cls, src: e.image, alt: "", loading: "lazy", decoding: "async", referrerpolicy: "no-referrer" }) : null);

function facts(e) {
  return [e.full ? "Lleno" : null, e.guests ? `${e.guests} anotados` : null, e.price, e.approval ? "requiere aprobación" : null]
    .filter(Boolean).join(" · ");
}

/** Botón "+ Itinerario" / "En tu itinerario" (fijado). */
function AddButton(e, onAdded) {
  if (e.in_itinerary) return IconText("fijar", "En tu itinerario", { className: "ra-tag is-new ra-icotext", size: 14 });
  const btn = Button("+ Itinerario", { onclick: async () => {
    btn.disabled = true;
    try {
      const r = await Itinerary.add(e.code);
      const mine = r.days.flatMap((d) => d.sessions).find((s) => s.code === e.code);
      toast(mine?.overlaps?.length ? `Agregado. Ojo: se superpone con ${mine.overlaps.join(", ")}.` : "Agregado y fijado en tu itinerario.");
      void refreshCountdown({ force: true });
      onAdded?.();
    } catch (err) { toast(err.message); btn.disabled = false; }
  } });
  return btn;
}

/** Tarjeta de evento: la usan la lista de Eventos y el itinerario. */
export function EventCard(e, { onAdded, actions = null } = {}) {
  return h("article", { class: "ra-event" },
    Cover(e, "ra-event-cover"),
    h("div", { class: "ra-event-body" },
      h("span", { class: "ra-kind" }, [e.type ? e.type.toUpperCase() : "EVENTO", dayLabel(e.day), when(e)].filter(Boolean).join(" · ")),
      h("h3", { class: "ra-card-title" }, h("a", { class: "ra-link", href: `#/evento/${encodeURIComponent(e.code)}` }, e.title)),
      h("div", { class: "ra-card-meta" }, h("span", {}, place(e)), e.organizers?.length ? h("span", {}, e.organizers.join(" · ")) : null),
      facts(e) ? h("p", { class: "caption" }, facts(e)) : null,
      e.overlaps?.length ? Hint(`Se superpone con ${e.overlaps.join(", ")}`, { tone: "error" }) : null,
      GoThere(destination(e)),
      h("div", { class: "actions" }, actions ?? AddButton(e, onAdded))));
}

// --- lista ---------------------------------------------------------------------
export async function viewEventos(view) {
  let [{ days }, mios] = await Promise.all([Events.list(), MyEventsSection()]);
  const all = days.flatMap((d) => d.events);
  if (!all.length) {
    view.append(h("div", { class: "stack" }, h("h1", { class: "title" }, "Eventos"), mios,
      h("p", { class: "caption" }, "Todavía no hay eventos cargados.")));
    return;
  }
  const types = [ALL, ...new Set(all.map((e) => e.type).filter(Boolean))];
  // Arranca en el día de hoy (o el del reloj simulado en modo prueba) si hay eventos ese día.
  const today = sandboxNow().toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
  const state = { day: days.some((d) => d.day === today) ? today : days[0].day, type: ALL, near: false };
  let here = null;
  void currentPosition().then((p) => { here = p; });

  const dayTabs = h("div", { class: "ra-chips", role: "tablist", "aria-label": "Día" });
  const typeChips = h("div", { class: "ra-chips", "aria-label": "Tipo de evento" });
  const list = h("div", { class: "daylist" });
  const chip = (label, on, onclick) => h("button", { type: "button", class: `ra-chip${on ? " ra-chip-on" : ""}`, "aria-pressed": String(on), onclick }, label);

  function paint() {
    dayTabs.replaceChildren(...days.map((d) => chip(`${dayLabel(d.day)} (${d.events.length})`, d.day === state.day, () => { state.day = d.day; paint(); })));
    typeChips.replaceChildren(...types.map((t) => chip(t === ALL ? "Todos" : t, t === state.type, () => { state.type = t; paint(); })),
      chip("↕ Más cerca", state.near, async () => {
        state.near = !state.near;
        here = here || await currentPosition();
        if (state.near && !here) { toast("Activá la ubicación para ordenar por cercanía."); }
        paint();
      }));
    let shown = days.find((d) => d.day === state.day)?.events || [];
    if (state.type !== ALL) shown = shown.filter((e) => e.type === state.type);
    if (state.near && here) shown = [...shown].sort((a, b) => distanceMeters(here, a.venue) - distanceMeters(here, b.venue));
    list.replaceChildren(...(shown.length ? shown.map((e) => EventCard(e, { onAdded: reload })) : [h("p", { class: "caption" }, "No hay eventos de ese tipo ese día.")]));
  }
  async function reload() {
    ({ days } = await Events.list());
    paint();
  }
  paint();
  view.append(h("div", { class: "stack-lg" },
    h("header", { class: "stack" }, h("h1", { class: "title" }, "Eventos"),
      h("p", { class: "caption" }, "Desayunos, happy hours, fiestas y meetups alrededor de re:Invent. Agregalos al itinerario y quedan fijados.")),
    mios, dayTabs, typeChips, list));
}

// --- ficha ---------------------------------------------------------------------
export async function viewEvento(view, code) {
  const e = await Events.get(decodeURIComponent(code));
  const section = (title, ...children) => h("section", { class: "stack" }, h("h2", { class: "label" }, title), ...children);
  const original = e.description ? h("details", { class: "notice" }, h("summary", {}, "Ver original en inglés"),
    h("p", { class: "ra-prose", lang: "en" }, e.description)) : null;
  const row = (label, value) => (value ? h("div", { class: "ra-event-row" }, h("span", { class: "label" }, label), h("span", {}, value)) : null);

  view.append(h("div", { class: "stack-lg" },
    h("a", { class: "ra-link", href: "#/eventos" }, "← Eventos"),
    Cover(e, "ra-event-hero"),
    h("header", { class: "stack" },
      h("span", { class: "ra-kind" }, [e.type ? e.type.toUpperCase() : "EVENTO", dayLabel(e.day), when(e)].filter(Boolean).join(" · ")),
      h("h1", { class: "title" }, e.title),
      CountdownBadge(startsAt(e.day, e.start)),
      e.topics?.length ? h("div", { class: "ra-chips" }, e.topics.map(Tag)) : null),
    e.summary ? section("De qué se trata", h("p", { class: "ra-prose" }, e.summary), original) : original,
    section("Cuándo y dónde",
      row("Cuándo", `${dayLabel(e.day)} · ${when(e)}`),
      row("Dónde", e.venue?.exact ? [e.venue.hotel, e.venue.address].filter(Boolean).join(" · ") : "Las Vegas · la dirección exacta aparece al anotarte en Luma"),
      e.near?.meters != null ? row("Cerca de", `${e.near.name} (${Math.round(e.near.meters / 100) / 10} km)`) : null,
      GoThere(destination(e), { start: startsAt(e.day, e.start), eta: true })),
    section("Detalles",
      row("Organizan", e.organizers?.join(" · ")),
      row("Entrada", [e.price, e.approval ? "requiere aprobación" : null].filter(Boolean).join(" · ")),
      row("Anotados", e.guests ? String(e.guests) : null),
      e.full ? Hint("Está lleno: anotate en la lista de espera de Luma.", { tone: "error" }) : null),
    e.clashes?.length ? Hint(`Choca con: ${e.clashes.map((c) => `${c.title} (${c.start})`).join(", ")}`, { tone: "error" }) : null,
    h("div", { class: "actions" },
      safeUrl(e.url) ? h("a", { class: "ra-btn ra-btn-primary", href: e.url, target: "_blank", rel: "noopener noreferrer" }, "Anotarme en Luma ↗") : null,
      AddButton(e, () => { view.replaceChildren(); void viewEvento(view, code); }))));
}
