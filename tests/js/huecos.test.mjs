// Tramos sin audio: detección, intercalado en la transcripción, envío tolerante al servidor y tip de No molestar.
import test from "node:test";
import assert from "node:assert/strict";

const datos = new Map();
globalThis.localStorage = {
  getItem: (k) => (datos.has(k) ? datos.get(k) : null),
  setItem: (k, v) => datos.set(k, String(v)),
  removeItem: (k) => datos.delete(k),
};

const hu = await import("../../web/js/huecos.js");

// Alimenta el detector como el medidor (cada 0,5 s): muestras = [segundo, silencioso].
function correr(detector, muestras) {
  for (const [t, silencioso] of muestras) detector.observar(t, silencioso);
  return detector;
}
const cada = (desde, hasta, silencioso, paso = 0.5) => {
  const out = [];
  for (let t = desde; t <= hasta + 1e-9; t += paso) out.push([t, silencioso]);
  return out;
};

test("el umbral mínimo es una constante con nombre de ~3 segundos", () => {
  assert.equal(hu.HUECO_MIN_S, 3);
});

test("un silencio corto del orador (menos que el umbral) no cuenta", () => {
  const d = correr(hu.crearDetectorDeHuecos(), [...cada(0, 10, false), ...cada(10.5, 12, true), ...cada(12.5, 20, false)]);
  d.finalizar();
  assert.deepEqual(d.huecos(), []);
});

test("un tramo sin sonido de más de 3 segundos queda registrado en segundos del contador", () => {
  const d = correr(hu.crearDetectorDeHuecos(), [...cada(0, 125.5, false), ...cada(126, 160, true), ...cada(160.5, 170, false)]);
  assert.deepEqual(d.huecos(), [{ desde: 126, hasta: 160.5 }]);
});

test("durante una pausa o un corte del sistema el contador está quieto: no suma y el tramo sigue abierto", () => {
  // 4 s sin sonido, pausa (muestras null con el contador en 14), y sigue sin sonido 1 s más al reanudar
  const d = correr(hu.crearDetectorDeHuecos(), [...cada(0, 9.5, false), ...cada(10, 14, true), ...cada(14, 14, null), ...cada(14.5, 15, true), [15.5, false]]);
  assert.deepEqual(d.huecos(), [{ desde: 10, hasta: 15.5 }]);
});

test("una pausa larga no inventa un hueco si no había silencio", () => {
  const d = correr(hu.crearDetectorDeHuecos(), [...cada(0, 20, false), [20, null], [20, null], ...cada(20.5, 30, false)]);
  d.finalizar();
  assert.deepEqual(d.huecos(), []);
});

test("si el sonido vuelve, el tramo se corta ahí; después puede haber otro", () => {
  const d = correr(hu.crearDetectorDeHuecos(), [...cada(0, 4, true), ...cada(4.5, 8, false), ...cada(8.5, 13, true), [13.5, false]]);
  assert.deepEqual(d.huecos(), [{ desde: 0, hasta: 4.5 }, { desde: 8.5, hasta: 13.5 }]);
});

test("al terminar con el tramo abierto, finalizar lo cierra con la última muestra sin sonido", () => {
  const d = correr(hu.crearDetectorDeHuecos(), [...cada(0, 5, false), ...cada(5.5, 12, true)]);
  assert.deepEqual(d.huecos(), []);
  assert.equal(d.finalizar(), true);
  assert.deepEqual(d.huecos(), [{ desde: 5.5, hasta: 12 }]);
  assert.equal(d.finalizar(), false);
});

test("observar avisa solo cuando se cierra un tramo nuevo (para guardarlo)", () => {
  const d = hu.crearDetectorDeHuecos();
  const avisos = [...cada(0, 4, true), [4.5, false]].map(([t, s]) => d.observar(t, s));
  assert.deepEqual(avisos.filter(Boolean).length, 1);
  assert.equal(avisos.at(-1), true);
});

test("retomar una grabación conserva los huecos guardados y no comparte el arreglo", () => {
  const guardados = [{ desde: 1, hasta: 6 }];
  const d = hu.crearDetectorDeHuecos(guardados);
  d.finalizar();
  assert.deepEqual(d.huecos(), guardados);
  d.huecos().push({ desde: 0, hasta: 1 });
  assert.equal(d.huecos().length, 1);
  assert.equal(guardados.length, 1);
});

// --- intercalado en la transcripción ---
const B = (start_s) => ({ start_s, es: `b${start_s}`, en: "x" });

test("intercalarHuecos pone el separador en el lugar que corresponde por tiempo", () => {
  const items = hu.intercalarHuecos([B(0), B(120), B(170), B(200)], [{ desde: 126, hasta: 160.5 }]);
  assert.deepEqual(items.map((i) => i.tipo === "hueco" ? "H" : i.bloque.start_s), [0, 120, "H", 170, 200]);
  assert.deepEqual(items[2], { tipo: "hueco", desde: 126, hasta: 160.5 });
});

test("intercalarHuecos: antes del primer bloque, al final y varios juntos", () => {
  const items = hu.intercalarHuecos([B(10), B(50)], [{ desde: 100, hasta: 110 }, { desde: 0, hasta: 5 }, { desde: 20, hasta: 30 }]);
  assert.deepEqual(items.map((i) => i.tipo === "hueco" ? `H${i.desde}` : i.bloque.start_s), ["H0", 10, "H20", 50, "H100"]);
});

test("intercalarHuecos sin huecos (o con basura) devuelve solo los bloques", () => {
  for (const huecos of [undefined, null, [], [{ desde: "a", hasta: 3 }], [{ desde: 5, hasta: 2 }], "x"]) {
    const items = hu.intercalarHuecos([B(0), B(60)], huecos);
    assert.deepEqual(items.map((i) => i.tipo), ["bloque", "bloque"]);
  }
});

test("textoHueco usa mm:ss y la forma «— sin audio 02:06–02:40 —»", () => {
  assert.equal(hu.textoHueco({ desde: 126, hasta: 160.5 }), "— sin audio 02:06–02:40 —");
  assert.equal(hu.textoHueco({ desde: 3725, hasta: 3800 }), "— sin audio 1:02:05–1:03:20 —");
});

// --- envío ---
const err = (status) => Object.assign(new Error("x"), { status });

test("mandarHuecos sin huecos no llama al servidor", async () => {
  assert.deepEqual(await hu.mandarHuecos("r1", [], async () => assert.fail("no debe enviar")), { resultado: "ok" });
});

test("mandarHuecos manda la lista a la sesión real", async () => {
  let enviado = null;
  const r = await hu.mandarHuecos("r1", [{ desde: 1, hasta: 5 }], async (id, hs) => { enviado = [id, hs]; return { huecos: hs }; });
  assert.equal(r.resultado, "ok");
  assert.deepEqual(enviado, ["r1", [{ desde: 1, hasta: 5 }]]);
});

test("mandarHuecos tolera 404 (backend sin el endpoint), 403 (sesión ajena) y 422: se descartan sin error", async () => {
  for (const status of [404, 403, 422, 405]) {
    assert.deepEqual(await hu.mandarHuecos("r1", [{ desde: 1, hasta: 5 }], async () => { throw err(status); }), { resultado: "ok" }, `status ${status}`);
  }
});

test("mandarHuecos pide reintentar si no hay red, 401 o 5xx", async () => {
  for (const status of [0, undefined, 401, 500, 503]) {
    const r = await hu.mandarHuecos("r1", [{ desde: 1, hasta: 5 }], async () => { throw err(status); });
    assert.equal(r.resultado, "reintentar", `status ${status}`);
    assert.equal(r.error.status, status);
  }
});

// --- tip de No molestar ---
test("el tip aparece hasta que se descarta, y después no vuelve", () => {
  datos.clear();
  assert.equal(hu.tipNoMolestarVisto(), false);
  hu.marcarTipNoMolestarVisto();
  assert.equal(hu.tipNoMolestarVisto(), true);
});

test("el tip no rompe si localStorage tira error", () => {
  const original = globalThis.localStorage;
  globalThis.localStorage = { getItem() { throw new Error("bloqueado"); }, setItem() { throw new Error("bloqueado"); }, removeItem() {} };
  try {
    assert.equal(hu.tipNoMolestarVisto(), false);
    assert.doesNotThrow(() => hu.marcarTipNoMolestarVisto());
  } finally { globalThis.localStorage = original; }
});

test("el texto del tip es el pedido", () => {
  assert.equal(hu.TIP_NO_MOLESTAR, "Tip: poné No molestar. Una llamada o grabar un audio de WhatsApp le saca el micrófono a la app y ese tramo queda sin sonido.");
});
