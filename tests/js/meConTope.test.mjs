// /api/me con tope (node --test): con un Wi-Fi que conecta pero no responde, la app no espera para siempre antes de
// dibujar (sandbox.js) ni Ajustes queda colgado (cuentaConCopia): a los ME_TIMEOUT_MS sigue como sin red, con la copia.
import test from "node:test";
import assert from "node:assert/strict";

const memoria = new Map();
globalThis.localStorage = {
  getItem: (k) => (memoria.has(k) ? memoria.get(k) : null), setItem: (k, v) => memoria.set(k, String(v)), removeItem: (k) => memoria.delete(k),
  key: (i) => [...memoria.keys()][i] ?? null, get length() { return memoria.size; },
};
globalThis.window = { dispatchEvent() {}, addEventListener() {} };
globalThis.location = { hash: "" };
const crearIntervalo = globalThis.setInterval;
globalThis.setInterval = (...args) => { const t = crearIntervalo(...args); t.unref?.(); return t; };
globalThis.document = { getElementById: () => null };

const { ME_TIMEOUT_MS, cuentaConCopia, setToken } = await import("../../web/js/api.js");
let versiones = 0;
const cargarSandbox = () => import(`../../web/js/sandbox.js?v=${versiones++}`);

const SANDBOX = { stt: "fake", llm: "fake", now: "2026-12-01T09:00:00", simulated_clock: true, location: { id: 1, name: "Venetian" } };
const ME = { username: "ale", is_admin: false, sandbox: SANDBOX };
const respuesta = (data) => ({ ok: true, status: 200, json: async () => data });

// AbortSignal.timeout de mentira: se cancela enseguida (no hace falta esperar 4 s) y anota el tope pedido.
const topes = [];
const timeoutReal = AbortSignal.timeout;
test.before(() => {
  AbortSignal.timeout = (ms) => {
    topes.push(ms);
    const c = new AbortController();
    setTimeout(() => c.abort(new DOMException("tardó demasiado", "TimeoutError")), 5);
    return c.signal;
  };
});
test.after(() => { AbortSignal.timeout = timeoutReal; });
test.beforeEach(() => { memoria.clear(); topes.length = 0; setToken("tok-aaaaaaaaaaaa"); });

// Un servidor que acepta la conexión y nunca contesta: solo termina si lo cancela la señal.
const colgado = async (_path, init) => new Promise((_, rechazar) => {
  init?.signal?.addEventListener("abort", () => rechazar(init.signal.reason));
});

test("el tope de /api/me es corto (4 s)", () => {
  assert.equal(ME_TIMEOUT_MS, 4000);
});

test("si /api/me no contesta, refreshSandbox no queda esperando y usa la copia del modo prueba", async () => {
  globalThis.fetch = async () => respuesta(ME);
  await (await cargarSandbox()).refreshSandbox({ force: true });

  globalThis.fetch = colgado;
  topes.length = 0;
  const sb = await cargarSandbox(); // app recién abierta
  await sb.refreshSandbox({ force: true });
  assert.deepEqual(topes, [ME_TIMEOUT_MS]);
  assert.equal(sb.inSandbox(), true);
  assert.equal(sb.sandboxLocation().name, "Venetian");
});

test("si /api/me no contesta y no hay copia, refreshSandbox igual termina (sin modo prueba)", async () => {
  globalThis.fetch = colgado;
  const sb = await cargarSandbox();
  await sb.refreshSandbox({ force: true });
  assert.equal(sb.inSandbox(), false);
});

test("Ajustes con /api/me colgado muestra la cuenta guardada en vez de quedar cargando", async () => {
  globalThis.fetch = async () => respuesta(ME);
  await cuentaConCopia();
  globalThis.fetch = colgado;
  topes.length = 0;
  assert.deepEqual(await cuentaConCopia(), { estado: "copia", username: "ale", is_admin: false });
  assert.deepEqual(topes, [ME_TIMEOUT_MS]);
});
