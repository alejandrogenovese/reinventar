// Aviso de charla que AWS publica en YouTube (web/js/avisoYoutube.js): avisa antes de grabar, una vez por charla.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { decidirPorYoutube } = await import("../../web/js/avisoYoutube.js");

const BREAKOUT = { code: "ANT301-R1", base: "ANT301", type: "Breakout session", en_youtube: true };
const CHALK = { code: "ANT302", base: "ANT302", type: "Chalk talk", en_youtube: false };

function memoria() {
  const datos = new Map();
  return { getItem: (k) => datos.get(k) ?? null, setItem: (k, v) => datos.set(k, String(v)) };
}
const contar = (respuesta) => {
  const p = async () => { p.veces += 1; return respuesta; };
  p.veces = 0;
  return p;
};

test("en una charla que sale en YouTube, «Grabar igual» sigue con la grabación", async () => {
  const preguntar = contar(true);
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar, storage: memoria() }), true);
  assert.equal(preguntar.veces, 1);
});

test("«No grabar» no graba", async () => {
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar: contar(false), storage: memoria() }), false);
});

test("no se muestra para un chalk talk ni sin charla elegida", async () => {
  const preguntar = contar(false);
  assert.equal(await decidirPorYoutube(CHALK, { preguntar, storage: memoria() }), true);
  assert.equal(await decidirPorYoutube(null, { preguntar, storage: memoria() }), true);
  assert.equal(preguntar.veces, 0);
});

test("una vez por charla: la segunda vez graba sin preguntar, aunque sea otro horario", async () => {
  const storage = memoria();
  const preguntar = contar(false);
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar, storage }), false);
  assert.equal(await decidirPorYoutube({ ...BREAKOUT, code: "ANT301-R2" }, { preguntar, storage }), true);
  assert.equal(preguntar.veces, 1);
  assert.equal(await decidirPorYoutube({ ...BREAKOUT, code: "KEY001", base: "KEY001" }, { preguntar, storage }), false);
  assert.equal(preguntar.veces, 2);
});

test("si el almacenamiento falla (modo privado), igual avisa y respeta la elección", async () => {
  const roto = { getItem() { throw new Error("bloqueado"); }, setItem() { throw new Error("bloqueado"); } };
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar: contar(true), storage: roto }), true);
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar: contar(false), storage: roto }), false);
});
