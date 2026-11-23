// Pruebas de «Mi ficha» en el front (node --test): el aviso del banner (prioridad frente a los otros, posponer, fases,
// notificaciones del dispositivo) y los bloques con su completitud (web/js/fichaReglas.js).
import test from "node:test";
import assert from "node:assert/strict";

const { CIERRE, PRIORIDAD, cerradoHasta, elegirAvisos } = await import("../../web/js/estado.js");
const {
  ID_AVISO_FICHA, POSPONER_MS, PRIORIDAD_FICHA, avisoFicha, bloques, completitud, faltanteNotificaciones, faltantesDe,
  faltantesParaBanner,
} = await import("../../web/js/fichaReglas.js");

const AHORA = Date.UTC(2026, 10, 23, 15, 0);
const HOTEL = { id: "hotel", texto: "Cargá tu hotel", prioridad: 3, link: "#/viajes", critico: false, banner: true };
const PERFIL = { id: "perfil", texto: "Completá tu perfil para recomendaciones", prioridad: 6, link: "#/itinerario/entrevista", critico: false, banner: true };
const PASSKEY = { id: "passkey", texto: "Entrá con huella o cara", prioridad: 9, link: "#/ajustes", critico: false, banner: false };
const ficha = (extra = {}) => ({ fase: "antes", faltantes: [HOTEL, PERFIL, PASSKEY], banner: [HOTEL, PERFIL], ...extra });
const PUSH_OK = { estado: "ok", activo: true, denegado: false };
const PUSH_APAGADO = { estado: "ok", activo: false, denegado: false };
const ids = (avisos) => avisos.map((a) => a.id);

test("el banner muestra el faltante de mayor prioridad con «Completar»", () => {
  const aviso = avisoFicha({ ficha: ficha(), notificaciones: PUSH_OK, ruta: "#/" });
  assert.equal(aviso.id, ID_AVISO_FICHA);
  assert.deepEqual(aviso.titulo, ["Cargá tu hotel."]);
  assert.deepEqual(aviso.accion, { texto: "Completar", tipo: "ir", destino: "#/viajes" });
  assert.equal(aviso.prioridad, PRIORIDAD_FICHA);
});

test("sin faltantes para el banner no hay aviso", () => {
  assert.equal(avisoFicha({ ficha: ficha({ banner: [] }), notificaciones: PUSH_OK }), null);
  assert.equal(avisoFicha({ ficha: null, notificaciones: PUSH_OK }), null);
});

test("no se muestra en la ficha ni en la pantalla donde se completa", () => {
  assert.equal(avisoFicha({ ficha: ficha(), notificaciones: PUSH_OK, ruta: "#/ficha" }), null);
  assert.equal(avisoFicha({ ficha: ficha(), notificaciones: PUSH_OK, ruta: "#/viajes" }), null);
});

test("las notificaciones apagadas en el dispositivo entran con prioridad 4 (antes que el perfil, después del hotel)", () => {
  const lista = faltantesParaBanner(ficha(), PUSH_APAGADO);
  assert.deepEqual(lista.map((f) => f.id), ["hotel", "notificaciones", "perfil"]);
  const soloPerfil = avisoFicha({ ficha: ficha({ banner: [PERFIL] }), notificaciones: PUSH_APAGADO });
  assert.deepEqual(soloPerfil.titulo, ["Activá las notificaciones."]);
});

test("notificaciones: no se insiste si están activas, denegadas, sin soporte o si no se pudo saber", () => {
  assert.equal(faltanteNotificaciones(PUSH_OK), null);
  assert.equal(faltanteNotificaciones({ estado: "ok", activo: false, denegado: true }), null);
  assert.equal(faltanteNotificaciones({ estado: "no_soportado", activo: false }), null);
  assert.equal(faltanteNotificaciones({ estado: "ok", activo: null }), null);
  assert.equal(faltanteNotificaciones(null), null);
  assert.equal(faltanteNotificaciones({ estado: "ios_sin_instalar" }).texto, "Instalá la app para recibir avisos");
});

test("durante la estadía solo lo crítico: el servidor filtra y las notificaciones siguen; después del viaje, nada", () => {
  const durante = ficha({ fase: "durante", banner: [] });
  assert.deepEqual(faltantesParaBanner(durante, PUSH_APAGADO).map((f) => f.id), ["notificaciones"]);
  assert.equal(avisoFicha({ ficha: durante, notificaciones: PUSH_OK }), null);
  assert.equal(avisoFicha({ ficha: ficha({ fase: "despues" }), notificaciones: PUSH_APAGADO }), null);
});

test("un faltante con link de afuera de la app se descarta", () => {
  const raro = { ...HOTEL, link: "https://ejemplo.com" };
  assert.equal(avisoFicha({ ficha: ficha({ banner: [raro] }), notificaciones: PUSH_OK }), null);
});

test("«Más tarde» lo pospone 24 h y mientras tanto no aparece", () => {
  const aviso = avisoFicha({ ficha: ficha(), notificaciones: PUSH_OK });
  assert.equal(aviso.cierre, CIERRE.posponer);
  const hasta = cerradoHasta(aviso, AHORA);
  assert.equal(hasta, AHORA + POSPONER_MS);
  assert.deepEqual(elegirAvisos({ ahora: AHORA, ficha: aviso, descartados: { [ID_AVISO_FICHA]: hasta } }), []);
  assert.deepEqual(ids(elegirAvisos({ ahora: hasta + 1, ficha: aviso, descartados: { [ID_AVISO_FICHA]: hasta } })), [ID_AVISO_FICHA]);
});

test("va después de los avisos de servicio y de «Próximo»", () => {
  const aviso = avisoFicha({ ficha: ficha(), notificaciones: PUSH_OK });
  const proximo = { tipo: "vuelo", titulo: "UA1355 a Houston", hora: "13:05", inicio: new Date(AHORA + 3_600_000).toISOString(), url: "#/viajes" };
  const avisos = elegirAvisos({
    ahora: AHORA, ficha: aviso, proximo,
    servicio: [{ id: "transcripcion", nivel: "demorado" }, { id: "resumenes", nivel: "caido" }],
  });
  assert.deepEqual(ids(avisos).slice(0, 2), ["servicio:resumenes:caido", "servicio:transcripcion:demorado"]);
  assert.equal(avisos.at(-1).id, ID_AVISO_FICHA);
  assert.ok(avisos.at(-2).id.startsWith("proximo:"));
  assert.ok(PRIORIDAD_FICHA > PRIORIDAD.proximo);
});

test("con «Salí ya» urgente no se muestra", () => {
  const aviso = avisoFicha({ ficha: ficha(), notificaciones: PUSH_OK });
  assert.deepEqual(elegirAvisos({ ahora: AHORA, ficha: aviso, countdownUrgente: true }), []);
});

test("faltantesDe suma las notificaciones y ordena por prioridad (la passkey queda en la ficha)", () => {
  assert.deepEqual(faltantesDe(ficha(), PUSH_APAGADO).map((f) => f.id), ["hotel", "notificaciones", "perfil", "passkey"]);
});

// ---------- bloques y completitud ----------

const FICHA_COMPLETA = {
  usuario: "tester", fase: "antes", faltantes: [], banner: [],
  perfil: { completo: true, rol: "Arquitecta", industria: "banca", intereses: ["Datos", "IA"] },
  viaje: { vuelos: [{ numero: "UA1355", fecha: "2026-11-29" }, { numero: "UA1356", fecha: "2026-12-07" }],
    hoteles: [{ nombre: "Hotel de prueba" }], ida: true, vuelta: true },
  documentos: 2, pendientes: { hechos: 10, total: 10 }, agenda: { charlas: 4, codigos_excel: 0 }, passkeys: 0,
};

test("con todo cargado la ficha está al 100% aunque falte la passkey (es opcional)", () => {
  const lista = bloques(FICHA_COMPLETA, PUSH_OK);
  assert.deepEqual(lista.map((b) => b.id), ["perfil", "viaje", "notificaciones", "passkey", "documentos", "pendientes", "agenda"]);
  assert.deepEqual(completitud(lista), { hechos: 6, total: 6, pct: 100 });
  const viaje = lista.find((b) => b.id === "viaje");
  assert.deepEqual(viaje.lineas, ["Vuelos: UA1355 29/11, UA1356 7/12", "Hotel: Hotel de prueba"]);
  assert.equal(lista.find((b) => b.id === "passkey").completo, false);
});

test("cada bloque dice qué falta y lleva a la pantalla donde se completa", () => {
  const vacia = { fase: "antes", perfil: { completo: false }, viaje: { vuelos: [], hoteles: [], ida: false, vuelta: false },
    documentos: 0, pendientes: { hechos: 3, total: 10 }, agenda: { charlas: 0, codigos_excel: 0 }, passkeys: 0 };
  const lista = bloques(vacia, PUSH_APAGADO);
  assert.deepEqual(completitud(lista), { hechos: 0, total: 6, pct: 0 });
  const por = Object.fromEntries(lista.map((b) => [b.id, b]));
  assert.equal(por.viaje.lineas.at(-1), "Falta el vuelo de ida, el vuelo de vuelta y el hotel.");
  assert.equal(por.pendientes.lineas[0], "3/10 listos.");
  assert.equal(por.perfil.boton, "Completar perfil");
  for (const b of lista) assert.ok(b.link.startsWith("#/"), b.id);
});

test("sin soporte de notificaciones el bloque es opcional y no baja el porcentaje", () => {
  const lista = bloques(FICHA_COMPLETA, { estado: "no_soportado", activo: false });
  assert.equal(lista.find((b) => b.id === "notificaciones").opcional, true);
  assert.equal(completitud(lista).pct, 100);
});

test("una respuesta rara no rompe los bloques", () => {
  const lista = bloques({ perfil: null, viaje: { vuelos: "x" }, pendientes: { hechos: -1 } }, null);
  assert.equal(lista.length, 7);
  assert.equal(completitud(lista).pct, 0);
});
