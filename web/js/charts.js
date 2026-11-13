// Gráficos chicos con h() y los tokens de la app, sin librerías: KPI, barras, columnas, heatmap y barra apilada.
// Cada barra, columna o celda lleva su número en aria-label/title; si tiene href, es un link (lleva a Buscar).
import { h } from "./ui.js";

export const int = (n) => Number(n || 0).toLocaleString("es-AR");
export const dec = (n, digits = 1) => Number(n || 0).toLocaleString("es-AR", { maximumFractionDigits: digits, minimumFractionDigits: digits });
export const pct = (part, total) => (total > 0 ? Math.round((part / total) * 100) : 0);

const WEEKDAY = new Intl.DateTimeFormat("es-AR", { weekday: "short", timeZone: "UTC" });
const LONG_DAY = new Intl.DateTimeFormat("es-AR", { weekday: "long", timeZone: "UTC" });
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);
/** "2026-12-01" → "Mar" (día corto, con mayúscula y sin punto). */
export const dayShort = (iso) => capital(WEEKDAY.format(new Date(`${iso}T12:00:00Z`)).replace(".", ""));
/** "2026-12-01" → "martes". */
export const dayLong = (iso) => LONG_DAY.format(new Date(`${iso}T12:00:00Z`));

/** Link a Buscar con filtros: { dia: ["2026-12-01"], hora: ["13 h"] } → "#/buscar?dia=…&hora=…". */
export function searchHref(filters) {
  const params = new URLSearchParams();
  for (const [facet, values] of Object.entries(filters)) for (const v of [values].flat()) params.append(facet, v);
  return `#/buscar?${params}`;
}

/** Un número grande con su etiqueta y una nota. unit va chica al lado (h, km, %). */
export const Kpi = (label, value, { unit, note, tone = "", wide = false } = {}) =>
  h("div", { class: `ra-kpi${tone ? ` is-${tone}` : ""}${wide ? " is-wide" : ""}` },
    h("span", { class: "ra-kpi-label" }, label),
    h("span", { class: "ra-kpi-value" }, value, unit ? h("small", {}, unit) : null),
    note ? h("span", { class: "ra-kpi-note" }, note) : null);

/** Fila de barra horizontal (misma forma que .ra-bar-row de Admin › LLM). Con href es un link. */
export function BarRow({ label, value, max, text, href, tone = "", extra = null, gap = false }) {
  const width = max > 0 && value > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  const attrs = { class: `ra-bar-row${gap ? " is-gap" : ""}${href ? " ra-bar-link" : ""}`, "aria-label": `${label}: ${text}`, title: `${label}: ${text}` };
  return h(href ? "a" : "div", href ? { ...attrs, href } : attrs,
    h("span", { class: "ra-bar-label" }, label, extra),
    h("span", { class: "ra-bar-track", "aria-hidden": "true" }, h("span", { class: `ra-bar-fill ${tone}`, style: { width: `${width}%` } })),
    h("span", { class: "ra-bar-value", "aria-hidden": "true" }, text));
}

export const Bars = (rows, { wide = false } = {}) => h("div", { class: `ra-bars${wide ? " is-wide" : ""}` }, rows.map(BarRow));

/** Columnas verticales: el total del catálogo, y abajo cuántas tenés vos (mine). */
export function Columns(cols, { height = 130 } = {}) {
  const max = Math.max(0, ...cols.map((c) => c.value));
  return h("div", { class: "ra-cols", style: { gridTemplateColumns: `repeat(${cols.length}, 1fr)` } },
    cols.map((c) => h("a", { class: `ra-col${c.today ? " is-today" : ""}`, href: c.href, "aria-label": c.aria, title: c.aria },
      h("span", { class: "ra-col-num" }, int(c.value)),
      h("span", { class: "ra-col-stick", style: { height: `${max > 0 ? Math.max(2, Math.round((c.value / max) * height)) : 2}px` } }),
      h("span", { class: "ra-col-day" }, c.label),
      h("span", { class: "ra-col-mine" }, int(c.mine)))));
}

/** Rampa del heatmap: del gris de la pista al naranja de marca, en los dos temas. */
export const heatColor = (n, max) => (n > 0 ? `color-mix(in srgb, var(--brand) ${Math.max(12, pct(n, max))}%, var(--surface-3))` : "");

/** Heatmap filas × columnas. rows: [{label, cells: [{n, href, aria, mine}]}]. */
export function Heatmap(columns, rows) {
  const max = Math.max(0, ...rows.flatMap((r) => r.cells.map((c) => c.n)));
  return h("div", { class: "ra-heat", style: { gridTemplateColumns: `var(--heat-label) repeat(${columns.length}, 1fr)` } },
    h("span", { "aria-hidden": "true" }),
    columns.map((c) => h("span", { class: "ra-heat-col", "aria-hidden": "true" }, c)),
    rows.map((r) => [
      h("span", { class: "ra-heat-row" }, r.label),
      r.cells.map((c) => h(c.n ? "a" : "span", {
        class: `ra-heat-cell${c.mine ? " is-mine" : ""}`, href: c.n ? c.href : null, "aria-label": c.aria, title: c.aria,
        role: c.n ? null : "img", style: { background: heatColor(c.n, max) },
      })),
    ]));
}

/** Barra apilada al 100 % (niveles): cada tramo con su etiqueta y su tono. */
export const StackBar = (parts) => h("div", { class: "ra-stack100" },
  parts.map((p) => h("span", { style: { flex: String(p.value), background: p.color }, title: p.aria, "aria-label": p.aria, role: "img" }, p.label)));

export const Legend = (items) => h("div", { class: "ra-legend" },
  items.map(([cls, text]) => h("span", {}, h("i", { class: `ra-legend-swatch ${cls}`, "aria-hidden": "true" }), text)));

/** Sección con título, dato a la derecha y tarjeta. */
export const Section = (title, sub, ...body) => h("section", { class: "stack" },
  h("div", { class: "ra-sec-head" }, h("h2", { class: "label" }, title), sub ? h("span", { class: "caption" }, sub) : null),
  h("div", { class: "ra-num-card" }, body));
