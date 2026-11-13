// Cuenta → Admin → LLM: costo, demora, errores y scores de los últimos 7 días, leídos de Langfuse por el servidor
// (/api/admin/llm, con cache de 5 minutos). Barras y números con h() y los tokens de la app, sin librerías.
import { api } from "./api.js";
import { Button, h } from "./ui.js";

const SCORE_LABEL = { lineas_faltantes: "Líneas faltantes (traducción)", json_valido: "JSON válido", util: "Útil (👍)" };
const SCORE_RATIO = new Set(["json_valido", "util"]); // 0/1: el promedio es un porcentaje

const usd = (n) => `US$ ${n.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: n < 1 ? 3 : 2 })}`;
const secs = (ms) => (ms >= 1000 ? `${(ms / 1000).toLocaleString("es-AR", { maximumFractionDigits: 1 })} s` : `${ms} ms`);
const int = (n) => n.toLocaleString("es-AR");
const pct = (x) => `${Math.round(x * 100)} %`;
const dayLabel = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("es-AR", { weekday: "short", day: "numeric" });

/** Una fila de barra horizontal: etiqueta, barra proporcional al máximo y valor. */
function Bar(label, value, max, text, tone = "") {
  const width = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return h("div", { class: "ra-bar-row" },
    h("span", { class: "ra-bar-label" }, label),
    h("span", { class: "ra-bar-track", "aria-hidden": "true" }, h("span", { class: `ra-bar-fill ${tone}`, style: { width: `${width}%` } })),
    h("span", { class: "ra-bar-value" }, text));
}

const Stat = (label, value, note) => h("div", { class: "ra-stat" },
  h("span", { class: "label" }, label), h("strong", { class: "ra-stat-value" }, value), note ? h("span", { class: "caption" }, note) : null);

function Summary(d) {
  const m = d.mes;
  return h("div", { class: "ra-stats" },
    Stat(`Costo ${d.dias} días`, usd(d.costo_semana)),
    Stat("Costo del mes", usd(m.costo)),
    Stat("Errores 7 días", int(d.errores_semana)),
    Stat("Unidades Langfuse del mes", `${int(m.unidades)} / ${int(m.limite_unidades)}`,
      m.unidades_estimadas ? `estimado: ${int(m.detalle.trazas)} trazas + ${int(m.detalle.observaciones)} observaciones + ${int(m.detalle.scores)} scores` : null));
}

function UnitsBar(m) {
  const ratio = m.unidades / m.limite_unidades;
  return Bar("Plan Hobby", m.unidades, m.limite_unidades, pct(ratio), ratio > 0.8 ? "is-warn" : "");
}

function CostByTask(tareas) {
  const max = Math.max(0, ...tareas.map((t) => t.costo));
  return h("div", { class: "stack" },
    h("h3", { class: "label" }, "Costo por tarea"),
    tareas.length ? tareas.map((t) => Bar(t.tarea, t.costo, max, usd(t.costo))) : h("p", { class: "caption" }, "Sin llamadas en estos días."));
}

function CostByDay(dias) {
  const max = Math.max(0, ...dias.map((d) => d.costo));
  return h("div", { class: "stack" },
    h("h3", { class: "label" }, "Costo por día (UTC)"),
    dias.map((d) => Bar(dayLabel(d.dia), d.costo, max, usd(d.costo))));
}

function LatencyAndErrors(tareas) {
  const max = Math.max(0, ...tareas.map((t) => t.p95_ms));
  return h("div", { class: "stack" },
    h("h3", { class: "label" }, "Demora y errores por tarea"),
    h("p", { class: "caption" }, "La barra es el p95 (el 5 % más lento); el número, p50 / p95."),
    tareas.map((t) => Bar(t.tarea, t.p95_ms, max,
      `${secs(t.p50_ms)} / ${secs(t.p95_ms)}${t.errores ? ` · ${int(t.errores)} err.` : ""}`, t.errores ? "is-err" : "")));
}

function Scores(scores) {
  if (!scores.length) return h("p", { class: "caption" }, "Todavía no hay scores (líneas faltantes, JSON válido, 👍/👎).");
  return h("div", { class: "stack" },
    h("h3", { class: "label" }, "Scores"),
    scores.map((s) => SCORE_RATIO.has(s.nombre)
      ? Bar(SCORE_LABEL[s.nombre] || s.nombre, s.promedio, 1, `${pct(s.promedio)} de ${int(s.cantidad)}`, s.promedio < 0.9 ? "is-warn" : "")
      : Bar(SCORE_LABEL[s.nombre] || s.nombre, 0, 1, `promedio ${s.promedio} en ${int(s.cantidad)}`)));
}

const LangfuseLink = (url) => (url
  ? h("a", { class: "ra-link", href: url, target: "_blank", rel: "noopener noreferrer" }, "Abrir en Langfuse ↗")
  : null);

function Dashboard(d) {
  if (!d.disponible) {
    return h("div", { class: "stack" },
      h("div", { class: "notice" }, `El tablero de LLM no está disponible: ${d.motivo}`),
      LangfuseLink(d.url));
  }
  const updated = new Date(d.actualizado).toLocaleTimeString("es-AR", { timeStyle: "short" });
  return h("div", { class: "stack" },
    Summary(d), UnitsBar(d.mes),
    CostByTask(d.tareas), CostByDay(d.costo_por_dia), LatencyAndErrors(d.tareas), Scores(d.scores),
    h("p", { class: "caption" }, `Datos de Langfuse de las ${updated} (se actualizan cada 5 minutos). `, LangfuseLink(d.url)));
}

/** Sección "LLM" del portal de admin: carga sola, sin frenar el resto de la pantalla. */
export function LlmPanel() {
  const body = h("div", { class: "stack" });
  const load = async () => {
    body.replaceChildren(h("p", { class: "caption" }, "Cargando métricas de Langfuse…"));
    try { body.replaceChildren(Dashboard(await api("/api/admin/llm"))); }
    catch (err) { body.replaceChildren(h("div", { class: "notice err" }, `No se pudo cargar el tablero: ${err.message}`)); }
  };
  void load();
  return h("div", { class: "stack" },
    h("h2", { class: "label" }, "LLM"),
    h("p", { class: "caption" }, "Últimos 7 días: costo, demora y errores por tarea, y la calidad medida."),
    body,
    h("div", { class: "actions" }, Button("Actualizar", { onclick: load })));
}
