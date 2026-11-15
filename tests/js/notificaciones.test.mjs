// Pruebas de Ajustes › Notificaciones (node --test): iPhone sin instalar, service worker que no responde y sede sin ubicación.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
const ponerNavigator = (valor) => Object.defineProperty(globalThis, "navigator", { value: valor, configurable: true, writable: true });

const { currentSubscription, disable, estadoPush, prenderSede } = await import("../../web/js/notifications.js");

const UA_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
const UA_ESCRITORIO = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15";
const entorno = (navigator, extra = {}) => ({ navigator: { serviceWorker: {}, ...navigator }, PushManager: function PushManager() {}, Notification: function Notification() {}, ...extra });
const nunca = () => new Promise(() => {});

// ---------- iPhone sin instalar ----------

test("en un iPhone con Safari en pestaña (sin instalar) se pide instalar la app", () => {
  assert.equal(estadoPush(entorno({ userAgent: UA_IPHONE, standalone: false })), "ios_sin_instalar");
  assert.equal(estadoPush(entorno({ userAgent: UA_IPHONE })), "ios_sin_instalar"); // standalone ni existe
});

test("en un iPhone con la app instalada se pueden activar", () => {
  assert.equal(estadoPush(entorno({ userAgent: UA_IPHONE, standalone: true })), "ok");
  const porDisplayMode = entorno({ userAgent: UA_IPHONE, standalone: false }, { matchMedia: () => ({ matches: true }) });
  assert.equal(estadoPush(porDisplayMode), "ok");
});

test("un iPad que se presenta como Mac también cuenta como iOS", () => {
  const ipad = entorno({ userAgent: UA_ESCRITORIO, platform: "MacIntel", maxTouchPoints: 5, standalone: false });
  assert.equal(estadoPush(ipad), "ios_sin_instalar");
});

test("en la compu no hace falta instalar nada", () => {
  assert.equal(estadoPush(entorno({ userAgent: UA_ESCRITORIO, platform: "MacIntel", maxTouchPoints: 0 })), "ok");
});

test("sin service worker, PushManager o Notification no está soportado", () => {
  assert.equal(estadoPush({ navigator: { userAgent: UA_ESCRITORIO }, PushManager() {}, Notification() {} }), "no_soportado");
  assert.equal(estadoPush({ navigator: { userAgent: UA_ESCRITORIO, serviceWorker: {} }, Notification() {} }), "no_soportado");
  assert.equal(estadoPush({ navigator: { userAgent: UA_ESCRITORIO, serviceWorker: {} }, PushManager() {} }), "no_soportado");
});

// ---------- service worker que no responde ----------

test("si el service worker nunca queda listo, currentSubscription falla con un mensaje en castellano", async () => {
  await assert.rejects(currentSubscription({ ready: nunca() }, 20), (e) => /service worker|servicio/i.test(e.message) && !/[Tt]imed? out|undefined/.test(e.message));
});

test("con el service worker listo devuelve el registro y la suscripción", async () => {
  const sub = { endpoint: "https://push.example/1" };
  const reg = { pushManager: { getSubscription: async () => sub } };
  assert.deepEqual(await currentSubscription({ ready: Promise.resolve(reg) }, 20), { reg, sub });
});

test("si pushManager no existe, rechaza en vez de quedarse esperando", async () => {
  await assert.rejects(currentSubscription({ ready: Promise.resolve({}) }, 20));
});

test("si getSubscription se cuelga también hay tope", async () => {
  const reg = { pushManager: { getSubscription: nunca } };
  await assert.rejects(currentSubscription({ ready: Promise.resolve(reg) }, 20), /service worker|servicio/i);
});

test("disable() no cuelga el cierre de sesión aunque el service worker no conteste", async () => {
  globalThis.caches = { delete: async () => true };
  ponerNavigator({ serviceWorker: { getRegistration: async () => ({ pushManager: { getSubscription: nunca } }) } });
  const t0 = Date.now();
  await disable({ timeoutMs: 20 });
  assert.ok(Date.now() - t0 < 1000);
});

test("disable() sin service worker termina igual", async () => {
  globalThis.caches = { delete: async () => true };
  ponerNavigator({});
  await disable({ timeoutMs: 20 });
});

// ---------- «sede» sin «Usar mi ubicación» ----------

const dependencias = ({ ubicacion, lee = true } = {}) => {
  const estado = { ubicacion, sede: false, llamadas: [] };
  return { estado, deps: {
    ubicacionPrendida: () => estado.ubicacion,
    prenderUbicacion: () => { estado.ubicacion = true; estado.llamadas.push("prenderUbicacion"); },
    apagarUbicacion: () => { estado.ubicacion = false; estado.llamadas.push("apagarUbicacion"); },
    guardar: async () => { estado.llamadas.push(`guardar:${estado.sede}`); },
    marcarSede: (on) => { estado.sede = on; },
    leerSede: async () => lee,
  } };
};

test("con «Usar mi ubicación» apagada, prender la sede prende las dos", async () => {
  const { estado, deps } = dependencias({ ubicacion: false });
  await prenderSede(deps);
  assert.equal(estado.ubicacion, true);
  assert.equal(estado.sede, true);
  assert.deepEqual(estado.llamadas, ["prenderUbicacion", "guardar:true"]);
});

test("con la ubicación ya prendida no se toca", async () => {
  const { estado, deps } = dependencias({ ubicacion: true });
  await prenderSede(deps);
  assert.deepEqual(estado.llamadas, ["guardar:true"]);
});

test("si no se puede leer la ubicación, vuelve todo a como estaba (ubicación apagada)", async () => {
  const { estado, deps } = dependencias({ ubicacion: false, lee: false });
  await assert.rejects(prenderSede(deps), /No pudimos leer tu ubicación/);
  assert.equal(estado.ubicacion, false);
  assert.equal(estado.sede, false);
  assert.equal(estado.llamadas.at(-1), "guardar:false");
});

test("si la ubicación ya estaba prendida y no se puede leer, esa queda prendida", async () => {
  const { estado, deps } = dependencias({ ubicacion: true, lee: false });
  await assert.rejects(prenderSede(deps), /No pudimos leer tu ubicación/);
  assert.equal(estado.ubicacion, true);
  assert.equal(estado.sede, false);
});
