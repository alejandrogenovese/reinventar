// Pruebas de la última copia buena (node --test): Hoy, Itinerario y grabaciones sin señal.
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
const eventos = [];
globalThis.window = { dispatchEvent: (e) => { eventos.push(e.type); return true; } };
globalThis.location = { hash: "" };

const { Itinerary, Sessions, Today, getToken, setToken } = await import("../../web/js/api.js");
const { clearLast, loadLast, saveLast, sinSenalTexto, staleAt } = await import("../../web/js/lastgood.js");

const respuesta = (data) => ({ ok: true, status: 200, json: async () => data });
const falla = (status, detail = "x") => ({ ok: false, status, statusText: "x", json: async () => ({ detail }) });
const sinRed = async () => { throw new TypeError("Failed to fetch"); };

beforeEach(() => { memoria.clear(); eventos.length = 0; setToken("tok-aaaaaaaaaaaa"); });

test("con red devuelve lo del servidor y deja una copia con su hora", async () => {
  globalThis.fetch = async () => respuesta({ days: [{ day: "lunes" }] });
  const data = await Itinerary.get();
  assert.deepEqual(data, { days: [{ day: "lunes" }] });
  assert.equal(staleAt(data), null);
  const copia = loadLast(getToken().slice(-12), "/api/itinerary");
  assert.deepEqual(copia.data, data);
  assert.ok(Math.abs(copia.at - Date.now()) < 5000);
});

test("sin red muestra la última copia y la marca con la hora en que se guardó", async () => {
  globalThis.fetch = async () => respuesta([{ id: "s1" }]);
  await Sessions.list();
  globalThis.fetch = sinRed;
  const data = await Sessions.list();
  assert.deepEqual(data, [{ id: "s1" }]);
  assert.ok(staleAt(data) > 0);
});

test("sin red y sin copia sigue fallando con «Sin conexión»", async () => {
  globalThis.fetch = sinRed;
  await assert.rejects(Today.get(), (e) => e.status === 0 && /Sin conexión/.test(e.message));
});

test("un 5xx del servidor también cae a la copia", async () => {
  globalThis.fetch = async () => respuesta({ items: [1] });
  await Today.get();
  globalThis.fetch = async () => falla(503);
  assert.deepEqual(await Today.get(), { items: [1] });
});

test("una sesión vencida (401) no se tapa con la copia", async () => {
  globalThis.fetch = async () => respuesta({ items: [1] });
  await Today.get();
  globalThis.fetch = async () => falla(401, "no autorizado");
  await assert.rejects(Today.get(), (e) => e.status === 401);
});

test("la copia es de quien inició sesión: otra sesión no la ve", async () => {
  globalThis.fetch = async () => respuesta({ days: ["mia"] });
  await Itinerary.get();
  memoria.set("reinventar.token", "tok-bbbbbbbbbbbb"); // otro token sin pasar por cerrar sesión
  globalThis.fetch = sinRed;
  await assert.rejects(Itinerary.get(), (e) => e.status === 0);
});

test("al cerrar sesión (token vacío) se borran las copias", async () => {
  globalThis.fetch = async () => respuesta({ days: [] });
  await Itinerary.get();
  assert.ok([...memoria.keys()].some((k) => k.startsWith("reinventar.last.")));
  setToken("");
  assert.ok(![...memoria.keys()].some((k) => k.startsWith("reinventar.last.")));
});

test("clearLast no toca el resto de lo guardado en el celular", () => {
  memoria.set("reinventar.theme", "dark");
  saveLast("yo", "/api/today", { a: 1 });
  clearLast();
  assert.equal(memoria.get("reinventar.theme"), "dark");
  assert.equal(loadLast("yo", "/api/today"), null);
});

test("si el almacenamiento está lleno o roto, guardar no rompe la pantalla", () => {
  const original = globalThis.localStorage.setItem;
  globalThis.localStorage.setItem = () => { throw new DOMException("lleno", "QuotaExceededError"); };
  assert.doesNotThrow(() => saveLast("yo", "/api/today", { a: 1 }));
  globalThis.localStorage.setItem = original;
});

test("una copia ilegible se ignora", () => {
  memoria.set("reinventar.last.yo./api/today", "{no es json");
  assert.equal(loadLast("yo", "/api/today"), null);
});

test("el texto de la franja lleva la hora de los datos", () => {
  const at = new Date(2026, 11, 2, 14, 5).getTime();
  assert.match(sinSenalTexto(at), /^Sin señal · datos de las 14:05$/);
});

test("al guardar el token, la app avisa para que el service worker se entere", () => {
  setToken("tok-cccccccccccc");
  assert.ok(eventos.includes("reinventar:token"));
});
