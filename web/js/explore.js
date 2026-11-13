// Buscar › Filtrar: facetas en cualquier orden con conteos en vivo, "agrupar por" y pedido en lenguaje natural.
// Los filtros se eligen en un panel que sube desde abajo ("Ver N charlas"). El estado vive en la URL.
import { Itinerary, Knowledge } from "./api.js";
import { icon } from "./icons.js";
import { SessionMiniCard } from "./itinerary.js";
import { Button, h, toast } from "./ui.js";

const PAGE = 50;
const VALUES_SHOWN = 8;
const SEARCH_DEBOUNCE_MS = 300;
const FACETS = [
  ["tema", "Tema emergente"], ["sector", "Sector"], ["dia", "Día"], ["empresa", "Empresa"], ["topico", "Tópico"],
  ["area", "Área de interés"], ["sede", "Sede"], ["tipo", "Tipo"], ["nivel", "Nivel"], ["servicio", "Servicio de AWS"],
  ["tecnologia", "Tecnología"], ["concepto", "Concepto"], ["enfoque", "Enfoque"],
  ["industria", "Industria"], ["seniority", "Seniority"], ["lanzamiento", "Nuevo lanzamiento"],
];
const LABEL = Object.fromEntries(FACETS);
// Facetas abiertas al abrir el panel: las que más se usan para acotar ("bancos el martes").
const OPEN_BY_DEFAULT = ["sector", "dia"];

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// --- estado <-> URL (#/buscar?sector=Finanzas&sector=Salud&q=...&agrupar=empresa) ----------------
function readState() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const filters = {};
  for (const [facet] of FACETS) {
    const values = params.getAll(facet);
    if (values.length) filters[facet] = new Set(values);
  }
  // open: facetas desplegadas en el panel ("<faceta>") y las que muestran todos sus valores ("<faceta>:all")
  return { q: params.get("q") || "", groupBy: params.get("agrupar") || "", filters, offset: 0, open: new Set(OPEN_BY_DEFAULT) };
}

function writeState(state) {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.groupBy) params.set("agrupar", state.groupBy);
  for (const [facet, values] of Object.entries(state.filters)) for (const v of values) params.append(facet, v);
  const qs = params.toString();
  history.replaceState(null, "", `#/buscar${qs ? `?${qs}` : ""}`);
}

const toggled = (state, facet, value) => {
  const current = new Set(state.filters[facet] || []);
  current.has(value) ? current.delete(value) : current.add(value);
  const filters = { ...state.filters, [facet]: current };
  if (!current.size) delete filters[facet];
  return { ...state, filters, offset: 0 };
};

const activeCount = (state) => Object.values(state.filters).reduce((n, values) => n + values.size, 0);

// --- piezas ------------------------------------------------------------------
const addToItinerary = (code) => async () => {
  try { await Itinerary.add(code); toast("Agregada al itinerario."); } catch (e) { toast(e.message); }
};
const Cards = (rows) => rows.map((s) => SessionMiniCard(s, { onAdd: addToItinerary(s.code) }));

/** Fila de píldoras: los filtros activos (solo el valor; tocarla lo quita) y "Agrupar" como selector. */
function PillRow(state, update) {
  const active = Object.entries(state.filters).flatMap(([facet, values]) => [...values].map((v) => [facet, v]));
  return h("div", { class: "ra-pillrow" },
    active.map(([facet, value]) => h("button", { type: "button", class: "ra-chip ra-chip-on", "aria-label": `Quitar filtro ${LABEL[facet]}: ${value}`,
      title: LABEL[facet], onclick: () => update(toggled(state, facet, value)) }, value)),
    GroupSelect(state, update));
}

function FacetList(state, facets, update) {
  return FACETS.map(([facet, label]) => {
    const values = facets[facet] || [];
    if (!values.length) return null;
    const selected = state.filters[facet] || new Set();
    const expanded = state.open.has(`${facet}:all`);
    const shown = expanded ? values : values.filter((v, i) => i < VALUES_SHOWN || selected.has(v.value));
    const details = h("details", { class: "ra-facetgroup", open: state.open.has(facet) },
      h("summary", { class: "label" }, `${label}${selected.size ? ` · ${selected.size}` : ""}`),
      h("div", { class: "ra-facet" }, shown.map((v) => h("label", { class: "ra-facet-item" },
        h("input", { type: "checkbox", checked: selected.has(v.value), onchange: () => update(toggled(state, facet, v.value)) }),
        h("span", {}, v.value), h("span", { class: "caption" }, String(v.count))))),
      values.length > VALUES_SHOWN ? h("button", { type: "button", class: "ra-more", onclick: () => {
        const open = new Set(state.open);
        expanded ? open.delete(`${facet}:all`) : open.add(`${facet}:all`);
        update({ ...state, open }, { refetch: false });
      } }, expanded ? "Ver menos" : `Ver las ${values.length}`) : null);
    details.addEventListener("toggle", () => (details.open ? state.open.add(facet) : state.open.delete(facet)));
    return details;
  });
}

/** Panel de filtros (bottom sheet en el celular, lateral en la compu). Cada cambio recalcula y el botón dice cuántas quedan. */
function FilterSheet() {
  const body = h("div", { class: "ra-sheet-body" });
  const clear = Button("Limpiar");
  const done = Button("Ver charlas", { variant: "primary" });
  const dlg = h("dialog", { class: "ra-sheet", "aria-labelledby": "sheet-title" },
    h("div", { class: "ra-sheet-head" },
      h("h2", { class: "ra-dialog-title", id: "sheet-title" }, "Filtros"),
      h("button", { type: "button", class: "iconbtn", "aria-label": "Cerrar filtros", onclick: () => dlg.close() }, icon("cerrar", 24))),
    body,
    h("div", { class: "ra-sheet-foot actions" }, clear, done));
  done.addEventListener("click", () => dlg.close());
  // Tocar el fondo oscuro cierra (el click llega al <dialog> mismo, no a su contenido).
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  // Al cerrar, el foco vuelve a quien abrió el panel (teclado y lector de pantalla no pierden el lugar).
  let opener = null;
  dlg.addEventListener("close", () => opener?.focus());
  document.body.append(dlg);

  return {
    showModal: (from) => { opener = from; dlg.showModal(); },
    remove: () => dlg.remove(),
    get isOpen() { return dlg.open; },
    paint(state, last, update) {
      const scroll = body.scrollTop;
      body.replaceChildren(...FacetList(state, last.facets, update).filter(Boolean));
      body.scrollTop = scroll;
      done.textContent = `Ver ${plural(last.total, "charla", "charlas")}`;
      clear.disabled = !activeCount(state);
      clear.onclick = () => update({ ...state, filters: {}, offset: 0 });
    },
  };
}

/** "Agrupar ▾": un <select> nativo con forma de píldora (punteada sin agrupar, llena al agrupar). */
function GroupSelect(state, update) {
  const options = [["", state.groupBy ? "Sin agrupar" : "Agrupar"], ...FACETS];
  return h("span", { class: "ra-pillselect-wrap" }, h("select", { class: `ra-pillselect${state.groupBy ? " is-on" : ""}`,
    "aria-label": "Agrupar por", onchange: (e) => update({ ...state, groupBy: e.target.value }) },
  options.map(([value, label]) => h("option", { value, selected: state.groupBy === value }, label))));
}

/** Filtros dentro del campo de búsqueda: ícono con el número de filtros activos. */
function paintFilterButton(btn, n) {
  btn.setAttribute("aria-label", n ? `Filtros, ${plural(n, "activo", "activos")}` : "Filtros");
  btn.replaceChildren(icon("filtrar", 20), n ? h("span", { class: "ra-badge", "aria-hidden": "true" }, String(n)) : "");
}

function Groups(state, groups, update) {
  return groups.map((g) => h("section", { class: "stack" },
    h("h2", { class: "label" }, `${LABEL[state.groupBy]}: ${g.value} · ${plural(g.count, "charla", "charlas")}`),
    h("div", { class: "daylist" }, Cards(g.results)),
    g.count > g.results.length ? Button(`Ver las ${g.count}`, { onclick: () => update({ ...toggled(state, state.groupBy, g.value), groupBy: "" }) }) : null));
}

// --- panel -------------------------------------------------------------------
/**
 * Modo Filtrar de Buscar. Devuelve { el, syncUrl, dispose }: syncUrl reescribe la URL con los filtros
 * (al volver desde Preguntar) y dispose saca el panel de filtros del <body> al salir de la pantalla.
 */
export async function ExplorePanel() {
  let state = readState();
  let last = null;
  const sheet = FilterSheet();
  const qInput = h("input", { type: "search", value: state.q, maxlength: "300", "aria-label": "Buscar charlas",
    placeholder: "Ej: bancos el martes · Nubank · agentes con Bedrock" });
  // "Convertir en filtros" es una sugerencia (fila tintada) que aparece solo cuando hay algo escrito.
  const nlText = h("span", {});
  const nlButton = h("button", { type: "submit", class: "ra-suggest", hidden: !state.q }, icon("filtrar", 16), nlText);
  const filterBtn = h("button", { type: "button", class: "ra-infield-btn", title: "Filtros", onclick: () => openSheet() });
  const clearBtn = Button("Limpiar", { variant: "ghost", onclick: () => update({ ...state, filters: {}, offset: 0 }) });
  const pills = h("div"), header = h("h2", { class: "caption", "aria-live": "polite" }), results = h("div", { class: "stack-lg" });

  const fetchPage = (s) => Knowledge.explore({
    q: s.q, group_by: s.groupBy || null, limit: PAGE, offset: s.offset,
    filters: Object.fromEntries(Object.entries(s.filters).map(([f, v]) => [f, [...v]])),
  });

  function paintSuggestion() {
    const text = qInput.value.trim();
    nlButton.hidden = !text;
    nlText.replaceChildren("Convertir ", h("b", {}, `«${text}»`), " en filtros");
  }

  function paintHeader() {
    const n = activeCount(state);
    paintFilterButton(filterBtn, n);
    clearBtn.hidden = !n;
    const hint = !last.total && state.q.includes(" ") ? " — probá «Convertir en filtros»: entiende pedidos como «bancos el martes»." : "";
    header.replaceChildren(h("strong", {}, String(last.total)), ` ${last.total === 1 ? "charla" : "charlas"}${hint}`);
  }

  function paint() {
    pills.replaceChildren(PillRow(state, update));
    paintHeader();
    if (sheet.isOpen) sheet.paint(state, last, update);
    if (state.groupBy && last.groups) { results.replaceChildren(...Groups(state, last.groups, update)); return; }
    const more = last.results.length < last.total
      ? Button("Mostrar más", { onclick: async (e) => {
          e.target.disabled = true;
          try {
            const page = await fetchPage({ ...state, offset: last.results.length });
            last = { ...last, results: [...last.results, ...page.results] };
            paint();
          } catch (err) { toast(err.message); e.target.disabled = false; }
        } })
      : "";
    results.replaceChildren(h("div", { class: "daylist" }, Cards(last.results)), more);
  }

  let requestSeq = 0;
  async function update(next, { refetch = true } = {}) {
    state = next;
    writeState(state);
    if (refetch) {
      const seq = ++requestSeq;
      try {
        const page = await fetchPage(state);
        if (seq !== requestSeq) return; // llegó tarde: ya hay un pedido más nuevo (ej. búsqueda en vivo vs. filtros)
        last = page;
      } catch (e) { toast(e.message); return; }
    }
    paint();
  }

  function openSheet() {
    sheet.paint(state, last, update);
    sheet.showModal(filterBtn);
  }

  // Lenguaje natural → filtros: reemplaza los filtros actuales, con Deshacer por si no era lo que querías.
  async function toFilters(e) {
    e.preventDefault();
    const text = qInput.value.trim();
    if (text.length < 2) { toast("Escribí qué buscás, por ejemplo «bancos el martes»."); return; }
    nlButton.disabled = true;
    const before = state;
    try {
      const parsed = await Knowledge.parseFilters(text);
      const filters = Object.fromEntries(Object.entries(parsed.filters).map(([f, v]) => [f, new Set(v)]));
      if (!Object.keys(filters).length && !parsed.q) { toast("No pude traducirlo a filtros: probá con otras palabras o abrí Filtros."); return; }
      qInput.value = parsed.q;
      paintSuggestion();
      await update({ ...state, filters, q: parsed.q, offset: 0 });
      const ignored = parsed.ignored.length ? ` No encontré: ${parsed.ignored.join(", ")}.` : "";
      toast(`Filtros aplicados.${ignored}`, { action: { label: "Deshacer", onClick: () => { qInput.value = before.q; paintSuggestion(); void update(before); } } });
    } catch (err) { toast(err.message); } finally { nlButton.disabled = false; }
  }

  const search = debounce(() => update({ ...state, q: qInput.value.trim(), offset: 0 }), SEARCH_DEBOUNCE_MS);
  qInput.addEventListener("input", () => { paintSuggestion(); search(); });

  const el = h("div", { class: "ra-explore" },
    h("form", { class: "ra-searchbar", role: "search", onsubmit: toFilters },
      h("div", { class: "ra-searchfield" }, icon("buscar", 20), qInput, filterBtn),
      nlButton),
    pills, h("div", { class: "ra-count" }, header, clearBtn), results);

  // Primera carga sin try: si la sesión venció, el router lo atrapa y manda al login.
  paintSuggestion();
  last = await fetchPage(state);
  writeState(state);
  paint();
  return { el, syncUrl: () => writeState(state), dispose: () => sheet.remove() };
}
