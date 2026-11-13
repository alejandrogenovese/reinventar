// Cuestionario de perfil + itinerario con mapa (la búsqueda manual vive en Explorar).
import { Catalog, Guided, Interview, Itinerary } from "./api.js";
import { refreshCountdown } from "./countdown.js";
import { startsAt } from "./location.js";
import { sandboxNow } from "./sandbox.js";
import { EventCard } from "./events.js";
import { renderMap } from "./map.js";
import { MyEventCard } from "./myEvents.js";
import { icon } from "./icons.js";
import { LlenoAvisos, avisosDe, codigosDeCharlas } from "./lleno.js";
import { Button, Hint, IconText, Tag, h, toast, toastOnError, withUndo } from "./ui.js";

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

// Idioma del resumen que eligió la persona ("es" traducido, "en" original); queda guardado en este celular.
const ABSTRACT_LANG = "ra.abstract-lang";
const abstractLang = () => { try { return localStorage.getItem(ABSTRACT_LANG) || "es"; } catch { return "es"; } };
const saveAbstractLang = (lang) => { try { localStorage.setItem(ABSTRACT_LANG, lang); } catch {} };

/** Resumen oficial en castellano o en el inglés original, con botón para cambiar. En las tarjetas (fold) se pliega a
 *  3 líneas con "Leer más" (aria-expanded para el lector de pantalla). Null si la charla no tiene resumen. */
export function Abstract(s, { fold = true, className = "ra-abstract" } = {}) {
  const texts = { es: s.abstract_es, en: s.abstract };
  if (!texts.es && !texts.en) return null;
  let lang = texts[abstractLang()] ? abstractLang() : (texts.en ? "en" : "es");
  const p = h("p", { class: className });
  const canFold = fold && Math.max((texts.es || "").length, (texts.en || "").length) > ABSTRACT_FOLD;
  const more = canFold ? h("button", { type: "button", class: "ra-more", "aria-expanded": "false", onclick: () => {
    const open = p.classList.toggle("is-folded") === false;
    more.setAttribute("aria-expanded", String(open));
    more.textContent = open ? "Leer menos" : "Leer más";
  } }, "Leer más") : null;
  const toggle = texts.es && texts.en ? h("button", { type: "button", class: "ra-more", onclick: () => {
    lang = lang === "es" ? "en" : "es";
    saveAbstractLang(lang);
    render();
  } }) : null;
  function render() {
    p.textContent = texts[lang];
    p.lang = lang === "es" ? "es-AR" : "en";
    if (toggle) toggle.textContent = lang === "es" ? "Ver original en inglés" : "Ver en castellano";
  }
  if (canFold) p.classList.add("is-folded");
  render();
  return [p, more || toggle ? h("div", { class: "ra-abstract-actions" }, more, toggle) : null];
}

/** Fijar: lo fijado queda aunque regeneres el itinerario (antes se llamaba "Bloquear"). */
const PinButton = (pinned, onclick) => Button([icon("fijar", 18), pinned ? "Fijada" : "Fijar"],
  { onclick, "aria-pressed": String(Boolean(pinned)), title: pinned ? "Tocá para soltarla" : "Queda aunque regeneres el itinerario" });

/** Ya terminó (con la hora simulada en modo prueba): para ofrecer "Me la perdí". */
const isOver = (s) => Boolean(s.day && (s.end || s.start)) && startsAt(s.day, s.end || s.start) < sandboxNow();

const minusMinutes = (hhmm, minutes) => {
  const [hh, mm] = hhmm.split(":").map(Number);
  const total = hh * 60 + mm - minutes;
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
};

/** Reservada (con tilde): sin reserva en el portal de AWS hay que hacer la cola 30 min antes (lo usa el armado guiado). */
const BookedButton = (booked, onclick) => Button(booked ? IconText("listo", "Reservada") : "Marcar reservada",
  { onclick, "aria-pressed": String(Boolean(booked)), title: "Si no la tenés reservada, hay que hacer la cola 30 min antes" });

// Códigos que ya están en tu itinerario: se piden una vez por pantalla y se olvidan al agregar o quitar.
let codesPromise = null;
export const itineraryCodes = () => (codesPromise ??= Itinerary.get()
  .then((r) => new Set(r.days.flatMap((d) => d.sessions).map((s) => s.code)))
  .catch(() => new Set()));
export const forgetItineraryCodes = () => { codesPromise = null; };

/** Agregar que confirma: queda en naranja como «Agregada» y otro toque la quita (por si fue sin querer).
 *  `onAdd` hace el agregado y su aviso; devuelve false si falló. */
export function AddButton(code, onAdd) {
  let added = false;
  const btn = Button("Agregar", { onclick: toggle, "aria-pressed": "false" });
  const paint = () => {
    btn.replaceChildren(added ? IconText("listo", "Agregada") : "Agregar");
    btn.classList.toggle("ra-btn-primary", added);
    btn.classList.toggle("ra-btn-secondary", !added);
    btn.setAttribute("aria-pressed", String(added));
    btn.setAttribute("aria-label", added ? "Agregada al itinerario. Tocá para quitarla." : "Agregar al itinerario");
  };
  async function toggle() {
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      if (added) {
        await Itinerary.remove(code);
        added = false;
        toast("Quitada del itinerario.");
        void refreshCountdown({ force: true });
      } else if (await onAdd() !== false) {
        added = true;
      }
      forgetItineraryCodes();
      paint();
    } catch (e) { toast(e.message); }
    finally { btn.disabled = false; }
  }
  if (code) void itineraryCodes().then((codes) => { if (codes.has(code)) { added = true; paint(); } });
  return btn;
}

export function SessionMiniCard(s, { onAdd, onLock, onRemove, onBook, locked, extra } = {}) {
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
      Abstract(s),
      s.reason ? h("p", { class: "caption" }, s.reason) : null,
      s.salir_antes && s.end ? Hint(`Salís a las ${minusMinutes(s.end, s.salir_antes)}, antes de que termine, para llegar a la siguiente.`, { tone: "warn" }) : null,
      s.overlaps?.length ? Hint(`Se superpone con ${s.overlaps.join(", ")}`, { tone: "error" }) : null,
      extra,
      h("div", { class: "actions" },
        onAdd ? AddButton(s.code, onAdd) : null,
        onLock ? PinButton(locked, onLock) : null,
        onBook ? BookedButton(s.reservada, onBook) : null,
        onRemove && isOver(s) ? Button("Me la perdí", { onclick: () => (location.hash = `#/perdida/${encodeURIComponent(s.code)}`) }) : null,
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

/** Pasa el itinerario al calendario del teléfono: compartir el .ics (iPhone/Android lo abren con Calendario) o, si el
 *  navegador no comparte archivos, descargarlo. */
async function exportCalendar() {
  const blob = await Itinerary.calendar();
  const file = new File([blob], "reinvent-itinerario.ics", { type: "text/calendar" });
  if (navigator.canShare?.({ files: [file] })) {
    try { await navigator.share({ files: [file], title: "Itinerario re:Invent" }); return; }
    catch (err) { if (err?.name === "AbortError") return; }
  }
  const url = URL.createObjectURL(file);
  const a = h("a", { href: url, download: file.name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  toast("Listo: abrí el archivo para sumarlo a tu calendario.");
}

/** Importa las reservas del portal de AWS (.ics): quedan en el itinerario fijadas y reservadas (sin cola). */
function importReservations(onDone) {
  const input = h("input", { type: "file", accept: ".ics,text/calendar", hidden: true });
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    input.remove();
    if (!file) return;
    try {
      const r = await Itinerary.importReservations(file);
      const partes = [`${r.importadas.length} reservas importadas`,
        r.cambiadas.length ? `${r.cambiadas.length} cambiadas al horario reservado` : null,
        r.ya_estaban.length ? `${r.ya_estaban.length} ya estaban` : null,
        r.sin_encontrar.length ? `${r.sin_encontrar.length} no son charlas del catálogo` : null];
      toast(partes.filter(Boolean).join(" · ") + ".");
      await onDone();
    } catch (err) { toast(err.message); }
  });
  document.body.append(input);
  input.click();
}

/** Una charla o evento del itinerario con Fijar y Quitar (con deshacer). onChanged vuelve a pintar la vista. */
function ItineraryItem(s, onChanged, lleno) {
  const refresh = () => refreshCountdown({ force: true });
  const onLock = () => toastOnError(Itinerary.lock(s.code, !s.locked).then(() => { void refresh(); return onChanged(); }));
  let card = null;
  const show = (visible) => { card.hidden = !visible; };
  const onBook = () => toastOnError(Guided.booked(s.code, !s.reservada).then(() => onChanged()));
  const removed = { event: "Evento quitado del itinerario.", mine: "Evento borrado." }[s.kind] || "Sesión quitada del itinerario.";
  const onRemove = () => withUndo(removed, {
    apply: () => show(false),
    commit: () => Itinerary.remove(s.code).then(refresh).catch((err) => { show(true); toast(err.message); }),
    undo: () => show(true),
  });
  const quitar = Button("Quitar", { variant: "danger", onclick: onRemove });
  if (s.kind === "mine") card = MyEventCard(s, [quitar]);
  else if (s.kind === "event") card = EventCard(s, { actions: [PinButton(s.locked, onLock), quitar] });
  else card = SessionMiniCard(s, { locked: s.locked, onLock, onRemove, onBook, extra: lleno });
  return card;
}

/** Entrada a «Tu re:Invent en números» (horas, choques, caminata y el catálogo en gráficos). */
const NumerosLink = (href = "#/itinerario/numeros", text = "Tu semana en números") =>
  h("a", { class: "ra-btn ra-btn-ghost ra-sec-action", href }, h("span", {}, text), icon("seguir", 16));

export async function viewItinerario(view) {
  async function paint() {
    const data = await Itinerary.get();
    view.replaceChildren();
    if (!data.days.length) {
      view.append(h("div", { class: "stack-lg" },
        h("div", { class: "empty" },
          h("p", {}, "Todavía no armaste tu itinerario."),
          h("p", { class: "caption" }, "Te conocemos y armamos cada día charla por charla, o lo armamos rápido con un par de preguntas.")),
        h("div", { class: "actions" },
          Button("Armar itinerario", { variant: "primary", onclick: () => (location.hash = "#/itinerario/nuevo") }),
          Button("Buscar sesiones", { onclick: () => (location.hash = "#/buscar") })),
        NumerosLink("#/itinerario/numeros?modo=catalogo", "El catálogo en números")));
      return;
    }

    let dayIndex = 0;
    const mapEl = h("div", { class: "mapbox" });
    const tabs = h("div", { class: "tabs", role: "tablist" });
    const list = h("div", { class: "daylist" });
    const dayHeading = h("h2", { class: "sr-only" }); // título para el lector de pantalla: las pestañas no son encabezados
    view.append(h("div", { class: "stack-lg" },
      h("div", { class: "ra-sec-head" }, h("h1", { class: "title" }, "Tu itinerario"), NumerosLink()),
      h("div", { class: "actions" },
        Button("Armar día por día", { variant: "primary", onclick: () => (location.hash = "#/itinerario/armar") }),
        Button("Otras formas de armarlo", { onclick: () => (location.hash = "#/itinerario/nuevo") }),
        Button(IconText("agregar", "Mi evento"), { onclick: () => (location.hash = "#/mi-evento/nuevo") }),
        Button("Pasar a mi calendario", { onclick: () => toastOnError(exportCalendar()) }),
        Button("Importar reservas de AWS", { title: "El calendario (.ics) que exportás desde tu agenda del portal de re:Invent", onclick: () => importReservations(paint) }),
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
      dayHeading.textContent = day ? `Tu agenda del ${day.day}` : "";
      const sessions = day?.sessions || [];
      // Los avisos de «llena» llegan después: la lista se pinta ya y cada tarjeta los suma cuando están.
      const lugares = new Map(codigosDeCharlas(sessions).map((code) => [code, h("div", { hidden: true })]));
      list.replaceChildren(...sessions.map((s) => ItineraryItem(s, paint, lugares.get(s.code))));
      void avisosDe([...lugares.keys()]).then((avisos) => lugares.forEach((lugar, code) => {
        const el = LlenoAvisos(code, avisos[code]);
        if (el) lugar.replaceWith(el);
      }));
    }
    paintTabs();
    paintList();
  }
  await paint();
}

/** Entrada: armado guiado (entrevista + día por día, recomendado) o armado rápido (el cuestionario de siempre). */
export async function viewNuevoItinerario(view) {
  const { ficha, faltan } = await Interview.get();
  const empezada = faltan.length < 8;
  const guiado = ficha
    ? [Button("Seguir armando día por día →", { variant: "primary", onclick: () => (location.hash = "#/itinerario/armar") }),
      Button("Ver o editar tu ficha", { onclick: () => (location.hash = "#/itinerario/ficha") }),
      Button("Rehacer la entrevista", { variant: "ghost", onclick: () => (location.hash = "#/itinerario/entrevista") })]
    : [Button(empezada ? "Seguir la entrevista →" : "Empezar →", { variant: "primary", onclick: () => (location.hash = "#/itinerario/entrevista") })];
  view.replaceChildren(h("div", { class: "stack-lg" },
    h("h1", { class: "title" }, "Armá tu itinerario"),
    h("article", { class: "ra-path is-recommended" },
      h("span", { class: "ra-kind" }, "Recomendado · 5 minutos"),
      h("h2", { class: "subtitle" }, "Armado guiado"),
      h("p", {}, "Primero te conocemos: tu rol, tu día a día y tu desafío (podés responder con la voz). Después armamos cada día charla por charla: elegís con qué arrancás y te propongo lo que sigue, avisándote si llegás caminando, si tenés que salir antes o hacer la cola."),
      h("div", { class: "actions" }, guiado)),
    h("article", { class: "ra-path" },
      h("span", { class: "ra-kind" }, "1 minuto"),
      h("h2", { class: "subtitle" }, "Armado rápido"),
      h("p", {}, "Rol, experiencia e intereses, y la IA te arma una agenda completa de una."),
      h("div", { class: "actions" }, Button("Armado rápido", { onclick: () => (location.hash = "#/itinerario/cuestionario") })))));
}
