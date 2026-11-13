// ReinventAR — router y pantallas.
import { ApiError, Auth, Sessions, getToken, mustChangePassword, setMustChangePassword, setToken } from "./api.js";
import { viewAdmin, viewPassword } from "./account.js";
import { confirmDialog } from "./dialog.js";
import { icon } from "./icons.js";
import { InstallPrompt } from "./install.js";
import { disable as disablePush } from "./notifications.js";
import { viewEvento, viewEventos } from "./events.js";
import { viewPerdida } from "./missed.js";
import { viewGrabarCharla } from "./grabarCharla.js";
import { viewCharla, viewEmpresa, viewSpeaker } from "./knowledge.js";
import { PasskeyLoginButton, PasskeyOffer, PasskeySettings } from "./passkey.js";
import { refreshChanges } from "./changes.js";
import { refreshCountdown } from "./countdown.js";
import { RecordingSearch } from "./grabado.js";
import { clearPageBar, viewDetail } from "./detail.js";
import { alertSettings, locationEnabled, reportVenue, saveAlertSettings, setLocationEnabled } from "./location.js";
import { PushSettings } from "./notifications.js";
import { refreshSandbox } from "./sandbox.js";
import { viewSearch } from "./search.js";
import { TalkPicker } from "./talkpicker.js";
import { TodayPanel } from "./today.js";
import * as it from "./itinerary.js";
import { viewArmar } from "./dayBuilder.js";
import { viewEntrevista, viewFicha } from "./interview.js";
import { viewMiEvento } from "./myEvents.js";
import { Recorder, listMics, pickDjI, preferredMic, uploader, wakeLock } from "./recorder.js";
import * as store from "./store.js";
import { Button, LevelMeter, METER_SILENT, RecordButton, SessionCard, Skeleton, StatusPill, h, hms, toast, toastOnError } from "./ui.js";

const view = document.getElementById("view");
const KINDS = ["Keynote", "Chalk talk", "Workshop", "Breakout"];
let cleanup = () => {};
let activeRecorder = null;

// --- tema --------------------------------------------------------------------
const THEME = "reinventar.theme";
const THEME_COLOR = { light: "#f4f4f4", dark: "#111111" };
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

// --- encabezado pegado arriba ---------------------------------------------------
// Lo que se pega debajo (pestañas del detalle) usa --masthead-h: el alto real de franjas + barra, que cambia con el
// notch y cuando aparece una franja. Antes estaba fijo en 68 px y las pestañas quedaban tapadas.
const masthead = document.getElementById("masthead");
if (masthead && "ResizeObserver" in window) {
  new ResizeObserver(() => document.documentElement.style.setProperty("--masthead-h", `${masthead.offsetHeight}px`)).observe(masthead);
}

// --- router ------------------------------------------------------------------
const routes = [
  [/^#\/?$/, viewList],
  [/^#\/login$/, viewLogin],
  [/^#\/nueva$/, viewNew],
  [/^#\/ajustes$/, viewSettings],
  [/^#\/password$/, () => viewPassword(view, { forced: mustChangePassword() })],
  [/^#\/admin$/, () => viewAdmin(view)],
  [/^#\/grabar\/([\w-]+)$/, viewRecord],
  [/^#\/grabar-charla\/([^/?#]+)$/, (code) => viewGrabarCharla(view, code)],
  [/^#\/s\/([\w-]+)(?:\/t\/(\d+)(?:\?q=([^&#]*))?)?$/, (id, at, q) => viewDetail(view, id, {
    at, q: q ? decodeURIComponent(q) : "", canGoBack: navigatedInApp, setCleanup: (fn) => { cleanup = fn; }, onError: renderError })],
  [/^#\/itinerario$/, () => it.viewItinerario(view)],
  [/^#\/eventos$/, () => viewEventos(view)],
  [/^#\/perdida\/([^/?#]+)$/, (code) => viewPerdida(view, code)],
  [/^#\/evento\/([^/?#]+)$/, (code) => viewEvento(view, code)],
  [/^#\/itinerario\/cuestionario$/, () => it.viewCuestionario(view)],
  [/^#\/itinerario\/nuevo$/, () => it.viewNuevoItinerario(view)],
  [/^#\/itinerario\/entrevista$/, () => viewEntrevista(view)],
  [/^#\/itinerario\/ficha$/, () => viewFicha(view)],
  [/^#\/itinerario\/armar$/, () => viewArmar(view)],
  [/^#\/mi-evento\/nuevo$/, () => viewMiEvento(view)],
  [/^#\/mi-evento\/([\w-]+)$/, (id) => viewMiEvento(view, id)],
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
let navigatedInApp = false; // Volver del detalle usa el historial solo si se llegó navegando dentro de la app
let routedOnce = false;
async function route() {
  if (ignoreNextHash) { ignoreNextHash = false; return; }
  if (activeRecorder && ["recording", "paused"].includes(activeRecorder.state) && !location.hash.startsWith("#/grabar/")) {
    const leave = await confirmDialog("¿Salir de la grabación?", { text: "Estás grabando: si salís, la grabación se detiene.", confirmLabel: "Salir y detener", cancelLabel: "Seguir grabando", danger: true });
    if (!leave) { ignoreNextHash = true; history.back(); return; }
    await activeRecorder.stop(); activeRecorder.close(); activeRecorder = null;
  }
  cleanup(); cleanup = () => {};
  clearPageBar();
  navigatedInApp = routedOnce;
  routedOnce = true;
  const hash = location.hash || "#/";
  if (!getToken() && hash !== "#/login") { location.hash = "#/login"; return; }
  if (getToken() && mustChangePassword() && hash !== "#/password") { location.hash = "#/password"; return; }
  markNav(hash);
  await refreshSandbox(); // antes de dibujar: la hora y la ubicación simuladas se usan en las pantallas
  void refreshCountdown();
  void refreshChanges();
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
  // Lugares que pueden quedar vacíos (subida pendiente, buscador): .ra-optional:empty no ocupa lugar ni suma espacio.
  const banner = h("div", { class: "ra-optional" });
  const searchSlot = h("div", { class: "ra-optional" });
  const todaySlot = h("div", {}, h("div", { class: "ra-skel ra-skel-today" }));
  // "Nueva" es la acción de la sección (botón chico en su encabezado), no un botón grande suelto.
  const newBtn = h("a", { class: "ra-btn ra-btn-ghost ra-sec-action", href: "#/nueva", "aria-label": "Nueva grabación" },
    icon("agregar", 16), h("span", {}, "Nueva"));
  view.append(h("div", { class: "stack-lg" },
    h("h1", { class: "sr-only" }, "Inicio"),
    todaySlot,
    InstallPrompt({ dismissible: true }), PasskeyOffer(),
    h("section", { class: "stack", "aria-labelledby": "grabaciones-title" },
      h("div", { class: "ra-sec-head" }, h("h2", { class: "label", id: "grabaciones-title" }, "Tus grabaciones"), newBtn),
      banner, searchSlot, list)));

  const showPending = ({ pending, error }) => banner.replaceChildren(
    pending ? h("div", { class: "notice upl" }, StatusPill("uploading", `Subiendo ${pending}`), h("span", { class: "caption" }, error || "En segundo plano")) : "");
  const onUp = (e) => showPending(e.detail);
  uploader.addEventListener("change", onUp);
  let search = null;
  cleanup = () => { uploader.removeEventListener("change", onUp); search?.dispose(); };
  toastOnError(uploader.refresh()); uploader.kick();

  const sessions = await Sessions.list();
  // Buscar en lo grabado: solo tiene sentido cuando hay alguna grabación procesada.
  if (sessions.some((s) => s.status === "ready")) searchSlot.replaceChildren(search = RecordingSearch());
  TodayPanel(sessions)
    .then(({ el }) => todaySlot.replaceChildren(el))
    .catch((err) => todaySlot.replaceChildren(h("p", { class: "caption" }, `No se pudo cargar Hoy: ${err.message}`)));
  list.replaceChildren();
  if (!sessions.length) {
    list.append(h("div", { class: "empty" }, h("p", {}, "Todavía no grabaste ninguna sesión."), h("p", { class: "caption" }, "Conectá el receptor del DJI al celular y tocá Nueva.")));
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
const SILENCE_WARN_MS = 8000;  // grabando sin sonido este rato → aviso visible

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
      h("div", { class: "field" }, h("label", { class: "label", for: "mic" }, "Micrófono"), micSelect), meter, silence),
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
  // Si mientras graba no llega sonido por un rato, se avisa arriba: el medidor solo dice "Sin señal" en chico.
  const silence = h("div", { class: "notice warn", role: "alert", hidden: true },
    "No llega sonido al micrófono. Revisá cuál está elegido; con auriculares, no oye lo que suena en el mismo equipo.");
  let quietSince = null;
  rec.addEventListener("level", (e) => {
    meter.update(e.detail, rec.deviceLabel);
    const quiet = rec.state === "recording" && e.detail < METER_SILENT;
    quietSince = quiet ? (quietSince ?? performance.now()) : null;
    silence.hidden = !(quiet && performance.now() - quietSince > SILENCE_WARN_MS);
  });
  rec.addEventListener("error", (e) => { msg.replaceChildren(h("div", { class: "notice err" }, e.detail.message)); });
  const onUp = (e) => {
    const { pending, error } = e.detail;
    upl.replaceChildren(pending ? StatusPill("uploading", `Subiendo ${pending}`) : StatusPill("ready", "Todo subido"), h("span", { class: "caption" }, error || ""));
  };
  uploader.addEventListener("change", onUp);
  toastOnError(uploader.refresh());
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
    void openMic(micSelect.value);
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
    if (rec.state === "recording") void wakeLock.acquire();
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

// --- login -------------------------------------------------------------------
function finishLogin(r) {
  setToken(r.token);
  setMustChangePassword(r.must_change_password);
  void store.persist();
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
function AlertSettings() {
  const s = alertSettings();
  const number = (id, value, key) => h("input", { type: "number", id, min: 0, max: 60, value, inputmode: "numeric",
    onchange: (e) => { saveAlertSettings({ [key]: Math.max(0, Math.min(60, Number(e.target.value) || 0)) }); toast("Alertas guardadas"); } });
  return h("div", { class: "stack" },
    h("h2", { class: "label" }, "Alertas"),
    h("label", { class: "field" }, h("span", { class: "label" }, "Margen para salir (min)"), number("leave-margin", s.leaveMarginMin, "leaveMarginMin")),
    h("label", { class: "field" }, h("span", { class: "label" }, "Aviso de inicio (min antes)"), number("start-notice", s.startNoticeMin, "startNoticeMin")),
    h("p", { class: "caption" }, "Para lo que fijaste en el itinerario: la franja de arriba cuenta cuánto falta y te avisa cuándo salir y cuándo empieza."));
}

function LocationSetting() {
  const box = h("input", { type: "checkbox", id: "use-location", checked: locationEnabled(),
    onchange: () => { setLocationEnabled(box.checked); toast(box.checked ? "Vas a ver distancias y tiempo caminando" : "Ubicación apagada"); } });
  return h("div", { class: "stack" },
    h("label", { class: "actions is-center", for: "use-location" }, box, "Usar mi ubicación"),
    h("p", { class: "caption" }, "Para mostrar a cuánto queda cada charla y cuándo salir. Tu ubicación se usa solo en este celular: no se guarda ni se manda al servidor. \"Llevame\" abre Google Maps igual aunque la apagues."));
}

async function viewSettings() {
  const pending = h("p", { class: "caption" });
  store.allChunks()
    .then((c) => (pending.textContent = c.length ? `${c.length} pedazos de audio esperando subir.` : "No hay audio pendiente de subir."))
    .catch(() => (pending.textContent = "No se pudo leer el audio pendiente."));

  let me = {};
  try { me = await Auth.me(); } catch {}
  const username = me.username || "";

  async function logout() {
    try { await disablePush(); } catch {}  // antes de borrar el token: la baja necesita la sesión
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
    LocationSetting(),
    AlertSettings(),
    PushSettings(),
    PasskeySettings(),
    InstallPrompt(),
    pending,
    h("p", { class: "caption" }, "Tip: en Android, desactivá la optimización de batería de Chrome antes de una keynote larga.")));
}

// --- arranque ----------------------------------------------------------------
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
// Sede reciente para el recordatorio "¿la grabás?": solo con la app abierta (una PWA no tiene GPS en segundo plano).
const reportVenueIfLoggedIn = () => { if (getToken() && !mustChangePassword()) void reportVenue(); };
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") reportVenueIfLoggedIn(); });
await route();
reportVenueIfLoggedIn();
