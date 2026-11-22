// Admin › LLM (#/admin/llm): costo, demora, errores y scores de los últimos 7 días, leídos de Langfuse por el servidor
// (/api/admin/llm, con cache de 5 minutos). Barras y números con h() y los tokens de la app, sin librerías.
import { api } from "./api.js";
import { AdminShell, Cargable, conOcupado } from "./adminUi.js";
import { nombreTarea } from "./adminTextos.js";
import { icon } from "./icons.js";
import { Button, h } from "./ui.js";

const SCORE_LABEL = {
  lineas_faltantes: "Líneas faltantes (traducción)", json_valido: "JSON válido",
  codigos_inventados: "Códigos inventados (chat y briefing)", momentos_citados: "Momentos citados (chat)", util: "Útil (👍)",
};
const SCORE_RATIO = new Set(["json_valido", "util"]); // 0/1: el promedio es un porcentaje
const LIMITE_LANGFUSE = 0.8; // arriba de esto del plan, el estado pasa a «cerca del límite»
const MINIMO_ESPERADO = 0.9; // por debajo de este promedio un score de 0/1 se marca

const int = (n) => n.toLocaleString("es-AR");
const dinero = (n) => n.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: n < 1 ? 3 : 2 });
const KpiUsd = (n) => h("span", {}, dinero(n), h("small", {}, " US$"));
const secs = (ms) => (ms >= 1000 ? `${(ms / 1000).toLocaleString("es-AR", { maximumFractionDigits: 1 })} s` : `${ms} ms`);
const pct = (x) => `${Math.round(x * 100)} %`;
const plural = (n, uno, varios) => `${int(n)} ${n === 1 ? uno : varios}`;
const dayLabel = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("es-AR", { weekday: "short", day: "numeric" });

/**
 * Una fila de barra horizontal: etiqueta, barra proporcional al máximo y valor. El estado (warn / err) nunca va solo con
 * color: `nota` lo dice con texto debajo de la barra. La fila se lee entera como un grupo («Resumen: US$ 4,90»).
 */
function Bar(label, value, max, text, tone = "", nota = null) {
  const width = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return h("div", { class: "ra-bar-row", role: "group", "aria-label": `${label}: ${text}${nota ? `. ${nota}` : ""}` },
    h("span", { class: "ra-bar-label" }, label),
    h("span", { class: "ra-bar-track", "aria-hidden": "true" }, h("span", { class: `ra-bar-fill ${tone}`, style: { width: `${width}%` } })),
    h("span", { class: "ra-bar-value", "aria-hidden": "true" }, text),
    nota ? h("span", { class: `ra-adm-bars-nota${tone === "is-err" ? " is-err" : ""}`, "aria-hidden": "true" }, icon("alerta", 14), h("span", {}, nota)) : null);
}

/** Una tarjeta del tablero: título y lo que corresponda (barras, datos, notas). */
const Tarjeta = (id, titulo, ...contenido) => h("section", { class: "ra-num-card", "aria-labelledby": id },
  h("h2", { class: "label", id }, titulo), ...contenido);
const Barras = (filas) => h("div", { class: "ra-bars ra-adm-bars" }, filas);

const Kpi = (etiqueta, valor, nota, { error = false, extra = null } = {}) => h("div", { class: `ra-kpi${error ? " is-err" : ""}` },
  h("span", { class: "ra-kpi-label" }, etiqueta), h("span", { class: "ra-kpi-value" }, valor), h("span", { class: "ra-kpi-note" }, nota), extra);

/** Cómo se calcularon las unidades del mes (null si vienen exactas). */
function UnitsNote(m) {
  if (!m.unidades_estimadas) return null;
  const tipo = m.unidades_cota_superior ? "cota superior estimada" : "estimado";
  return `${tipo}: ${int(m.detalle.trazas)} trazas + ${int(m.detalle.observaciones)} observaciones + ${int(m.detalle.scores)} scores`;
}

function Kpis(d) {
  const m = d.mes;
  const ratio = m.unidades / m.limite_unidades;
  const cerca = ratio > LIMITE_LANGFUSE;
  const barra = h("span", { class: `ra-g-avance${cerca ? " is-warn" : ""} ra-adm-kpi-bar`, "aria-hidden": "true" },
    h("span", { style: { width: `${Math.min(100, Math.round(ratio * 100))}%` } }));
  return h("div", { class: "ra-kpis" },
    Kpi(`Costo ${d.dias} días`, KpiUsd(d.costo_semana), "sin contar el modo prueba"),
    Kpi("Costo del mes", KpiUsd(m.costo), "mes en curso"),
    Kpi(`Errores ${d.dias} días`, int(d.errores_semana), d.errores_semana ? "revisar demora y errores por tarea" : "sin errores", { error: d.errores_semana > 0 }),
    Kpi("Langfuse", h("span", {}, String(Math.round(ratio * 100)), h("small", {}, " %")),
      [cerca ? "Cerca del límite" : null, `${int(m.unidades)} de ${int(m.limite_unidades)} unidades`, UnitsNote(m)].filter(Boolean).join(" · "), { extra: barra }));
}

function CostByTask(tareas) {
  const max = Math.max(0, ...tareas.map((t) => t.costo));
  return Tarjeta("llm-tarea", "Costo por tarea · US$, 7 días",
    tareas.length ? Barras(tareas.map((t) => Bar(nombreTarea(t.tarea), t.costo, max, dinero(t.costo)))) : h("p", { class: "ra-adm-cap" }, "Sin llamadas en estos días."));
}

const CostByDay = (dias) => {
  const max = Math.max(0, ...dias.map((d) => d.costo));
  return Tarjeta("llm-dia", "Costo por día · US$ (UTC)", Barras(dias.map((d) => Bar(dayLabel(d.dia), d.costo, max, dinero(d.costo)))));
};

function LatencyAndErrors(tareas) {
  const max = Math.max(0, ...tareas.map((t) => t.p95_ms));
  return Tarjeta("llm-demora", "Demora y errores por tarea",
    Barras(tareas.map((t) => Bar(nombreTarea(t.tarea), t.p95_ms, max, `${secs(t.p50_ms)} / ${secs(t.p95_ms)}`, t.errores ? "is-err" : "",
      t.errores ? `${plural(t.errores, "error", "errores")} en 7 días` : null))),
    h("p", { class: "ra-adm-cap" }, "La barra es el p95 (el 5 % más lento); el número, p50 / p95."));
}

/** Calidad medida: los scores de 0/1 llevan barra; los demás son promedios y van como datos (una barra vacía no dice nada). */
function Scores(scores) {
  if (!scores.length) return Tarjeta("llm-calidad", "Calidad", h("p", { class: "ra-adm-cap" }, "Todavía no hay scores (líneas faltantes, JSON válido, 👍/👎)."));
  const conBarra = scores.filter((s) => SCORE_RATIO.has(s.nombre));
  const promedios = scores.filter((s) => !SCORE_RATIO.has(s.nombre));
  return Tarjeta("llm-calidad", "Calidad",
    conBarra.length ? Barras(conBarra.map((s) => Bar(SCORE_LABEL[s.nombre] || s.nombre, s.promedio, 1, pct(s.promedio),
      s.promedio < MINIMO_ESPERADO ? "is-warn" : "", s.promedio < MINIMO_ESPERADO ? `Por debajo de lo esperado (${pct(MINIMO_ESPERADO)})` : null))) : null,
    promedios.length ? h("p", { class: "ra-adm-sub" }, "Promedios (sin barra)") : null,
    promedios.length ? h("dl", { class: "ra-adm-datos" }, promedios.map((s) => h("div", {},
      h("dt", {}, SCORE_LABEL[s.nombre] || s.nombre), h("dd", {}, `${s.promedio} en ${int(s.cantidad)}`)))) : null);
}

const LangfuseLink = (url) => (url
  ? h("a", { class: "ra-link", href: url, target: "_blank", rel: "noopener noreferrer" }, "Abrir en Langfuse", icon("externo", 16))
  : null);

/** Cabecera: «Uso del LLM», cuándo se actualizó y el botón «Actualizar» (ghost, arriba a la derecha). */
function Cabecera(actualizado, alActualizar) {
  const boton = Button("Actualizar", { class: "ra-btn ra-btn-ghost ra-sec-action", onclick: () => conOcupado(boton, alActualizar) });
  return h("div", { class: "ra-sec-head" },
    h("div", { class: "ra-adm-nueva-head" }, h("h2", { class: "label" }, "Uso del LLM"),
      h("span", { class: "ra-adm-cap" }, actualizado ? `Actualizado ${actualizado}` : "Últimos 7 días: costo, demora y errores por tarea, y la calidad medida.")),
    boton);
}

function Dashboard(d, alActualizar) {
  if (!d.disponible) {
    return [Cabecera(null, alActualizar), h("div", { class: "notice" }, `El tablero de LLM no está disponible: ${d.motivo}`), LangfuseLink(d.url)];
  }
  const updated = new Date(d.actualizado).toLocaleTimeString("es-AR", { timeStyle: "short" });
  return [
    h("section", { class: "ra-adm-sec", "aria-label": "Resumen del LLM" }, Cabecera(updated, alActualizar), Kpis(d)),
    CostByTask(d.tareas), CostByDay(d.costo_por_dia), LatencyAndErrors(d.tareas), Scores(d.scores),
    h("p", { class: "ra-adm-cap" }, `Datos de Langfuse (se actualizan cada 5 minutos). Lo de ${d.dias} días no cuenta el modo prueba. `, LangfuseLink(d.url)),
  ];
}

/** Pestaña LLM: carga sola; si falla, muestra el error con Reintentar y las demás pestañas siguen andando. */
export function viewAdminLlm(view) {
  const tablero = Cargable({
    cargar: () => api("/api/admin/llm"),
    pintar: (d) => Dashboard(d, () => tablero.recargar()),
    textoCargando: "Cargando métricas de Langfuse…",
  });
  tablero.classList.add("ra-adm-resumen");
  AdminShell(view, "llm", tablero);
}
