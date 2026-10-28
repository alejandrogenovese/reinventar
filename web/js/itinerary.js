// Cuestionario de perfil + itinerario con mapa + exploración manual del catálogo.
import { Catalog, Itinerary } from "./api.js";
import { renderMap } from "./map.js";
import { Button, h, toast } from "./ui.js";

const INTEREST_TOPICS_LIMIT = 14;
const EXPERIENCE_OPTIONS = ["", "Junior", "Mid", "Senior", "Lead / Staff"];

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function SessionMiniCard(s, { onAdd, onLock, onRemove, locked } = {}) {
  const hotel = s.venue?.hotel || "";
  const tags = [...(s.topic || []), ...(s.aoi || [])];
  return h("div", { class: "ra-minicard" },
    h("div", { class: "ra-minicard-top" },
      h("span", { class: "ra-minicard-time" }, [s.day, s.start].filter(Boolean).join(" · ")),
      h("span", { class: "ra-kind" }, [s.type, s.level ? `Nivel ${s.level}` : null, s.base].filter(Boolean).join(" · "))),
    h("h4", { class: "ra-minicard-title" }, s.title),
    h("div", { class: "ra-minicard-meta" }, [hotel, s.venue?.detail].filter(Boolean).join(" · ")),
    tags.length || s.newlaunch ? h("div", { class: "ra-chips" },
      s.newlaunch ? h("span", { class: "ra-chip" }, "Nuevo lanzamiento") : null,
      tags.slice(0, 6).map((t) => h("span", { class: "ra-chip" }, t))) : null,
    s.speakers ? h("p", { class: "caption" }, s.speakers) : null,
    s.abstract ? h("p", {}, s.abstract) : null,
    s.reason ? h("p", { class: "caption" }, s.reason) : null,
    h("div", { class: "actions" },
      onAdd ? Button("Agregar", { onclick: onAdd }) : null,
      onLock ? Button(locked ? "Desbloquear" : "Bloquear", { onclick: onLock }) : null,
      onRemove ? Button("Quitar", { variant: "danger", onclick: onRemove }) : null));
}

export async function viewCuestionario(view) {
  const [meta, profile] = await Promise.all([Catalog.meta(), Itinerary.profile()]);
  const topics = meta.topics.slice(0, INTEREST_TOPICS_LIMIT);
  const chosen = new Set(profile.interests || []);

  const chips = topics.map((t, i) => {
    const id = `int${i}`;
    return [
      h("input", { type: "checkbox", id, checked: chosen.has(t.value), onchange: (e) => (e.target.checked ? chosen.add(t.value) : chosen.delete(t.value)) }),
      h("label", { for: id }, t.value),
    ];
  });

  const promptInput = h("textarea", { id: "prompt", name: "prompt", rows: "3", maxlength: "2000", placeholder: "Ej: me interesa gobierno de datos, lakehouse y agentic AI aplicado a banca." });
  promptInput.value = profile.prompt || "";

  const form = h("form", { class: "stack-lg", onsubmit: async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    btn.textContent = "Armando tu itinerario…";
    try {
      await Itinerary.generate(
        { role: fd.get("role").trim(), experience: fd.get("experience"), interests: [...chosen] },
        promptInput.value.trim(),
      );
      location.hash = "#/itinerario";
    } catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Generar itinerario"; }
  } },
    h("h1", { class: "title" }, "Armá tu itinerario"),
    h("p", { class: "caption" }, "Contanos quién sos y qué te interesa: la IA te recomienda sesiones y te arma una agenda por día."),
    h("div", { class: "field" }, h("label", { class: "label", for: "role" }, "Tu rol"),
      h("input", { id: "role", name: "role", maxlength: "200", placeholder: "Architect Lead de Arquitectura de Datos", value: profile.role || "" })),
    h("div", { class: "field" }, h("label", { class: "label" }, "Experiencia"),
      h("select", { name: "experience" },
        EXPERIENCE_OPTIONS.map((x) => h("option", { value: x, selected: x === (profile.experience || "") }, x || "Elegí una opción")))),
    h("div", { class: "field" }, h("label", { class: "label" }, "Intereses"), h("div", { class: "chipgroup" }, chips)),
    h("div", { class: "field" }, h("label", { class: "label", for: "prompt" }, "Contanos más (opcional)"), promptInput),
    h("div", { class: "actions" }, h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Generar itinerario")));
  view.replaceChildren(form);
}

export async function viewItinerario(view) {
  async function paint() {
    const data = await Itinerary.get();
    view.replaceChildren();
    if (!data.days.length) {
      view.append(h("div", { class: "stack-lg" },
        h("div", { class: "empty" },
          h("p", {}, "Todavía no armaste tu itinerario."),
          h("p", { class: "caption" }, "Contestá un par de preguntas y la IA te recomienda sesiones.")),
        h("div", { class: "actions" }, Button("Armar itinerario", { variant: "primary", onclick: () => (location.hash = "#/itinerario/cuestionario") }))));
      return;
    }

    let dayIndex = 0;
    const mapEl = h("div", { class: "mapbox" });
    const tabs = h("div", { class: "tabs", role: "tablist" });
    const list = h("div", { class: "daylist" });
    view.append(h("div", { class: "stack-lg" },
      h("h1", { class: "title" }, "Tu itinerario"),
      h("div", { class: "actions" },
        Button("Rehacer cuestionario", { onclick: () => (location.hash = "#/itinerario/cuestionario") }),
        Button("Buscar sesiones", { onclick: () => (location.hash = "#/itinerario/explorar") })),
      data.notes ? h("p", { class: "caption" }, data.notes) : null,
      mapEl, tabs, list,
      data.skipped?.length ? h("details", { class: "notice" },
        h("summary", { class: "label" }, `${data.skipped.length} sesión${data.skipped.length === 1 ? "" : "es"} no entraron por superposición de horario (tocá para ver cuáles)`),
        h("ul", {}, data.skipped.map((sk) => h("li", { class: "caption" },
          sk.conflict
            ? h("details", {}, h("summary", {}, h("strong", {}, sk.title), ` — ${sk.reason}`), SessionMiniCard(sk.conflict))
            : h("span", {}, h("strong", {}, sk.title), ` — ${sk.reason}`))))) : null));

    renderMap(mapEl, { days: data.days })
      .then((api) => { mapEl._api = api; api.update(dayIndex); })
      .catch((err) => mapEl.replaceChildren(h("p", { class: "caption" }, `No se pudo cargar el mapa: ${err.message}. El itinerario sigue funcionando igual.`)));

    function paintTabs() {
      tabs.replaceChildren(...data.days.map((d, i) =>
        h("button", { class: "ra-tab", role: "tab", "aria-selected": String(i === dayIndex), onclick: () => { dayIndex = i; paintTabs(); paintList(); mapEl._api?.update(dayIndex); } }, d.day)));
    }
    function paintList() {
      const day = data.days[dayIndex];
      list.replaceChildren(...(day?.sessions || []).map((s) => SessionMiniCard(s, {
        locked: s.locked,
        onLock: async () => { await Itinerary.lock(s.code, !s.locked); paint(); },
        onRemove: async () => { if (!confirm("¿Quitar esta sesión del itinerario?")) return; await Itinerary.remove(s.code); paint(); },
      })));
    }
    paintTabs();
    paintList();
  }
  await paint();
}

export async function viewExplorar(view) {
  const meta = await Catalog.meta();
  const qInput = h("input", { placeholder: "Buscar por título o tema…", "aria-label": "Buscar sesiones" });
  const daySelect = h("select", { "aria-label": "Día" },
    h("option", { value: "" }, "Todos los días"),
    meta.dates.map((d) => h("option", { value: d.value }, d.value)));
  const results = h("div", { class: "daylist" });

  async function search() {
    const rows = await Catalog.search({ q: qInput.value.trim(), day: daySelect.value, limit: "40" });
    results.replaceChildren(...(rows.length
      ? rows.map((s) => SessionMiniCard(s, { onAdd: async () => { await Itinerary.add(s.code); toast("Agregada al itinerario."); } }))
      : [h("div", { class: "empty" }, "Sin resultados.")]));
  }
  qInput.addEventListener("input", debounce(search, 300));
  daySelect.addEventListener("change", search);

  view.replaceChildren(h("div", { class: "stack-lg" },
    h("h1", { class: "title" }, "Buscar sesiones"),
    h("div", { class: "field" }, qInput),
    h("div", { class: "field" }, daySelect),
    results));
  await search();
}
