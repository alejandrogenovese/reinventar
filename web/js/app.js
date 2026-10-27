// ReinventAR — router y pantallas.
import { ApiError, Sessions, api, getToken, setToken } from "./api.js";
import * as it from "./itinerary.js";
import { Recorder, listMics, pickDjI, preferredMic, uploader, wakeLock } from "./recorder.js";
import * as store from "./store.js";
import { Button, LevelMeter, RecordButton, SessionCard, StatusPill, SummaryPanel, TranscriptBlock, h, hms, toast } from "./ui.js";

const view = document.getElementById("view");
const KINDS = ["Keynote", "Chalk talk", "Workshop", "Breakout"];
const PROCESSING = ["queued", "transcribing", "translating", "summarizing"];
let cleanup = () => {};
const kids = (...xs) => xs.filter((x) => x != null && x !== false);
let activeRecorder = null;

// --- tema --------------------------------------------------------------------
const THEME = "reinventar.theme";
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  document.querySelector('meta[name="theme-color"]').content = t === "light" ? "#f7f5fc" : "#0b0a1a";
}
try { applyTheme(localStorage.getItem(THEME) || "dark"); } catch { applyTheme("dark"); }
document.getElementById("themeBtn").addEventListener("click", () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(t); try { localStorage.setItem(THEME, t); } catch {}
});

// --- router ------------------------------------------------------------------
const routes = [
  [/^#\/?$/, viewList],
  [/^#\/nueva$/, viewNew],
  [/^#\/ajustes$/, viewSettings],
  [/^#\/grabar\/([\w-]+)$/, viewRecord],
  [/^#\/s\/([\w-]+)$/, viewDetail],
  [/^#\/itinerario$/, () => it.viewItinerario(view)],
  [/^#\/itinerario\/cuestionario$/, () => it.viewCuestionario(view)],
  [/^#\/itinerario\/explorar$/, () => it.viewExplorar(view)],
];

let ignoreNextHash = false;
async function route() {
  if (ignoreNextHash) { ignoreNextHash = false; return; }
  if (activeRecorder && ["recording", "paused"].includes(activeRecorder.state) && !location.hash.startsWith("#/grabar/")) {
    if (!confirm("Estás grabando. ¿Salir igual? La grabación se detiene.")) { ignoreNextHash = true; history.back(); return; }
    await activeRecorder.stop(); activeRecorder.close(); activeRecorder = null;
  }
  cleanup(); cleanup = () => {};
  const hash = location.hash || "#/";
  if (!getToken() && hash !== "#/ajustes") { location.hash = "#/ajustes"; return; }
  for (const [re, fn] of routes) {
    const m = hash.match(re);
    if (m) {
      view.replaceChildren();
      try { await fn(...m.slice(1)); } catch (e) { renderError(e); }
      window.scrollTo(0, 0);
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (e) => { if (activeRecorder?.state === "recording" || activeRecorder?.state === "paused") e.preventDefault(); });

function renderError(e) {
  console.error(e);
  const msg = e instanceof ApiError && e.status === 401 ? "El token no es válido. Revisalo en Ajustes." : e.message || String(e);
  view.replaceChildren(h("div", { class: "notice err" }, msg));
}

// --- lista -------------------------------------------------------------------
async function viewList() {
  const list = h("div", { class: "stack" });
  const banner = h("div");
  view.append(h("div", { class: "stack-lg" },
    h("div", { class: "actions" }, Button("Nueva sesión", { variant: "primary", onclick: () => (location.hash = "#/nueva") })),
    banner, list));

  const showPending = ({ pending, error }) => banner.replaceChildren(
    pending ? h("div", { class: "notice upl" }, StatusPill("uploading", `Subiendo ${pending}`), h("span", { class: "caption" }, error || "En segundo plano")) : "");
  const onUp = (e) => showPending(e.detail);
  uploader.addEventListener("change", onUp);
  cleanup = () => uploader.removeEventListener("change", onUp);
  uploader.refresh(); uploader.kick();

  const sessions = await Sessions.list();
  if (!sessions.length) {
    list.append(h("div", { class: "empty" }, h("p", {}, "Todavía no grabaste ninguna sesión."), h("p", { class: "caption" }, "Conectá el receptor del DJI al celular y tocá Nueva sesión.")));
    return;
  }
  for (const s of sessions) {
    const live = s.status === "recording" || s.status === "uploading";
    list.append(SessionCard(s, () => (location.hash = live ? `#/grabar/${s.id}` : `#/s/${s.id}`)));
  }
}

// --- nueva sesión ------------------------------------------------------------
function viewNew() {
  const radios = KINDS.map((k, i) => [
    h("input", { type: "radio", name: "kind", id: `k${i}`, value: k, checked: i === 0 }),
    h("label", { for: `k${i}` }, k),
  ]);
  const field = (label, input) => h("div", { class: "field" }, h("label", { class: "label", for: input.id }, label), input);
  const form = h("form", { class: "stack-lg", onsubmit: async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      const s = await Sessions.create({
        title: fd.get("title").trim(), kind: fd.get("kind"),
        code: fd.get("code").trim() || null, venue: fd.get("venue").trim() || null, speaker: fd.get("speaker").trim() || null,
      });
      location.hash = `#/grabar/${s.id}`;
    } catch (err) { toast(err.message); btn.disabled = false; }
  } },
    h("h1", { class: "title" }, "Nueva sesión"),
    h("fieldset", { style: { border: 0, padding: 0, margin: 0 } }, h("legend", { class: "label", style: { marginBottom: "8px" } }, "Tipo"), h("div", { class: "segmented" }, radios)),
    field("Título", h("input", { id: "title", name: "title", required: true, maxlength: "200", placeholder: "Keynote de apertura", autocomplete: "off" })),
    field("Código de agenda", h("input", { id: "code", name: "code", maxlength: "40", placeholder: "ANT301", autocapitalize: "characters", autocomplete: "off" })),
    field("Sala", h("input", { id: "venue", name: "venue", maxlength: "120", placeholder: "Venetian · Hall A", autocomplete: "off" })),
    field("Speakers", h("input", { id: "speaker", name: "speaker", maxlength: "200", autocomplete: "off" })),
    h("div", { class: "actions" }, h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Preparar grabación")));
  view.append(form);
  form.querySelector("#title").focus();
}

// --- grabación ---------------------------------------------------------------
async function viewRecord(id) {
  const s = await Sessions.get(id);
  if (!["recording", "uploading", "error"].includes(s.status) || s.blocks?.length) { location.hash = `#/s/${id}`; return; }

  const rec = new Recorder(id);
  activeRecorder = rec;
  const counter = h("div", { class: "counter", "aria-live": "off" }, hms(rec.elapsed() / 1000));
  const meter = LevelMeter();
  const micSelect = h("select", { id: "mic", "aria-label": "Micrófono" });
  const recSlot = h("div");
  const upl = h("div", { class: "upl" });
  const msg = h("div");
  const finishBtn = Button("Terminar y procesar", { variant: "primary", disabled: true, onclick: finish });
  const salaBtn = Button("Modo sala", { onclick: salaOn });

  const resumed = Object.keys(rec.meta.parts).length > 0;
  view.append(h("div", { class: "stack-lg" },
    h("div", {}, h("span", { class: "ra-kind" }, s.kind + (s.code ? ` · ${s.code}` : "")), h("h1", { class: "title" }, s.title),
      resumed ? h("p", { class: "caption" }, "Retomás una grabación: lo nuevo se agrega a continuación.") : null),
    h("div", { class: "field" }, h("label", { class: "label", for: "mic" }, "Micrófono"), micSelect),
    h("div", { class: "recorder" }, meter, counter, recSlot, upl, msg,
      h("div", { class: "actions" }, salaBtn, finishBtn),
      h("div", { class: "actions" }, Button("Descartar", { variant: "danger", onclick: discard })))));

  const paint = () => recSlot.replaceChildren(RecordButton(rec.state === "stopped" ? "idle" : rec.state, toggle));
  rec.addEventListener("state", () => { paint(); finishBtn.disabled = !(rec.state === "recording" || rec.state === "paused" || resumed); });
  rec.addEventListener("tick", (e) => { counter.textContent = hms(e.detail / 1000); sala?.update?.(); });
  rec.addEventListener("level", (e) => meter.update(e.detail, rec.deviceLabel));
  rec.addEventListener("error", (e) => { msg.replaceChildren(h("div", { class: "notice err" }, e.detail.message)); });
  const onUp = (e) => {
    const { pending, error } = e.detail;
    upl.replaceChildren(pending ? StatusPill("uploading", `Subiendo ${pending}`) : StatusPill("ready", "Todo subido"), h("span", { class: "caption" }, error || ""));
  };
  uploader.addEventListener("change", onUp);
  uploader.refresh();
  if (resumed) finishBtn.disabled = false;
  paint();

  async function openMic(deviceId) {
    try {
      await rec.open(deviceId);
      msg.replaceChildren();
      const mics = await listMics();
      const chosen = deviceId || mics.find((m) => m.label === rec.deviceLabel)?.deviceId;
      micSelect.replaceChildren(...mics.map((m, i) => h("option", { value: m.deviceId, selected: m.deviceId === chosen }, m.label || `Micrófono ${i + 1}`)));
      return mics;
    } catch (e) {
      msg.replaceChildren(h("div", { class: "notice err" }, e.name === "NotAllowedError" ? "Necesito permiso para usar el micrófono." : `No pude abrir el micrófono: ${e.message}`));
      return [];
    }
  }
  micSelect.addEventListener("change", () => {
    if (rec.state === "recording" || rec.state === "paused") { toast("Para cambiar de micrófono, terminá o pausá y volvé a entrar."); return; }
    openMic(micSelect.value);
  });
  // Primero con el preferido; si no, con el default para obtener permiso y labels, y buscamos el DJI.
  const pref = preferredMic();
  let mics = await openMic(pref || undefined);
  if (!pref) { const dji = pickDjI(mics); if (dji) await openMic(dji.deviceId); }

  function toggle() {
    try {
      if (rec.state === "idle" || rec.state === "stopped") rec.start();
      else if (rec.state === "recording") rec.pause();
      else if (rec.state === "paused") rec.resume();
    } catch (e) { toast(e.message); }
  }

  let sala = null;
  function salaOn() {
    const c = h("div", { class: "counter" }, counter.textContent);
    sala = h("div", { class: "sala", role: "dialog", "aria-label": "Modo sala. Tocá para salir.", onclick: () => { sala.remove(); sala = null; } },
      StatusPill(rec.state === "recording" ? "recording" : "queued", rec.state === "recording" ? "Grabando" : "Sin grabar"), c,
      h("span", { class: "caption" }, "Tocá para salir"));
    sala.update = () => { c.textContent = counter.textContent; };
    document.body.append(sala);
    if (rec.state === "recording") wakeLock.acquire();
  }

  async function finish() {
    finishBtn.disabled = true;
    await rec.stop();
    rec.close();
    msg.replaceChildren(h("div", { class: "notice" }, "Esperando que termine de subir…"));
    uploader.kick();
    for (let i = 0; (await store.countFor(id)) > 0; i++) {
      if (i > 0 && i % 15 === 0) uploader.kick();
      await new Promise((r) => setTimeout(r, 1000));
      if (i > 600) { msg.replaceChildren(h("div", { class: "notice err" }, "La subida no termina. Revisá la conexión; lo pendiente queda guardado en el celular.")); finishBtn.disabled = false; return; }
    }
    try {
      await Sessions.finish(id, rec.partsCount());
      store.dropRecMeta(id);
      activeRecorder = null;
      location.hash = `#/s/${id}`;
    } catch (e) {
      const missing = e.detail?.missing;
      msg.replaceChildren(h("div", { class: "notice err" }, missing ? `Faltan pedazos en el servidor (${Object.values(missing).flat().length}). Si el celular los tiene, se suben solos: probá Terminar de nuevo en un rato.` : e.message));
      finishBtn.disabled = false;
    }
  }

  async function discard() {
    if (!confirm("¿Descartar esta grabación? Se borra el audio del celular y del servidor.")) return;
    await rec.stop(); rec.close(); activeRecorder = null;
    store.dropRecMeta(id);
    try { await Sessions.remove(id); } catch {}
    location.hash = "#/";
  }

  cleanup = () => { uploader.removeEventListener("change", onUp); sala?.remove();
    if (!["recording", "paused"].includes(rec.state)) { rec.close(); if (activeRecorder === rec) activeRecorder = null; } };
}

// --- detalle -----------------------------------------------------------------
async function viewDetail(id) {
  let tab = "resumen";
  let timer;
  const head = h("div");
  const body = h("div", { class: "stack" });
  const actions = h("div", { class: "actions" });
  view.append(h("div", { class: "stack-lg" }, head, actions, body));

  async function load() {
    const s = await Sessions.get(id);
    const meta = [s.venue, s.speaker, s.duration_s ? hms(s.duration_s) : null].filter(Boolean).join(" · ");
    head.replaceChildren(...kids(
      h("span", { class: "ra-kind" }, s.kind + (s.code ? ` · ${s.code}` : "")),
      h("h1", { class: "title" }, s.title),
      h("div", { class: "actions", style: { alignItems: "center" } }, StatusPill(s.status, s.progress || undefined), meta ? h("span", { class: "caption" }, meta) : null),
      s.error ? h("div", { class: "notice err", style: { marginTop: "12px" } }, s.error) : null));

    actions.replaceChildren(...kids(
      s.status === "ready" ? Button("Exportar .md", { onclick: () => exportMd(s) }) : null,
      s.status === "error" ? Button("Reintentar", { variant: "primary", onclick: async () => { await Sessions.retry(id); load(); } }) : null,
      ["recording", "uploading"].includes(s.status) ? Button("Seguir grabando", { variant: "primary", onclick: () => (location.hash = `#/grabar/${id}`) }) : null,
      Button("Eliminar", { variant: "danger", onclick: async () => {
        if (!confirm("¿Eliminar la sesión con su audio, transcripción y resumen?")) return;
        await Sessions.remove(id); store.dropRecMeta(id); location.hash = "#/";
      } })));

    const tabs = h("div", { class: "tabs", role: "tablist" },
      [["resumen", "Resumen"], ["transcripcion", "Transcripción"]].map(([k, label]) =>
        h("button", { class: "ra-tab", role: "tab", "aria-selected": String(tab === k), onclick: () => { tab = k; load(); } }, label)));
    let content;
    if (tab === "resumen") {
      content = s.summary ? SummaryPanel(s.summary) : h("div", { class: "empty" }, PROCESSING.includes(s.status) ? "El resumen aparece cuando termina el procesamiento." : "Sin resumen todavía.");
    } else {
      content = s.blocks?.length ? h("div", {}, s.blocks.map(TranscriptBlock)) : h("div", { class: "empty" }, "Sin transcripción todavía.");
    }
    body.replaceChildren(tabs, content);

    clearTimeout(timer);
    if (PROCESSING.includes(s.status)) timer = setTimeout(() => load().catch(renderError), 4000);
  }

  async function exportMd(s) {
    const md = await Sessions.exportMd(id);
    const name = `${(s.code ? s.code + "-" : "") + s.title}`.replace(/[^\w\-áéíóúñÁÉÍÓÚÑ ]+/g, "").trim().replace(/\s+/g, "-") + ".md";
    const file = new File([md], name, { type: "text/markdown" });
    if (navigator.canShare?.({ files: [file] })) { try { await navigator.share({ files: [file], title: s.title }); return; } catch {} }
    const a = h("a", { href: URL.createObjectURL(file), download: name });
    document.body.append(a); a.click(); a.remove();
  }

  cleanup = () => clearTimeout(timer);
  await load();
}

// --- ajustes -----------------------------------------------------------------
function viewSettings() {
  const input = h("input", { id: "token", type: "password", value: getToken(), autocomplete: "off", placeholder: "El APP_TOKEN de Railway" });
  const status = h("div");
  const pending = h("p", { class: "caption" });
  store.allChunks().then((c) => (pending.textContent = c.length ? `${c.length} pedazos de audio esperando subir.` : "No hay audio pendiente de subir."));
  view.append(h("form", { class: "stack-lg", onsubmit: async (e) => {
    e.preventDefault();
    setToken(input.value.trim());
    try {
      await api("/api/me");
      status.replaceChildren(StatusPill("ready", "Conectado"));
      store.persist();
      setTimeout(() => (location.hash = "#/"), 600);
    } catch (err) { status.replaceChildren(h("div", { class: "notice err" }, err.status === 401 ? "Token inválido." : err.message)); }
  } },
    h("h1", { class: "title" }, "Ajustes"),
    h("div", { class: "field" }, h("label", { class: "label", for: "token" }, "Token de acceso"), input),
    h("div", { class: "actions" }, h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Guardar y probar")),
    status, pending,
    h("p", { class: "caption" }, "Tip: instalá la app (menú de Chrome → Agregar a pantalla principal) y desactivá la optimización de batería de Chrome antes de una keynote larga.")));
}

// --- arranque ----------------------------------------------------------------
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
route();
