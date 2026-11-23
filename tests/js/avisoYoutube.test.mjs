// Aviso de charla que AWS publica en YouTube (web/js/avisoYoutube.js): avisa antes de grabar, una vez por charla,
// y nunca frena una grabación por una falla propia.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { MAX_RECORDADAS, decidirPorYoutube, leerAvisadas, recordarAvisada } = await import("../../web/js/avisoYoutube.js");
const { decidirGrabar } = await import("../../web/js/grabacionDuplicada.js");

const CLAVE = "reinventar.aviso-youtube";
const BREAKOUT = { code: "ANT301-R1", base: "ANT301", type: "Breakout session", en_youtube: true };
const CHALK = { code: "ANT302", base: "ANT302", type: "Chalk talk", en_youtube: false };

function memoria(inicial = {}) {
  const datos = new Map(Object.entries(inicial));
  return { getItem: (k) => datos.get(k) ?? null, setItem: (k, v) => datos.set(k, String(v)) };
}
// "ok" = «Grabar igual», "cancel" = «No grabar», "" = cerrado con Esc
const contar = (respuesta) => {
  const p = async () => { p.veces += 1; return respuesta; };
  p.veces = 0;
  return p;
};

test("en una charla que sale en YouTube, «Grabar igual» sigue con la grabación", async () => {
  const preguntar = contar("ok");
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar, storage: memoria() }), true);
  assert.equal(preguntar.veces, 1);
});

test("«No grabar» no graba", async () => {
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar: contar("cancel"), storage: memoria() }), false);
});

test("no se muestra para un chalk talk ni sin charla elegida", async () => {
  const preguntar = contar("cancel");
  assert.equal(await decidirPorYoutube(CHALK, { preguntar, storage: memoria() }), true);
  assert.equal(await decidirPorYoutube(null, { preguntar, storage: memoria() }), true);
  assert.equal(preguntar.veces, 0);
});

test("una vez por charla: la segunda vez graba sin preguntar, aunque sea otro horario", async () => {
  const storage = memoria();
  const preguntar = contar("cancel");
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar, storage }), false);
  assert.equal(await decidirPorYoutube({ ...BREAKOUT, code: "ANT301-R2" }, { preguntar, storage }), true);
  assert.equal(preguntar.veces, 1);
  assert.equal(await decidirPorYoutube({ ...BREAKOUT, code: "KEY001", base: "KEY001" }, { preguntar, storage }), false);
  assert.equal(preguntar.veces, 2);
});

test("cerrar el aviso con Esc no graba ni lo da por visto: la próxima vez vuelve a preguntar", async () => {
  const storage = memoria();
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar: contar(""), storage }), false);
  assert.deepEqual(leerAvisadas(storage), []);
  const preguntar = contar("ok");
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar, storage }), true);
  assert.equal(preguntar.veces, 1);
});

test("si el almacenamiento falla (modo privado), igual avisa y respeta la elección", async () => {
  const roto = { getItem() { throw new Error("bloqueado"); }, setItem() { throw new Error("bloqueado"); } };
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar: contar("ok"), storage: roto }), true);
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar: contar("cancel"), storage: roto }), false);
});

test("si leer localStorage tira SecurityError (Safari con cookies bloqueadas), se puede grabar", async () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, get() { throw new Error("SecurityError"); } });
  try {
    assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar: contar("ok") }), true);
  } finally {
    Object.defineProperty(globalThis, "localStorage", original);
  }
});

test("si el diálogo falla, se graba", async () => {
  const falla = async () => { throw new Error("sin <dialog>"); };
  assert.equal(await decidirPorYoutube(BREAKOUT, { preguntar: falla, storage: memoria() }), true);
});

test("un JSON roto o que no es una lista cuenta como nada avisado", () => {
  assert.deepEqual(leerAvisadas(memoria({ [CLAVE]: "{no es json" })), []);
  assert.deepEqual(leerAvisadas(memoria({ [CLAVE]: '{"ANT301": true}' })), []);
  const storage = memoria({ [CLAVE]: "{no es json" });
  recordarAvisada(storage, "ANT301");
  assert.deepEqual(leerAvisadas(storage), ["ANT301"]);
});

test("recuerda como mucho las últimas MAX_RECORDADAS charlas", () => {
  const storage = memoria();
  for (let i = 0; i < MAX_RECORDADAS + 5; i++) recordarAvisada(storage, `C${i}`);
  const avisadas = leerAvisadas(storage);
  assert.equal(avisadas.length, MAX_RECORDADAS);
  assert.equal(avisadas[0], "C5");
  assert.equal(avisadas.at(-1), `C${MAX_RECORDADAS + 4}`);
});

test("con «Grabar igual» se llega a la consulta de grabación duplicada; con «No grabar», no", async () => {
  let consultas = 0;
  const consultar = async () => { consultas += 1; return { activa: null }; };
  const sigue = await decidirGrabar("ANT301-R1", { talk: BREAKOUT, consultar, youtube: { preguntar: contar("ok"), storage: memoria() } });
  assert.deepEqual(sigue, { grabar: true });
  assert.equal(consultas, 1);

  const frena = await decidirGrabar("ANT301-R1", { talk: BREAKOUT, consultar, youtube: { preguntar: contar("cancel"), storage: memoria() } });
  assert.deepEqual(frena, { grabar: false });
  assert.equal(consultas, 1);
});
