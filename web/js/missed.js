// "¿Te perdiste X?": otros horarios de la misma charla (primero los que no chocan) y parecidas que empiezan pronto.
import { Itinerary } from "./api.js";
import { refreshCountdown } from "./countdown.js";
import { SessionMiniCard, shortDay } from "./itinerary.js";
import { GoThere } from "./location.js";
import { Button, IconText, h, toast } from "./ui.js";

const section = (title, ...children) => h("section", { class: "stack" }, h("h2", { class: "label" }, title), ...children);
const where = (c) => [c.venue?.hotel, c.venue?.detail].filter(Boolean).join(" · ");
const destination = (c) => (c.venue?.lat != null ? { lat: c.venue.lat, lng: c.venue.lng, name: c.venue.hotel } : null);

function OptionRow(c, actionLabel, onAction) {
  return h("li", { class: "ra-slot" },
    h("div", { class: "ra-rail" }, h("span", { class: "ra-rail-time" }, c.start), h("span", { class: "ra-rail-day" }, shortDay(c.day))),
    h("div", { class: "ra-slot-body" },
      h("span", {}, where(c) || "Sede a confirmar"),
      c.clashes?.length ? IconText("alerta", `choca con ${c.clashes.join(", ")}`, { className: "caption ra-icotext" }) : h("span", { class: "caption" }, "libre en tu itinerario"),
      GoThere(destination(c))),
    c.in_itinerary ? h("span", { class: "ra-tag is-new" }, "En tu itinerario") : Button(actionLabel, { onclick: onAction }));
}

export async function viewPerdida(view, code) {
  code = decodeURIComponent(code);
  const [data, current] = await Promise.all([Itinerary.missed(code), Itinerary.get()]);
  const inItinerary = current.days.some((d) => d.sessions.some((s) => s.code === code));
  const done = async (msg) => { toast(msg); await refreshCountdown({ force: true }); location.hash = "#/itinerario"; };

  const goTo = (to) => async () => {
    try {
      if (inItinerary) await Itinerary.swap(code, to); else await Itinerary.add(to);
      await done("Listo: quedó el nuevo horario en tu itinerario.");
    } catch (err) { toast(err.message); }
  };
  const add = (to) => async () => {
    try { await Itinerary.add(to); toast("Agregada y fijada en tu itinerario."); await refreshCountdown({ force: true }); } catch (err) { toast(err.message); }
  };

  view.append(h("div", { class: "stack-lg" },
    h("header", { class: "stack" },
      h("h1", { class: "title" }, `¿Te perdiste ${data.talk.base}?`),
      h("p", {}, h("a", { class: "ra-link", href: `#/charla/${data.talk.base}` }, data.talk.title))),
    section("Se repite",
      data.repeats.length
        ? h("ul", { class: "ra-slots" }, data.repeats.map((c) => OptionRow(c, c.clashes.length ? "Ir igual" : "Ir a esa", goTo(c.code))))
        : h("p", { class: "caption" }, "No se repite en lo que queda de re:Invent.")),
    section("Parecidas, pronto",
      data.similar.length
        ? h("div", { class: "daylist" }, data.similar.map((c) => SessionMiniCard(c, { onAdd: add(c.code) })))
        : h("p", { class: "caption" }, "No hay charlas parecidas en las próximas 4 horas.")),
    section("Más tarde",
      h("p", { class: "caption" }, "AWS suele publicar muchas charlas en YouTube después del evento; no todas."),
      inItinerary ? Button("Quitarla del itinerario", { variant: "danger", onclick: async () => {
        try { await Itinerary.remove(code); await done("Quitada del itinerario."); } catch (err) { toast(err.message); }
      } }) : null)));
}
