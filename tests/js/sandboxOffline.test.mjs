// Modo prueba sin señal (node --test): si /api/me falla por la red, la franja y el reloj simulado salen de la última copia.
import test from "node:test";
import assert from "node:assert/strict";

const memoria = new Map();
globalThis.localStorage = {
  getItem: (k) => (memoria.has(k) ? memoria.get(k) : null), setItem: (k, v) => memoria.set(k, String(v)), removeItem: (k) => memoria.delete(k),
  key: (i) => [...memoria.keys()][i] ?? null, get length() { return memoria.size; },
};
globalThis.window = { dispatchEvent() {}, addEventListener() {} };
globalThis.location = { hash: "" };
// El reloj de la franja repinta con un setInterval: sin unref, Node no termina nunca.
const crearIntervalo = globalThis.setInterval;
globalThis.setInterval = (...args) => { const t = crearIntervalo(...args); t.unref?.(); return t; };
globalThis.document = { getElementById: () => null };

const { setToken } = await import("../../web/js/api.js");
const FRANJA_COPIAS = (k) => k.startsWith("reinventar.last.");

let versiones = 0;
/** sandbox.js nuevo por prueba: el estado (info, offset) vive en el módulo. */
const cargarSandbox = () => import(`../../web/js/sandbox.js?v=${versiones++}`);

const respuesta = (data) => ({ ok: true, status: 200, json: async () => data });
const sinRed = async () => { throw new TypeError("Failed to fetch"); };
const SESION_VENCIDA = async () => ({ ok: false, status: 401, statusText: "Unauthorized", json: async () => ({ detail: "Sesión inválida" }) });

const AHORA_SIMULADO = "2026-12-01T09:00:00";
const SANDBOX = { stt: "fake", llm: "fake", now: AHORA_SIMULADO, simulated_clock: true, location: { id: 1, name: "Venetian", lat: 36.12, lng: -115.17 } };
const me = (sandbox) => ({ username: "ale", is_admin: false, sandbox });

test.beforeEach(() => { memoria.clear(); setToken("tok-aaaaaaaaaaaa"); });

test("con red guarda la última respuesta del modo prueba en el celular", async () => {
  globalThis.fetch = async () => respuesta(me(SANDBOX));
  const sb = await cargarSandbox();
  await sb.refreshSandbox({ force: true });
  assert.equal(sb.inSandbox(), true);
  assert.ok([...memoria.keys()].some((k) => FRANJA_COPIAS(k) && k.endsWith("/api/me/sandbox")), [...memoria.keys()].join());
});

test("al abrir la app sin red usa la copia: sigue la franja, la sede simulada y el reloj simulado", async () => {
  globalThis.fetch = async () => respuesta(me(SANDBOX));
  await (await cargarSandbox()).refreshSandbox({ force: true });

  globalThis.fetch = sinRed;
  const sb = await cargarSandbox(); // app abierta de cero: el módulo no sabe nada
  assert.equal(sb.inSandbox(), false);
  await sb.refreshSandbox({ force: true });
  assert.equal(sb.inSandbox(), true);
  assert.equal(sb.sandboxLocation().name, "Venetian");
  // El reloj simulado coincide con el «now» guardado más lo que pasó desde que se guardó.
  const esperado = Date.parse(AHORA_SIMULADO);
  assert.ok(Math.abs(sb.sandboxNow().getTime() - esperado) < 5_000, `${sb.sandboxNow().toISOString()} vs ${AHORA_SIMULADO}`);
});

test("el reloj de la copia avanza con el tiempo transcurrido desde que se guardó", async () => {
  globalThis.fetch = async () => respuesta(me(SANDBOX));
  await (await cargarSandbox()).refreshSandbox({ force: true });

  const dateNow = Date.now;
  try {
    Date.now = () => dateNow() + 10 * 60_000; // pasaron 10 minutos
    globalThis.fetch = sinRed;
    const sb = await cargarSandbox();
    await sb.refreshSandbox({ force: true });
    const adelanto = sb.sandboxNow().getTime() - Date.parse(AHORA_SIMULADO);
    assert.ok(Math.abs(adelanto - 10 * 60_000) < 5_000, `adelanto ${adelanto} ms`);
  } finally { Date.now = dateNow; }
});

test("sin copia y sin red no hay modo prueba (como antes)", async () => {
  globalThis.fetch = sinRed;
  const sb = await cargarSandbox();
  await sb.refreshSandbox({ force: true });
  assert.equal(sb.inSandbox(), false);
  assert.equal(sb.sandboxLocation(), null);
});

test("si el usuario no estaba en modo prueba, sin red tampoco aparece", async () => {
  globalThis.fetch = async () => respuesta(me(null));
  await (await cargarSandbox()).refreshSandbox({ force: true });
  globalThis.fetch = sinRed;
  const sb = await cargarSandbox();
  await sb.refreshSandbox({ force: true });
  assert.equal(sb.inSandbox(), false);
});

test("una sesión vencida (401) no resucita la copia: solo la falta de red", async () => {
  globalThis.fetch = async () => respuesta(me(SANDBOX));
  await (await cargarSandbox()).refreshSandbox({ force: true });
  globalThis.fetch = SESION_VENCIDA;
  const sb = await cargarSandbox();
  await sb.refreshSandbox({ force: true });
  assert.equal(sb.inSandbox(), false);
});

test("la copia es de quien tenía la sesión: otra persona en el mismo celular no la ve", async () => {
  globalThis.fetch = async () => respuesta(me(SANDBOX));
  await (await cargarSandbox()).refreshSandbox({ force: true });
  setToken("tok-bbbbbbbbbbbb"); // otra sesión (el cierre de sesión borra todo; acá se simula el cambio de token)
  memoria.set("reinventar.token", "tok-bbbbbbbbbbbb");
  globalThis.fetch = sinRed;
  const sb = await cargarSandbox();
  await sb.refreshSandbox({ force: true });
  assert.equal(sb.inSandbox(), false);
});

test("al cerrar sesión se borra la copia del modo prueba", async () => {
  globalThis.fetch = async () => respuesta(me(SANDBOX));
  await (await cargarSandbox()).refreshSandbox({ force: true });
  assert.ok([...memoria.keys()].some(FRANJA_COPIAS));
  setToken("");
  assert.deepEqual([...memoria.keys()].filter(FRANJA_COPIAS), []);
});

test("una copia rota o con otra forma se ignora sin romper el arranque", async () => {
  globalThis.fetch = async () => respuesta(me(SANDBOX));
  await (await cargarSandbox()).refreshSandbox({ force: true });
  const clave = [...memoria.keys()].find((k) => k.endsWith("/api/me/sandbox"));
  for (const rota of ["{no es json", JSON.stringify({ at: "ayer", data: { sandbox: SANDBOX } }), JSON.stringify({ at: 1, data: "x" })]) {
    memoria.set(clave, rota);
    globalThis.fetch = sinRed;
    const sb = await cargarSandbox();
    await sb.refreshSandbox({ force: true });
    assert.equal(sb.inSandbox(), false, rota);
  }
});
