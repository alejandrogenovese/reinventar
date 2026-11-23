// Dónde comer barato (node --test): la consulta con el tipo de lugar y la etiqueta del tipo en la tarjeta.
import test from "node:test";
import assert from "node:assert/strict";

import "./domMinimo.mjs";

const { consulta, LugarCard } = await import("../../web/js/comer.js");

const lugar = (extra = {}) => ({ place_id: "p1", nombre: "Hershey's Chocolate World", lat: 36.1, lng: -115.17, rating: 4.6,
  resenas: 9000, precio: 1, minutos: 6, abierto: true, direccion: "Las Vegas Blvd", extracto: [], ...extra });

test("sin tipo, la consulta queda como antes", () => {
  assert.equal(consulta({ precio: 2, minutos: 10 }), "/api/comer?precio=2&minutos=10");
  assert.equal(consulta({ precio: 2, minutos: 10, tipo: "todo" }), "/api/comer?precio=2&minutos=10");
});

test("con tipo, lo manda junto con la ubicación", () => {
  const url = new URL(consulta({ precio: 1, minutos: 5, tipo: "dulces" }, { lat: 36.1, lng: -115.17 }), "https://x");
  assert.equal(url.searchParams.get("tipo"), "dulces");
  assert.equal(url.searchParams.get("lat"), "36.1");
});

test("la tarjeta muestra el tipo de lugar si Google lo trae", () => {
  assert.ok(LugarCard(lugar({ tipo: "Tienda de chocolate" })).textContent.includes("Tienda de chocolate"));
  assert.ok(!LugarCard(lugar()).textContent.includes("undefined"));
});
