// «Llevame» y la caminata a la sede (node --test): lejos no se camina, en la sede no hay nada que caminar.
import test from "node:test";
import assert from "node:assert/strict";

class Nodo {
  constructor(tag) { this.tag = tag; this.nodeType = 1; this.attrs = {}; this.children = []; this.className = ""; this.hidden = false; this.textContent = ""; this.classList = { add: () => {} }; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener() {}
  append(...hijos) { this.children.push(...hijos); }
  replaceChildren(...hijos) { this.children = hijos; }
}
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.document = { createElement: (t) => new Nodo(t), createElementNS: (_n, t) => new Nodo(t), getElementById: () => null };
globalThis.window = { dispatchEvent() {}, addEventListener() {}, google: { maps: {} } };
// Routes API de mentira: 10 minutos caminando, siempre.
globalThis.google = { maps: { importLibrary: async () => ({ Route: { computeRoutes: async () => ({ routes: [{ durationMillis: 600_000 }] }) } }) } };

let versiones = 0;
/** location.js nuevo por prueba (cachea la última posición un minuto) con el GPS en `posicion`. */
async function cargar(posicion) {
  // Node ya trae un navigator de solo lectura: se lo pisa con defineProperty.
  Object.defineProperty(globalThis, "navigator", { configurable: true, writable: true,
    value: { geolocation: { getCurrentPosition: (ok) => ok({ coords: { latitude: posicion.lat, longitude: posicion.lng } }) } } });
  return import(`../../web/js/location.js?v=${versiones++}`);
}

const VENETIAN = { lat: 36.1212, lng: -115.1697, name: "Venetian" };
const BUENOS_AIRES = { lat: -34.6037, lng: -58.3816 };
const METROS_EN_GRADOS = 1 / 111_320; // un metro de latitud, en grados

/** El texto que termina mostrando «Llevame» (espera a que el async de GoThereParts lo ponga). */
async function textoDe(loc, opts) {
  const { info } = loc.GoThereParts(VENETIAN, opts);
  for (let i = 0; i < 50 && info.hidden; i++) await new Promise((r) => setTimeout(r, 10));
  assert.equal(info.hidden, false, "la info nunca apareció");
  return info.children[1].textContent;
}

test("cercania: en la sede por debajo de 50 m, caminable hasta 20 km, lejos después", async () => {
  const { cercania, EN_LA_SEDE_M, LEJOS_M } = await cargar(VENETIAN);
  assert.equal(EN_LA_SEDE_M, 50);
  assert.equal(LEJOS_M, 20_000);
  assert.equal(cercania(0), "en_sede");
  assert.equal(cercania(49), "en_sede");
  assert.equal(cercania(50), "caminable");
  assert.equal(cercania(20_000), "caminable");
  assert.equal(cercania(20_001), "lejos");
  assert.equal(cercania(9_819_700), "lejos");
});

test("con el GPS en Argentina muestra solo la distancia: sin minutos ni «salí»", async () => {
  const texto = await textoDe(await cargar(BUENOS_AIRES), { eta: true, start: new Date(Date.now() + 3600_000) });
  assert.match(texto, /^a [\d,]+ km$/, texto);
  assert.doesNotMatch(texto, /min|salí|caminando/);
});

test("con la sede simulada en el mismo lugar dice «Estás en la sede», no «a 0 m · ~0 min»", async () => {
  const texto = await textoDe(await cargar(VENETIAN), { eta: true, start: new Date(Date.now() + 3600_000) });
  assert.equal(texto, "Estás en la sede");
});

test("a 30 m también está en la sede", async () => {
  const texto = await textoDe(await cargar({ lat: VENETIAN.lat + 30 * METROS_EN_GRADOS, lng: VENETIAN.lng }), { eta: true });
  assert.equal(texto, "Estás en la sede");
});

test("a 1,5 km (cerca) sigue mostrando distancia, minutos caminando y cuándo salir", async () => {
  const loc = await cargar({ lat: VENETIAN.lat + 1500 * METROS_EN_GRADOS, lng: VENETIAN.lng });
  const texto = await textoDe(loc, { eta: true, start: new Date(Date.now() + 3 * 3600_000) });
  assert.match(texto, /^a 1,5 km · 10 min caminando · salí \d{2}:\d{2}$/, texto);
});

test("sin ETA, a 1,5 km solo la distancia (como antes)", async () => {
  const loc = await cargar({ lat: VENETIAN.lat + 1500 * METROS_EN_GRADOS, lng: VENETIAN.lng });
  assert.equal(await textoDe(loc, {}), "a 1,5 km");
});
