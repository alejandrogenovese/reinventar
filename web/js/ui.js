// Helpers de DOM y los componentes del design system (misma markup que el bundle de React).
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) if (c != null && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}

export const hms = (sec) => {
  sec = Math.max(0, Math.floor(sec || 0));
  return [sec / 3600, (sec % 3600) / 60, sec % 60].map((n) => String(Math.floor(n)).padStart(2, "0")).join(":");
};

const STATUS = { recording: "Grabando", uploading: "Subiendo", queued: "En cola", transcribing: "Transcribiendo", translating: "Traduciendo", summarizing: "Resumiendo", ready: "Listo", error: "Error" };
export const StatusPill = (status, text) =>
  h("span", { class: `ra-pill ra-pill-${status}`, role: "status" }, h("span", { class: "ra-pill-dot", "aria-hidden": "true" }), text || STATUS[status] || status);

export const Button = (label, { variant = "secondary", ...attrs } = {}) =>
  h("button", { type: "button", class: `ra-btn ra-btn-${variant}`, ...attrs }, label);

export function RecordButton(state, onClick) {
  const aria = state === "recording" ? "Pausar grabación" : state === "paused" ? "Seguir grabando" : "Empezar a grabar";
  const label = { idle: "Grabar", recording: "Grabando", paused: "En pausa" }[state] || "Grabar";
  return h("div", { class: "ra-recwrap" },
    h("button", { type: "button", class: `ra-rec is-${state}`, "aria-label": aria, "aria-pressed": String(state === "recording"), onclick: onClick },
      h("span", { class: "ra-rec-glyph", "aria-hidden": "true" })),
    h("span", { class: "ra-rec-label" }, label));
}

const METER_SEGMENTS = 24;
const METER_HOT = 0.75;   // desde acá conviene alejar el micrófono
const METER_CLIP = 0.95;  // satura: se pierde audio
const METER_SILENT = 0.05;

const meterZone = (x) => (x > METER_CLIP ? "clip" : x > METER_HOT ? "hot" : "ok");

/** Medidor de entrada por segmentos (verde/ámbar/rojo) con la palabra de estado al costado. */
export function LevelMeter() {
  const name = h("strong", {}, "Micrófono"), word = h("span", { class: "ra-meter-word" }, "Sin señal");
  const segs = Array.from({ length: METER_SEGMENTS }, (_, i) => h("span", { class: `ra-seg is-${meterZone((i + 1) / METER_SEGMENTS)}` }));
  const track = h("div", { class: "ra-meter-track", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0", "aria-label": "Nivel de entrada" }, segs);
  const el = h("div", { class: "ra-meter" }, h("div", { class: "ra-meter-head" }, h("span", {}, name), word), track);
  el.update = (level, device) => {
    if (device) name.textContent = device;
    const lit = Math.round(level * METER_SEGMENTS);
    segs.forEach((s, i) => s.classList.toggle("is-lit", i < lit));
    const state = level > METER_CLIP ? "clip" : level > METER_HOT ? "hot" : level < METER_SILENT ? "silent" : "ok";
    word.textContent = { clip: "Satura", hot: "Alto", silent: "Sin señal", ok: "Bien" }[state];
    word.dataset.state = state;
    track.setAttribute("aria-valuenow", String(Math.round(level * 100)));
  };
  return el;
}

export function SessionCard(s, onClick) {
  const meta = [s.venue, s.duration_s ? hms(s.duration_s) : null, s.speaker].filter(Boolean);
  return h("button", { type: "button", class: "ra-card", onclick: onClick },
    h("div", { class: "ra-card-top" }, h("span", { class: "ra-kind" }, s.kind + (s.code ? ` · ${s.code}` : "")), StatusPill(s.status)),
    h("h3", { class: "ra-card-title" }, s.title),
    meta.length ? h("div", { class: "ra-card-meta" }, meta.map((m) => h("span", {}, m))) : null);
}

export const TranscriptBlock = (b) =>
  h("div", { class: "ra-tb" },
    h("span", { class: "ra-tc" }, hms(b.start_s)),
    h("div", { class: "ra-tb-body" },
      b.es ? h("p", { class: "ra-tb-es", lang: "es" }, h("span", { class: "ra-tb-lang" }, "ES"), b.es) : null,
      h("p", { class: "ra-tb-en", lang: "en" }, h("span", { class: "ra-tb-lang" }, "EN"), b.en)));

export function SummaryPanel(sm) {
  const sec = (title, body) => h("section", {}, h("h3", {}, title), body);
  const list = (xs) => h("ul", {}, xs.map((x) => h("li", {}, x)));
  return h("div", { class: "ra-sum" },
    sm.tldr ? sec("TL;DR", h("p", { class: "ra-tldr" }, sm.tldr)) : null,
    sm.announcements?.length ? sec("Anuncios", h("ul", {}, sm.announcements.map((a) => h("li", {}, h("span", { class: "ra-hl" }, a.service), " ", a.text)))) : null,
    sm.key_points?.length ? sec("Puntos clave", list(sm.key_points)) : null,
    sm.services?.length ? sec("Servicios mencionados", h("div", { class: "ra-chips" }, sm.services.map(Tag))) : null,
    sm.quotes?.length ? sec("Frases", h("ul", {}, sm.quotes.map((q) => h("li", { class: "quote" }, h("span", { class: "ra-tag ra-mono" }, q.time || ""), " ", `“${q.text}”`)))) : null,
    sm.vs_abstract ? sec("Versus lo prometido", h("p", {}, sm.vs_abstract)) : null,
    sm.takeaways?.length ? sec("Para llevar a Galicia", list(sm.takeaways)) : null);
}

const TOAST_MS = 3500;
const UNDO_MS = 6000;
let toastTimer;

/** Aviso breve abajo. Con `action` ({ label, onClick }) queda más tiempo y suma un botón (ej. Deshacer). */
export function toast(msg, { action } = {}) {
  document.querySelector(".toast")?.remove();
  const el = h("div", { class: "toast", role: "status" }, h("span", {}, msg),
    action ? h("button", { type: "button", class: "toast-action", onclick: () => { clearTimeout(toastTimer); el.remove(); action.onClick(); } }, action.label) : null);
  document.body.append(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), action ? UNDO_MS : TOAST_MS);
}

/**
 * Acción con Deshacer: `apply` se ejecuta ya (ej. ocultar), `commit` recién cuando vence el aviso
 * y `undo` si el usuario se arrepiente. Así no hace falta reconstruir lo borrado.
 */
export function withUndo(msg, { apply, commit, undo }) {
  apply();
  let undone = false;
  const timer = setTimeout(() => { if (!undone) commit(); }, UNDO_MS);
  toast(msg, { action: { label: "Deshacer", onClick: () => { undone = true; clearTimeout(timer); undo(); } } });
}

/** Etiqueta informativa (no se toca); los filtros que sí se tocan son `button.ra-chip`. */
export const Tag = (text) => h("span", { class: "ra-tag" }, text);

/** Placeholder gris mientras carga una pantalla. */
export const Skeleton = (cards = 3) => h("div", { class: "ra-skeleton", "aria-busy": "true", "aria-label": "Cargando" },
  h("div", { class: "ra-skel ra-skel-title" }),
  Array.from({ length: cards }, () => h("div", { class: "ra-skel ra-skel-card" })));

const CODE = /\[([A-Z0-9][A-Z0-9-]{2,19})\]/g;

/** Texto con [CODIGO] → links a la ficha de la charla; solo para códigos de `valid` (los demás quedan como texto). */
export function withCodeLinks(text, valid) {
  const parts = [];
  let last = 0;
  for (const m of text.matchAll(CODE)) {
    parts.push(text.slice(last, m.index));
    parts.push(valid.has(m[1]) ? h("a", { class: "ra-link", href: `#/charla/${m[1]}` }, m[1]) : m[0]);
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));
  return parts;
}
