// Buscar › Preguntar: chat de búsqueda sobre el catálogo y lo grabado. La respuesta cita charlas por código ([ARC407])
// y momentos de las grabaciones ([G1]); unas y otros se muestran abajo.
import { Itinerary, Knowledge } from "./api.js";
import { MomentCard, momentHash } from "./grabado.js";
import { SessionMiniCard } from "./itinerary.js";
import { icon } from "./icons.js";
import { clock, h, toast, withCodeLinks } from "./ui.js";

const MAX_QUESTION = 500;
const HISTORY_LIMIT = 10;
const EXAMPLES = [
  "Bancos latinoamericanos usando IA generativa",
  "Cómo bajar costos de inferencia",
  "Data mesh y gobierno de datos en empresas grandes",
  "Clientes de retail que usan agentes",
];

// Se conserva mientras la app esté abierta: entrar a una charla y volver no borra la conversación.
let history = [];

const addToItinerary = (code) => async () => {
  try { await Itinerary.add(code); toast("Agregada al itinerario."); } catch (e) { toast(e.message); }
};

const MOMENT_REF = /\[(G\d{1,2})\]/g;

const CITE = { className: "ra-cite" };

/** Texto con citas: [G1] → pastilla naranja ▶ al minuto de la grabación (si vino citado) y [ARC407] → pastilla gris
 *  a la ficha de la charla. Las dos en mono, como los demás datos. */
function withLinks(text, cited, moments) {
  const parts = [];
  let last = 0;
  for (const m of text.matchAll(MOMENT_REF)) {
    parts.push(...withCodeLinks(text.slice(last, m.index), cited, CITE));
    const moment = moments.get(m[1]);
    parts.push(moment ? h("a", { class: "ra-cite ra-moment-ref", href: momentHash(moment.session_id, moment.start_s),
      title: moment.title, "aria-label": `Ir al momento ${clock(moment.start_s)} de ${moment.title}` }, icon("reproducir", 14), clock(moment.start_s)) : "");
    last = m.index + m[0].length;
  }
  parts.push(...withCodeLinks(text.slice(last), cited, CITE));
  return parts;
}

function Answer(text, citedList, momentList = []) {
  const cited = new Set(citedList);
  const moments = new Map(momentList.map((m) => [m.ref, m]));
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const bullets = lines.filter((l) => l.startsWith("- "));
  const paragraphs = lines.filter((l) => !l.startsWith("- "));
  return h("div", { class: "ra-answer" },
    paragraphs.map((l) => h("p", {}, withLinks(l, cited, moments))),
    bullets.length ? h("ul", {}, bullets.map((l) => h("li", {}, withLinks(l.slice(2), cited, moments)))) : null);
}

function Exchange({ q, result }) {
  const cited = new Set(result.cited);
  const citedCards = result.sessions.filter((s) => cited.has(s.base));
  const others = result.sessions.filter((s) => !cited.has(s.base));
  const cards = (rows) => h("div", { class: "daylist" }, rows.map((s) => SessionMiniCard(s, { onAdd: addToItinerary(s.code) })));
  return h("section", { class: "stack ra-ask-turn" },
    h("h2", { class: "ra-ask-q" }, q),
    Answer(result.answer, result.cited, result.momentos),
    result.momentos?.length ? h("div", { class: "stack" }, h("h3", { class: "ra-group-label" }, `En tus grabaciones · ${result.momentos.length}`),
      h("div", { class: "ra-hits" }, result.momentos.map((m) => MomentCard(m)))) : null,
    citedCards.length ? cards(citedCards) : null,
    others.length ? h("details", { class: "notice" }, h("summary", { class: "label" }, `Otras que pueden servirte (${others.length})`), cards(others)) : null);
}

/**
 * El teclado del celular tapa lo que está fijo abajo: con visualViewport se mide cuánto ocupa y el campo sube
 * (--kb). Devuelve la función que deja de escuchar.
 */
function followKeyboard(el) {
  const vv = window.visualViewport;
  if (!vv) return () => {};
  const sync = () => el.style.setProperty("--kb", `${Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop))}px`);
  vv.addEventListener("resize", sync);
  vv.addEventListener("scroll", sync);
  sync();
  return () => { vv.removeEventListener("resize", sync); vv.removeEventListener("scroll", sync); };
}

/** Alto del campo fijo en --composer-h: la pantalla deja ese espacio abajo para que no tape la última respuesta. */
function trackHeight(el) {
  if (!("ResizeObserver" in window)) return () => {};
  const ro = new ResizeObserver(() => document.documentElement.style.setProperty("--composer-h", `${el.offsetHeight}px`));
  ro.observe(el);
  return () => { ro.disconnect(); document.documentElement.style.removeProperty("--composer-h"); };
}

const COMPOSER_MAX_PX = 140; // el campo crece con el texto hasta ~5 líneas; después scrollea

/** Modo Preguntar de Buscar: ejemplos, la conversación (de la más vieja a la más nueva, sobrevive al cambiar de
 *  pantalla) y el campo para escribir fijo abajo, sobre la barra de navegación. */
export function AskPanel() {
  const input = h("textarea", { rows: "1", maxlength: String(MAX_QUESTION), "aria-label": "Tu pregunta", enterkeyhint: "send" });
  const submit = h("button", { type: "submit", class: "ra-send", "aria-label": "Enviar pregunta", title: "Enviar" }, icon("enviar", 20));
  const turns = h("div", { class: "ra-turns" });
  const placeholder = () => (history.length ? "Preguntá otra cosa…" : "Preguntá lo que buscás…");
  // Crece con lo escrito; vacío vuelve a una línea (el placeholder no cuenta).
  const grow = () => {
    input.style.height = "";
    if (input.value) input.style.height = `${Math.min(input.scrollHeight, COMPOSER_MAX_PX)}px`;
  };
  const paint = () => { turns.replaceChildren(...history.map(Exchange)); input.placeholder = placeholder(); };

  async function ask(q) {
    if (q.length < 2) { toast("Escribí una pregunta un poco más larga."); return; }
    submit.disabled = true;
    const pending = h("p", { class: "caption", role: "status" }, "Buscando en el catálogo y en lo que grabaste…");
    turns.append(pending);
    pending.scrollIntoView({ block: "nearest" });
    try {
      const result = await Knowledge.ask(q);
      history = [...history, { q, result }].slice(-HISTORY_LIMIT);
      input.value = "";
      grow();
      examples.remove();
      paint();
      turns.lastElementChild?.scrollIntoView({ block: "start" }); // la pregunta nueva arriba, con su respuesta abajo
    } catch (e) {
      pending.remove();
      toast(e.message);
    } finally {
      submit.disabled = false;
    }
  }

  const form = h("form", { class: "ra-composer", onsubmit: (e) => { e.preventDefault(); void ask(input.value.trim()); } },
    h("div", { class: "ra-composer-box" }, input, submit));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  input.addEventListener("input", grow);

  const examples = history.length ? h("div") : h("div", { class: "ra-chips" },
    EXAMPLES.map((ex) => h("button", { type: "button", class: "ra-chip", onclick: () => { input.value = ex; void ask(ex); } }, ex)));

  const panel = h("div", { class: "ra-ask" },
    h("p", { class: "caption" }, "Contá qué buscás con tus palabras: busco en todo el catálogo y en lo que grabaste, y te respondo citando las charlas y los momentos que sirven."),
    examples, turns, form);
  paint();

  // Lo fijo se engancha al mostrar el panel y se suelta al salir (cambiar a Filtrar o a otra pantalla): search.js.
  let stop = [];
  panel.attach = () => { if (!stop.length) stop = [followKeyboard(form), trackHeight(form)]; };
  panel.detach = () => { stop.forEach((fn) => fn()); stop = []; };
  return panel;
}
