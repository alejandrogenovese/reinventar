// Buscar › Preguntar: chat de búsqueda sobre el catálogo. La respuesta cita charlas por código ([ARC407]) y las muestra abajo.
import { Itinerary, Knowledge } from "./api.js";
import { SessionMiniCard } from "./itinerary.js";
import { Button, h, toast, withCodeLinks } from "./ui.js";

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

function Answer(text, citedList) {
  const cited = new Set(citedList);
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const bullets = lines.filter((l) => l.startsWith("- "));
  const paragraphs = lines.filter((l) => !l.startsWith("- "));
  return h("div", { class: "stack" },
    paragraphs.map((l) => h("p", {}, withCodeLinks(l, cited))),
    bullets.length ? h("ul", { class: "ra-people" }, bullets.map((l) => h("li", {}, withCodeLinks(l.slice(2), cited)))) : null);
}

function Exchange({ q, result }) {
  const cited = new Set(result.cited);
  const citedCards = result.sessions.filter((s) => cited.has(s.base));
  const others = result.sessions.filter((s) => !cited.has(s.base));
  const cards = (rows) => h("div", { class: "daylist" }, rows.map((s) => SessionMiniCard(s, { onAdd: addToItinerary(s.code) })));
  return h("section", { class: "stack ra-ask-turn" },
    h("p", { class: "label" }, q),
    h("div", { class: "notice" }, Answer(result.answer, result.cited)),
    citedCards.length ? cards(citedCards) : null,
    others.length ? h("details", { class: "notice" }, h("summary", { class: "label" }, `Otras que pueden servirte (${others.length})`), cards(others)) : null);
}

/** Modo Preguntar de Buscar: formulario, ejemplos y la conversación (sobrevive al cambiar de pantalla). */
export function AskPanel() {
  const input = h("textarea", { rows: "2", maxlength: String(MAX_QUESTION), "aria-label": "Tu pregunta",
    placeholder: "Ej: ¿qué bancos cuentan cómo usan agentes con Bedrock?" });
  const submit = Button("Preguntar", { variant: "primary", type: "submit" });
  const turns = h("div", { class: "stack-lg" });
  const paint = () => turns.replaceChildren(...history.map(Exchange));

  async function ask(q) {
    if (q.length < 2) { toast("Escribí una pregunta un poco más larga."); return; }
    submit.disabled = true;
    const pending = h("p", { class: "caption" }, "Buscando en el catálogo…");
    turns.prepend(pending);
    try {
      const result = await Knowledge.ask(q);
      history = [{ q, result }, ...history].slice(0, HISTORY_LIMIT);
      input.value = "";
      paint();
    } catch (e) {
      pending.remove();
      toast(e.message);
    } finally {
      submit.disabled = false;
    }
  }

  const form = h("form", { class: "stack", onsubmit: (e) => { e.preventDefault(); ask(input.value.trim()); } },
    h("div", { class: "field" }, input),
    h("div", { class: "actions" }, submit));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });

  const panel = h("div", { class: "stack-lg" },
    h("p", { class: "caption" }, "Contá qué buscás con tus palabras: busco en todo el catálogo y te respondo citando las charlas que sirven."),
    form,
    history.length ? null : h("div", { class: "ra-chips" },
      EXAMPLES.map((ex) => h("button", { type: "button", class: "ra-chip", onclick: () => { input.value = ex; ask(ex); } }, ex))),
    turns);
  paint();
  return panel;
}
