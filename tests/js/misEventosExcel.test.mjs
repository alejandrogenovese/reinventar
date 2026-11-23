// Carga de eventos desde Excel (node --test): el resumen de la vista previa y cuántas filas se guardan al confirmar.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.window = { dispatchEvent() {}, addEventListener() {} };
globalThis.location = { hash: "" };
globalThis.document = { createElement: () => ({ append() {}, setAttribute() {}, addEventListener() {}, classList: { add() {} } }) };

const { aGuardar, textoResumen } = await import("../../web/js/misEventosExcel.js");

test("el resumen nombra solo lo que hay, en singular o plural", () => {
  assert.equal(textoResumen({ nueva: 6, actualiza: 1, sin_cambios: 0, error: 2 }), "6 nuevos · 1 actualiza · 2 con error");
  assert.equal(textoResumen({ nueva: 1, actualiza: 2, sin_cambios: 3, error: 0 }), "1 nuevo · 2 actualizan · 3 sin cambios");
});

test("sin filas que sirvan, lo dice", () => {
  assert.equal(textoResumen({ nueva: 0, actualiza: 0, sin_cambios: 0, error: 0 }), "Nada para cargar");
});

test("al confirmar se guardan las nuevas y las que cambian, no las sin cambios ni las con error", () => {
  assert.equal(aGuardar({ nueva: 2, actualiza: 3, sin_cambios: 4, error: 5 }), 5);
});
