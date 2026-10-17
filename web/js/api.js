// Cliente de la API. El token vive en localStorage del celular (un único usuario).
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
