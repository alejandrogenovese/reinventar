// Fichas navegables: charla → speaker → empresa → otras charlas, y resultados de personas/empresas para Buscar.
import { Itinerary, Knowledge } from "./api.js";
import { People, SessionMiniCard } from "./itinerary.js";
import { Button, StatusPill, h, toast } from "./ui.js";

const section = (title, ...children) => h("section", { class: "stack" }, h("h2", { class: "label" }, title), ...children);
const chips = (items) => (items?.length ? h("div", { class: "ra-chips" }, items.map((t) => h("span", { class: "ra-chip" }, t))) : null);
// Solo links https: los perfiles vienen de una fuente externa y no se confía en el esquema.
const safeUrl = (url) => (typeof url === "string" && url.startsWith("https://") ? url : null);
const external = (label, url) => (safeUrl(url) ? h("a", { class: "ra-link", href: url, target: "_blank", rel: "noopener noreferrer" }, label) : null);
const period = (from, to) => [from, to || "hoy"].filter(Boolean).join(" – ");
const addToItinerary = (code) => async () => {
  try { await Itinerary.add(code); toast("Agregada al itinerario."); } catch (e) { toast(e.message); }
};
const cardList = (talks) => h("div", { class: "daylist" }, talks.map((s) => SessionMiniCard(s, { onAdd: addToItinerary(s.code) })));

function PersonLink(p, extra) {
  const where = [p.title, p.company].filter(Boolean).join(" · ");
  return h("li", {},
    h("a", { class: "ra-link", href: `#/speaker/${p.id}` }, h("strong", {}, p.name)),
    where ? ` — ${where}` : "",
    extra ? h("span", { class: "caption" }, ` ${extra}`) : "");
}

// --- charla ------------------------------------------------------------------
export async function viewCharla(view, base) {
  const s = await Knowledge.speech(base);
  view.append(h("div", { class: "stack-lg" },
    h("div", { class: "stack" },
      h("span", { class: "ra-kind" }, [s.type, s.level ? `Nivel ${s.level}` : null, s.base].filter(Boolean).join(" · ")),
      h("h1", { class: "title" }, s.title),
      s.newlaunch ? h("span", { class: "ra-chip" }, "Nuevo lanzamiento") : null,
      chips([...(s.topic || []), ...(s.aoi || [])])),
    section("Horarios", h("ul", { class: "ra-people" }, s.instances.map((i) => h("li", { class: "actions", style: { alignItems: "center", justifyContent: "space-between" } },
      h("span", {}, h("strong", {}, `${i.day} · ${i.start}`), ` — ${[i.venue?.hotel, i.venue?.detail].filter(Boolean).join(" · ")}`),
      Button("Agregar", { onclick: addToItinerary(i.code) }))))),
    section("Quién la da", People(s) || h("p", { class: "caption" }, "Sin speakers cargados.")),
    s.abstract ? section("De qué se trata", h("p", {}, s.abstract)) : null,
    s.services?.length ? section("Servicios de AWS", chips(s.services)) : null,
    s.recordings?.length ? section("Tus grabaciones", h("ul", { class: "ra-people" }, s.recordings.map((r) =>
      h("li", { class: "actions", style: { alignItems: "center" } }, h("a", { class: "ra-link", href: `#/s/${r.id}` }, r.title), StatusPill(r.status))))) : null,
    s.related.length ? section("Charlas relacionadas", cardList(s.related)) : null));
}

// --- speaker -----------------------------------------------------------------
function Profile(p) {
  if (!p || !p.found) return h("p", { class: "caption" }, "No encontramos su perfil profesional.");
  const links = [external("LinkedIn", p.linkedin), external("GitHub", p.github),
    p.x ? external("X", `https://x.com/${encodeURIComponent(p.x.replace(/^@/, ""))}`) : null].filter(Boolean);
  return h("div", { class: "stack" },
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
    h("div", { class: "stack" },
      h("h1", { class: "title" }, sp.name),
      h("p", {}, [p.title, company].filter(Boolean).flatMap((x, i) => (i ? [" · ", x] : [x]))),
      sp.company?.sector ? h("span", { class: "caption" }, [sp.company.sector, sp.company.industry].filter(Boolean).join(" › ")) : null),
    Profile(sp.profile),
    section(`Charlas en re:Invent (${sp.talks.length})`, cardList(sp.talks)),
    sp.co_speakers.length ? section("Comparte escenario con", h("ul", { class: "ra-people" }, sp.co_speakers.map((c) => PersonLink(c)))) : null));
}

// --- empresa -----------------------------------------------------------------
export async function viewEmpresa(view, id) {
  const e = await Knowledge.empresa(id);
  const truncated = (shown, total, what) => (total > shown ? h("p", { class: "caption" }, `Mostrando ${shown} de ${total} ${what}.`) : null);
  view.append(h("div", { class: "stack-lg" },
    h("div", { class: "stack" },
      h("h1", { class: "title" }, e.name),
      h("p", { class: "caption" }, [e.sector, e.industry].filter(Boolean).join(" › ") || "Sin clasificar"),
      e.group && e.group !== e.name ? h("p", { class: "caption" }, `Grupo: ${e.group}`) : null),
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
