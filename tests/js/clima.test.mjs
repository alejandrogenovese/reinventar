// Pruebas del clima de Las Vegas en Hoy (node --test): el bloque compacto, los textos y la copia sin señal. Sin red:
// fetch es de mentira. Con el DOM mínimo compartido.
import test from "node:test";
import assert from "node:assert/strict";
import "./domMinimo.mjs";

const memoria = new Map();
globalThis.localStorage = {
  getItem: (k) => (memoria.has(k) ? memoria.get(k) : null),
  setItem: (k, v) => { memoria.set(k, String(v)); },
  removeItem: (k) => { memoria.delete(k); },
  key: (i) => [...memoria.keys()][i] ?? null,
  get length() { return memoria.size; },
};

const { ClimaHoy, cargarClima, copiaVieja, horaLasVegas, lineaProximos, maxMin, nombreDia } = await import("../../web/js/clima.js");
const { Clima, setToken } = await import("../../web/js/api.js");
const { markStale } = await import("../../web/js/lastgood.js");

const DATOS = Object.freeze({
  ahora: { temp_c: 14, descripcion: "Parcialmente nublado", viento_kmh: 5, desde: "18:00" },
  dias: [
    { fecha: "2026-11-30", max_c: 16, min_c: 7, descripcion: "Soleado", lluvia_pct: 0 },
    { fecha: "2026-12-01", max_c: 17, min_c: 8, descripcion: "Mayormente soleado", lluvia_pct: 0 },
    { fecha: "2026-12-02", max_c: 15, min_c: 6, descripcion: "Nublado", lluvia_pct: 10 },
  ],
  consejos: ["Fresco a la noche: llevá abrigo"],
  actualizado: "2026-11-30T18:44-08:00",
});

const texto = (nodo) => nodo.textContent;
const AL_RATO = Date.parse("2026-11-30T19:44-08:00"); // una hora después de actualizado

test("la hora va en hora de Las Vegas, no la del celular", () => {
  assert.equal(horaLasVegas("2026-11-30T18:44-08:00"), "18:44");
  assert.equal(horaLasVegas("2026-12-01T02:44Z"), "18:44");
  assert.equal(horaLasVegas("cualquier cosa"), "");
  assert.equal(horaLasVegas(null), "");
});

test("mañana se llama «Mañana» y pasado lleva el día de la semana", () => {
  assert.equal(nombreDia("2026-12-01", 1), "Mañana");
  assert.match(nombreDia("2026-12-02", 2), /^Mié/);
  assert.match(nombreDia("2026-12-02", 2), /2/);
});

test("máxima y mínima, o solo la que haya (a la noche NWS ya no da la máxima)", () => {
  assert.equal(maxMin({ max_c: 16, min_c: 7 }), "Máx 16° · Mín 7°");
  assert.equal(maxMin({ max_c: null, min_c: 7 }), "Mín 7°");
  assert.equal(maxMin({}), "");
});

test("mañana y pasado en una línea", () => {
  const linea = lineaProximos(DATOS.dias);
  assert.match(linea, /^Mañana 17°\/8° Mayormente soleado · Mié.* 15°\/6° Nublado$/);
  assert.equal(lineaProximos([DATOS.dias[0]]), "");
});

test("el bloque muestra lo de ahora, máx/mín, el consejo, los próximos días y la hora", () => {
  const el = ClimaHoy(DATOS);
  const todo = texto(el);
  assert.equal(el.attrs["aria-label"], "Clima en Las Vegas");
  assert.match(todo, /14 °C · Parcialmente nublado/);
  assert.match(todo, /Máx 16° · Mín 7°/);
  assert.match(todo, /Fresco a la noche: llevá abrigo/);
  assert.match(todo, /Mañana 17°\/8°/);
  assert.match(todo, /Actualizado a las 18:44 \(hora de Las Vegas\) · National Weather Service/);
});

test("sin señal dice que es la copia y de qué hora", () => {
  const copia = markStale(JSON.parse(JSON.stringify(DATOS)), Date.now() - 60_000);
  assert.match(texto(ClimaHoy(copia, AL_RATO)), /Sin señal: actualizado a las 18:44 \(hora de Las Vegas\)/);
});

test("una copia sin señal de hace más de 6 h no se muestra; lo fresco del servidor, sí", () => {
  const copia = markStale(JSON.parse(JSON.stringify(DATOS)), AL_RATO);
  const despues = AL_RATO + 6 * 60 * 60 * 1000;
  assert.equal(copiaVieja(copia, despues), true);
  assert.equal(ClimaHoy(copia, despues), null);
  assert.equal(copiaVieja(DATOS, despues), false);
  assert.notEqual(ClimaHoy(DATOS, despues), null);
  assert.equal(copiaVieja(markStale({ ...DATOS, actualizado: null }, AL_RATO), AL_RATO), true);
});

test("sin datos no hay bloque", () => {
  for (const dato of [null, undefined, "x", {}, { ahora: null, dias: [] }]) assert.equal(ClimaHoy(dato), null);
});

test("si el pedido falla, el lugar queda vacío y no rompe", async () => {
  const slot = globalThis.document.createElement("div");
  await cargarClima(slot, Promise.reject(new Error("NWS caído")));
  assert.equal(texto(slot), "");
  await cargarClima(slot, Promise.resolve(null));
  assert.equal(texto(slot), "");
  await cargarClima(slot, Promise.resolve(DATOS));
  assert.match(texto(slot), /14 °C/);
});

test("pide /api/clima y sin red devuelve la última copia marcada", async () => {
  setToken("tok-clima-aaaaaaaa");
  const pedidos = [];
  globalThis.fetch = async (url) => { pedidos.push(String(url)); return { ok: true, status: 200, json: async () => DATOS }; };
  assert.equal((await Clima.get()).ahora.temp_c, 14);
  assert.ok(pedidos.some((u) => u.endsWith("/api/clima")));
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  const copia = await Clima.get();
  assert.equal(copia.ahora.temp_c, 14);
  assert.match(texto(ClimaHoy(copia, AL_RATO)), /Sin señal/);
});

test("el clima tiene tope propio y no avisa al banner de estado si falla", async () => {
  setToken("tok-clima-bbbbbbbb");
  const eventos = [];
  globalThis.window = { dispatchEvent: (e) => { eventos.push(e.type); return true; }, addEventListener() {} };
  let senal = null;
  globalThis.fetch = async (_url, opciones) => { senal = opciones?.signal; return { ok: true, status: 200, json: async () => DATOS }; };
  await Clima.get();
  assert.ok(senal, "sin copia igual va con tope");
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await Clima.get();
  assert.deepEqual(eventos, []);
});
