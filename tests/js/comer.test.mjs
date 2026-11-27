// Dónde comer barato (node --test): la consulta con el tipo de lugar y la etiqueta del tipo en la tarjeta.
import test from "node:test";
import assert from "node:assert/strict";

import "./domMinimo.mjs";

const { alternarPrecio, consulta, Estrellas, llenoPct, LugarCard, MINUTOS, minutosTexto, Precio, textoOrigen } = await import("../../web/js/comer.js");

const lugar = (extra = {}) => ({ place_id: "p1", nombre: "Hershey's Chocolate World", lat: 36.1, lng: -115.17, rating: 4.6,
  resenas: 9000, precio: 1, minutos: 6, abierto: true, direccion: "Las Vegas Blvd", extracto: [], ...extra });

test("sin tipo, la consulta manda los precios elegidos y los minutos", () => {
  assert.equal(consulta({ precios: [1, 2], minutos: 10 }), "/api/comer?precios=1&precios=2&minutos=10");
  assert.equal(consulta({ precios: [3, 1], minutos: 10, tipo: "todo" }), "/api/comer?precios=1&precios=3&minutos=10");
});

test("los precios se eligen de a varios y nunca queda ninguno", () => {
  assert.deepEqual(alternarPrecio([1, 2], 4), [1, 2, 4]);
  assert.deepEqual(alternarPrecio([1, 2], 1), [2]);
  assert.deepEqual(alternarPrecio([2], 2), [2]);
});

test("con tipo, lo manda junto con la ubicación", () => {
  const url = new URL(consulta({ precios: [1], minutos: 5, tipo: "dulces" }, { lat: 36.1, lng: -115.17 }), "https://x");
  assert.equal(url.searchParams.get("tipo"), "dulces");
  assert.equal(url.searchParams.get("lat"), "36.1");
});

test("la tarjeta muestra el tipo de lugar si Google lo trae", () => {
  assert.ok(LugarCard(lugar({ tipo: "Tienda de chocolate" })).textContent.includes("Tienda de chocolate"));
  assert.ok(!LugarCard(lugar()).textContent.includes("undefined"));
});

test("los filtros nuevos viajan solo si no están en su valor por defecto", () => {
  const base = { precios: [2], minutos: 10 };
  assert.equal(consulta({ ...base, abierto: false, puntaje: 0, orden: "recomendado" }), "/api/comer?precios=2&minutos=10");
  const url = new URL(consulta({ precios: [4], minutos: 25, abierto: true, puntaje: 4.5, orden: "cerca" }), "https://x");
  assert.deepEqual(Object.fromEntries(url.searchParams), { precios: "4", minutos: "25", abierto: "true", puntaje: "4.5", orden: "cerca" });
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

test("las estrellas se llenan como en Google: la última parcial, redondeada a la décima", () => {
  assert.equal(llenoPct(5), 100);
  assert.equal(llenoPct(4.3), 86);
  assert.equal(llenoPct(4.55), 92);
  assert.equal(llenoPct(0), 0);
  assert.equal(llenoPct(7), 100);
});

test("el puntaje muestra número, estrellas y reseñas, y lo dice entero para el lector de pantalla", () => {
  const el = Estrellas(4.6, { resenas: 9000 });
  assert.ok(el.textContent.startsWith("4,6"));
  assert.ok(el.textContent.includes("(9.000)"));
  assert.equal(el.getAttribute("aria-label"), "4,6 de 5 estrellas, 9.000 reseñas");
});

/** Primer descendiente con esa clase (el DOM de prueba no tiene querySelector). */
function buscar(nodo, clase) {
  if (typeof nodo !== "object" || !nodo) return null;
  if (String(nodo.className).split(" ").includes(clase) || String(nodo.attrs?.class ?? "").split(" ").includes(clase)) return nodo;
  for (const hijo of nodo.children ?? []) { const r = buscar(hijo, clase); if (r) return r; }
  return null;
}

test("el precio resalta su nivel, apaga el resto y dice la palabra", () => {
  const el = Precio(2);
  assert.equal(el.textContent, "$$$$ · Moderado");
  assert.equal(buscar(el, "ra-precio-on").textContent, "$$");
  assert.equal(buscar(el, "ra-precio-off").textContent, "$$");
  assert.equal(Precio(null).textContent, "Sin dato de precio");
});

test("cada reseña lleva sus estrellas", () => {
  const card = LugarCard(lugar({ extracto: [{ texto: "Muy rico", puntaje: 5 }] }));
  assert.ok(card.textContent.includes("“Muy rico”"));
  assert.ok(buscar(buscar(card, "ra-resena"), "ra-estrellas"));
});

test("«Apps de pedidos» es un tipo más y lleva a Uber Eats, DoorDash y Grubhub", async () => {
  const { APPS_PEDIDOS, AppsPedidos } = await import("../../web/js/appsPedidos.js");
  assert.deepEqual(APPS_PEDIDOS.map((a) => a.nombre), ["Uber Eats", "DoorDash", "Grubhub"]);
  assert.ok(APPS_PEDIDOS.every((a) => a.url.startsWith("https://www.")));
  const nodos = AppsPedidos();
  assert.equal(nodos.length, 1 + APPS_PEDIDOS.length);  // el aviso del hotel y una tarjeta por app
  assert.ok(nodos[1].textContent.includes("Abrir Uber Eats"));
});
