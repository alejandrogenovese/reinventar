// Alertas de ofertas (node --test): qué pasa al tocar «Avisarme de ofertas» y el porcentaje de una baja de precio.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.window = { dispatchEvent() {}, addEventListener() {} };
globalThis.location = { hash: "" };
globalThis.document = { createElement: () => ({ append() {}, setAttribute() {}, addEventListener() {}, classList: { add() {} } }) };

const { decisionActivacion, estadoVacio, porcentajeBaja, TEXTO_DENEGADO } = await import("../../web/js/ofertas.js");

test("iPhone sin instalar: se muestran los pasos de instalación, no se pide permiso", () => {
  assert.equal(decisionActivacion({ estado: "ios_sin_instalar", permiso: "default" }), "instalar");
});

test("navegador sin push: se avisa que no está soportado", () => {
  assert.equal(decisionActivacion({ estado: "no_soportado", permiso: undefined }), "no_soportado");
});

test("permiso denegado: se explica cómo habilitarlo en vez de fallar en silencio", () => {
  assert.equal(decisionActivacion({ estado: "ok", permiso: "denied" }), "denegado");
  assert.match(TEXTO_DENEGADO, /bloqueadas/);
  assert.match(TEXTO_DENEGADO, /Ajustes/);
});

test("permiso pendiente o concedido: se pide el permiso y se suscribe", () => {
  assert.equal(decisionActivacion({ estado: "ok", permiso: "default" }), "pedir");
  assert.equal(decisionActivacion({ estado: "ok", permiso: "granted" }), "pedir");
});

test("porcentajeBaja redondea y solo habla de bajas", () => {
  assert.equal(porcentajeBaja({ precio_antes: 89, precio_ahora: 62 }), "-30 %");
  assert.equal(porcentajeBaja({ precio_antes: null, precio_ahora: null }), "");
  assert.equal(porcentajeBaja({ precio_antes: 50, precio_ahora: 60 }), "");
});

test("sin ofertas: se explica de dónde salen y se lleva a Shows", () => {
  const vacio = estadoVacio({ categoria: "todas", esAdmin: false });
  assert.match(vacio.texto, /Ticketmaster publica precios/);
  assert.match(vacio.texto, /comida y outlets/);
  assert.deepEqual(vacio.enlaces.map((e) => e.href), ["#/eventos/shows"]);
});

test("sin ofertas y es admin: se ofrece «Cargar una oferta» en Admin › Ofertas", () => {
  const vacio = estadoVacio({ categoria: "todas", esAdmin: true });
  const cargar = vacio.enlaces.find((e) => e.texto === "Cargar una oferta");
  assert.equal(cargar?.href, "#/admin/ofertas");
  assert.equal(cargar?.primario, true);
});

test("sin ofertas en una categoría filtrada: texto corto y sin enlaces", () => {
  const vacio = estadoVacio({ categoria: "comida", esAdmin: true });
  assert.equal(vacio.texto, "No hay ofertas vigentes en esta categoría.");
  assert.deepEqual(vacio.enlaces, []);
});
