// Ajustes y «Tus grabaciones» sin señal (node --test): sin red no se dice «Sesión no válida» ni «Todavía no grabaste».
import test, { beforeEach } from "node:test";
import assert from "node:assert/strict";

const memoria = new Map();
globalThis.localStorage = {
  getItem: (k) => (memoria.has(k) ? memoria.get(k) : null),
  setItem: (k, v) => { memoria.set(k, String(v)); },
  removeItem: (k) => { memoria.delete(k); },
  key: (i) => [...memoria.keys()][i] ?? null,
  get length() { return memoria.size; },
};
globalThis.window = { dispatchEvent() {}, addEventListener() {} };
globalThis.location = { hash: "" };
globalThis.document = { createElement: () => ({ append() {}, setAttribute() {}, addEventListener() {}, classList: { add() {} } }) };

const { Sessions, cuentaConCopia, duenoDeCopias, setToken } = await import("../../web/js/api.js");
const { loadLast, markStale } = await import("../../web/js/lastgood.js");
const { textoDeCuenta, textosSinGrabaciones } = await import("../../web/js/sinSenal.js");

const respuesta = (data) => ({ ok: true, status: 200, json: async () => data });
const falla = (status, detail = "x") => ({ ok: false, status, statusText: "x", json: async () => ({ detail }) });
const sinRed = async () => { throw new TypeError("Failed to fetch"); };
const ME = { username: "ale", is_admin: true, sandbox: null };
const copiaDeCuenta = async () => loadLast(await duenoDeCopias(), "/api/me/cuenta");
const reposo = () => new Promise((r) => setTimeout(r, 20));

beforeEach(() => { memoria.clear(); setToken("tok-aaaaaaaaaaaa"); });

test("con red devuelve la cuenta y deja una copia de usuario y admin", async () => {
  globalThis.fetch = async () => respuesta(ME);
  assert.deepEqual(await cuentaConCopia(), { estado: "ok", username: "ale", is_admin: true });
  assert.deepEqual((await copiaDeCuenta()).data, { username: "ale", is_admin: true });
});

test("sin red y con copia sigue «Conectado como X» y con su botón de Administración", async () => {
  globalThis.fetch = async () => respuesta(ME);
  await cuentaConCopia();
  globalThis.fetch = sinRed;
  assert.deepEqual(await cuentaConCopia(), { estado: "copia", username: "ale", is_admin: true });
});

test("sin red y sin copia dice que la cuenta se muestra cuando vuelva la red", async () => {
  globalThis.fetch = sinRed;
  assert.deepEqual(await cuentaConCopia(), { estado: "sin_senal" });
});

test("un 5xx también cuenta como falta de señal", async () => {
  globalThis.fetch = async () => falla(503);
  assert.equal((await cuentaConCopia()).estado, "sin_senal");
});

test("«Sesión no válida» solo con 401 o 403 reales, aunque haya copia", async () => {
  globalThis.fetch = async () => respuesta(ME);
  await cuentaConCopia();
  for (const status of [401, 403]) {
    globalThis.fetch = async () => falla(status);
    assert.equal((await cuentaConCopia()).estado, "sin_sesion", String(status));
  }
});

test("otro error del servidor (404) no es ni sesión inválida ni falta de señal", async () => {
  globalThis.fetch = async () => falla(404);
  assert.equal((await cuentaConCopia()).estado, "error");
});

test("la copia de la cuenta es de quien tenía la sesión y se borra al cerrarla", async () => {
  globalThis.fetch = async () => respuesta(ME);
  await cuentaConCopia();
  setToken("tok-bbbbbbbbbbbb");
  globalThis.fetch = sinRed;
  assert.equal((await cuentaConCopia()).estado, "sin_senal", "otra sesión no ve la copia");
  setToken("");
  assert.deepEqual([...memoria.keys()].filter((k) => k.startsWith("reinventar.last.")), []);
});

test("los textos de Ajustes según el estado", () => {
  assert.equal(textoDeCuenta({ estado: "ok", username: "ale" }), "Conectado como ale.");
  assert.equal(textoDeCuenta({ estado: "copia", username: "ale" }), "Conectado como ale.");
  assert.equal(textoDeCuenta({ estado: "sin_senal" }), "Sin señal: tu cuenta se muestra cuando vuelva la red.");
  assert.equal(textoDeCuenta({ estado: "sin_sesion" }), "Sesión no válida.");
  assert.match(textoDeCuenta({ estado: "error" }), /No se pudo cargar tu cuenta/);
});

test("una lista vacía que es copia no se presenta como «todavía no grabaste»", () => {
  assert.match(textosSinGrabaciones([]).titulo, /^Todavía no grabaste/);
  const copia = markStale([], Date.now());
  assert.equal(textosSinGrabaciones(copia).titulo, "Sin señal: tus grabaciones se muestran cuando vuelva la red.");
  assert.equal(textosSinGrabaciones(copia).detalle, null);
});

test("crear, cerrar o borrar una grabación con red actualiza la copia de la lista", async () => {
  let servidor = [];
  globalThis.fetch = async (url, init = {}) => {
    if (url === "/api/sessions" && (init.method ?? "GET") === "GET") return respuesta(servidor);
    if (url === "/api/sessions") { servidor = [{ id: "s1", status: "recording" }]; return respuesta({ id: "s1" }); }
    if (url.endsWith("/finish")) { servidor = [{ id: "s1", status: "transcribing" }]; return respuesta({ ok: true }); }
    servidor = []; return respuesta({ ok: true }); // DELETE
  };
  await Sessions.list();
  assert.deepEqual((loadLast(await duenoDeCopias(), "/api/sessions")).data, [], "la copia arranca vacía");
  await Sessions.create({ title: "x" });
  await reposo();
  assert.deepEqual(loadLast(await duenoDeCopias(), "/api/sessions").data, [{ id: "s1", status: "recording" }], "tras crear");
  await Sessions.finish("s1", { 0: 1 });
  await reposo();
  assert.deepEqual(loadLast(await duenoDeCopias(), "/api/sessions").data, [{ id: "s1", status: "transcribing" }], "tras cerrar");
  await Sessions.remove("s1");
  await reposo();
  assert.deepEqual(loadLast(await duenoDeCopias(), "/api/sessions").data, [], "tras borrar");
});

test("si la actualización de la copia falla (sin red), crear la grabación igual anda", async () => {
  globalThis.fetch = async (url, init = {}) => {
    if ((init.method ?? "GET") === "GET") throw new TypeError("Failed to fetch");
    return respuesta({ id: "s1" });
  };
  assert.deepEqual(await Sessions.create({ title: "x" }), { id: "s1" });
  await reposo();
});
