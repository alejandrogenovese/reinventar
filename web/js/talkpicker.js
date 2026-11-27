// Elegir la charla que vas a grabar: "ahora en tu itinerario" o búsqueda por código/título en el catálogo.
import { Itinerary, Knowledge } from "./api.js";
import { enVegas } from "./dia.js";
import { sandboxNow } from "./sandbox.js";
import { h, mensajeError, toast } from "./ui.js";

const SEARCH_DELAY_MS = 250;
const NOW_BEFORE_MIN = 30; // charlas que empezaron hace hasta 30 min…
const NOW_AFTER_MIN = 90;  // …o que empiezan en la próxima hora y media

const minutes = (hhmm) => { const [hh, mm] = hhmm.split(":").map(Number); return hh * 60 + mm; };
const label = (s) => `${s.code} · ${[s.day, s.start].filter(Boolean).join(" ")} · ${s.title}`;

/** Del itinerario (`days`), las de hoy cerca de `ahora` en hora de Las Vegas (el celular puede seguir en otra zona). */
export function cercaDeAhora(days, ahora) {
  const { fecha, hora } = enVegas(ahora);
  const current = minutes(hora);
  const sessions = (days || []).find((d) => d.day === fecha)?.sessions || [];
  return sessions.filter((s) => s.start && minutes(s.start) - current <= NOW_AFTER_MIN && current - minutes(s.start) <= NOW_BEFORE_MIN);
}

async function nowInItinerary() {
  const { days } = await Itinerary.get();
  return cercaDeAhora(days, sandboxNow());
}

/**
 * @param {{ onPick: (talk: object | null) => void }} opts  talk = card del catálogo + recording_kind; null = desvincular
 */
export function TalkPicker({ onPick }) {
  const input = h("input", { id: "talkq", type: "search", maxlength: "80", autocomplete: "off", autocapitalize: "characters",
    placeholder: "Código (ARC407) o parte del título" });
  const results = h("div", { class: "ra-chips" });
  const nowSlot = h("div", { class: "stack" });
  const chosen = h("div");
  let timer;

  const choose = async (code) => {
    try {
      const [talk] = await Knowledge.pickTalk(code);
      if (!talk) { toast("No encontré esa charla en el catálogo."); return; }
      results.replaceChildren();
      input.value = "";
      chosen.replaceChildren(h("button", { type: "button", class: "ra-chip ra-chip-on", "aria-label": `Desvincular ${talk.code}`,
        onclick: () => { chosen.replaceChildren(); onPick(null); } }, `Vinculada a ${talk.code}`));
      onPick(talk);
    } catch (e) { toast(mensajeError(e)); }
  };
  const option = (s) => h("button", { type: "button", class: "ra-chip", onclick: () => choose(s.code) }, label(s));

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { results.replaceChildren(); return; }
    timer = setTimeout(async () => {
      try {
        const rows = await Knowledge.pickTalk(q);
        if (input.value.trim() !== q) return; // llegó tarde: ya escribiste otra cosa
        results.replaceChildren(...(rows.length ? rows.map(option) : [h("span", { class: "caption" }, "Sin resultados en el catálogo.")]));
      } catch (e) { toast(mensajeError(e)); }
    }, SEARCH_DELAY_MS);
  });

  nowInItinerary().then((rows) => {
    if (rows.length) nowSlot.replaceChildren(h("span", { class: "label" }, "Ahora en tu itinerario"), h("div", { class: "ra-chips" }, rows.map(option)));
  }).catch(() => {}); // sin itinerario o sin red: el buscador alcanza

  return h("div", { class: "stack" },
    h("label", { class: "label", for: "talkq" }, "Charla del catálogo"),
    nowSlot, input, results, chosen,
    h("p", { class: "caption" }, "Si la vinculás, el resumen usa el abstract oficial y escribe bien los nombres de speakers y empresas."));
}
