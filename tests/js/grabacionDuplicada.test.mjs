// Aviso de grabación duplicada (web/js/grabacionDuplicada.js): avisa quién ya graba y nunca frena la grabación.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { consultarActiva, decidirGrabar, textoAviso } = await import("../../web/js/grabacionDuplicada.js");

const ACTIVA = { id: "abc123def456", quien: "ana", status: "recording" };
const responde = (activa) => async () => ({ activa });

test("si nadie la graba, se graba sin preguntar", async () => {
  let pregunto = false;
  const r = await decidirGrabar("ANT301", { consultar: responde(null), preguntar: async () => { pregunto = true; return true; } });
  assert.deepEqual(r, { grabar: true });
  assert.equal(pregunto, false);
});

test("si otra persona la graba, avisa quién y «Grabar igual» graba", async () => {
  let vista;
  const r = await decidirGrabar("ANT301", { consultar: responde(ACTIVA), preguntar: async (a) => { vista = a; return true; } });
  assert.deepEqual(r, { grabar: true });
  assert.equal(textoAviso(vista), "ana ya está grabando esta charla");
});

test("elegir «Ver la suya» no graba y lleva a la grabación de la otra persona", async () => {
  const r = await decidirGrabar("ANT301", { consultar: responde(ACTIVA), preguntar: async () => false });
  assert.deepEqual(r, { grabar: false, ver: ACTIVA.id });
});

test("sin señal, con error o sin código, se graba igual (la consulta no tira)", async () => {
  const falla = async () => { throw Object.assign(new Error("Sin conexión"), { status: 0 }); };
  assert.equal(await consultarActiva("ANT301", falla), null);
  assert.equal(await consultarActiva(null, responde(ACTIVA)), null);
  assert.deepEqual(await decidirGrabar("ANT301", { consultar: falla, preguntar: async () => false }), { grabar: true });
});

test("una consulta lenta se corta: no hace esperar para grabar", async () => {
  const lenta = (code, signal) => new Promise((_, reject) => signal.addEventListener("abort", () => reject(signal.reason)));
  const t0 = Date.now();
  assert.equal(await consultarActiva("ANT301", lenta, 50), null);
  assert.ok(Date.now() - t0 < 1000);
});

test("sin nombre (grabaciones viejas) dice «Alguien»", () => {
  assert.equal(textoAviso({ id: "x", quien: null }), "Alguien ya está grabando esta charla");
});
