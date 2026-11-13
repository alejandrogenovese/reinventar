// Buscar en lo grabado: fragmentos de las transcripciones que responden a la consulta (app/fragmentos.py).
// Cada resultado abre la transcripción de esa grabación en el minuto donde se dijo.
import { Sessions } from "./api.js";
import { icon } from "./icons.js";
import { clock, h } from "./ui.js";

const DEBOUNCE_MS = 350;
const MIN_CHARS = 2;
const MAX_CHARS = 300;

/** Link a la transcripción de una grabación en un segundo dado (ruta #/s/<id>/t/<segundo> en app.js). Con `q`, el
 *  detalle muestra «Desde la búsqueda «q»» sobre el momento marcado. */
export const momentHash = (sid, seconds, q = "") =>
  `#/s/${sid}/t/${Math.floor(seconds)}${q ? `?q=${encodeURIComponent(q)}` : ""}`;

/** Tarjeta de un momento grabado: hora, charla y lo que se dijo. La usan este buscador y el chat (ask.js). */
export function MomentCard(r, q = "") {
  const meta = [r.kind, r.code].filter(Boolean).join(" · ");
  return h("a", { class: "ra-hit", href: momentHash(r.session_id, r.start_s, q) },
    h("div", { class: "ra-hit-top" },
      h("span", { class: "ra-hit-time ra-mono" }, icon("reproducir", 14), clock(r.start_s)),
      meta ? h("span", { class: "ra-kind" }, meta) : null),
    h("strong", { class: "ra-hit-title" }, r.title),
    h("p", { class: "ra-hit-text", lang: r.es ? "es" : "en" }, r.es || r.en));
}

/** Campo de búsqueda + resultados. Busca mientras se escribe (con una pausa) y cancela el pedido anterior. */
export function RecordingSearch() {
  const input = h("input", { type: "search", maxlength: String(MAX_CHARS), autocomplete: "off", enterkeyhint: "search",
    "aria-label": "Buscar en lo que grabaste", placeholder: "Buscar en lo que grabaste" });
  const status = h("p", { class: "caption ra-hits-status", "aria-live": "polite" });
  const results = h("div", { class: "ra-hits" });
  let timer, ctrl;

  async function run() {
    const q = input.value.trim();
    ctrl?.abort();
    if (q.length < MIN_CHARS) { results.replaceChildren(); status.textContent = ""; return; }
    ctrl = new AbortController();
    status.textContent = "Buscando…";
    try {
      const r = await Sessions.search(q, ctrl.signal);
      if (!r.disponible) { status.textContent = "La búsqueda en lo grabado no está disponible en este servidor."; results.replaceChildren(); return; }
      const n = r.resultados.length;
      status.textContent = !n ? "No aparece en lo que grabaste." : n === 1 ? "1 momento en lo que grabaste" : `${n} momentos en lo que grabaste`;
      results.replaceChildren(...r.resultados.map((m) => MomentCard(m, q)));
    } catch (err) {
      if (err?.name === "AbortError") return;
      status.textContent = err?.message || "No se pudo buscar. Probá de nuevo.";
    }
  }

  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, DEBOUNCE_MS); });
  const form = h("form", { class: "ra-searchbar", role: "search", onsubmit: (e) => { e.preventDefault(); clearTimeout(timer); void run(); } },
    h("div", { class: "ra-searchfield" }, icon("buscar", 20), input));
  const el = h("section", { class: "ra-recsearch" }, form, status, results);
  el.dispose = () => { clearTimeout(timer); ctrl?.abort(); };
  return el;
}

/** En la transcripción ya dibujada: marca el bloque de ese segundo (franja de borde a borde) y, salvo
 *  `{ scroll: false }`, lleva la vista hasta él. */
export function scrollToMoment(container, seconds, { scroll = true } = {}) {
  const blocks = [...container.querySelectorAll(".ra-tb[data-start]")];
  const target = blocks.findLast((b) => Number(b.dataset.start) <= seconds) || blocks[0];
  if (!target) return;
  target.classList.add("is-hit");
  if (scroll) target.scrollIntoView({ block: "center" });
}
