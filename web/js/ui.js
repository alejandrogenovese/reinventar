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

export function LevelMeter() {
  const name = h("strong", {}, "Micrófono"), word = h("span", {}, "Sin señal");
  const fill = h("div", { class: "ra-meter-fill", style: { width: "0%" } });
  const track = h("div", { class: "ra-meter-track", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0", "aria-label": "Nivel de entrada" }, fill);
  const el = h("div", { class: "ra-meter" }, h("div", { class: "ra-meter-head" }, h("span", {}, name), word), track);
  el.update = (level, device) => {
    if (device) name.textContent = device;
    fill.style.width = `${Math.round(level * 100)}%`;
    fill.className = "ra-meter-fill" + (level > 0.95 ? " is-clip" : level > 0.75 ? " is-hot" : "");
    word.textContent = level > 0.95 ? "Satura" : level > 0.75 ? "Alto" : level < 0.05 ? "Sin señal" : "Bien";
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
    sm.services?.length ? sec("Servicios mencionados", h("div", { class: "ra-chips" }, sm.services.map((x) => h("span", { class: "ra-chip" }, x)))) : null,
    sm.quotes?.length ? sec("Frases", h("ul", {}, sm.quotes.map((q) => h("li", { class: "quote" }, h("span", { class: "ra-chip" }, q.time || ""), " ", `“${q.text}”`)))) : null,
    sm.takeaways?.length ? sec("Para llevar a Galicia", list(sm.takeaways)) : null);
}

let toastTimer;
export function toast(msg) {
  document.querySelector(".toast")?.remove();
  const el = h("div", { class: "toast", role: "status" }, msg);
  document.body.append(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 3500);
}
