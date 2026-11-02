// "Preparar conversación": ficha generada por el LLM para hablar con un speaker o con gente de una empresa.
import { Knowledge } from "./api.js";
import { Button, h, toast, withCodeLinks } from "./ui.js";

const formatDate = (epochSeconds) => new Date(epochSeconds * 1000).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" });

function BriefingBody(b, codes) {
  const para = (title, text) => (text ? h("section", { class: "stack" }, h("h3", { class: "label" }, title), h("p", {}, withCodeLinks(text, codes))) : null);
  return h("div", { class: "stack" },
    para("Quién es", b.quien),
    para("La empresa y AWS", b.empresa_y_aws),
    para("En re:Invent", b.en_reinvent),
    b.temas?.length ? h("section", { class: "stack" }, h("h3", { class: "label" }, "Temas para abrir"),
      h("ul", { class: "ra-people" }, b.temas.map((t) => h("li", {}, h("strong", {}, t.tema), t.por_que ? ` — ${t.por_que}` : "")))) : null,
    b.preguntas?.length ? h("section", { class: "stack" }, h("h3", { class: "label" }, "Preguntas"),
      h("ul", { class: "ra-people" }, b.preguntas.map((q) => h("li", {}, q)))) : null,
    b.cuidado ? h("div", { class: "notice" }, h("strong", {}, "Ojo: "), b.cuidado) : null);
}

/**
 * @param {"speaker" | "empresa"} kind
 * @param {number} id
 * @param {string[]} talkCodes  códigos de sus charlas: solo esos se convierten en links
 */
export function BriefingPanel(kind, id, talkCodes) {
  const codes = new Set(talkCodes);
  const slot = h("div", { class: "stack" });

  async function load(refresh) {
    slot.replaceChildren(h("p", { class: "caption" }, "Preparando la ficha… (tarda unos segundos la primera vez)"));
    try {
      const r = await Knowledge.briefing(kind, id, refresh);
      slot.replaceChildren(
        BriefingBody(r.briefing, codes),
        h("div", { class: "actions is-center" },
          h("span", { class: "caption" }, `Generada el ${formatDate(r.created_at)}`),
          Button("Regenerar", { onclick: () => load(true) })));
    } catch (e) {
      slot.replaceChildren(start);
      toast(e.message);
    }
  }

  const start = Button("Preparar conversación", { variant: "primary", onclick: () => load(false) });
  slot.append(start);
  return h("section", { class: "stack notice" },
    h("h2", { class: "label" }, "Para conversar"),
    h("p", { class: "caption" }, "Quién es, qué hace su empresa con AWS y temas para abrir, cruzados con tu perfil del itinerario."),
    slot);
}
