// Fichas navegables: charla → speaker → empresa → otras charlas, y resultados de personas/empresas para Buscar.
import { Itinerary, Knowledge, Lleno } from "./api.js";
import { BriefingPanel } from "./briefing.js";
import { Abstract, People, SessionMiniCard, forgetItineraryCodes, shortDay } from "./itinerary.js";
import { refreshCountdown } from "./countdown.js";
import { GoThere } from "./location.js";
import { recordTalk } from "./today.js";
import { Button, IconText, StatusPill, Tag, h, toast } from "./ui.js";

const section = (title, ...children) => h("section", { class: "stack" }, h("h2", { class: "label" }, title), ...children);
const chips = (items) => (items?.length ? h("div", { class: "ra-chips" }, items.map(Tag)) : null);
// Solo links https: los perfiles vienen de una fuente externa y no se confía en el esquema.
const safeUrl = (url) => (typeof url === "string" && url.startsWith("https://") ? url : null);
const external = (label, url) => (safeUrl(url) ? h("a", { class: "ra-link", href: url, target: "_blank", rel: "noopener noreferrer" }, label) : null);
const period = (from, to) => [from, to || "hoy"].filter(Boolean).join(" – ");
const addToItinerary = (code) => async () => {
  try {
    const r = await Itinerary.add(code);
    const mine = r.days.flatMap((d) => d.sessions).find((s) => s.code === code);
    toast(mine?.overlaps?.length ? `Agregada y fijada. Ojo: se superpone con ${mine.overlaps.join(", ")}.` : "Agregada y fijada en tu itinerario.");
    void refreshCountdown({ force: true });
  } catch (e) { toast(e.message); return false; }
};
const cardList = (talks) => h("div", { class: "daylist" }, talks.map((s) => SessionMiniCard(s, { onAdd: addToItinerary(s.code) })));

const initials = (name) => (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

/** Encabezado de ficha: avatar con iniciales (speaker/empresa), título y líneas de contexto. */
function EntityHeader(name, ...lines) {
  return h("header", { class: "ra-entity" },
    h("span", { class: "ra-avatar", "aria-hidden": "true" }, initials(name)),
    h("div", { class: "stack" }, h("h1", { class: "title" }, name), ...lines));
}

const live = (r) => r.status === "recording" || r.status === "uploading";

/** Acción principal de la charla: grabarla, o seguir/ver la grabación si ya existe. */
function TalkRecordAction(s) {
  const mine = s.recordings?.[0];
  if (mine) return Button(live(mine) ? "Seguir grabando" : "Ver grabación", { variant: "primary",
    onclick: () => (location.hash = live(mine) ? `#/grabar/${mine.id}` : `#/s/${mine.id}`) });
  const btn = Button("Grabar esta charla", { variant: "primary", onclick: () => recordTalk(s, btn) });
  return btn;
}

/** Horario como tarjeta tocable: riel de hora/día, sede y Agregar. */
const minutes = (hhmm) => { const [hh, mm] = hhmm.split(":").map(Number); return hh * 60 + mm; };

/** Lo que tenés ese día y se superpone con este horario (sin contar la misma charla). Duración estimada: 1 h. */
const clashesWith = (i, mine) => mine.filter((m) => m.day === i.day && m.base !== i.base && m.start && i.start
  && minutes(m.start) < minutes(i.start) + 60 && minutes(i.start) < minutes(m.end || m.start) + (m.end ? 0 : 60)).map((m) => m.title);

const ESTADOS_LLENO = { lleno: "Está llena", cola: "Hay mucha cola" };
const personas = (n) => `${n} persona${n === 1 ? "" : "s"}`;

/** Lo que avisó la gente en la puerta: «Llena · 3 personas · hace 5 min». */
function LlenoResumen(a) {
  const partes = [a.lleno ? `Llena según ${personas(a.lleno)}` : null, a.cola ? `mucha cola según ${personas(a.cola)}` : null].filter(Boolean);
  if (!partes.length) return null;
  const hace = a.hace_min ? `hace ${a.hace_min} min` : "recién";
  return h("span", { class: "ra-lleno-dato", role: "status" }, `${partes.join(" · ")} · ${hace}`);
}

/** Pista del catálogo + lo que avisó la gente + botones para avisar (solo mientras la charla está por empezar o en curso). */
function LlenoAvisos(code, a) {
  if (!a) return null;
  const box = h("div", { class: "ra-lleno" });
  const pintar = (x) => {
    const botones = x.abierto ? h("div", { class: "ra-lleno-avisar" }, h("span", { class: "caption" }, "¿Estás en la puerta?"),
      Object.entries(ESTADOS_LLENO).map(([estado, label]) => {
      const mio = x.mio === estado;
      const btn = h("button", { type: "button", class: mio ? "ra-chip ra-chip-on" : "ra-chip", "aria-pressed": String(mio), onclick: async () => {
        btn.disabled = true;
        try { pintar(mio ? await Lleno.retirar(code) : await Lleno.avisar(code, estado)); if (!mio) toast("Gracias: le avisamos al resto."); }
        catch (e) { toast(e.message); btn.disabled = false; }
      } }, label);
      return btn;
    })) : null;
    box.replaceChildren(...[x.pista ? h("span", { class: "caption" }, x.pista) : null, LlenoResumen(x), botones].filter(Boolean));
  };
  pintar(a);
  return box;
}

/** Un horario de la charla: si está en tu itinerario, con qué choca, y "Cambiar a este" si tenés otro horario de la misma. */
function Slot(i, mine, onChange, aviso) {
  const own = mine.find((m) => m.code === i.code);
  const other = mine.find((m) => m.base === i.base && m.code !== i.code);
  const clashes = clashesWith(i, mine);
  const swap = async () => {
    try { await Itinerary.swap(other.code, i.code); toast("Listo: cambiaste al nuevo horario."); void refreshCountdown({ force: true }); onChange(); }
    catch (err) { toast(err.message); }
  };
  const remove = async () => {
    try { await Itinerary.remove(i.code); toast("Quitada del itinerario."); forgetItineraryCodes(); void refreshCountdown({ force: true }); onChange(); }
    catch (err) { toast(err.message); }
  };
  let action;
  if (own) action = h("div", { class: "actions" },
    own.locked ? IconText("fijar", "En tu itinerario", { className: "ra-tag is-new ra-icotext", size: 14 })
      : h("span", { class: "ra-tag is-new" }, "En tu itinerario"),
    Button("Quitar", { onclick: remove, "aria-label": `Quitar el horario ${shortDay(i.day)} ${i.start} del itinerario` }));
  else if (other) action = Button("Cambiar a este", { onclick: swap, "aria-label": `Cambiar al horario ${shortDay(i.day)} ${i.start}` });
  else action = Button("Agregar", { onclick: async () => { await addToItinerary(i.code)(); onChange(); }, "aria-label": `Agregar el horario ${shortDay(i.day)} ${i.start} al itinerario` });
  return h("li", { class: "ra-slot" },
    h("div", { class: "ra-rail" }, h("span", { class: "ra-rail-time" }, i.start || "—"), h("span", { class: "ra-rail-day" }, shortDay(i.day))),
    h("div", { class: "ra-slot-body" },
      h("span", {}, [i.venue?.hotel, i.venue?.detail].filter(Boolean).join(" · ") || "Sede a confirmar"),
      i.code !== i.base ? h("span", { class: "caption" }, i.code) : null,
      !own && clashes.length ? IconText("alerta", `choca con ${clashes.join(", ")}`, { className: "caption ra-icotext" }) : null,
      GoThere(i.venue?.lat != null ? { lat: i.venue.lat, lng: i.venue.lng, name: i.venue.hotel } : null)),
    action,
    LlenoAvisos(i.code, aviso));
}

function PersonLink(p, extra) {
  const where = [p.title, p.company].filter(Boolean).join(" · ");
  return h("li", {},
    h("a", { class: "ra-link", href: `#/speaker/${p.id}` }, h("strong", {}, p.name)),
    where ? ` — ${where}` : "",
    extra ? h("span", { class: "caption" }, ` ${extra}`) : "");
}

// --- charla ------------------------------------------------------------------
export async function viewCharla(view, base) {
  const [s, current] = await Promise.all([Knowledge.speech(base), Itinerary.get().catch(() => ({ days: [] }))]);
  const mine = current.days.flatMap((d) => d.sessions);
  // Si falla (sin conexión), la ficha se muestra igual, sin avisos de lleno.
  const avisos = s.instances.length ? await Lleno.estado(s.instances.map((i) => i.code)).catch(() => ({})) : {};
  const rerender = () => { view.replaceChildren(); void viewCharla(view, base); };
  view.append(h("div", { class: "stack-lg" },
    h("header", { class: "stack" },
      h("span", { class: "ra-kind" }, [s.type, s.level ? `Nivel ${s.level}` : null, s.base].filter(Boolean).join(" · ")),
      h("h1", { class: "title" }, s.title),
      s.newlaunch || s.topic?.length || s.aoi?.length ? h("div", { class: "ra-chips" },
        s.newlaunch ? h("span", { class: "ra-tag is-new" }, "Nuevo lanzamiento") : null,
        [...(s.topic || []), ...(s.aoi || [])].map(Tag)) : null,
      h("div", { class: "actions" }, TalkRecordAction(s))),
    s.abstract || s.abstract_es ? section("De qué se trata", Abstract(s, { fold: false, className: "ra-prose" })) : null,
    section("Quién la da", People(s) || h("p", { class: "caption" }, "Sin speakers cargados.")),
    s.instances.length ? section(s.instances.length === 1 ? "Horario" : "Otros horarios", h("ul", { class: "ra-slots" }, s.instances.map((i) => Slot(i, mine, rerender, avisos[i.code])))) : null,
    s.concepts?.length ? section("Conceptos", chips(s.concepts)) : null,
    s.services?.length ? section("Servicios de AWS", chips(s.services)) : null,
    s.tech?.length ? section("Otras tecnologías", chips(s.tech)) : null,
    s.recordings?.length ? section("Tus grabaciones", h("ul", { class: "ra-people" }, s.recordings.map((r) =>
      h("li", { class: "actions is-center" }, h("a", { class: "ra-link", href: `#/s/${r.id}` }, r.title), StatusPill(r.status))))) : null,
    s.related.length ? section("Charlas relacionadas", cardList(s.related)) : null));
}

// --- speaker -----------------------------------------------------------------
function Profile(p) {
  if (!p || !p.found) return h("p", { class: "caption" }, "No encontramos su perfil profesional.");
  const links = [external("LinkedIn", p.linkedin), external("GitHub", p.github),
    p.x ? external("X", `https://x.com/${encodeURIComponent(p.x.replace(/^@/, ""))}`) : null].filter(Boolean);
  return h("div", { class: "stack" },
    p.unverified ? h("p", { class: "ra-disclaimer", role: "note" },
      "Puede no ser esta persona: el perfil se encontró por nombre y empresa, pero no lo pudimos confirmar.") : null,
    p.headline && !p.headline.startsWith(p.title || "\u0000") ? h("p", {}, p.headline) : null,
    h("p", { class: "caption" }, [p.seniority, p.location, p.since ? `en el cargo desde ${p.since.slice(0, 7)}` : null].filter(Boolean).join(" · ")),
    links.length ? h("div", { class: "actions" }, links) : null,
    p.experience.length ? section("Trayectoria", h("ul", { class: "ra-people" }, p.experience.map((x) =>
      h("li", {}, h("strong", {}, x.cargo || "—"), x.empresa ? ` · ${x.empresa}` : "", h("span", { class: "caption" }, ` (${period(x.desde, x.hasta)})`))))) : null,
    p.education.length ? section("Educación", h("ul", { class: "ra-people" }, p.education.map((e) =>
      h("li", {}, [e.titulo, e.area].filter(Boolean).join(" — ") || "—", e.institucion ? h("span", { class: "caption" }, ` · ${e.institucion}`) : "")))) : null,
    p.skills.length ? section("Skills", chips(p.skills.slice(0, 15))) : null,
    h("p", { class: "caption" }, `Fuente: ${p.source || "—"}${p.consulted ? ` (${p.consulted})` : ""}${p.match ? ` · coincidencia: ${p.match}` : ""}`));
}

export async function viewSpeaker(view, id) {
  const sp = await Knowledge.speaker(id);
  const p = sp.profile || {};
  const company = sp.company?.id ? h("a", { class: "ra-link", href: `#/empresa/${sp.company.id}` }, sp.company.name) : sp.company?.name;
  view.append(h("div", { class: "stack-lg" },
    EntityHeader(sp.name,
      h("p", {}, [p.title, company].filter(Boolean).flatMap((x, i) => (i ? [" · ", x] : [x]))),
      sp.company?.sector ? h("span", { class: "caption" }, [sp.company.sector, sp.company.industry].filter(Boolean).join(" › ")) : null),
    BriefingPanel("speaker", sp.id, sp.talks.map((t) => t.base)),
    Profile(sp.profile),
    section(`Charlas en re:Invent (${sp.talks.length})`, cardList(sp.talks)),
    sp.co_speakers.length ? section("Comparte escenario con", h("ul", { class: "ra-people" }, sp.co_speakers.map((c) => PersonLink(c)))) : null));
}

// --- empresa -----------------------------------------------------------------
export async function viewEmpresa(view, id) {
  const e = await Knowledge.empresa(id);
  const truncated = (shown, total, what) => (total > shown ? h("p", { class: "caption" }, `Mostrando ${shown} de ${total} ${what}.`) : null);
  view.append(h("div", { class: "stack-lg" },
    EntityHeader(e.name,
      h("p", { class: "caption" }, [e.sector, e.industry].filter(Boolean).join(" › ") || "Sin clasificar"),
      e.group && e.group !== e.name ? h("p", { class: "caption" }, `Grupo: ${e.group}`) : null),
    BriefingPanel("empresa", e.id, e.talks.map((t) => t.base)),
    section(`Quiénes vienen (${e.people_total})`,
      h("ul", { class: "ra-people" }, e.people.map((p) => PersonLink(p, `· ${p.talks} charla${p.talks === 1 ? "" : "s"}`))),
      truncated(e.people.length, e.people_total, "personas")),
    section(`Charlas (${e.talks_total})`, cardList(e.talks), truncated(e.talks.length, e.talks_total, "charlas"))));
}

// --- personas y empresas en Buscar -------------------------------------------
/** Bloque con las personas y empresas que coinciden con q (vacío si no hay o si q es muy corto). */
export async function EntityResults(q) {
  if (q.trim().length < 2) return h("div");
  const { speakers, companies } = await Knowledge.searchEntities(q.trim());
  if (!speakers.length && !companies.length) return h("div");
  const count = (n) => `${n} charla${n === 1 ? "" : "s"}`;
  return h("div", { class: "stack" },
    companies.length ? section("Empresas", h("ul", { class: "ra-people" }, companies.map((c) => h("li", {},
      h("a", { class: "ra-link", href: `#/empresa/${c.id}` }, h("strong", {}, c.name)),
      h("span", { class: "caption" }, ` · ${[c.sector, count(c.talks)].filter(Boolean).join(" · ")}`))))) : null,
    speakers.length ? section("Personas", h("ul", { class: "ra-people" }, speakers.map((p) => PersonLink(p, `· ${count(p.talks)}`)))) : null);
}
