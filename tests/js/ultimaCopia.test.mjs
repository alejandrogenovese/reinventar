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
const detalles = [];
globalThis.window = { dispatchEvent: (e) => { eventos.push(e.type); detalles.push(e.detail); return true; } };
globalThis.location = { hash: "" };

const { Anuncios, Itinerary, Sessions, Today, duenoDeCopias, getToken, setToken } = await import("../../web/js/api.js");
const { clearLast, horaCorta, leerUltimaSync, loadLast, marcarUltimaSync, markStale, saveLast, staleAt } = await import("../../web/js/lastgood.js");

const DUENO = "0123456789ab"; // forma que tiene el dueño real: 12 hex
const copiasGuardadas = () => [...memoria.keys()].filter((k) => k.startsWith("reinventar.last."));
const respuesta = (data) => ({ ok: true, status: 200, json: async () => data });
const falla = (status, detail = "x") => ({ ok: false, status, statusText: "x", json: async () => ({ detail }) });
const sinRed = async () => { throw new TypeError("Failed to fetch"); };

beforeEach(() => { memoria.clear(); eventos.length = 0; detalles.length = 0; setToken("tok-aaaaaaaaaaaa"); });

test("con red devuelve lo del servidor y deja una copia con su hora", async () => {
  globalThis.fetch = async () => respuesta({ days: [{ day: "lunes" }] });
  const data = await Itinerary.get();
  assert.deepEqual(data, { days: [{ day: "lunes" }] });
  assert.equal(staleAt(data), null);
  const copia = loadLast(await duenoDeCopias(), "/api/itinerary");
  assert.deepEqual(copia.data, data);
  assert.ok(Math.abs(copia.at - Date.now()) < 5000);
});

test("el nombre de la clave no lleva ningún pedazo del token (se ve en DevTools y en backups)", async () => {
  globalThis.fetch = async () => respuesta({ days: [] });
  await Itinerary.get();
  const token = getToken();
  const claves = [...memoria.keys()].filter((k) => k.startsWith("reinventar.last."));
  assert.ok(claves.length > 0);
  for (const clave of claves) {
    for (let i = 0; i + 6 <= token.length; i++) assert.ok(!clave.includes(token.slice(i, i + 6)), `${clave} lleva «${token.slice(i, i + 6)}»`);
  }
  assert.match(await duenoDeCopias(), /^[0-9a-f]{12}$/);
});

test("el dueño es el mismo para el mismo token y distinto para otro", async () => {
  const a = await duenoDeCopias();
  assert.equal(await duenoDeCopias(), a);
  setToken("tok-zzzzzzzzzzzz");
  assert.notEqual(await duenoDeCopias(), a);
});

test("sin token no hay dueño: no se guarda ni se lee nada", async () => {
  setToken("");
  assert.equal(await duenoDeCopias(), null);
});

test("sin red muestra la última copia y la marca con la hora en que se guardó", async () => {
  globalThis.fetch = async () => respuesta([{ id: "s1" }]);
  await Sessions.list();
  globalThis.fetch = sinRed;
  const data = await Sessions.list();
  assert.deepEqual(data, [{ id: "s1" }]);
  assert.ok(staleAt(data) > 0);
});

test("los anuncios sin reserva también muestran la última copia sin señal", async () => {
  const anuncios = { items: [{ code: "KEY001" }], total: 1, is_today: true };
  globalThis.fetch = async () => respuesta(anuncios);
  await Anuncios.get();
  assert.deepEqual(loadLast(await duenoDeCopias(), "/api/anuncios").data, anuncios, "la respuesta buena se guarda");
  globalThis.fetch = sinRed;
  const data = await Anuncios.get();
  assert.deepEqual(data, anuncios);
  assert.ok(staleAt(data) > 0, "la copia va marcada con su hora");
});

test("anuncios con la misma validación de forma y tamaño que el resto", () => {
  for (const dato of ["<script>", 42, null]) saveLast(DUENO, "/api/anuncios", dato);
  saveLast(DUENO, "/api/anuncios", { relleno: "x".repeat(2_000_001) });
  assert.equal(loadLast(DUENO, "/api/anuncios"), null);
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

test("un portal cautivo (200 con HTML) también cae a la copia en vez de mostrar un error", async () => {
  globalThis.fetch = async () => respuesta({ items: [1] });
  await Today.get();
  globalThis.fetch = async () => ({ ok: true, status: 200, headers: { get: () => "text/html" }, text: async () => "<html>portal</html>" });
  const data = await Today.get();
  assert.deepEqual(data, { items: [1] });
  assert.ok(staleAt(data) > 0);
});

test("un portal cautivo sin copia guardada da el mensaje del portal, no un SyntaxError", async () => {
  globalThis.fetch = async () => ({ ok: true, status: 200, headers: { get: () => "text/html" }, text: async () => "<html>portal</html>" });
  await assert.rejects(Today.get(), (e) => e.status === 0 && /Wi-Fi|red/i.test(e.message) && !(e instanceof SyntaxError));
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
  saveLast(DUENO, "/api/today", { a: 1 });
  clearLast();
  assert.equal(memoria.get("reinventar.theme"), "dark");
  assert.equal(loadLast(DUENO, "/api/today"), null);
});

test("si el almacenamiento está lleno o roto, guardar no rompe la pantalla", () => {
  const original = globalThis.localStorage.setItem;
  globalThis.localStorage.setItem = () => { throw new DOMException("lleno", "QuotaExceededError"); };
  assert.doesNotThrow(() => saveLast(DUENO, "/api/today", { a: 1 }));
  globalThis.localStorage.setItem = original;
});

test("una copia ilegible se ignora", () => {
  memoria.set(`reinventar.last.${DUENO}./api/today`, "{no es json");
  assert.equal(loadLast(DUENO, "/api/today"), null);
});

test("solo se guardan las tres pantallas previstas: cualquier otra ruta se ignora", () => {
  for (const ruta of ["/api/me", "/api/today/../me", "__proto__", "/api/today?x=1", ""]) {
    saveLast(DUENO, ruta, { a: 1 });
    assert.equal(loadLast(DUENO, ruta), null, ruta);
  }
  assert.deepEqual(copiasGuardadas(), []);
});

test("solo se guardan objetos o listas: un texto o un número del servidor no entra", () => {
  for (const dato of ["<script>", 42, true, null, undefined]) saveLast(DUENO, "/api/today", dato);
  assert.deepEqual(copiasGuardadas(), []);
  saveLast(DUENO, "/api/sessions", [{ id: "s1" }]);
  assert.deepEqual(loadLast(DUENO, "/api/sessions").data, [{ id: "s1" }]);
});

test("el dueño tiene que tener forma de hash: nada raro en el nombre de la clave", () => {
  for (const dueno of ["yo", "../x", "0123456789AB", "0123456789abc", "", null]) {
    saveLast(dueno, "/api/today", { a: 1 });
    assert.equal(loadLast(dueno, "/api/today"), null, String(dueno));
  }
  assert.deepEqual(copiasGuardadas(), []);
});

test("una respuesta enorme no se guarda (no llena el almacenamiento del celular)", () => {
  saveLast(DUENO, "/api/sessions", [{ texto: "x".repeat(3_000_000) }]);
  assert.deepEqual(copiasGuardadas(), []);
});

test("al leer se descartan las claves que contaminan prototipos", () => {
  memoria.set(`reinventar.last.${DUENO}./api/today`, '{"at":1,"data":{"ok":1,"__proto__":{"admin":true},"anidado":{"__proto__":{"x":1},"y":2}}}');
  const { data } = loadLast(DUENO, "/api/today");
  assert.deepEqual(data, { ok: 1, anidado: { y: 2 } });
  assert.equal({}.admin, undefined);
  assert.equal(Object.getPrototypeOf(data), Object.prototype);
});

test("al leer se valida la forma: una copia con otra forma se ignora", () => {
  const clave = `reinventar.last.${DUENO}./api/today`;
  for (const rota of [{ at: "ayer", data: { a: 1 } }, { at: 1, data: "<script>" }, { at: 1 }, [1, 2], "texto", 7]) {
    memoria.set(clave, JSON.stringify(rota));
    assert.equal(loadLast(DUENO, "/api/today"), null, JSON.stringify(rota));
  }
});

test("la hora corta de los datos va en 24 h", () => {
  const at = new Date(2026, 11, 2, 14, 5).getTime();
  assert.equal(horaCorta(at), "14:05");
});

test("al caer a la copia se avisa «ra:sin-servicio» con la hora de la copia, y al volver «ra:con-servicio»", async () => {
  globalThis.fetch = async () => respuesta({ date: "2026-12-01" });
  await Today.get();
  assert.ok(eventos.includes("ra:con-servicio"), "con red, la API contestó");
  const guardada = loadLast(await duenoDeCopias(), "/api/today").at;
  eventos.length = 0; detalles.length = 0;
  globalThis.fetch = sinRed;
  await Today.get();
  const i = eventos.indexOf("ra:sin-servicio");
  assert.ok(i >= 0, "sin red cayó a la copia y avisó al banner");
  assert.equal(detalles[i].at, guardada);
  assert.equal(detalles[i].path, "/api/today");
  assert.equal(detalles[i].status, 0);
});

test("sin copia guardada no se avisa nada: el error sigue a la pantalla", async () => {
  globalThis.fetch = sinRed;
  await assert.rejects(Today.get());
  assert.ok(!eventos.includes("ra:sin-servicio"));
});

test("la última sincronización se guarda y se lee; sin valor o con basura es null", () => {
  assert.equal(leerUltimaSync(), null);
  marcarUltimaSync(1_764_690_000_000);
  assert.equal(leerUltimaSync(), 1_764_690_000_000);
  memoria.set("reinventar.ultimaSync", "ayer");
  assert.equal(leerUltimaSync(), null);
});

test("al guardar el token, la app avisa para que el service worker se entere", () => {
  setToken("tok-cccccccccccc");
  assert.ok(eventos.includes("reinventar:token"));
});
