// Menú de acciones "⋯" (patrón menu button de WAI-ARIA): el botón dice si está abierto (aria-expanded), las flechas
// recorren las opciones, Escape cierra y devuelve el foco al botón, y tocar afuera también cierra.
import { icon } from "./icons.js";
import { h } from "./ui.js";

let menuSeq = 0;

/**
 * @param {{ label: string, items: Array<{ label: string, iconName?: string, danger?: boolean, onSelect: () => void }> }} opts
 * @returns {HTMLElement} el contenedor con el botón y la lista (se cierra solo al elegir).
 */
export function MenuButton({ label, items }) {
  const id = `menu-${++menuSeq}`;
  const trigger = h("button", { type: "button", class: "iconbtn", "aria-label": label, title: label,
    "aria-haspopup": "menu", "aria-expanded": "false", "aria-controls": id }, icon("mas", 24));
  const options = items.map((it) => h("button", { type: "button", role: "menuitem", tabindex: "-1",
    class: `ra-menu-item${it.danger ? " is-danger" : ""}`, onclick: () => { close({ refocus: true }); it.onSelect(); } },
  it.iconName ? icon(it.iconName, 20) : null, h("span", {}, it.label)));
  const list = h("div", { class: "ra-menu", role: "menu", id, "aria-label": label, hidden: true }, options);
  const el = h("div", { class: "ra-menuwrap" }, trigger, list);

  const isOpen = () => trigger.getAttribute("aria-expanded") === "true";
  const focusAt = (i) => options[(i + options.length) % options.length]?.focus();

  function onOutside(e) { if (!el.contains(e.target)) close(); }

  function open(at = 0) {
    trigger.setAttribute("aria-expanded", "true");
    list.hidden = false;
    document.addEventListener("pointerdown", onOutside, true);
    focusAt(at);
  }

  function close({ refocus = false } = {}) {
    if (!isOpen()) return;
    trigger.setAttribute("aria-expanded", "false");
    list.hidden = true;
    document.removeEventListener("pointerdown", onOutside, true);
    if (refocus) trigger.focus();
  }

  trigger.addEventListener("click", () => (isOpen() ? close() : open()));
  trigger.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); open(0); }
    else if (e.key === "ArrowUp") { e.preventDefault(); open(-1); }
  });
  list.addEventListener("keydown", (e) => {
    const i = options.indexOf(document.activeElement);
    const moves = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: -1 };
    if (e.key in moves) { e.preventDefault(); focusAt(moves[e.key]); }
    else if (e.key === "Escape") { e.preventDefault(); close({ refocus: true }); }
    else if (e.key === "Tab") close();
  });
  // Si el foco se va del menú (por ejemplo con el lector de pantalla), se cierra.
  list.addEventListener("focusout", (e) => { if (e.relatedTarget && !el.contains(e.relatedTarget)) close(); });
  el.close = close;
  return el;
}
