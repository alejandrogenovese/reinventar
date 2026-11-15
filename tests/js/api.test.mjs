// Pruebas del cliente de la API (node --test): qué ve el usuario cuando no hay red.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { api, ApiError, MSG_PORTAL_CAUTIVO, MSG_RESPUESTA_INVALIDA, MSG_SIN_CONEXION } = await import("../../web/js/api.js");

// Una respuesta 200 cuyo cuerpo no es JSON, como la de un portal cautivo (Wi-Fi del hotel) o un proxy.
const respuestaNoJson = ({ tipo = "text/html; charset=utf-8", cuerpo = "<html><body>Aceptá los términos</body></html>", extra = {} } = {}) => ({
  ok: true, status: 200, redirected: false, url: "http://localhost/api/today",
  headers: { get: (n) => (n.toLowerCase() === "content-type" ? tipo : null) },
  json: async () => JSON.parse(cuerpo),
  clone() { return { text: async () => cuerpo }; },
  ...extra,
});

test("sin red, el error dice «Sin conexión» en castellano y no «Failed to fetch»", async () => {
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(api("/api/me"), (e) => e instanceof ApiError && e.status === 0 && e.message === MSG_SIN_CONEXION);
});

test("una cancelación (AbortError) sigue saliendo tal cual: quien llama la ignora", async () => {
  globalThis.fetch = async () => { throw new DOMException("cancelado", "AbortError"); };
  await assert.rejects(api("/api/me"), (e) => e.name === "AbortError");
});

test("un 200 con HTML (portal cautivo) es un ApiError en castellano con status 0, no un SyntaxError", async () => {
  globalThis.fetch = async () => respuestaNoJson();
  await assert.rejects(api("/api/today"), (e) => e instanceof ApiError && e.status === 0 && e.message === MSG_PORTAL_CAUTIVO);
  assert.match(MSG_PORTAL_CAUTIVO, /red|Wi-Fi/i);
  assert.doesNotMatch(MSG_PORTAL_CAUTIVO, /JSON|Unexpected|token/);
});

test("un 200 que viene de otro sitio (redirección del portal) también parece portal cautivo", async () => {
  globalThis.fetch = async () => respuestaNoJson({ tipo: "text/plain", cuerpo: "no es json", extra: { redirected: true, url: "http://portal.hotel.net/login" } });
  await assert.rejects(api("/api/today"), (e) => e.status === 0 && e.message === MSG_PORTAL_CAUTIVO);
});

test("sin content-type de HTML pero con cuerpo que empieza con «<» también parece portal", async () => {
  globalThis.fetch = async () => respuestaNoJson({ tipo: "text/plain", cuerpo: "  <!DOCTYPE html><html>" });
  await assert.rejects(api("/api/today"), (e) => e.status === 0 && e.message === MSG_PORTAL_CAUTIVO);
});

test("un 200 con un cuerpo roto que no es HTML da un error propio en castellano", async () => {
  globalThis.fetch = async () => respuestaNoJson({ tipo: "application/json", cuerpo: '{"cortado":' });
  await assert.rejects(api("/api/today"), (e) => e instanceof ApiError && e.status === 502 && e.message === MSG_RESPUESTA_INVALIDA);
  assert.doesNotMatch(MSG_RESPUESTA_INVALIDA, /JSON|Unexpected|token/);
});

test("una respuesta sin clone ni headers (cuerpo roto) igual sale como error en castellano", async () => {
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError("Unexpected token <"); } });
  await assert.rejects(api("/api/today"), (e) => e instanceof ApiError && e.message !== "Unexpected token <");
});

test("si se corta la conexión mientras se lee el cuerpo, es falta de señal y no «respuesta ilegible»", async () => {
  globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => { throw new TypeError("network error"); } });
  await assert.rejects(api("/api/today"), (e) => e.status === 0 && e.message === MSG_SIN_CONEXION);
  globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => { throw new DOMException("tope", "TimeoutError"); } });
  await assert.rejects(api("/api/today"), (e) => e.status === 0 && e.message === MSG_SIN_CONEXION);
});

test("con text() (las respuestas reales) el HTML también se reconoce, y un JSON bueno se lee", async () => {
  globalThis.fetch = async () => ({ ok: true, status: 200, headers: { get: () => "text/html" }, text: async () => "<html>portal</html>" });
  await assert.rejects(api("/api/today"), (e) => e.status === 0 && e.message === MSG_PORTAL_CAUTIVO);
  globalThis.fetch = async () => ({ ok: true, status: 200, headers: { get: () => "application/json" }, text: async () => '{"a":[1,2]}' });
  assert.deepEqual(await api("/api/today"), { a: [1, 2] });
});

test("un JSON válido y raw:true no cambian", async () => {
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ ok: 1 }) });
  assert.deepEqual(await api("/api/today"), { ok: 1 });
  const cruda = { ok: true, status: 200, json: async () => { throw new Error("no se debe leer"); } };
  globalThis.fetch = async () => cruda;
  assert.equal(await api("/api/x", { raw: true }), cruda);
});

test("los errores del servidor no cambian", async () => {
  globalThis.fetch = async () => ({ ok: false, status: 500, statusText: "Internal", json: async () => ({ detail: "se rompió" }) });
  await assert.rejects(api("/api/me"), (e) => e instanceof ApiError && e.status === 500 && e.message === "se rompió");
});
