// Pruebas de la lógica pura de la grabación (node --test). Sin navegador: se simulan los globales mínimos.
import test from "node:test";
import assert from "node:assert/strict";

const setInterval0 = globalThis.setInterval;
// recorder.js arma un setInterval al importarse: no debe retener el proceso.
globalThis.setInterval = (f, ms) => setInterval0(f, ms).unref();
globalThis.window = { addEventListener() {}, MediaRecorder: undefined };
globalThis.document = { addEventListener() {}, visibilityState: "visible" };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { InterruptionTracker, clasificarFalloDeSubida, MSG_PEDAZO_GRANDE } = await import("../../web/js/recorder.js");
const { atFaltante } = await import("../../web/js/store.js");

test("un 413 queda como fallido con el mensaje de pedazo grande y no se descarta", () => {
  assert.deepEqual(clasificarFalloDeSubida(413), { accion: "fallido", mensaje: MSG_PEDAZO_GRANDE });
});

test("un 422 también queda fallido para no trabar la cola", () => {
  assert.equal(clasificarFalloDeSubida(422).accion, "fallido");
});

test("404 y 409 se descartan: la sesión ya no existe o cerró", () => {
  assert.equal(clasificarFalloDeSubida(404).accion, "descartar");
  assert.equal(clasificarFalloDeSubida(409).accion, "descartar");
});

test("errores de red, 401 y 5xx se reintentan", () => {
  for (const s of [undefined, 401, 500, 502, 503]) assert.equal(clasificarFalloDeSubida(s).accion, "reintentar");
});

test("el corte empieza con el primer motivo y termina cuando se van todos", () => {
  const t = new InterruptionTracker();
  assert.equal(t.add("mute"), "begin");
  assert.equal(t.add("audiocontext"), null);
  assert.equal(t.remove("mute"), null);
  assert.equal(t.active, true);
  assert.equal(t.remove("audiocontext"), "end");
  assert.equal(t.active, false);
});

test("quitar un motivo que no estaba no genera un fin", () => {
  assert.equal(new InterruptionTracker().remove("mute"), null);
});

test("reset borra los motivos pendientes", () => {
  const t = new InterruptionTracker();
  t.add("mute"); t.reset();
  assert.equal(t.active, false);
});

test("la migración conserva el 'at' que ya tenía el pedazo", () => {
  assert.equal(atFaltante({ at: 1_700_000_000_000 }, 3), 1_700_000_000_000);
});

test("la migración le da un 'at' al pedazo que no lo tenía, antes que cualquier fecha real", () => {
  assert.equal(atFaltante({}, 2), 2);
  assert.equal(atFaltante({ at: "x" }, 5), 5);
  assert.ok(atFaltante({}, 0) < 1_000_000_000_000);
});
