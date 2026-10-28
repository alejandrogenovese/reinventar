// Cliente de la API. El token de sesión (lo da /api/login) vive en localStorage de este celular.
const KEY = "reinventar.token";

export function getToken() { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } }
export function setToken(t) { try { localStorage.setItem(KEY, t); } catch {} }

export class ApiError extends Error {
  constructor(status, detail) { super(typeof detail === "string" ? detail : detail?.message || `HTTP ${status}`); this.status = status; this.detail = detail; }
}

export async function api(path, { method = "GET", json, body, headers = {}, raw = false, signal } = {}) {
  const h = { Authorization: `Bearer ${getToken()}`, ...headers };
  if (json !== undefined) { h["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  const r = await fetch(path, { method, headers: h, body, signal });
  if (!r.ok) {
    let detail; try { detail = (await r.json()).detail; } catch { detail = r.statusText; }
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
};

export const Catalog = {
  meta: () => api("/api/catalog/meta"),
  search: (params) => api(`/api/catalog/sessions?${new URLSearchParams(params)}`),
  get: (base) => api(`/api/catalog/sessions/${base}`),
};

export const Itinerary = {
  profile: () => api("/api/itinerary/profile"),
  generate: (profile, prompt) => api("/api/itinerary/generate", { method: "POST", json: { profile, prompt } }),
  get: () => api("/api/itinerary"),
  add: (code) => api("/api/itinerary/items", { method: "POST", json: { code } }),
  lock: (code, locked = true) => api(`/api/itinerary/items/${code}/lock?locked=${locked}`, { method: "POST" }),
  remove: (code) => api(`/api/itinerary/items/${code}`, { method: "DELETE" }),
};

export const Auth = {
  login: (username, password) => api("/api/login", { method: "POST", json: { username, password } }),
  logout: () => api("/api/logout", { method: "POST" }),
  me: () => api("/api/me"),
};
