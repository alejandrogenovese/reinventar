// Pruebas de mensajeError (node --test): qué texto le llega al usuario cuando algo falla.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { mensajeError, GENERIC_ERROR } = await import("../../web/js/ui.js");
const { ApiError } = await import("../../web/js/api.js");

// Los errores técnicos van a console; el test los silencia para no ensuciar la salida.
function sinConsola(fn) {
  const original = console.error;
  const llamadas = [];
  console.error = (...args) => llamadas.push(args);
  try { return { resultado: fn(), llamadas }; } finally { console.error = original; }
}

test("un error de la API conserva su mensaje (ya viene en castellano del servidor)", () => {
  assert.equal(mensajeError(new ApiError(422, "Falta el nombre")), "Falta el nombre");
});

test("un Error propio de la app (con texto en castellano) pasa tal cual", () => {
  assert.equal(mensajeError(new Error("Primero prendé «Usar mi ubicación».")), "Primero prendé «Usar mi ubicación».");
});

for (const [nombre, error] of [
  ["«Load failed» de Safari (TypeError)", new TypeError("Load failed")],
  ["«Failed to fetch» (TypeError)", new TypeError("Failed to fetch")],
  ["NotAllowedError del navegador (DOMException)", new DOMException("The operation either timed out or was not allowed.", "NotAllowedError")],
  ["InvalidStateError de una passkey repetida (DOMException)", new DOMException("The user attempted to register an authenticator that contains one of the credentials already registered.", "InvalidStateError")],
  ["JSON roto (SyntaxError)", new SyntaxError("Unexpected token '<', \"<html>\" is not valid JSON")],
]) {
  test(`${nombre} no llega al usuario en inglés: sale el texto genérico y el detalle va a console`, () => {
    const { resultado, llamadas } = sinConsola(() => mensajeError(error));
    assert.equal(resultado, GENERIC_ERROR);
    assert.doesNotMatch(resultado, /failed|Unexpected|authenticator|not allowed/i);
    assert.equal(llamadas.length, 1);
    assert.equal(llamadas[0].includes(error), true);
  });
}

test("se puede pasar un texto propio para el caso genérico", () => {
  const { resultado } = sinConsola(() => mensajeError(new TypeError("Load failed"), "No se pudo activar."));
  assert.equal(resultado, "No se pudo activar.");
});

test("null, undefined o un texto suelto también dan el texto genérico, nunca «null» ni «undefined»", () => {
  for (const raro of [null, undefined, "boom"]) {
    const { resultado } = sinConsola(() => mensajeError(raro));
    assert.equal(resultado, GENERIC_ERROR);
  }
});
