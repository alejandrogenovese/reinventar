// #/grabar-charla/{code}: adonde lleva el aviso "¿La grabás?" (app/recordatorio.py). Muestra la charla y un botón
// grande "Empezar a grabar": no arranca sola porque iOS pide un gesto para el micrófono (y así no quedan grabaciones
// vacías). Si alguien ya la está grabando, abre esa grabación.
import { Itinerary, Sessions } from "./api.js";
import { icon } from "./icons.js";
import { recordTalk } from "./today.js";
import { Button, IconText, h } from "./ui.js";

const LIVE = ["recording", "uploading"];
const place = (s) => [s.venue?.hotel, s.venue?.detail].filter(Boolean).join(" · ");

export async function viewGrabarCharla(view, code) {
  code = decodeURIComponent(code);
  const [itinerary, sessions] = await Promise.all([Itinerary.get(), Sessions.list()]);
  const live = sessions.find((s) => s.code === code && LIVE.includes(s.status));
  if (live) { location.replace(`#/grabar/${live.id}`); return; }

  const talk = itinerary.days.flatMap((d) => d.sessions).find((s) => s.code === code);
  if (!talk) {
    view.append(h("div", { class: "stack-lg" },
      h("h1", { class: "title" }, "Grabar"),
      h("p", {}, `${code} ya no está en tu itinerario.`),
      Button("Grabar otra cosa", { onclick: () => (location.hash = "#/nueva") })));
    return;
  }
  const btn = Button([icon("grabar", 20), "Empezar a grabar"], { variant: "primary", onclick: () => recordTalk(talk, btn) });
  view.append(h("div", { class: "stack-lg" },
    h("header", { class: "stack" },
      h("p", { class: "label" }, "¿La grabás?"),
      h("h1", { class: "title" }, talk.title),
      h("div", { class: "ra-card-meta" }, place(talk) ? IconText("ubicacion", place(talk)) : null,
        h("span", { class: "ra-mono" }, talk.code), talk.start ? h("span", { class: "ra-time" }, `${talk.start}–${talk.end || ""}`) : null)),
    h("div", { class: "ra-today-actions" }, btn), // el botón ocupa la fila, como "Grabar esta charla" en Hoy
    h("p", { class: "caption" }, "Dejá el celular cerca del parlante y con la pantalla prendida.")));
  btn.focus();
}
