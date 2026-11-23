// Actividades (node --test): textos de duración, precio y distancia de las tarjetas, y la consulta de Cerca.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.window = { dispatchEvent() {}, addEventListener() {} };
globalThis.location = { hash: "" };
globalThis.document = { createElement: () => ({ append() {}, setAttribute() {}, addEventListener() {}, classList: { add() {} } }) };

const { minutosTexto, duracionTexto, precioTexto, distanciaTexto, consultaCerca } = await import("../../web/js/actividades.js");

test("minutos en horas y minutos", () => {
  assert.equal(minutosTexto(45), "45 min");
  assert.equal(minutosTexto(120), "2 h");
  assert.equal(minutosTexto(90), "1 h 30 min");
});

test("duración fija, variable o sin dato", () => {
  assert.equal(duracionTexto(720, 720), "12 h");
  assert.equal(duracionTexto(30, 60), "30 min a 1 h");
  assert.equal(duracionTexto(null, 90), "1 h 30 min");
  assert.equal(duracionTexto(null, null), null);
});

test("precio desde, con decimales solo si hacen falta", () => {
  assert.equal(precioTexto(189.99), "desde US$ 189,99");
  assert.equal(precioTexto(25, "USD"), "desde US$ 25");
  assert.equal(precioTexto(30, "EUR"), "desde EUR 30");
  assert.equal(precioTexto(null), null);
});

test("distancia en metros redondeados o en km", () => {
  assert.equal(distanciaTexto(648), "a 650 m");
  assert.equal(distanciaTexto(2300), "a 2,3 km");
});

test("Cerca manda lat/lng solo si hay ubicación", () => {
  assert.equal(consultaCerca(null), "/api/actividades/cerca");
  assert.equal(consultaCerca({ lat: 36.1, lng: -115.2 }), "/api/actividades/cerca?lat=36.1&lng=-115.2");
});
