// Itinerario › «Tu re:Invent en números»: dos modos, Mi semana (tu agenda: horas, choques, caminata, ficha) y Catálogo
// (cuántas charlas hay por día, hora, tipo, sede y tema). Los datos salen de /api/numeros (agregados en memoria);
// tocar una columna, celda o barra abre Buscar con ese filtro. Gráficos con h() y tokens, sin librerías (charts.js).
import { Numeros } from "./api.js";
import { Bars, Columns, Heatmap, Kpi, Legend, Section, StackBar, dayLong, dayShort, dec, int, pct, searchHref } from "./charts.js";
import { icon } from "./icons.js";
import { Button, Hint, h } from "./ui.js";

const MODES = [["mia", "Mi semana"], ["catalogo", "Catálogo"]];
const TL_FROM = 8 * 60;   // la franja de la semana va de 8 a 22 h
const TL_SPAN = 14 * 60;
const TL_TICKS = [8, 10, 12, 14, 16, 18, 20, 22];
const LEVEL_TONES = { 100: 15, 200: 30, 300: 50, 400: 75, 500: 100 };
const SLOW_HOURS = 3;     // cuántas horas flojas nombra el caption del heatmap

const modeFromUrl = () => (new URLSearchParams(location.hash.split("?")[1] || "").get("modo") === "catalogo" ? "catalogo" : "mia");
const hoursText = (min) => `${Math.floor(min / 60)} h${min % 60 ? ` ${min % 60} min` : ""}`;
const km = (m) => dec(m / 1000);
const range = (dias) => (dias.length > 1 ? `de ${dayShort(dias[0].dia).toLowerCase()} a ${dayShort(dias.at(-1).dia).toLowerCase()}` : dias[0] ? dayLong(dias[0].dia) : "");
const plural = (n, one, many) => `${int(n)} ${n === 1 ? one : many}`;
const pos = (min) => `${(Math.min(Math.max(min - TL_FROM, 0), TL_SPAN) / TL_SPAN) * 100}%`;
const width = (from, to) => `${((Math.min(to, TL_FROM + TL_SPAN) - Math.max(from, TL_FROM)) / TL_SPAN) * 100}%`;

// ---------- Mi semana ----------

function WeekKpis(m) {
  const eventos = m.eventos ? ` · ${plural(m.eventos, "evento", "eventos")}` : "";
  const grabado = m.grabado?.grabaciones
    ? Kpi("Grabaste", int(m.grabado.grabaciones), { note: `${hoursText(Math.round(m.grabado.segundos / 60))} de audio`, wide: true })
    : null;
  return h("div", { class: "ra-kpis" },
    Kpi("En tu agenda", int(m.total), { note: `${plural(m.charlas, "charla", "charlas")} · ${plural(m.keynotes, "keynote", "keynotes")}${eventos}` }),
    Kpi("Horas ocupadas", int(Math.round(m.minutos_ocupados / 60)), { unit: "h", note: range(m.dias) }),
    Kpi("Caminando", km(m.caminata_m), { unit: "km", note: `${hoursText(m.caminata_min)} entre sedes` }),
    Kpi("Choques", int(m.choques), { tone: m.choques ? "err" : "", note: m.no_llegas ? `y ${plural(m.no_llegas, "cambio de sede", "cambios de sede")} a los que no llegás` : "ningún cambio de sede imposible" }),
    grabado);
}

function TimelineRow(d) {
  const lane = h("div", { class: "ra-tl-lane" });
  for (const t of d.tramos) {
    const prev = d.items.find((i) => i.code === t.previa.code);
    if (prev) lane.append(h("span", { class: "ra-tl-walk", style: { left: pos(prev.fin_min), width: width(prev.fin_min, prev.fin_min + Math.min(t.minutos, t.hueco)) } }));
  }
  for (const it of d.items) {
    const cls = ["ra-tl-blk", it.choque ? `is-clash l${it.carril}` : "is-solo", it.keynote && !it.choque ? "is-key" : "",
      it.kind !== "talk" && !it.choque ? "is-event" : "", it.no_llegas ? "is-late" : ""].filter(Boolean).join(" ");
    const aria = `${it.start}–${it.end} ${it.title}${it.choque ? " (choca)" : ""}${it.no_llegas ? " (no llegás)" : ""}`;
    lane.append(h("span", { class: cls, role: "img", "aria-label": aria, title: aria, style: { left: pos(it.inicio_min), width: width(it.inicio_min, it.fin_min) } }));
  }
  return h("div", { class: "ra-tl-row" }, h("span", { class: "ra-tl-day" }, dayShort(d.dia)), lane);
}

function WeekHints(dias) {
  const hints = [];
  for (const d of dias) {
    for (const c of d.choques) hints.push(Hint(`${capitalDay(d.dia)}: ${c.a.title} (${c.a.start}) se pisa con ${c.b.title} (${c.b.start}).`, { tone: "error" }));
    for (const t of d.no_llegas) hints.push(Hint(`${capitalDay(d.dia)} ${t.siguiente.start}: de ${t.desde} a ${t.hasta} son ${t.minutos} min caminando y ${t.hueco ? `tenés ${t.hueco}` : "no hay hueco"}.`, { tone: "warn" }));
  }
  return hints;
}
const capitalDay = (iso) => { const s = dayLong(iso); return s.charAt(0).toUpperCase() + s.slice(1); };

function Timeline(dias) {
  const axis = h("div", { class: "ra-tl-row ra-tl-axis", "aria-hidden": "true" }, h("span"),
    h("div", { class: "ra-tl-ticks" }, TL_TICKS.map((t) => h("span", { style: { left: pos(t * 60) } }, t))));
  return Section("Tu semana", "8 a 22 h",
    h("div", { class: "ra-tl" }, axis, dias.map(TimelineRow)),
    Legend([["is-talk", "Charla"], ["is-key", "Keynote"], ["is-event", "Evento"], ["is-clash", "Choque"], ["is-late", "No llegás"]]),
    WeekHints(dias),
    h("p", { class: "caption" }, "Las duraciones de las charlas son estimadas por tipo: los choques son aproximados."));
}

function Walking(dias) {
  const conCaminata = dias.filter((d) => d.caminata_min);
  if (!conCaminata.length) return Section("Caminata por día", "entre sedes", h("p", { class: "caption" }, "Todo lo que agendaste queda en la misma sede cada día: no hay que cruzar el Strip."));
  const max = Math.max(...conCaminata.map((d) => d.caminata_min));
  const largo = conCaminata.map((d) => ({ dia: d.dia, ...d.tramo_mas_largo })).sort((a, b) => b.minutos - a.minutos)[0];
  return Section("Caminata por día", "entre sedes",
    Bars(conCaminata.map((d) => ({ label: dayShort(d.dia), value: d.caminata_min, max, text: `${d.caminata_min} min · ${km(d.caminata_m)} km` }))),
    h("p", { class: "caption" }, `El tramo más largo es el ${dayLong(largo.dia)}: ${largo.desde} → ${largo.hasta} son ${largo.minutos} min.`));
}

function Ficha(f) {
  if (!f) {
    return Section("Tu ficha vs. tu agenda", null,
      h("p", { class: "caption" }, "Contanos qué buscás y te mostramos cuánto de tu agenda lo cubre."),
      h("a", { class: "ra-btn ra-btn-ghost ra-sec-action", href: "#/itinerario/entrevista" }, h("span", {}, "Hacer la entrevista"), icon("seguir", 16)));
  }
  const max = Math.max(1, f.charlas);
  const hueco = f.prioridades.find((p) => !p.agendadas);
  return Section("Tu ficha vs. tu agenda", null,
    h("p", { class: "caption" }, "Charlas agendadas que tocan cada prioridad de tu ficha (el número chico es el peso, de 1 a 3)."),
    Bars(f.prioridades.map((p) => ({ label: p.tema, value: p.agendadas, max, text: `${p.agendadas} de ${f.charlas}`, gap: !p.agendadas,
      extra: h("span", { class: "ra-weight", "aria-label": `peso ${p.peso}` }, `×${p.peso}`) })), { wide: true }),
    hueco ? Hint(`Pediste «${hueco.tema}» y no agendaste ninguna. Hay ${plural(hueco.en_catalogo, "charla", "charlas")} que lo tocan en el catálogo.`, { tone: "info" }) : null,
    h("a", { class: "ra-btn ra-btn-ghost ra-sec-action", href: "#/itinerario/armar" }, h("span", {}, "Ver las que entran en tus huecos"), icon("seguir", 16)));
}

function Levels(niveles, ficha) {
  const total = niveles.reduce((n, l) => n + l.n, 0);
  if (!total) return null;
  const avanzadas = niveles.filter((l) => Number(l.valor) >= 400).reduce((n, l) => n + l.n, 0);
  const prefer = ficha?.nivel?.length ? ` Tu ficha pide ${ficha.nivel.join(", ")}.` : "";
  return Section("Nivel", plural(total, "charla", "charlas"),
    StackBar(niveles.map((l) => ({ label: l.valor, value: l.n, aria: `Nivel ${l.valor}: ${l.n}`,
      color: `color-mix(in srgb, var(--brand) ${LEVEL_TONES[l.valor] || 50}%, var(--surface-3))` }))),
    h("p", { class: "caption" }, `${pct(avanzadas, total)} % es 400 o 500.${prefer}`));
}

function WeekEmpty(goCatalog) {
  return h("div", { class: "empty" },
    h("p", {}, "Todavía no tenés nada en tu agenda."),
    h("p", { class: "caption" }, "Cuando agregues charlas vas a ver acá tus horas, los choques y cuánto caminás."),
    h("div", { class: "actions ra-center" },
      Button("Armar itinerario", { variant: "primary", onclick: () => (location.hash = "#/itinerario/nuevo") }),
      Button("Ver el catálogo", { onclick: goCatalog })));
}

function Week(m, goCatalog) {
  if (!m.total) return [WeekKpis(m), WeekEmpty(goCatalog)];
  return [WeekKpis(m), Timeline(m.dias), Walking(m.dias), Ficha(m.ficha), Levels(m.niveles, m.ficha)];
}

// ---------- Catálogo ----------

function CatalogKpis(c) {
  const pico = [...c.lanzamientos_por_dia].sort((a, b) => b.n - a.n)[0];
  return h("div", { class: "ra-kpis" },
    Kpi("Charlas", int(c.charlas), { note: `${int(c.horarios)} horarios` }),
    Kpi("Speakers", int(c.speakers), { note: `en ${plural(c.sedes, "sede", "sedes")}` }),
    Kpi("Sin reserva", int(pct(c.walk_up, c.horarios)), { unit: "%", note: `${int(c.walk_up)} horarios walk-up` }),
    Kpi("Lanzamientos", int(c.lanzamientos), { note: pico?.n ? `${int(pico.n)} el ${dayLong(pico.dia)}` : "" }));
}

/** Códigos de día y día|hora de lo que tenés agendado, para marcarlo en las columnas y el heatmap. */
function mineIndex(m) {
  const perDay = Object.fromEntries((m?.dias || []).map((d) => [d.dia, d.items.length]));
  const cells = new Set((m?.dias || []).flatMap((d) => d.items.map((i) => `${d.dia}|${Number(i.start.slice(0, 2))}`)));
  return { perDay, cells };
}

function PerDay(c, mine) {
  const cols = c.por_dia.map((d) => ({ label: dayShort(d.dia), value: d.n, mine: mine.perDay[d.dia] || 0, today: d.dia === c.hoy,
    href: searchHref({ dia: d.dia }), aria: `${dayLong(d.dia)}: ${int(d.n)} horarios, ${int(mine.perDay[d.dia] || 0)} en tu agenda` }));
  const pico = [...c.por_dia].sort((a, b) => b.n - a.n)[0];
  return Section("Charlas por día", "horarios",
    Columns(cols),
    Legend([["is-catalog", "Catálogo"], ["is-mine-text", "Abajo, en naranja: cuántas tenés vos"]]),
    pico ? h("p", { class: "caption" }, `El día con más es el ${dayLong(pico.dia)}: ${int(pico.n)} horarios. Tocá una columna para verlos.`) : null);
}

function slowHours(c) {
  const sums = c.horas.map((hora, i) => [hora, c.dia_hora.reduce((n, d) => n + d.n[i], 0)]).filter(([, n]) => n > 0);
  return sums.sort((a, b) => a[1] - b[1]).slice(0, SLOW_HOURS).map(([hora]) => hora).sort((a, b) => a - b);
}

function Heat(c, mine) {
  const pad = (n) => String(n).padStart(2, "0");
  const rows = c.dia_hora.map((d) => ({ label: dayShort(d.dia), cells: d.n.map((n, i) => {
    const hora = c.horas[i];
    const isMine = mine.cells.has(`${d.dia}|${hora}`);
    return { n, mine: isMine, href: searchHref({ dia: d.dia, hora: `${pad(hora)} h` }),
      aria: `${dayLong(d.dia)} ${hora} h: ${plural(n, "charla", "charlas")}${isMine ? ", tenés algo" : ""}` };
  }) }));
  const max = Math.max(0, ...c.dia_hora.flatMap((d) => d.n));
  const flojas = slowHours(c);
  return Section("Cuándo hay más", "día × hora de inicio",
    Heatmap(c.horas, rows),
    h("div", { class: "ra-legend" }, h("span", { class: "ra-ramp", "aria-hidden": "true" }, "0",
      [0, 35, 70, 100].map((p) => h("span", { class: "ra-ramp-sw", style: { background: p ? `color-mix(in srgb, var(--brand) ${p}%, var(--surface-3))` : "var(--surface-3)" } })),
      int(max)), h("span", {}, h("i", { class: "ra-legend-swatch is-mine-cell", "aria-hidden": "true" }), "Tenés algo")),
    h("p", { class: "caption" }, `Tocá una celda para ver esas charlas.${flojas.length ? ` Las horas más flojas: ${flojas.join(", ")} h. Buenas para caminar o almorzar.` : ""}`));
}

function Breakdown(title, sub, rows, facet, caption) {
  const max = Math.max(0, ...rows.map((r) => r.n));
  return Section(title, sub,
    Bars(rows.map((r) => ({ label: r.valor, value: r.n, max, text: int(r.n), tone: r.otros ? "is-muted" : "",
      href: r.otros ? null : searchHref({ [facet]: r.valor }) }))),
    caption ? h("p", { class: "caption" }, caption) : null);
}

function lastDayCaption(c) {
  const ultimo = c.sede_principal_por_dia.at(-1);
  const total = c.por_dia.at(-1)?.n || 0;
  return ultimo && pct(ultimo.n, total) >= 50 ? `El ${dayLong(ultimo.dia)} casi todo es en ${ultimo.sede} (${int(ultimo.n)} de ${int(total)}).` : null;
}

function Catalog(c, m) {
  const mine = mineIndex(m);
  return [CatalogKpis(c), PerDay(c, mine), Heat(c, mine),
    Breakdown("Por tipo", "charlas", c.por_tipo, "tipo"),
    Breakdown("Por sede", "horarios", c.por_sede, "sede", lastDayCaption(c)),
    Breakdown("Temas", "una charla puede tener varios", c.por_tema, "topico")];
}

// ---------- pantalla ----------

export async function viewNumeros(view) {
  let mode = modeFromUrl();
  const body = h("div", { class: "stack-lg" });
  const tabs = MODES.map(([value, label]) => h("button", { type: "button", class: "ra-segtab", role: "tab", id: `num-${value}`,
    "aria-controls": "numeros-panel", onclick: () => show(value) }, label));
  view.append(h("div", { class: "stack-lg" },
    h("div", { class: "stack" },
      h("a", { class: "ra-btn ra-btn-ghost ra-back", href: "#/itinerario" }, icon("volver", 16), h("span", {}, "Itinerario")),
      h("h1", { class: "title" }, "Tu re:Invent en números"),
      h("div", { class: "ra-segtabs", role: "tablist", "aria-label": "Qué números ver" }, tabs)),
    h("div", { id: "numeros-panel", role: "tabpanel" }, body)));

  const [catalogo, mio] = await Promise.allSettled([Numeros.catalogo(), Numeros.mio()]);
  const failed = (r) => h("div", { class: "notice err" }, `No se pudieron cargar los números: ${r.reason?.message || r.reason}`);

  function show(next) {
    mode = next;
    for (const t of tabs) t.setAttribute("aria-selected", String(t.id === `num-${mode}`));
    history.replaceState(null, "", `#/itinerario/numeros${mode === "catalogo" ? "?modo=catalogo" : ""}`);
    if (mode === "catalogo") {
      body.replaceChildren(...(catalogo.status === "fulfilled" ? Catalog(catalogo.value, mio.value) : [failed(catalogo)]));
    } else {
      body.replaceChildren(...(mio.status === "fulfilled" ? Week(mio.value, () => show("catalogo")).filter(Boolean) : [failed(mio)]));
    }
  }
  show(mode);
}
