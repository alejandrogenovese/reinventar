// Buscar: una sola entrada para encontrar charlas, con dos modos — Filtrar (facetas) y Preguntar (chat con citas).
import { AskPanel } from "./ask.js";
import { ExplorePanel } from "./explore.js";
import { h } from "./ui.js";

const MODES = [["filtrar", "Filtrar"], ["preguntar", "Preguntar"]];

const modeFromUrl = () => (new URLSearchParams(location.hash.split("?")[1] || "").get("modo") === "preguntar" ? "preguntar" : "filtrar");

/** Pantalla Buscar. Devuelve la función de limpieza para el router (saca el panel de filtros del <body> y suelta el
 *  campo fijo de Preguntar). */
export async function viewSearch(view) {
  let mode = modeFromUrl();
  const explore = await ExplorePanel();
  let ask = null; // el chat se arma recién la primera vez que se entra a Preguntar
  const slot = h("div");

  const tabs = MODES.map(([value, label]) => h("button", { type: "button", class: "ra-segtab", role: "tab", id: `tab-${value}`,
    "aria-controls": "buscar-panel", onclick: () => show(value) }, label));

  function show(next) {
    mode = next;
    for (const t of tabs) t.setAttribute("aria-selected", String(t.id === `tab-${mode}`));
    if (mode === "preguntar") {
      ask ??= AskPanel();
      slot.replaceChildren(ask);
      ask.attach();
      history.replaceState(null, "", "#/buscar?modo=preguntar");
    } else {
      ask?.detach();
      slot.replaceChildren(explore.el);
      explore.syncUrl();
    }
  }

  view.append(h("div", { class: "ra-search-page" },
    h("h1", { class: "title" }, "Buscar"),
    h("div", { class: "ra-segtabs", role: "tablist", "aria-label": "Modo de búsqueda" }, tabs),
    h("div", { id: "buscar-panel", role: "tabpanel" }, slot)));
  show(mode);
  return () => { explore.dispose(); ask?.detach(); };
}
