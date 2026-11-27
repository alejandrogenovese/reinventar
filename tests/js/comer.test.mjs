// Dónde comer barato (node --test): la consulta con el tipo de lugar y la etiqueta del tipo en la tarjeta.
import test from "node:test";
import assert from "node:assert/strict";

import "./domMinimo.mjs";

const { consulta, LugarCard, MINUTOS, minutosTexto, textoOrigen } = await import("../../web/js/comer.js");

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

test("los filtros nuevos viajan solo si no están en su valor por defecto", () => {
  const base = { precio: 2, minutos: 10 };
  assert.equal(consulta({ ...base, abierto: false, puntaje: 0, orden: "recomendado" }), "/api/comer?precio=2&minutos=10");
  const url = new URL(consulta({ precio: 4, minutos: 25, abierto: true, puntaje: 4.5, orden: "cerca" }), "https://x");
  assert.deepEqual(Object.fromEntries(url.searchParams), { precio: "4", minutos: "25", abierto: "true", puntaje: "4.5", orden: "cerca" });
});

test("el deslizador va de 5 a 30 minutos, como acepta el servidor", () => {
  assert.deepEqual(MINUTOS, { min: 5, max: 30, paso: 5 });
  assert.equal(minutosTexto(25), "Hasta 25 min caminando");
});

test("el origen dice si se buscó desde la sesión, el hotel o el celular", () => {
  assert.equal(textoOrigen({ fuente: "sesion", nombre: "MGM Grand" }), "Cerca de MGM Grand, tu próxima sesión");
  assert.equal(textoOrigen({ fuente: "hotel", nombre: "The Venetian Resort" }), "Cerca de tu hotel, The Venetian Resort");
  assert.equal(textoOrigen({ fuente: "telefono", nombre: null }), "Cerca de donde estás");
});
