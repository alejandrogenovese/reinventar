// Pruebas de la lógica pura de «Llevame» embebido (node --test): cuándo se muestra el mapa y cuándo cae al link externo.
import test from "node:test";
import assert from "node:assert/strict";

const { decidirLlevame, pedidoRuta, formatearDistancia, resumenRuta } = await import("../../web/js/llevamePuro.js");

const SEDE = { lat: 36.1216, lng: -115.1691, name: "Venetian" };
const AQUI = { lat: 36.1147, lng: -115.1728 };

test("con sede exacta, ubicación y señal se embebe el mapa", () => {
  assert.deepEqual(decidirLlevame({ dest: SEDE, here: AQUI, online: true }), { embeber: true });
});

test("la ubicación simulada del modo prueba también alcanza", () => {
  assert.equal(decidirLlevame({ dest: SEDE, here: { ...AQUI, simulated: true } }).embeber, true);
});

test("sin ubicación cae al link externo", () => {
  assert.deepEqual(decidirLlevame({ dest: SEDE, here: null }), { embeber: false, motivo: "sin-ubicacion" });
  assert.equal(decidirLlevame({ dest: SEDE, here: { lat: null, lng: null } }).motivo, "sin-ubicacion");
});

test("sin señal cae al link externo", () => {
  assert.deepEqual(decidirLlevame({ dest: SEDE, here: AQUI, online: false }), { embeber: false, motivo: "sin-senal" });
});

test("sin destino o con zona aproximada no hay ruta que dibujar", () => {
  assert.equal(decidirLlevame({ dest: null, here: AQUI }).motivo, "sin-destino");
  assert.equal(decidirLlevame({ dest: { name: "x" }, here: AQUI }).motivo, "sin-destino");
  assert.equal(decidirLlevame({ dest: { ...SEDE, approx: true }, here: AQUI }).motivo, "zona-aproximada");
});

test("sin argumentos no tira error y no se embebe", () => {
  assert.equal(decidirLlevame().embeber, false);
});

test("el pedido de ruta es a pie, de la ubicación a la sede, y no arrastra datos de más", () => {
  const pedido = pedidoRuta({ ...AQUI, simulated: true, at: 123 }, { ...SEDE, placeId: "abc" });

  assert.deepEqual(pedido.origin, { lat: AQUI.lat, lng: AQUI.lng });
  assert.deepEqual(pedido.destination, { lat: SEDE.lat, lng: SEDE.lng });
  assert.equal(pedido.travelMode, "WALKING");
  assert.deepEqual(pedido.fields, ["durationMillis", "distanceMeters", "viewport", "path"]);
});

test("la distancia usa metros bajo el kilómetro y coma decimal arriba", () => {
  assert.equal(formatearDistancia(347), "350 m");
  assert.equal(formatearDistancia(3), "10 m");
  assert.equal(formatearDistancia(1000), "1,0 km");
  assert.equal(formatearDistancia(1432), "1,4 km");
});

test("el resumen redondea los minutos para arriba y junta duración y distancia", () => {
  assert.deepEqual(resumenRuta({ durationMillis: 17 * 60_000 + 1, distanceMeters: 1432 }),
    { minutos: 18, distancia: "1,4 km", texto: "18 min caminando · 1,4 km" });
});

test("el resumen sin distancia muestra solo la duración y nunca dice 0 min", () => {
  assert.equal(resumenRuta({ durationMillis: 5_000 }).texto, "1 min caminando");
});

test("una respuesta sin duración (sin ruta) no tiene resumen", () => {
  assert.equal(resumenRuta(undefined), null);
  assert.equal(resumenRuta({ distanceMeters: 500 }), null);
});
