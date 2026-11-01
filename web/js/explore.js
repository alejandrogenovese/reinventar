// Explorar por facetas: filtros en cualquier orden, conteos en vivo y "agrupar por". El estado vive en la URL.
import { Itinerary, Knowledge } from "./api.js";
import { SessionMiniCard } from "./itinerary.js";
import { Button, h, toast } from "./ui.js";

const PAGE = 50;
const VALUES_SHOWN = 8;
const FACETS = [
  ["sector", "Sector"], ["empresa", "Empresa"], ["topico", "Tópico"], ["area", "Área de interés"],
  ["dia", "Día"], ["sede", "Sede"], ["tipo", "Tipo"], ["nivel", "Nivel"], ["servicio", "Servicio de AWS"],
  ["industria", "Industria"], ["seniority", "Seniority"], ["lanzamiento", "Nuevo lanzamiento"],
];
const LABEL = Object.fromEntries(FACETS);

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// --- estado <-> URL (#/explorar?sector=Finanzas&sector=Salud&q=...&agrupar=empresa) ------------
function readState() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const filters = {};
  for (const [facet] of FACETS) {
    const values = params.getAll(facet);
    if (values.length) filters[facet] = new Set(values);
  }
  // open: desplegables abiertos ("panel" = el bloque Filtros; "<faceta>" y "<faceta>:all" = ver todos sus valores)
  return { q: params.get("q") || "", groupBy: params.get("agrupar") || "", filters, offset: 0, open: new Set(["sector"]) };
}

function writeState(state) {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.groupBy) params.set("agrupar", state.groupBy);
  for (const [facet, values] of Object.entries(state.filters)) for (const v of values) params.append(facet, v);
  const qs = params.toString();
  history.replaceState(null, "", `#/explorar${qs ? `?${qs}` : ""}`);
}

const toggled = (state, facet, value) => {
  const current = new Set(state.filters[facet] || []);
  current.has(value) ? current.delete(value) : current.add(value);
  const filters = { ...state.filters, [facet]: current };
  if (!current.size) delete filters[facet];
  return { ...state, filters, offset: 0 };
};

// --- piezas ------------------------------------------------------------------
const addToItinerary = (code) => async () => {
  try { await Itinerary.add(code); toast("Agregada al itinerario."); } catch (e) { toast(e.message); }
};
const Cards = (rows) => rows.map((s) => SessionMiniCard(s, { onAdd: addToItinerary(s.code) }));

function ActiveChips(state, update) {
  const active = Object.entries(state.filters).flatMap(([facet, values]) => [...values].map((v) => [facet, v]));
  if (!active.length) return null;
  return h("div", { class: "ra-chips" },
    active.map(([facet, value]) => h("button", { type: "button", class: "ra-chip ra-chip-on", "aria-label": `Quitar filtro ${LABEL[facet]}: ${value}`,
      onclick: () => update(toggled(state, facet, value)) }, `${LABEL[facet]}: ${value} ✕`)),
    h("button", { type: "button", class: "ra-chip", onclick: () => update({ ...state, filters: {}, offset: 0 }) }, "Limpiar todo"));
}

function FacetPanel(state, facets, update) {
  const active = Object.values(state.filters).reduce((n, values) => n + values.size, 0);
  const panel = h("details", { class: "ra-filters", open: state.open.has("panel") },
    h("summary", { class: "ra-btn ra-btn-secondary" }, active ? `Filtros · ${active} activo${active === 1 ? "" : "s"}` : "Filtros"),
    h("div", { class: "stack" }, FacetList(state, facets, update)));
  panel.addEventListener("toggle", () => (panel.open ? state.open.add("panel") : state.open.delete("panel")));
  return panel;
}

function FacetList(state, facets, update) {
  return FACETS.map(([facet, label]) => {
    const values = facets[facet] || [];
    if (!values.length) return null;
    const selected = state.filters[facet] || new Set();
    const expanded = state.open.has(`${facet}:all`);
    const shown = expanded ? values : values.filter((v, i) => i < VALUES_SHOWN || selected.has(v.value));
    const details = h("details", { class: "notice", open: state.open.has(facet) },
      h("summary", { class: "label" }, `${label}${selected.size ? ` · ${selected.size}` : ""}`),
      h("div", { class: "ra-facet" }, shown.map((v) => h("label", { class: "ra-facet-item" },
        h("input", { type: "checkbox", checked: selected.has(v.value), onchange: () => update(toggled(state, facet, v.value)) }),
        h("span", {}, v.value), h("span", { class: "caption" }, String(v.count))))),
      values.length > VALUES_SHOWN ? Button(expanded ? "Ver menos" : `Ver las ${values.length}`, { onclick: () => {
        const open = new Set(state.open);
        expanded ? open.delete(`${facet}:all`) : open.add(`${facet}:all`);
        update({ ...state, open }, { refetch: false });
      } }) : null);
    details.addEventListener("toggle", () => (details.open ? state.open.add(facet) : state.open.delete(facet)));
    return details;
  });
}

function Groups(state, groups, update) {
  return groups.map((g) => h("section", { class: "stack" },
    h("h2", { class: "label" }, `${LABEL[state.groupBy]}: ${g.value} · ${g.count} charla${g.count === 1 ? "" : "s"}`),
    h("div", { class: "daylist" }, Cards(g.results)),
    g.count > g.results.length ? Button(`Ver las ${g.count}`, { onclick: () => update({ ...toggled(state, state.groupBy, g.value), groupBy: "" }) }) : null));
}

// --- vista -------------------------------------------------------------------
export async function viewExplore(view) {
  let state = readState();
  let last = null;
  const qInput = h("input", { value: state.q, placeholder: "Texto libre: título, tema, persona o empresa…", "aria-label": "Buscar" });
  const groupSelect = h("select", { "aria-label": "Agrupar por" },
    h("option", { value: "" }, "Sin agrupar"), FACETS.map(([f, label]) => h("option", { value: f, selected: state.groupBy === f }, `Agrupar por ${label.toLowerCase()}`)));
  const chips = h("div"), panel = h("div"), header = h("p", { class: "caption" }), results = h("div", { class: "stack-lg" });

  const fetchPage = (s) => Knowledge.explore({
    q: s.q, group_by: s.groupBy || null, limit: PAGE, offset: s.offset,
    filters: Object.fromEntries(Object.entries(s.filters).map(([f, v]) => [f, [...v]])),
  });

  function paint() {
    chips.replaceChildren(ActiveChips(state, update) || "");
    panel.replaceChildren(FacetPanel(state, last.facets, update));
    header.textContent = `${last.total} charla${last.total === 1 ? "" : "s"}`;
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

  async function update(next, { refetch = true } = {}) {
    state = next;
    writeState(state);
    if (refetch) {
      try { last = await fetchPage(state); } catch (e) { toast(e.message); return; }
    }
    paint();
  }

  qInput.addEventListener("input", debounce(() => update({ ...state, q: qInput.value.trim(), offset: 0 }), 300));
  groupSelect.addEventListener("change", () => update({ ...state, groupBy: groupSelect.value }));

  view.append(h("div", { class: "stack-lg" },
    h("h1", { class: "title" }, "Explorar"),
    h("p", { class: "caption" }, "Filtrá en el orden que quieras: cada opción muestra cuántas charlas quedan."),
    h("div", { class: "field" }, qInput),
    chips,
    h("div", { class: "ra-explore" }, h("aside", {}, panel), h("div", { class: "stack" }, h("div", { class: "field" }, groupSelect), header, results))));
  // Primera carga sin try: si la sesión venció, el router lo atrapa y manda al login.
  last = await fetchPage(state);
  writeState(state);
  paint();
}
