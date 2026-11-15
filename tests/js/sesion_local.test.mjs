// Sesiones locales (grabar sin señal): ids provisorios, estado persistido, cierre automático y rutas.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// localStorage en memoria; se reinicia en cada test con limpiar().
const datos = new Map();
globalThis.localStorage = {
  getItem: (k) => (datos.has(k) ? datos.get(k) : null),
  setItem: (k, v) => datos.set(k, String(v)),
  removeItem: (k) => datos.delete(k),
};
globalThis.crypto ??= (await import("node:crypto")).webcrypto;
const limpiar = () => datos.clear();

const setInterval0 = globalThis.setInterval;
globalThis.setInterval = (f, ms) => setInterval0(f, ms).unref(); // recorder.js arma un setInterval al importarse
globalThis.window = { addEventListener() {}, MediaRecorder: undefined };
globalThis.document = { addEventListener() {}, visibilityState: "visible" };

const store = await import("../../web/js/store.js");
const rec = await import("../../web/js/recorder.js");

const META = { title: "Charla de prueba", kind: "talk", code: "ARC407", venue: null, speaker: null };

test("los ids locales tienen prefijo loc_ y 12 hex, y no se repiten", () => {
  const a = store.nuevoIdLocal(), b = store.nuevoIdLocal();
  assert.match(a, /^loc_[0-9a-f]{12}$/);
  assert.notEqual(a, b);
});

test("esLocal distingue ids locales de los del servidor", () => {
  assert.equal(store.esLocal(store.nuevoIdLocal()), true);
  assert.equal(store.esLocal("a1b2c3d4e5f6"), false);
  assert.equal(store.esLocal("loc_xyz"), false);
  assert.equal(store.esLocal(undefined), false);
});

test("crear una sesión local la guarda con sus datos y sin realId", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  assert.equal(store.esLocal(s.id), true);
  assert.deepEqual(store.sesionLocal(s.id).meta, META);
  assert.equal(store.sesionLocal(s.id).realId, null);
});

test("sesionLocal devuelve null si no existe", () => {
  limpiar();
  assert.equal(store.sesionLocal("loc_000000000000"), null);
});

test("marcarCreada guarda el realId y idLocalDe lo encuentra", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.marcarCreada(s.id, "abc123def456");
  assert.equal(store.sesionLocal(s.id).realId, "abc123def456");
  assert.equal(store.idLocalDe("abc123def456"), s.id);
  assert.equal(store.idLocalDe("otro"), null);
});

test("las sesiones locales no se pisan entre sí", () => {
  limpiar();
  const a = store.crearSesionLocal(META), b = store.crearSesionLocal({ ...META, title: "Otra" });
  store.marcarCreada(a.id, "r1");
  assert.equal(store.sesionLocal(b.id).realId, null);
  assert.equal(store.sesionLocal(b.id).meta.title, "Otra");
});

test("pedirTerminar guarda las partes para cerrar cuando vuelva la señal", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.pedirTerminar(s.id, { 0: 3, 1: 2 });
  assert.deepEqual(store.sesionLocal(s.id).terminar, { parts: { 0: 3, 1: 2 }, intentos: 0 });
});

test("quitarSesionLocal borra la sesión, el índice y los datos de grabación", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.saveRecMeta(s.id, { parts: { 0: 1 } });
  store.quitarSesionLocal(s.id);
  assert.equal(store.sesionLocal(s.id), null);
  assert.deepEqual(store.sesionesLocalesPendientes(), []);
  assert.deepEqual(store.recMeta(s.id), { parts: {} });
});

test("el estado es 'grabando' mientras hay actividad reciente", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.registrarActividad(s.id, true);
  const [p] = store.sesionesLocalesPendientes();
  assert.deepEqual({ id: p.id, title: p.title, estado: p.estado }, { id: s.id, title: "Charla de prueba", estado: "grabando" });
});

test("sin actividad reciente (app cerrada a mitad) queda 'pendiente' de subir", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.registrarActividad(s.id, true);
  const viejo = store.sesionLocal(s.id);
  datos.set(`reinventar.sesion-local.${s.id}`, JSON.stringify({ ...viejo, latido: Date.now() - 10 * 60_000 }));
  assert.equal(store.sesionesLocalesPendientes()[0].estado, "pendiente");
});

test("terminada esperando señal se distingue de pendiente", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.pedirTerminar(s.id, { 0: 1 });
  assert.equal(store.sesionesLocalesPendientes()[0].estado, "terminada");
});

test("el error de una sesión local se ve en la lista", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.marcarErrorLocal(s.id, "No se pudo cerrar la grabación");
  assert.equal(store.sesionesLocalesPendientes()[0].error, "No se pudo cerrar la grabación");
});

test("empezarSesion usa la sesión del servidor cuando hay señal", async () => {
  limpiar();
  const r = await rec.empezarSesion(META, async () => ({ id: "real00000009" }));
  assert.deepEqual(r, { id: "real00000009", local: false });
  assert.deepEqual(store.sesionesLocalesPendientes(), []);
});

test("empezarSesion arma una sesión local si falla por falta de señal (status 0)", async () => {
  limpiar();
  const r = await rec.empezarSesion(META, async () => { throw Object.assign(new Error("Sin conexión"), { status: 0 }); });
  assert.equal(r.local, true);
  assert.equal(store.esLocal(r.id), true);
  assert.deepEqual(store.sesionLocal(r.id).meta, META);
});

test("empezarSesion deja pasar los demás errores (por ejemplo un 422)", async () => {
  limpiar();
  await assert.rejects(rec.empezarSesion(META, async () => { throw Object.assign(new Error("kind inválido"), { status: 422 }); }), /kind inválido/);
  assert.deepEqual(store.sesionesLocalesPendientes(), []);
});

test("reabrirCierres borra el error y devuelve los intentos de cierre", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.pedirTerminar(s.id, { 0: 1 });
  store.contarIntentoDeCierre(s.id);
  store.marcarErrorLocal(s.id, "Faltan pedazos");
  store.reabrirCierres();
  assert.equal(store.sesionLocal(s.id).error, null);
  assert.equal(store.sesionLocal(s.id).terminar.intentos, 0);
});

test("sesionRemota devuelve el id tal cual si no es local", async () => {
  limpiar();
  assert.equal(await rec.sesionRemota("a1b2c3d4e5f6", async () => assert.fail("no debe crear")), "a1b2c3d4e5f6");
});

test("sesionRemota crea la sesión una sola vez aunque la pidan dos loops a la vez", async () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  let creadas = 0;
  const crear = async () => { creadas++; await new Promise((r) => setTimeout(r, 20)); return { id: "real00000001" }; };
  const [a, b] = await Promise.all([rec.sesionRemota(s.id, crear), rec.sesionRemota(s.id, crear)]);
  assert.equal(creadas, 1);
  assert.deepEqual([a, b], ["real00000001", "real00000001"]);
  assert.equal(store.sesionLocal(s.id).realId, "real00000001");
});

test("sesionRemota usa el realId ya guardado sin volver a crear", async () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.marcarCreada(s.id, "yaguardado001");
  assert.equal(await rec.sesionRemota(s.id, async () => assert.fail("no debe crear")), "yaguardado001");
});

test("sesionRemota deja la sesión sin realId si crear falla, para reintentar después", async () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  await assert.rejects(rec.sesionRemota(s.id, async () => { throw Object.assign(new Error("Sin conexión"), { status: 0 }); }));
  assert.equal(store.sesionLocal(s.id).realId, null);
  assert.equal(await rec.sesionRemota(s.id, async () => ({ id: "real00000002" })), "real00000002");
});

test("sesionRemota falla claro si la sesión local ya no existe", async () => {
  limpiar();
  await assert.rejects(rec.sesionRemota("loc_aaaaaaaaaaaa", async () => ({ id: "x" })), /no existe/);
});

test("fallo al crear: sin señal y errores del servidor se reintentan; un 4xx es definitivo", () => {
  for (const s of [0, undefined, 401, 500, 502, 503]) assert.equal(rec.clasificarFalloAlCrear(s).accion, "reintentar");
  assert.equal(rec.clasificarFalloAlCrear(422).accion, "fallido");
  assert.equal(rec.clasificarFalloAlCrear(400).accion, "fallido");
});

test("cierre: espera mientras queden pedazos, y cierra cuando no hay y la sesión ya existe", () => {
  const base = { terminar: { parts: { 0: 2 }, intentos: 0 }, realId: "r1", pendientes: 0, fallidos: 0 };
  assert.equal(rec.decidirCierre({ ...base, pendientes: 2 }), "esperar");
  assert.equal(rec.decidirCierre({ ...base, realId: null }), "esperar");
  assert.equal(rec.decidirCierre(base), "cerrar");
});

test("cierre: con pedazos fallidos no cierra y lo informa", () => {
  const base = { terminar: { parts: { 0: 2 }, intentos: 0 }, realId: "r1", pendientes: 0, fallidos: 1 };
  assert.equal(rec.decidirCierre(base), "fallidos");
});

test("cierre: sin terminar pedido no hace nada", () => {
  assert.equal(rec.decidirCierre({ terminar: null, realId: "r1", pendientes: 0, fallidos: 0 }), "esperar");
});

test("finish con faltantes reintenta hasta el tope y después deja el error visible", () => {
  const faltantes = Object.assign(new Error("Faltan pedazos"), { status: 409, detail: { missing: { 0: [1] } } });
  assert.equal(rec.resultadoDeFinishFallido(faltantes, 0), "reintentar");
  assert.equal(rec.resultadoDeFinishFallido(faltantes, rec.MAX_INTENTOS_CIERRE - 1), "error");
});

test("finish sin red o con error 5xx se reintenta siempre, sin gastar intentos", () => {
  for (const status of [0, 500, 503]) assert.equal(rec.resultadoDeFinishFallido(Object.assign(new Error("x"), { status }), 99), "reintentar");
});

test("finish rechazado por otro 4xx deja el error visible", () => {
  assert.equal(rec.resultadoDeFinishFallido(Object.assign(new Error("no existe"), { status: 404 }), 0), "error");
});

test("el router acepta ids locales (con guion bajo) en #/grabar/:id y #/s/:id", () => {
  const app = readFileSync(new URL("../../web/js/app.js", import.meta.url), "utf8");
  const rutas = [...app.matchAll(/^\s*\[(\/\^#\\\/(?:grabar|s)\\\/.*?\/),/gm)].map((m) => new Function(`return ${m[1]}`)());
  assert.ok(rutas.length >= 2, "no encontré las rutas de grabar y detalle");
  for (const r of rutas) assert.ok(r.test(`#/${r.source.includes("grabar") ? "grabar" : "s"}/loc_0123456789ab`), String(r));
});
