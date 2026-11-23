// «Charlas nuevas» (node --test): los textos de la tarjeta de Inicio y del toast al agregar.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.window = { dispatchEvent() {}, addEventListener() {} };
globalThis.location = { hash: "" };

const { RUTA, textoAgregada, textoCantidad } = await import("../../web/js/charlasNuevas.js");

test("la cantidad va en singular o plural", () => {
  assert.equal(textoCantidad(1), "1 charla nueva");
  assert.equal(textoCantidad(3), "3 charlas nuevas");
});

test("al agregar avisa con qué se superpone, si choca", () => {
  assert.equal(textoAgregada([]), "Agregada a tu agenda.");
  assert.equal(textoAgregada(["Keynote", "DEV302"]), "Agregada a tu agenda. Se superpone con Keynote, DEV302.");
});

test("el push y la tarjeta abren la misma lista", () => {
  assert.equal(RUTA, "#/itinerario/nuevas");
});
