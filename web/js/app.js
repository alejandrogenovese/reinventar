// ReinventAR — router y pantallas.
import { ApiError, Auth, Sessions, getToken, mustChangePassword, setMustChangePassword, setToken } from "./api.js";
import { viewAdmin, viewPassword } from "./account.js";
import { confirmDialog } from "./dialog.js";
import { icon } from "./icons.js";
import { InstallPrompt } from "./install.js";
import { viewCharla, viewEmpresa, viewSpeaker } from "./knowledge.js";
import { PasskeyLoginButton, PasskeyOffer, PasskeySettings } from "./passkey.js";
import { viewSearch } from "./search.js";
import { TalkPicker } from "./talkpicker.js";
import { TodayPanel } from "./today.js";
import * as it from "./itinerary.js";
import { Recorder, listMics, pickDjI, preferredMic, uploader, wakeLock } from "./recorder.js";
import * as store from "./store.js";
import { Button, LevelMeter, RecordButton, SessionCard, Skeleton, StatusPill, SummaryPanel, TranscriptBlock, h, hms, toast } from "./ui.js";

const view = document.getElementById("view");
const KINDS = ["Keynote", "Chalk talk", "Workshop", "Breakout"];
const PROCESSING = ["queued", "transcribing", "translating", "summarizing"];
let cleanup = () => {};
const kids = (...xs) => xs.filter((x) => x != null && x !== false);
let activeRecorder = null;

// --- tema --------------------------------------------------------------------
const THEME = "reinventar.theme";
const THEME_COLOR = { light: "#f4f4f4", dark: "#121212" };
for (const slot of document.querySelectorAll("[data-icon]")) slot.replaceWith(icon(slot.dataset.icon));
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  document.querySelector('meta[name="theme-color"]').content = THEME_COLOR[t];
  // El botón muestra a qué tema pasás: luna en claro, sol en oscuro.
  const next = t === "dark" ? "claro" : "oscuro";
  const btn = document.getElementById("themeBtn");
  btn.replaceChildren(icon(next));
  btn.setAttribute("aria-label", `Cambiar a tema ${next}`);
  btn.title = `Tema ${next}`;
}
// El <head> ya puso el tema (elegido o el del sistema); acá solo se sincroniza la barra del navegador.
applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
document.getElementById("themeBtn").addEventListener("click", () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(t); try { localStorage.setItem(THEME, t); } catch {}
});

// --- router ------------------------------------------------------------------
const routes = [
  [/^#\/?$/, viewList],
  [/^#\/login$/, viewLogin],
  [/^#\/nueva$/, viewNew],
  [/^#\/ajustes$/, viewSettings],
  [/^#\/password$/, () => viewPassword(view, { forced: mustChangePassword() })],
  [/^#\/admin$/, () => viewAdmin(view)],
  [/^#\/grabar\/([\w-]+)$/, viewRecord],
  [/^#\/s\/([\w-]+)$/, viewDetail],
  [/^#\/itinerario$/, () => it.viewItinerario(view)],
  [/^#\/itinerario\/cuestionario$/, () => it.viewCuestionario(view)],
  [/^#\/buscar(\?.*)?$/, async () => { cleanup = await viewSearch(view); }],
  // Rutas viejas: Explorar y Preguntar ahora son los dos modos de Buscar.
  [/^#\/itinerario\/explorar$/, () => location.replace("#/buscar")],
  [/^#\/explorar(\?.*)?$/, (qs = "") => location.replace(`#/buscar${qs}`)],
  [/^#\/preguntar$/, () => location.replace("#/buscar?modo=preguntar")],
  [/^#\/charla\/([\w-]+)$/, (base) => viewCharla(view, base)],
  [/^#\/speaker\/(\d+)$/, (id) => viewSpeaker(view, id)],
  [/^#\/empresa\/(\d+)$/, (id) => viewEmpresa(view, id)],
];

const SKELETON_DELAY_MS = 150; // si la pantalla carga más rápido, no se muestra (evita el parpadeo)

/** Muestra un skeleton mientras la pantalla no tenga contenido propio; devuelve la función para sacarlo. */
function skeletonUntilContent() {
  const sk = Skeleton();
  const timer = setTimeout(() => { if (!view.childElementCount) view.append(sk); }, SKELETON_DELAY_MS);
  const obs = new MutationObserver(() => { if ([...view.children].some((c) => c !== sk)) done(); });
  obs.observe(view, { childList: true });
  function done() { clearTimeout(timer); obs.disconnect(); sk.remove(); }
  return done;
}

const APP_NAME = "ReinventAR";
let firstScreen = true;

/**
 * Tras cambiar de pantalla: título de la pestaña con el de la pantalla y foco en su h1, así el lector de
 * pantalla anuncia dónde estás (en vez de leer todo con aria-live). En la primera carga no se mueve el foco.
 */
function announceScreen() {
  const h1 = view.querySelector("h1");
  document.title = h1 ? `${h1.textContent} · ${APP_NAME}` : APP_NAME;
  if (firstScreen) { firstScreen = false; return; }
  if (view.contains(document.activeElement) && document.activeElement !== view) return; // la pantalla ya enfocó algo (ej. un campo)
  const target = h1 || view;
  if (target !== view) target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}

// "Saltar al contenido": el href #view se usa sin tocar el hash (el router lo tomaría como ruta).
document.querySelector(".skip-link").addEventListener("click", (e) => { e.preventDefault(); view.focus(); });

/** Marca la sección actual (aria-current: se ve y lo anuncia el lector de pantalla); sin sesión se oculta la nav. */
function markNav(hash) {
  document.body.classList.toggle("is-guest", !getToken());
  for (const a of document.querySelectorAll(".topbar [data-match]")) {
    if (new RegExp(a.dataset.match).test(hash)) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

let ignoreNextHash = false;
async function route() {
  if (ignoreNextHash) { ignoreNextHash = false; return; }
  if (activeRecorder && ["recording", "paused"].includes(activeRecorder.state) && !location.hash.startsWith("#/grabar/")) {
    const leave = await confirmDialog("¿Salir de la grabación?", { text: "Estás grabando: si salís, la grabación se detiene.", confirmLabel: "Salir y detener", cancelLabel: "Seguir grabando", danger: true });
    if (!leave) { ignoreNextHash = true; history.back(); return; }
    await activeRecorder.stop(); activeRecorder.close(); activeRecorder = null;
  }
  cleanup(); cleanup = () => {};
  const hash = location.hash || "#/";
  if (!getToken() && hash !== "#/login") { location.hash = "#/login"; return; }
  if (getToken() && mustChangePassword() && hash !== "#/password") { location.hash = "#/password"; return; }
  markNav(hash);
  for (const [re, fn] of routes) {
    const m = hash.match(re);
    if (m) {
      view.replaceChildren();
      const hideSkeleton = skeletonUntilContent();
      try { await fn(...m.slice(1)); } catch (e) { renderError(e); } finally { hideSkeleton(); }
      window.scrollTo(0, 0);
      announceScreen();
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (e) => { if (activeRecorder?.state === "recording" || activeRecorder?.state === "paused") e.preventDefault(); });

function renderError(e) {
  console.error(e);
  if (e instanceof ApiError && e.status === 401) { setToken(""); location.hash = "#/login"; return; }
  view.replaceChildren(h("div", { class: "notice err" }, e.message || String(e)));
}

// --- lista -------------------------------------------------------------------
async function viewList() {
  // Los dos bloques que llegan de la API reservan su lugar con un skeleton: así no empujan la pantalla (CLS).
  const list = h("div", { class: "stack" }, h("div", { class: "ra-skel ra-skel-card" }));
  const banner = h("div");
  const todaySlot = h("div", {}, h("div", { class: "ra-skel ra-skel-today" }));
  const newBtn = Button("Nueva sesión", { variant: "primary", onclick: () => (location.hash = "#/nueva") });
  view.append(h("div", { class: "stack-lg" },
    h("h1", { class: "sr-only" }, "Inicio"),
    todaySlot,
    h("div", { class: "actions" }, newBtn),
    InstallPrompt({ dismissible: true }), PasskeyOffer(), banner,
    h("h2", { class: "label" }, "Tus grabaciones"), list));

  const showPending = ({ pending, error }) => banner.replaceChildren(
    pending ? h("div", { class: "notice upl" }, StatusPill("uploading", `Subiendo ${pending}`), h("span", { class: "caption" }, error || "En segundo plano")) : "");
  const onUp = (e) => showPending(e.detail);
  uploader.addEventListener("change", onUp);
  cleanup = () => uploader.removeEventListener("change", onUp);
  uploader.refresh(); uploader.kick();

  const sessions = await Sessions.list();
  TodayPanel(sessions)
    .then(({ el, hasTalk }) => {
      todaySlot.replaceChildren(el);
      // Un solo botón primario: si hay una charla para grabar, "Nueva sesión" pasa a secundario.
      if (hasTalk) newBtn.className = "ra-btn ra-btn-secondary";
    })
    .catch((err) => todaySlot.replaceChildren(h("p", { class: "caption" }, `No se pudo cargar Hoy: ${err.message}`)));
  list.replaceChildren();
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
    TalkPicker({ onPick: (talk) => fillFromTalk(form, talk) }),
    h("fieldset", { class: "fieldset-plain" }, h("legend", { class: "label" }, "Tipo"), h("div", { class: "segmented" }, radios)),
    field("Título", h("input", { id: "title", name: "title", required: true, maxlength: "200", placeholder: "Keynote de apertura", autocomplete: "off" })),
    field("Código de agenda", h("input", { id: "code", name: "code", maxlength: "40", placeholder: "ANT301", autocapitalize: "characters", autocomplete: "off" })),
    field("Sala", h("input", { id: "venue", name: "venue", maxlength: "120", placeholder: "Venetian · Hall A", autocomplete: "off" })),
    field("Speakers", h("input", { id: "speaker", name: "speaker", maxlength: "200", autocomplete: "off" })),
    h("div", { class: "actions" }, h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Preparar grabación")));
  view.append(form);
  form.querySelector("#title").focus();
}

/** Completa el formulario con la charla elegida (los campos siguen siendo editables); null = solo desvincula. */
function fillFromTalk(form, talk) {
  const set = (name, value, max) => { form.elements[name].value = (value || "").slice(0, max); };
  if (!talk) { set("code", "", 40); return; }
  const names = (talk.people || []).map((p) => p.name).join(", ") || talk.speakers;
  set("title", talk.title, 200);
  set("code", talk.code, 40);
  set("venue", [talk.venue?.hotel, talk.venue?.detail].filter(Boolean).join(" · "), 120);
  set("speaker", names, 200);
  const radio = form.querySelector(`input[name=kind][value="${talk.recording_kind}"]`);
  if (radio) radio.checked = true;
}

// --- grabación ---------------------------------------------------------------
async function viewRecord(id) {
  const s = await Sessions.get(id);
  if (!["recording", "uploading", "error"].includes(s.status) || s.blocks?.length) { location.hash = `#/s/${id}`; return; }

  const rec = new Recorder(id);
  activeRecorder = rec;
  const counter = h("div", { class: "counter", "aria-live": "off" }, hms(rec.elapsed() / 1000));
  const recStatus = h("p", { class: "ra-recstatus", role: "status" });
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
    h("section", { class: "ra-input", "aria-label": "Entrada de audio" },
      h("div", { class: "field" }, h("label", { class: "label", for: "mic" }, "Micrófono"), micSelect), meter),
    h("div", { class: "recorder" }, h("div", { class: "ra-clock" }, counter, recStatus), recSlot, upl, msg,
      h("div", { class: "actions" }, salaBtn, finishBtn),
      h("div", { class: "actions" }, Button("Descartar", { variant: "danger", onclick: discard })))));

  const REC_STATUS = { idle: "Listo para grabar", stopped: "Listo para grabar", recording: "Grabando", paused: "En pausa" };
  const paint = () => {
    recSlot.replaceChildren(RecordButton(rec.state === "stopped" ? "idle" : rec.state, toggle));
    counter.dataset.state = rec.state;
    recStatus.dataset.state = rec.state;
    recStatus.textContent = REC_STATUS[rec.state] || "";
  };
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
    if (!await confirmDialog("¿Descartar esta grabación?", { text: "Se borra el audio del celular y del servidor. No se puede deshacer.", confirmLabel: "Descartar", danger: true })) return;
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
      s.talk ? h("p", {}, h("a", { class: "ra-link", href: `#/charla/${s.talk.base}` }, `Ficha de la charla: ${s.talk.title}`)) : null,
      h("div", { class: "actions is-center" }, StatusPill(s.status, s.progress || undefined), meta ? h("span", { class: "caption" }, meta) : null),
      s.error ? h("div", { class: "notice err" }, s.error) : null));

    actions.replaceChildren(...kids(
      s.status === "ready" ? Button("Exportar .md", { onclick: () => exportMd(s) }) : null,
      s.status === "error" ? Button("Reintentar", { variant: "primary", onclick: async () => { await Sessions.retry(id); load(); } }) : null,
      ["recording", "uploading"].includes(s.status) ? Button("Seguir grabando", { variant: "primary", onclick: () => (location.hash = `#/grabar/${id}`) }) : null,
      Button("Eliminar", { variant: "danger", onclick: async () => {
        if (!await confirmDialog("¿Eliminar la sesión?", { text: "Se borran el audio, la transcripción y el resumen. No se puede deshacer.", confirmLabel: "Eliminar", danger: true })) return;
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

// --- login -------------------------------------------------------------------
function finishLogin(r) {
  setToken(r.token);
  setMustChangePassword(r.must_change_password);
  store.persist();
  location.hash = r.must_change_password ? "#/password" : "#/";
}

function viewLogin() {
  const userInput = h("input", { id: "username", name: "username", required: true, autocomplete: "username", autocapitalize: "none" });
  const passInput = h("input", { id: "password", name: "password", type: "password", required: true, autocomplete: "current-password" });
  const status = h("div");
  const form = h("form", { class: "stack-lg", onsubmit: async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    status.replaceChildren();
    try {
      finishLogin(await Auth.login(userInput.value.trim(), passInput.value));
    } catch (err) {
      status.replaceChildren(h("div", { class: "notice err" }, err.status === 401 ? "Usuario o contraseña inválidos." : err.message));
      btn.disabled = false;
    }
  } },
    h("h1", { class: "title" }, "Ingresá a ReinventAR"),
    h("div", { class: "field" }, h("label", { class: "label", for: "username" }, "Usuario"), userInput),
    h("div", { class: "field" }, h("label", { class: "label", for: "password" }, "Contraseña"), passInput),
    h("div", { class: "actions" }, h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Entrar")),
    status);
  const passkey = PasskeyLoginButton(finishLogin, (msg) => status.replaceChildren(h("div", { class: "notice err" }, msg)));
  view.append(form, passkey);
  userInput.focus();
}

// --- ajustes -----------------------------------------------------------------
async function viewSettings() {
  const pending = h("p", { class: "caption" });
  store.allChunks().then((c) => (pending.textContent = c.length ? `${c.length} pedazos de audio esperando subir.` : "No hay audio pendiente de subir."));

  let me = {};
  try { me = await Auth.me(); } catch {}
  const username = me.username || "";

  async function logout() {
    try { await Auth.logout(); } catch {}
    setToken("");
    location.hash = "#/login";
  }

  view.append(h("div", { class: "stack-lg" },
    h("h1", { class: "title" }, "Ajustes"),
    h("p", {}, username ? `Conectado como ${username}.` : "Sesión no válida."),
    h("div", { class: "actions" },
      Button("Cambiar contraseña", { onclick: () => (location.hash = "#/password") }),
      me.is_admin ? Button("Administración", { onclick: () => (location.hash = "#/admin") }) : null,
      Button("Cerrar sesión", { variant: "danger", onclick: logout })),
    PasskeySettings(),
    InstallPrompt(),
    pending,
    h("p", { class: "caption" }, "Tip: en Android, desactivá la optimización de batería de Chrome antes de una keynote larga.")));
}

// --- arranque ----------------------------------------------------------------
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
route();
