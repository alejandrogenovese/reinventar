// Cuestionario de perfil + itinerario con mapa (la búsqueda manual vive en Explorar).
import { Catalog, Itinerary } from "./api.js";
import { renderMap } from "./map.js";
import { Button, Tag, h, toast, toastOnError, withUndo } from "./ui.js";

const INTEREST_TOPICS_LIMIT = 14;
const EXPERIENCE_OPTIONS = ["", "Junior", "Mid", "Senior", "Lead / Staff"];

const PEOPLE_LIMIT = 4;

// Speakers con cargo y empresa (de la base); si la sesión no tiene speakers cargados, el texto original del catálogo.
export function People(s) {
  const people = s.people || [];
  if (!people.length) return s.speakers ? h("p", { class: "caption" }, s.speakers) : null;
  const line = (p) => h("li", {},
    h("a", { class: "ra-link", href: `#/speaker/${p.id}` }, h("strong", {}, p.name)),
    p.title ? ` — ${p.title}` : "",
    p.company ? [" · ", p.company_id ? h("a", { class: "ra-link", href: `#/empresa/${p.company_id}` }, p.company) : p.company] : "",
    p.sector && !p.is_amazon ? h("span", { class: "caption" }, ` (${p.sector})`) : "");
  const extra = people.length - PEOPLE_LIMIT;
  return h("ul", { class: "ra-people" }, people.slice(0, PEOPLE_LIMIT).map(line), extra > 0 ? h("li", { class: "caption" }, `y ${extra} más`) : null);
}

const ABSTRACT_FOLD = 220; // más largo que esto se pliega a 3 líneas con "Leer más"

export const shortDay = (iso) => (iso
  ? new Date(`${iso}T12:00:00`).toLocaleDateString("es-AR", { weekday: "short", day: "numeric", month: "short" }).replace(/[.,]/g, "")
  : "");

/** Abstract plegado a 3 líneas; el botón lo despliega (aria-expanded para el lector de pantalla). */
function Abstract(text) {
  const p = h("p", { class: "ra-abstract" }, text);
  if (text.length <= ABSTRACT_FOLD) return p;
  p.classList.add("is-folded");
  const btn = h("button", { type: "button", class: "ra-more", "aria-expanded": "false", onclick: () => {
    const open = p.classList.toggle("is-folded") === false;
    btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? "Leer menos" : "Leer más";
  } }, "Leer más");
  return [p, btn];
}

export function SessionMiniCard(s, { onAdd, onLock, onRemove, locked } = {}) {
  const tags = [...(s.topic || []), ...(s.aoi || [])];
  return h("article", { class: "ra-minicard" },
    h("div", { class: "ra-rail" },
      h("span", { class: "ra-rail-time" }, s.start || "—"),
      h("span", { class: "ra-rail-day" }, shortDay(s.day))),
    h("div", { class: "ra-minicard-body" },
      h("span", { class: "ra-kind" }, [s.type, s.level ? `Nivel ${s.level}` : null, s.base].filter(Boolean).join(" · ")),
      h("h3", { class: "ra-minicard-title" }, h("a", { class: "ra-link", href: `#/charla/${s.base}` }, s.title)),
      h("div", { class: "ra-minicard-meta" }, [s.venue?.hotel, s.venue?.detail].filter(Boolean).join(" · ")),
      tags.length || s.newlaunch ? h("div", { class: "ra-chips" },
        s.newlaunch ? h("span", { class: "ra-tag is-new" }, "Nuevo lanzamiento") : null,
        tags.slice(0, 6).map(Tag)) : null,
      People(s),
      s.abstract ? Abstract(s.abstract) : null,
      s.reason ? h("p", { class: "caption" }, s.reason) : null,
      h("div", { class: "actions" },
        onAdd ? Button("Agregar", { onclick: onAdd }) : null,
        onLock ? Button(locked ? "Desbloquear" : "Bloquear", { onclick: onLock }) : null,
        onRemove ? Button("Quitar", { variant: "danger", onclick: onRemove }) : null)));
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
        h("div", { class: "actions" },
          Button("Armar itinerario", { variant: "primary", onclick: () => (location.hash = "#/itinerario/cuestionario") }),
          Button("Buscar sesiones", { onclick: () => (location.hash = "#/buscar") }))));
      return;
    }

    let dayIndex = 0;
    const mapEl = h("div", { class: "mapbox" });
    const tabs = h("div", { class: "tabs", role: "tablist" });
    const list = h("div", { class: "daylist" });
    const dayHeading = h("h2", { class: "sr-only" }); // título para el lector de pantalla: las pestañas no son encabezados
    view.append(h("div", { class: "stack-lg" },
      h("h1", { class: "title" }, "Tu itinerario"),
      h("div", { class: "actions" },
        Button("Rehacer cuestionario", { onclick: () => (location.hash = "#/itinerario/cuestionario") }),
        Button("Buscar sesiones", { onclick: () => (location.hash = "#/buscar") })),
      data.notes ? h("p", { class: "caption" }, data.notes) : null,
      mapEl, tabs, dayHeading, list,
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
      dayHeading.textContent = day ? `Charlas del ${day.day}` : "";
      list.replaceChildren(...(day?.sessions || []).map((s) => {
        const card = SessionMiniCard(s, {
          locked: s.locked,
          onLock: () => toastOnError(Itinerary.lock(s.code, !s.locked).then(paint)),
          onRemove: () => withUndo("Sesión quitada del itinerario.", {
            apply: () => { card.hidden = true; },
            commit: () => Itinerary.remove(s.code).catch((err) => { card.hidden = false; toast(err.message); }),
            undo: () => { card.hidden = false; },
          }),
        });
        return card;
      }));
    }
    paintTabs();
    paintList();
  }
  await paint();
}
