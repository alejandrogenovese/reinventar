// Cliente de la API. El token de sesión (lo da /api/login) vive en localStorage de este celular.
const KEY = "reinventar.token";

const MUST_CHANGE = "reinventar.mustChangePassword";

export function getToken() { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } }
export function setToken(t) { try { localStorage.setItem(KEY, t); } catch {} }
// Lo informa el login: mientras esté en true, el router manda a #/password.
export function mustChangePassword() { try { return localStorage.getItem(MUST_CHANGE) === "1"; } catch { return false; } }
export function setMustChangePassword(v) { try { localStorage.setItem(MUST_CHANGE, v ? "1" : "0"); } catch {} }

export class ApiError extends Error {
  constructor(status, detail) { super(typeof detail === "string" ? detail : detail?.message || `HTTP ${status}`); this.status = status; this.detail = detail; }
}

export async function api(path, { method = "GET", json, body, headers = {}, raw = false, signal } = {}) {
  const h = { Authorization: `Bearer ${getToken()}`, ...headers };
  if (json !== undefined) { h["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  const r = await fetch(path, { method, headers: h, body, signal });
  if (!r.ok) {
    let detail; try { detail = (await r.json()).detail; } catch { detail = r.statusText; }
    // El servidor exige cambiar la contraseña temporal antes de usar el resto de la API.
    if (r.status === 403 && detail === "must_change_password") { setMustChangePassword(true); location.hash = "#/password"; }
    throw new ApiError(r.status, detail);
  }
  return raw ? r : r.json();
}

export const Sessions = {
  list: () => api("/api/sessions"),
  get: (id) => api(`/api/sessions/${id}`),
  create: (data) => api("/api/sessions", { method: "POST", json: data }),
  putChunk: (id, part, seq, blob, signal) => api(`/api/sessions/${id}/chunks/${part}/${seq}`, { method: "PUT", body: blob, headers: { "Content-Type": "application/octet-stream" }, signal }),
  finish: (id, parts) => api(`/api/sessions/${id}/finish`, { method: "POST", json: { parts } }),
  retry: (id, fromScratch = false) => api(`/api/sessions/${id}/retry?from_scratch=${fromScratch}`, { method: "POST" }),
  remove: (id) => api(`/api/sessions/${id}`, { method: "DELETE" }),
  exportMd: (id) => api(`/api/sessions/${id}/export.md`, { raw: true }).then((r) => r.text()),
  search: (q, signal) => api(`/api/grabaciones/buscar?q=${encodeURIComponent(q)}`, { signal }),
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

export const Today = {
  get: () => api("/api/today"),
};

// Anuncios sin reserva para Inicio (app/anuncios.py).
export const Anuncios = {
  get: () => api("/api/anuncios"),
};

export const Itinerary = {
  profile: () => api("/api/itinerary/profile"),
  generate: (profile, prompt) => api("/api/itinerary/generate", { method: "POST", json: { profile, prompt } }),
  get: () => api("/api/itinerary"),
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
  me: () => api("/api/me"),
  changePassword: (currentPassword, newPassword) =>
    api("/api/password", { method: "POST", json: { current_password: currentPassword, new_password: newPassword } }),
};

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
  revokeSessions: (username) => api(`/api/admin/users/${enc(username)}/sessions`, { method: "DELETE" }),
  usage: () => api("/api/admin/usage"),
  reloadCatalog: () => api("/api/admin/catalog/reload", { method: "POST" }),
  setSandbox: (username, settings) => api(`/api/admin/users/${enc(username)}/sandbox`, { method: "PUT", json: settings }),
  advanceSandbox: (username, minutes) => api(`/api/admin/users/${enc(username)}/sandbox/advance`, { method: "POST", json: { minutes } }),
  clearSandboxData: () => api("/api/admin/sandbox/data", { method: "DELETE" }),
  venues: () => api("/api/admin/venues"),
  check: () => api("/api/admin/check"),
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
