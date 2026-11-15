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
  assert.deepEqual(store.sesionesLocales(), []);
  assert.deepEqual(store.recMeta(s.id), { parts: {} });
});

test("el estado es 'grabando' mientras hay actividad reciente", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.registrarActividad(s.id, true);
  const [p] = store.sesionesLocales();
  assert.deepEqual({ id: p.id, title: p.title, estado: p.estado }, { id: s.id, title: "Charla de prueba", estado: "grabando" });
});

test("sin actividad reciente (app cerrada a mitad) queda 'pendiente' de subir", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.registrarActividad(s.id, true);
  const viejo = store.sesionLocal(s.id);
  datos.set(`reinventar.sesion-local.${s.id}`, JSON.stringify({ ...viejo, latido: Date.now() - 10 * 60_000 }));
  assert.equal(store.sesionesLocales()[0].estado, "pendiente");
});

test("terminada esperando señal se distingue de pendiente", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.pedirTerminar(s.id, { 0: 1 });
  assert.equal(store.sesionesLocales()[0].estado, "terminada");
});

test("el error de una sesión local se ve en la lista", () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  store.marcarErrorLocal(s.id, "No se pudo cerrar la grabación");
  assert.equal(store.sesionesLocales()[0].error, "No se pudo cerrar la grabación");
});

// Forma pública para la lista de Inicio: async, siempre un array, estados y `at` acordados con la pantalla.
test("sesionesLocalesPendientes es async y devuelve un array vacío si no hay nada", async () => {
  limpiar();
  const r = store.sesionesLocalesPendientes();
  assert.ok(r instanceof Promise);
  assert.deepEqual(await r, []);
});

test("sesionesLocalesPendientes devuelve id, title, estado y at (ms de creación)", async () => {
  limpiar();
  const antes = Date.now();
  const s = store.crearSesionLocal(META);
  store.registrarActividad(s.id, true);
  const [p] = await store.sesionesLocalesPendientes();
  assert.equal(p.id, s.id);
  assert.equal(p.title, "Charla de prueba");
  assert.equal(p.estado, "grabando");
  assert.ok(p.at >= antes && p.at <= Date.now());
});

test("sesionesLocalesPendientes usa los estados pendiente_de_subir y esperando_senal", async () => {
  limpiar();
  const a = store.crearSesionLocal(META), b = store.crearSesionLocal({ ...META, title: "Otra" });
  store.pedirTerminar(b.id, { 0: 1 });
  const estados = Object.fromEntries((await store.sesionesLocalesPendientes()).map((p) => [p.id, p.estado]));
  assert.deepEqual(estados, { [a.id]: "pendiente_de_subir", [b.id]: "esperando_senal" });
});

test("sesionesLocalesPendientes pone un título por defecto si la sesión no tiene", async () => {
  limpiar();
  store.crearSesionLocal({ ...META, title: "" });
  assert.equal((await store.sesionesLocalesPendientes())[0].title, "Grabación sin conexión");
});

test("sesionesLocalesPendientes viene ordenada de la más reciente a la más vieja", async () => {
  limpiar();
  const vieja = store.crearSesionLocal(META);
  datos.set(`reinventar.sesion-local.${vieja.id}`, JSON.stringify({ ...store.sesionLocal(vieja.id), creadaEn: Date.now() - 5_000 }));
  const nueva = store.crearSesionLocal({ ...META, title: "Nueva" });
  assert.deepEqual((await store.sesionesLocalesPendientes()).map((p) => p.id), [nueva.id, vieja.id]);
});

test("empezarSesion usa la sesión del servidor cuando hay señal", async () => {
  limpiar();
  const r = await rec.empezarSesion(META, async () => ({ id: "real00000009" }));
  assert.deepEqual(r, { id: "real00000009", local: false });
  assert.deepEqual(store.sesionesLocales(), []);
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
  assert.deepEqual(store.sesionesLocales(), []);
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

test("sesionRemota manda client_id (el id local) y recorded_at (ISO de la creación local)", async () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  const creadaEn = store.sesionLocal(s.id).creadaEn;
  let enviado = null;
  await rec.sesionRemota(s.id, async (m) => { enviado = m; return { id: "real00000003" }; });
  assert.equal(enviado.client_id, s.id);
  assert.equal(enviado.recorded_at, new Date(creadaEn).toISOString());
  assert.equal(enviado.title, META.title);
});

test("sesionRemota no cambia la meta guardada al agregar client_id y recorded_at", async () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  await rec.sesionRemota(s.id, async () => ({ id: "real00000004" }));
  assert.deepEqual(store.sesionLocal(s.id).meta, META);
});

test("sesionRemota usa como realId la sesión que el servidor ya tenía para ese client_id", async () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  // la app se cayó tras el POST sin guardar el realId: el reintento recibe la misma sesión
  await assert.rejects(rec.sesionRemota(s.id, async () => { throw Object.assign(new Error("Sin conexión"), { status: 0 }); }));
  assert.equal(await rec.sesionRemota(s.id, async () => ({ id: "yaexistente01" })), "yaexistente01");
  assert.equal(store.sesionLocal(s.id).realId, "yaexistente01");
});

test("si el servidor rechaza recorded_at con 422, reintenta sin ese campo y no falla", async () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  const envios = [];
  const crear = async (m) => {
    envios.push(m);
    if ("recorded_at" in m) throw Object.assign(new Error("recorded_at fuera de rango"), { status: 422 });
    return { id: "real00000005" };
  };
  assert.equal(await rec.sesionRemota(s.id, crear), "real00000005");
  assert.equal(envios.length, 2);
  assert.equal(envios[1].client_id, s.id);
  assert.equal("recorded_at" in envios[1], false);
});

test("un 422 sin recorded_at no se reintenta más y se informa", async () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  let llamadas = 0;
  const crear = async () => { llamadas++; throw Object.assign(new Error("kind inválido"), { status: 422 }); };
  await assert.rejects(rec.sesionRemota(s.id, crear), (e) => e.status === 422 && e.origen === "crear");
  assert.equal(llamadas, 2);
  assert.equal(store.sesionLocal(s.id).realId, null);
});

test("otros errores al crear no disparan el reintento sin recorded_at", async () => {
  limpiar();
  const s = store.crearSesionLocal(META);
  let llamadas = 0;
  const crear = async () => { llamadas++; throw Object.assign(new Error("caído"), { status: 503 }); };
  await assert.rejects(rec.sesionRemota(s.id, crear));
  assert.equal(llamadas, 1);
});

// Textos de la pantalla de grabar después de tocar «Terminar y procesar».
test("terminar sin señal en una sesión local: aviso claro, estado «Terminada» y botón para volver al inicio", () => {
  const t = rec.textosTerminar({ local: true, conRed: false });
  assert.match(t.aviso, /Sin señal: la grabación quedó guardada en el celular\. Se sube y se procesa sola cuando vuelva la señal; podés cerrar la app\./);
  assert.equal(t.estado, "Terminada · esperando señal");
  assert.equal(t.boton, "Volver al inicio");
});

test("terminar sin señal es igual para una sesión local y para una ya creada en el servidor: se puede cerrar la app", () => {
  const t = rec.textosTerminar({ local: false, conRed: false });
  assert.deepEqual(t, rec.textosTerminar({ local: true, conRed: false }));
  assert.match(t.aviso, /Sin señal: la grabación quedó guardada en el celular/);
  assert.match(t.aviso, /podés cerrar la app/);
  assert.doesNotMatch(t.aviso, /dejá la app abierta/);
  assert.equal(t.boton, "Volver al inicio");
});

// Terminar sin poder completarlo en una sesión que ya existe en el servidor: queda pedido y lo cierra el uploader.
test("pedirTerminarReal guarda las partes, el título y los intentos por id real", () => {
  limpiar();
  store.pedirTerminarReal("real00000010", { 0: 3 }, "Charla real");
  const t = store.terminarReal("real00000010");
  assert.deepEqual(t.terminar, { parts: { 0: 3 }, intentos: 0 });
  assert.equal(t.title, "Charla real");
  assert.equal(store.terminarReal("otro"), null);
  assert.deepEqual(store.terminaresReales().map((x) => x.id), ["real00000010"]);
});

test("el cierre diferido de una sesión real se cuenta, falla y se quita sin tocar las locales", () => {
  limpiar();
  const loc = store.crearSesionLocal(META);
  store.pedirTerminarReal("real00000011", { 0: 1 }, "Otra");
  store.contarIntentoDeCierreReal("real00000011");
  assert.equal(store.terminarReal("real00000011").terminar.intentos, 1);
  store.marcarErrorReal("real00000011", "Faltan pedazos");
  assert.equal(store.terminarReal("real00000011").error, "Faltan pedazos");
  store.reabrirCierres();
  assert.equal(store.terminarReal("real00000011").error, null);
  assert.equal(store.terminarReal("real00000011").terminar.intentos, 0);
  store.quitarTerminarReal("real00000011");
  assert.equal(store.terminarReal("real00000011"), null);
  assert.deepEqual(store.terminaresReales(), []);
  assert.equal(store.sesionLocal(loc.id).realId, null);
});

test("un cierre diferido de sesión real aparece en «Grabadas en este celular» como esperando_senal", async () => {
  limpiar();
  store.pedirTerminarReal("real00000012", { 0: 1 }, "Charla del pasillo");
  const [p] = await store.sesionesLocalesPendientes();
  assert.equal(p.id, "real00000012");
  assert.equal(p.title, "Charla del pasillo");
  assert.equal(p.estado, "esperando_senal");
  assert.equal(p.realId, "real00000012");
  assert.ok(Number.isFinite(p.at));
});

test("quitar el cierre diferido lo saca de la lista de Inicio", async () => {
  limpiar();
  store.pedirTerminarReal("real00000013", { 0: 1 }, "X");
  store.quitarTerminarReal("real00000013");
  assert.deepEqual(await store.sesionesLocalesPendientes(), []);
});

const FIN = { terminar: { parts: { 0: 2 }, intentos: 0 }, realId: "r1", pendientes: 0, fallidos: 0, error: null };

test("intentarCierre espera si quedan pedazos y no llama a finish", async () => {
  const r = await rec.intentarCierre({ ...FIN, pendientes: 1 }, async () => assert.fail("no debe cerrar"));
  assert.equal(r.resultado, "esperar");
});

test("intentarCierre cierra con las partes guardadas cuando la cola quedó en cero", async () => {
  let llamada = null;
  const r = await rec.intentarCierre(FIN, async (id, parts) => { llamada = [id, parts]; });
  assert.equal(r.resultado, "cerrada");
  assert.deepEqual(llamada, ["r1", { 0: 2 }]);
});

test("intentarCierre informa los pedazos fallidos sin cerrar", async () => {
  const r = await rec.intentarCierre({ ...FIN, fallidos: 1 }, async () => assert.fail("no debe cerrar"));
  assert.equal(r.resultado, "fallidos");
});

test("intentarCierre: sin red se reintenta; con 409 se cuenta el intento y al tope queda el error", async () => {
  const sinRed = await rec.intentarCierre(FIN, async () => { throw Object.assign(new Error("x"), { status: 0 }); });
  assert.equal(sinRed.resultado, "reintentar");
  const faltan = Object.assign(new Error("Faltan"), { status: 409, detail: { missing: { 0: [1] } } });
  assert.equal((await rec.intentarCierre(FIN, async () => { throw faltan; })).resultado, "contar");
  const alTope = { ...FIN, terminar: { parts: { 0: 2 }, intentos: rec.MAX_INTENTOS_CIERRE - 1 } };
  assert.equal((await rec.intentarCierre(alTope, async () => { throw faltan; })).resultado, "error");
});

test("intentarCierre: un 404 deja el error visible y el audio sigue guardado", async () => {
  const r = await rec.intentarCierre(FIN, async () => { throw Object.assign(new Error("no existe"), { status: 404 }); });
  assert.equal(r.resultado, "error");
  assert.equal(r.error.status, 404);
});

test("intentarCierre no hace nada si ya hay un error marcado", async () => {
  const r = await rec.intentarCierre({ ...FIN, error: "algo" }, async () => assert.fail("no debe cerrar"));
  assert.equal(r.resultado, "esperar");
});

test("terminar con señal: sin aviso de sin señal y sin «Listo para grabar»", () => {
  for (const local of [true, false]) {
    const t = rec.textosTerminar({ local, conRed: true });
    assert.equal(t.aviso, null);
    assert.equal(t.boton, null);
    assert.doesNotMatch(t.estado, /Listo para grabar/);
  }
});

// Pastilla del modo sala: sigue el estado del grabador.
test("estadoSala: grabando, en pausa y cualquier otro estado «Sin grabar»", () => {
  assert.deepEqual(rec.estadoSala("recording"), { status: "recording", texto: "Grabando" });
  assert.deepEqual(rec.estadoSala("paused"), { status: "queued", texto: "En pausa" });
  for (const s of ["idle", "stopped", undefined]) assert.deepEqual(rec.estadoSala(s), { status: "queued", texto: "Sin grabar" });
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
