// Cliente de la API. El token de sesión (lo da /api/login) vive en localStorage de este celular.
import { borrarDocsLocales } from "./docsLocal.js";
import { clearLast, loadLast, markStale, saveLast } from "./lastgood.js";

const KEY = "reinventar.token";

const MUST_CHANGE = "reinventar.mustChangePassword";
const MUST_MAIL = "reinventar.debeCargarMail";

export function getToken() { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } }
export function setToken(t) {
  try { localStorage.setItem(KEY, t); } catch {}
  if (!t) { // cerrar sesión: las copias sin señal y los documentos guardados son de esa persona y no se quedan en el celular
    setDebeCargarMail(false);
    clearLast();
    void borrarDocsLocales();
  }
  // Avisa que hay un token nuevo: notifications.js se lo deja al service worker (pushsubscriptionchange con la app cerrada).
  try { globalThis.window?.dispatchEvent(new Event("reinventar:token")); } catch {}
}
// Lo informa el login: mientras esté en true, el router manda a #/password.
export function mustChangePassword() { try { return localStorage.getItem(MUST_CHANGE) === "1"; } catch { return false; } }
export function setMustChangePassword(v) { try { localStorage.setItem(MUST_CHANGE, v ? "1" : "0"); } catch {} }
// Lo informan el login y /api/me: mientras no tenga el mail verificado, el router manda a #/mail (no se puede saltear).
export function debeCargarMail() { try { return localStorage.getItem(MUST_MAIL) === "1"; } catch { return false; } }
export function setDebeCargarMail(v) { try { localStorage.setItem(MUST_MAIL, v ? "1" : "0"); } catch {} }

export class ApiError extends Error {
  constructor(status, detail) { super(typeof detail === "string" ? detail : detail?.message || `HTTP ${status}`); this.status = status; this.detail = detail; }
}

// Sin red, fetch tira un TypeError con texto del navegador en inglés («Failed to fetch», «Load failed»).
export const MSG_SIN_CONEXION = "Sin conexión: revisá la señal y probá de nuevo.";

// Un 200 que no es JSON: casi siempre el portal cautivo del Wi-Fi (hotel, salón) o un proxy que contesta con su HTML.
// Se trata como falta de señal (status 0): la última copia guardada se muestra igual. Sin esto salía el SyntaxError del
// navegador, en inglés y sin explicación.
export const MSG_PORTAL_CAUTIVO = "La red del lugar parece pedir que inicies sesión (Wi-Fi con portal) y no deja pasar la app. Probá con datos del celular.";
export const MSG_RESPUESTA_INVALIDA = "El servidor contestó algo que no pudimos leer. Probá de nuevo en un rato.";

// ¿Lo que llegó parece la página de un portal? Por el tipo de contenido, por venir redirigido de otro sitio o porque el
// cuerpo empieza con «<».
async function parecePortal(r, texto) {
  if (/html/i.test(r.headers?.get?.("content-type") ?? "")) return true;
  if (r.redirected) {
    try { if (new URL(r.url).origin !== location.origin) return true; } catch { return true; }
  }
  try { return /^\s*</.test(texto ?? (await r.clone?.().text()) ?? ""); } catch { return false; }
}

/** El cuerpo como JSON; si no lo es, un ApiError en castellano (nunca el SyntaxError del navegador). */
async function leerJson(r) {
  let texto = null;
  try {
    if (typeof r.text !== "function") return await r.json();
    texto = await r.text();
    return JSON.parse(texto);
  } catch (e) {
    if (e?.name === "AbortError") throw e; // cancelado a propósito: quien llama lo ignora
    if (e instanceof TypeError || e?.name === "TimeoutError") throw new ApiError(0, MSG_SIN_CONEXION); // se cortó leyendo el cuerpo
    throw (await parecePortal(r, texto)) ? new ApiError(0, MSG_PORTAL_CAUTIVO) : new ApiError(502, MSG_RESPUESTA_INVALIDA);
  }
}

async function pedir(path, init) {
  try { return await fetch(path, init); } catch (e) {
    if (e?.name === "AbortError") throw e; // cancelado a propósito: quien llama lo ignora
    throw new ApiError(0, MSG_SIN_CONEXION); // status 0: la subida de pedazos lo sigue tomando como reintentable
  }
}

export async function api(path, { method = "GET", json, body, headers = {}, raw = false, signal } = {}) {
  const h = { Authorization: `Bearer ${getToken()}`, ...headers };
  if (json !== undefined) { h["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  const r = await pedir(path, { method, headers: h, body, signal });
  if (!r.ok) {
    let detail; try { detail = (await r.json()).detail; } catch { detail = r.statusText; }
    // El servidor exige cambiar la contraseña temporal antes de usar el resto de la API.
    if (r.status === 403 && detail === "must_change_password") { setMustChangePassword(true); location.hash = "#/password"; }
    throw new ApiError(r.status, detail);
  }
  return raw ? r : leerJson(r);
}

// Sin señal en los salones: Hoy, Itinerario y grabaciones muestran la última respuesta buena en vez de quedar vacías.
// Con copia guardada, la red tiene un tope: un Wi-Fi que conecta pero no responde no deja la pantalla esperando.
const SIN_SENAL_TIMEOUT_MS = 8000;
export const sinServicio = (e) => e instanceof ApiError && (e.status === 0 || e.status >= 500); // sin red o servidor caído (no 401/403/404)

// De quién es la copia: los primeros 12 hex del SHA-256 del token. El nombre de la clave queda a la vista (DevTools,
// backups), así que nunca lleva un pedazo del token en sí. Sin token (o sin crypto.subtle) no hay dueño ni copia.
let dueno = { token: "", valor: null };
export async function duenoDeCopias() {
  const token = getToken();
  if (!token) return null;
  if (dueno.token === token) return dueno.valor;
  let valor = null;
  try {
    const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token)));
    valor = Array.from(hash.slice(0, 6), (b) => b.toString(16).padStart(2, "0")).join("");
  } catch { /* contexto sin crypto.subtle: se sigue sin copia */ }
  dueno = { token, valor };
  return valor;
}

// El banner de estado (estadoBanner.js) se entera así de que una pantalla cayó a la última copia («ra:sin-servicio», con
// la hora de esa copia) y de que la API volvió a contestar («ra:con-servicio»). Sin window (tests de node) no pasa nada.
export const EVENTO_SIN_SERVICIO = "ra:sin-servicio";
export const EVENTO_CON_SERVICIO = "ra:con-servicio";
function avisarServicio(tipo, detail) {
  try { globalThis.window?.dispatchEvent(new CustomEvent(tipo, { detail })); } catch { /* sin banner: no pasa nada */ }
}

/** GET que guarda la respuesta buena y, si no hay señal, devuelve la última (marcada con staleAt). */
export async function apiConUltimaCopia(path) {
  const de = await duenoDeCopias();
  const copia = de ? loadLast(de, path) : null;
  try {
    const data = await api(path, copia ? { signal: AbortSignal.timeout?.(SIN_SENAL_TIMEOUT_MS) } : {});
    if (de) saveLast(de, path, data);
    avisarServicio(EVENTO_CON_SERVICIO, { path });
    return data;
  } catch (e) {
    if (!copia || !sinServicio(e)) throw e;
    avisarServicio(EVENTO_SIN_SERVICIO, { path, at: copia.at, status: e.status });
    return markStale(copia.data, copia.at);
  }
}

// La copia de la lista de grabaciones solo se renovaba al abrir Inicio con red: lo grabado entre una visita y otra no estaba y
// sin señal Inicio mostraba una lista vieja (o vacía, con «Todavía no grabaste…»). Tras crear, cerrar o borrar una grabación
// se vuelve a pedir la lista en segundo plano; si falla (sin red), no pasa nada y se sigue con lo que había.
const refrescarLista = (r) => { void Sessions.list().catch(() => {}); return r; };

export const Sessions = {
  list: () => apiConUltimaCopia("/api/sessions"),
  get: (id) => api(`/api/sessions/${id}`),
  create: (data) => api("/api/sessions", { method: "POST", json: data }).then(refrescarLista),
  putChunk: (id, part, seq, blob, signal) => api(`/api/sessions/${id}/chunks/${part}/${seq}`, { method: "PUT", body: blob, headers: { "Content-Type": "application/octet-stream" }, signal }),
  finish: (id, parts) => api(`/api/sessions/${id}/finish`, { method: "POST", json: { parts } }).then(refrescarLista),
  huecos: (id, huecos) => api(`/api/sessions/${id}/huecos`, { method: "POST", json: { huecos } }),  // tramos sin audio: reemplaza la lista
  retry: (id, fromScratch = false) => api(`/api/sessions/${id}/retry?from_scratch=${fromScratch}`, { method: "POST" }),
  remove: (id) => api(`/api/sessions/${id}`, { method: "DELETE" }).then(refrescarLista),
  exportMd: (id) => api(`/api/sessions/${id}/export.md`, { raw: true }).then((r) => r.text()),
  resumenMd: (id) => api(`/api/sessions/${id}/resumen.md`, { raw: true }).then((r) => r.text()), // sin lo personal: para compartir
  compartir: (id) => api(`/api/sessions/${id}/compartir`, { method: "POST" }), // {url, vence}: link público de solo lectura
  activa: (code, signal) => api(`/api/sessions/activa?code=${encodeURIComponent(code)}`, { signal }), // ¿alguien más ya la graba?
  search: (q, signal) => api(`/api/grabaciones/buscar?q=${encodeURIComponent(q)}`, { signal }),
  votar: (id, util) => api(`/api/sessions/${id}/voto`, { method: "PUT", json: { util } }),
  retirarVoto: (id) => api(`/api/sessions/${id}/voto`, { method: "DELETE" }),
};

export const Catalog = {
  meta: () => api("/api/catalog/meta"),
  search: (params) => api(`/api/catalog/sessions?${new URLSearchParams(params)}`),
  get: (base) => api(`/api/catalog/sessions/${base}`),
};

export const Numeros = {
  catalogo: () => api("/api/numeros/catalogo"),
  mio: () => api("/api/numeros/mio"),
};

export const Viajes = {
  get: () => api("/api/viajes"),
  agregarVuelo: (json) => api("/api/viajes/vuelos", { method: "POST", json }),
  ciudades: (q) => api(`/api/viajes/ciudades?q=${encodeURIComponent(q)}`),
  editarVuelo: (id, json) => api(`/api/viajes/vuelos/${encodeURIComponent(id)}`, { method: "PUT", json }),
  quitarVuelo: (id) => api(`/api/viajes/vuelos/${encodeURIComponent(id)}`, { method: "DELETE" }),
  agregarHotel: (json) => api("/api/viajes/hoteles", { method: "POST", json }),
  editarHotel: (id, json) => api(`/api/viajes/hoteles/${encodeURIComponent(id)}`, { method: "PUT", json }),
  quitarHotel: (id) => api(`/api/viajes/hoteles/${encodeURIComponent(id)}`, { method: "DELETE" }),
  prefs: () => api("/api/viajes/preferencias"),
  savePrefs: (prefs) => api("/api/viajes/preferencias", { method: "PUT", json: prefs }),
  proximo: () => api("/api/viajes/proximo"),  // «Próximo» del banner de estado (o null)
};

// Documentos de viaje (app/documentos_api.py). La lista (solo metadatos) tiene copia sin señal; el archivo nunca: sin
// señal se ve solo si la persona lo guardó en el teléfono (docsLocal.js).
const RUTA_DOCS = "/api/viajes/documentos";
export const Documentos = {
  list: () => apiConUltimaCopia(RUTA_DOCS),
  create: (form) => api(RUTA_DOCS, { method: "POST", body: form }),
  edit: (id, json) => api(`${RUTA_DOCS}/${enc(id)}`, { method: "PUT", json }),
  replaceFile: (form, id) => api(`${RUTA_DOCS}/${enc(id)}/archivo`, { method: "PUT", body: form }),
  file: (id) => api(`${RUTA_DOCS}/${enc(id)}/archivo`, { raw: true }).then((r) => r.blob()),
  remove: (id) => api(`${RUTA_DOCS}/${enc(id)}`, { method: "DELETE" }),
  removeAll: () => api(RUTA_DOCS, { method: "DELETE" }),
};

// Pendientes del viaje (app/pendientes_api.py): el GET siembra la lista sugerida la primera vez.
const urlPendiente = (id, resto = "") => `/api/viajes/pendientes/${encodeURIComponent(id)}${resto}`;
export const Pendientes = {
  get: () => api("/api/viajes/pendientes"),
  agregar: (json) => api("/api/viajes/pendientes", { method: "POST", json }),
  editar: (id, json) => api(urlPendiente(id), { method: "PUT", json }),
  marcar: (id, hecho) => api(urlPendiente(id, "/hecho"), { method: hecho ? "POST" : "DELETE" }),
  borrar: (id) => api(urlPendiente(id), { method: "DELETE" }),
};

export const Today = {
  get: () => apiConUltimaCopia("/api/today"),
};

// Anuncios sin reserva para Inicio (app/anuncios.py).
export const Anuncios = {
  get: () => apiConUltimaCopia("/api/anuncios"),
};

export const Itinerary = {
  profile: () => api("/api/itinerary/profile"),
  generate: (profile, prompt) => api("/api/itinerary/generate", { method: "POST", json: { profile, prompt } }),
  get: () => apiConUltimaCopia("/api/itinerary"),
  add: (code, reason) => api("/api/itinerary/items", { method: "POST", json: { code, reason } }),
  lock: (code, locked = true) => api(`/api/itinerary/items/${code}/lock?locked=${locked}`, { method: "POST" }),
  remove: (code) => api(`/api/itinerary/items/${code}`, { method: "DELETE" }),
  changes: () => api("/api/itinerary/changes"),
  missed: (code) => api(`/api/itinerary/missed/${enc(code)}`),
  swap: (code, to) => api(`/api/itinerary/items/${enc(code)}/swap`, { method: "POST", json: { to } }),
  calendar: () => api("/api/itinerary/calendar.ics", { raw: true }).then((r) => r.blob()),
  importReservations: (file) => api("/api/itinerary/import-ics", { method: "POST", body: file, headers: { "Content-Type": "text/calendar" } }),
  ackChanges: (codes) => api("/api/itinerary/changes/ack", { method: "POST", json: { codes } }),
};

export const Auth = {
  login: (username, password) => api("/api/login", { method: "POST", json: { username, password } }),
  logout: () => api("/api/logout", { method: "POST" }),
  me: () => api("/api/me").then((me) => { setDebeCargarMail(me.debe_cargar_mail === true); return me; }),
  changePassword: (currentPassword, newPassword) =>
    api("/api/password", { method: "POST", json: { current_password: currentPassword, new_password: newPassword } }),
};

// Mail obligatorio y recuperación de contraseña (app/mail_api.py).
export const Mail = {
  pedirCodigo: (email) => api("/api/me/email", { method: "POST", json: { email } }),
  verificar: (codigo) => api("/api/me/email/verificar", { method: "POST", json: { codigo } }),
  olvide: (usuario) => api("/api/password/olvide", { method: "POST", json: { usuario } }),
  restablecer: (usuario, codigo, newPassword) =>
    api("/api/password/restablecer", { method: "POST", json: { usuario, codigo, new_password: newPassword } }),
};

// Ajustes sin señal: quién es y si es admin se guarda por usuario junto a las otras copias (lastgood.js, se borra al cerrar
// sesión). «/api/me/cuenta» no es una ruta del servidor: es la clave de esa copia.
const RUTA_CUENTA = "/api/me/cuenta";

/** Guarda quién es (usuario e is_admin) de una respuesta de /api/me: la usa Ajustes sin señal, y sandbox.js al refrescar. */
export async function guardarCuenta(me) {
  const de = await duenoDeCopias();
  if (de) saveLast(de, RUTA_CUENTA, { username: me.username, is_admin: Boolean(me.is_admin) });
}

/**
 * Quién está conectado para la pantalla Ajustes. estado: «ok» (del servidor), «copia» (sin señal, con lo último que se
 * supo), «sin_senal» (sin señal y sin copia), «sin_sesion» (solo con 401/403 reales) o «error» (cualquier otro fallo).
 */
export async function cuentaConCopia() {
  const de = await duenoDeCopias();
  try {
    const me = await Auth.me();
    await guardarCuenta(me);
    return { estado: "ok", username: me.username, is_admin: Boolean(me.is_admin) };
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return { estado: "sin_sesion" };
    if (!sinServicio(e)) return { estado: "error" };
    const guardada = de ? loadLast(de, RUTA_CUENTA)?.data : null;
    return typeof guardada?.username === "string" && guardada.username
      ? { estado: "copia", username: guardada.username, is_admin: guardada.is_admin === true }
      : { estado: "sin_senal" };
  }
}

export const Passkeys = {
  registerOptions: () => api("/api/passkey/register/options", { method: "POST" }),
  registerVerify: (challengeId, credential, device) =>
    api("/api/passkey/register/verify", { method: "POST", json: { challenge_id: challengeId, credential, device } }),
  loginOptions: () => api("/api/passkey/login/options", { method: "POST" }),
  loginVerify: (challengeId, credential) =>
    api("/api/passkey/login/verify", { method: "POST", json: { challenge_id: challengeId, credential } }),
  list: () => api("/api/passkeys"),
  remove: (id) => api(`/api/passkeys/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

const enc = encodeURIComponent;
export const Admin = {
  users: () => api("/api/admin/users"),
  createUser: (username, password) => api("/api/admin/users", { method: "POST", json: { username, password } }),
  resetPassword: (username, password) => api(`/api/admin/users/${enc(username)}/reset-password`, { method: "POST", json: { password } }),
  setActive: (username, active) => api(`/api/admin/users/${enc(username)}/active`, { method: "POST", json: { active } }),
  deleteUser: (username) => api(`/api/admin/users/${enc(username)}`, { method: "DELETE" }),
  revokeSessions: (username) => api(`/api/admin/users/${enc(username)}/sessions`, { method: "DELETE" }),
  usage: () => api("/api/admin/usage"),
  reloadCatalog: () => api("/api/admin/catalog/reload", { method: "POST" }),
  setSandbox: (username, settings) => api(`/api/admin/users/${enc(username)}/sandbox`, { method: "PUT", json: settings }),
  advanceSandbox: (username, minutes) => api(`/api/admin/users/${enc(username)}/sandbox/advance`, { method: "POST", json: { minutes } }),
  clearSandboxData: () => api("/api/admin/sandbox/data", { method: "DELETE" }),
  venues: () => api("/api/admin/venues"),
  check: () => api("/api/admin/check"),
  eventos: () => api("/api/admin/eventos"),
  eventosRevisar: () => api("/api/admin/eventos/revisar", { method: "POST" }),
  eventosVistaPrevia: (url) => api("/api/admin/eventos/link/vista-previa", { method: "POST", json: { url } }),
  eventosGuardarLink: (datos) => api("/api/admin/eventos/link", { method: "POST", json: datos }),
};

export const Push = {
  key: () => api("/api/push/key"),
  subscribe: (sub) => api("/api/push/subscribe", { method: "POST", json: sub }),
  unsubscribe: (endpoint) => api("/api/push/unsubscribe", { method: "POST", json: { endpoint } }),
  test: () => api("/api/push/test", { method: "POST" }),
  prefs: () => api("/api/push/preferencias"),
  savePrefs: (prefs) => api("/api/push/preferencias", { method: "PUT", json: prefs }),
};

// Sede reciente para el recordatorio "¿la grabás?" (app/ubicacion_api.py): solo el número de sede, nunca coordenadas.
export const Ubicacion = {
  set: (idSede) => api("/api/ubicacion", { method: "POST", json: { id_sede: idSede } }),
  clear: () => api("/api/ubicacion", { method: "DELETE" }),
};

export const Lleno = {
  estado: (codes) => api(`/api/lleno?codes=${codes.map(enc).join(",")}`),
  avisar: (code, estado) => api(`/api/lleno/${enc(code)}`, { method: "POST", json: { estado } }),
  retirar: (code) => api(`/api/lleno/${enc(code)}`, { method: "DELETE" }),
};

export const Events = {
  list: () => api("/api/events"),
  get: (code) => api(`/api/events/${enc(code)}`),
};

export const Shows = {
  list: () => api("/api/shows"),
  get: (id) => api(`/api/shows/${enc(id)}`),
  cuando: (id) => api(`/api/shows/${enc(id)}/cuando`),
};

export const Knowledge = {
  speech: (base) => api(`/api/k/speech/${encodeURIComponent(base)}`),
  speaker: (id) => api(`/api/k/speaker/${encodeURIComponent(id)}`),
  empresa: (id) => api(`/api/k/empresa/${encodeURIComponent(id)}`),
  searchEntities: (q) => api(`/api/k/search/entities?${new URLSearchParams({ q })}`),
  explore: (body) => api("/api/k/explore", { method: "POST", json: body }),
  parseFilters: (text) => api("/api/k/explore/parse", { method: "POST", json: { text } }),
  ask: (q) => api("/api/k/ask", { method: "POST", json: { q } }),
  briefing: (kind, id, refresh = false) => api("/api/k/briefing", { method: "POST", json: { kind, id: Number(id), refresh } }),
  pickTalk: (q) => api(`/api/k/talks/pick?${new URLSearchParams({ q })}`),
};

export const Maps = {
  key: () => api("/api/maps-key"),
};

// Itinerario guiado: entrevista y ficha (app/interview_api.py).
export const Interview = {
  get: () => api("/api/itinerary/interview"),
  save: (respuestas) => api("/api/itinerary/interview", { method: "PUT", json: respuestas }),
  followups: () => api("/api/itinerary/interview/repreguntas", { method: "POST" }),
  createFicha: () => api("/api/itinerary/ficha", { method: "POST" }),
  editFicha: (ficha) => api("/api/itinerary/ficha", { method: "PUT", json: ficha }),
  voice: (blob) => api("/api/itinerary/interview/voz", { method: "POST", body: blob, headers: { "Content-Type": blob.type || "audio/webm" } }),
};

// Armado día por día (app/guided_api.py).
export const Guided = {
  next: ({ day, after = null, desde = null }) => api("/api/itinerary/guided/next", { method: "POST", json: { day, after, desde } }),
  pending: () => api("/api/itinerary/pending"),
  addPending: (base, day) => api("/api/itinerary/pending", { method: "POST", json: { base, day } }),
  removePending: (base) => api(`/api/itinerary/pending/${enc(base)}`, { method: "DELETE" }),
  leaveEarly: (code, minutos) => api(`/api/itinerary/items/${enc(code)}/salir-antes`, { method: "PUT", json: { minutos } }),
  booked: (code, reservada) => api(`/api/itinerary/items/${enc(code)}/reservada`, { method: "PUT", json: { reservada } }),
};

// Mis eventos (app/my_events_api.py).
export const MyEvents = {
  list: () => api("/api/my-events"),
  venues: () => api("/api/my-events/sedes"),
  create: (data) => api("/api/my-events", { method: "POST", json: data }),
  edit: (id, data) => api(`/api/my-events/${enc(id)}`, { method: "PUT", json: data }),
  remove: (id) => api(`/api/my-events/${enc(id)}`, { method: "DELETE" }),
  autocomplete: (q, sesion) => api(`/api/places/autocomplete?${new URLSearchParams({ q, sesion })}`),
};
