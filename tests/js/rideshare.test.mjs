// Pruebas de «Uber» y «Lyft» (node --test): armado de los links universales y zonas de rideshare por sede, sin red.
import test from "node:test";
import assert from "node:assert/strict";
import "./domMinimo.mjs";

const { ZONAS, coordenadasValidas, uberUrl, lyftUrl, zonaCercana, zonaDeTerminal, PedirAuto, DondeTeLevanta, textoAca } =
  await import("../../web/js/rideshare.js");
const { GoThere } = await import("../../web/js/location.js");

const VENETIAN_EXPO = { lat: 36.121898, lng: -115.16623, name: "Venetian Expo" };
const buscar = (nodo, pred) => (pred(nodo) ? [nodo] : (nodo.children || []).flatMap((c) => (typeof c === "string" ? [] : buscar(c, pred))));
const drop = (url) => JSON.parse(new URL(url).searchParams.get("drop[0]"));

test("Uber: link universal con el destino como JSON y sin punto de partida (sale de la ubicación actual)", () => {
  const url = uberUrl(VENETIAN_EXPO);
  assert.ok(url.startsWith("https://m.uber.com/looking?drop%5B0%5D="));
  assert.deepEqual(drop(url), { latitude: 36.121898, longitude: -115.16623, addressLine1: "Venetian Expo" });
  assert.equal(new URL(url).searchParams.has("pickup"), false);
});

test("Uber: nombres con espacios, acentos y signos viajan codificados y vuelven iguales", () => {
  const nombre = "Café & Bar «Ñandú» #1 / Caesars";
  const url = uberUrl({ lat: 36.1, lng: -115.1, name: nombre });
  assert.doesNotMatch(url, /[ «»Ñéú&#]/u, "nada sin codificar");
  assert.equal(drop(url).addressLine1, nombre);
});

test("Uber: el nombre se limpia (saltos de línea, largo) y si falta no se manda", () => {
  assert.equal(drop(uberUrl({ lat: 1, lng: 2, name: "  MGM\nGrand  " })).addressLine1, "MGM Grand");
  assert.equal(drop(uberUrl({ lat: 1, lng: 2, name: "x".repeat(200) })).addressLine1.length, 80);
  assert.deepEqual(drop(uberUrl({ lat: 1, lng: 2 })), { latitude: 1, longitude: 2 });
});

test("Lyft: link universal con id=lyft y las coordenadas del destino", () => {
  const url = new URL(lyftUrl({ ...VENETIAN_EXPO, lat: 36.1218981234 }));
  assert.equal(url.origin + url.pathname, "https://www.lyft.com/ride");
  assert.equal(url.searchParams.get("id"), "lyft");
  assert.equal(url.searchParams.get("destination[latitude]"), "36.121898");
  assert.equal(url.searchParams.get("destination[longitude]"), "-115.16623");
  assert.equal([...url.searchParams.keys()].length, 3, "solo el destino: nada personal en la URL");
});

test("sin coordenadas (null, vacías o inválidas) no hay link", () => {
  for (const d of [null, {}, { lat: null, lng: -115 }, { lat: 36, lng: null }, { lat: "", lng: "" }, { lat: NaN, lng: 1 }, { lat: 91, lng: 0 }]) {
    assert.equal(coordenadasValidas(d), false);
    assert.equal(uberUrl(d), null);
    assert.equal(lyftUrl(d), null);
  }
  assert.equal(coordenadasValidas({ lat: 0, lng: 0 }), true, "0 es una coordenada válida");
});

test("cada sede de re:Invent y cada terminal tiene zona, con fuente https y al menos una línea", () => {
  for (const clave of ["venetian", "forum", "caesarsPalace", "mgmGrand", "wynnEncore", "lasT1", "lasT3"]) {
    const z = ZONAS[clave];
    assert.ok(z, clave);
    assert.ok(z.subida.length >= 1 && z.subida.length <= 2, `${clave}: 1 o 2 líneas`);
    assert.ok(z.fuente.startsWith("https://"), `${clave}: fuente`);
  }
});

test("las fuentes que no son oficiales van marcadas «a confirmar»", () => {
  assert.equal(ZONAS.mgmGrand.aConfirmar, true);
  assert.equal(ZONAS.forum.aConfirmar, true);
  assert.ok(!ZONAS.venetian.aConfirmar && !ZONAS.lasT1.aConfirmar);
});

test("la zona se reconoce por coordenadas: hotel, área de convenciones y aeropuerto", () => {
  assert.equal(zonaCercana(VENETIAN_EXPO), "venetian");
  assert.equal(zonaCercana({ lat: 36.1216, lng: -115.1691 }), "venetian");
  assert.equal(zonaCercana({ lat: 36.118937, lng: -115.166189 }), "forum");
  assert.equal(zonaCercana({ lat: 36.116389, lng: -115.178808 }), "caesarsPalace");
  assert.equal(zonaCercana({ lat: 36.104554, lng: -115.164814 }), "mgmGrand");
  assert.equal(zonaCercana({ lat: 36.126492, lng: -115.165741 }), "wynnEncore");
  assert.equal(zonaCercana({ lat: 36.0801, lng: -115.1524 }), "lasT1");
  assert.equal(zonaCercana({ lat: 36.0858, lng: -115.161 }), "lasT3");
});

test("lejos de toda sede, o sin coordenadas, no hay zona", () => {
  assert.equal(zonaCercana({ lat: -34.6037, lng: -58.3816 }), null);   // Buenos Aires
  assert.equal(zonaCercana({ lat: 36.1447, lng: -115.1567 }), null);   // Strat, fuera de las sedes
  assert.equal(zonaCercana(null), null);
});

test("las terminales del aeropuerto quedan cerca de LAS y separadas entre sí", () => {
  const LAS = [36.084, -115.1537];
  for (const clave of ["lasT1", "lasT3"]) {
    const [lat, lng] = ZONAS[clave].puntos[0];
    assert.ok(Math.hypot((lat - LAS[0]) * 111_000, (lng - LAS[1]) * 90_000) < 2000, clave);
  }
});

test("terminal de llegada: «1», «T3» o vacía", () => {
  assert.equal(zonaDeTerminal("1"), "lasT1");
  assert.equal(zonaDeTerminal("T3"), "lasT3");
  assert.equal(zonaDeTerminal(3), "lasT3");
  assert.equal(zonaDeTerminal(null), null);
  assert.equal(zonaDeTerminal("2"), null);
});

test("PedirAuto: dos botones accesibles con el destino y el desplegable de la zona del destino", () => {
  const { botones, zonas } = PedirAuto(VENETIAN_EXPO);
  assert.deepEqual(botones.map((b) => b.textContent), ["Uber", "Lyft"]);
  assert.deepEqual(botones.map((b) => b.getAttribute("aria-label")), ["Pedir Uber a Venetian Expo", "Pedir Lyft a Venetian Expo"]);
  assert.equal(botones[0].getAttribute("href"), uberUrl(VENETIAN_EXPO));
  assert.equal(botones[1].getAttribute("href"), lyftUrl(VENETIAN_EXPO));
  assert.ok(botones.every((b) => b.getAttribute("rel") === "noopener" && b.className.includes("ra-btn")));
  const det = buscar(zonas, (n) => n.tag === "details")[0];
  assert.match(det.textContent, /Nivel 2 del garage/);
  assert.match(det.textContent, /venetianlasvegas\.com/);
});

test("PedirAuto: sin coordenadas o con destino aproximado no aparece", () => {
  assert.equal(PedirAuto({ lat: null, lng: null, name: "x" }), null);
  assert.equal(PedirAuto({ ...VENETIAN_EXPO, approx: true }), null);
});

test("PedirAuto: fuera de las sedes y en una lista no se agrega nada debajo de los botones", () => {
  assert.equal(PedirAuto({ lat: 36.1447, lng: -115.1567, name: "The STRAT" }).zonas, null);
});

test("PedirAuto en una lista (sin «aca»): solo el desplegable del destino, sin «Estás en…»", () => {
  const { zonas } = PedirAuto(VENETIAN_EXPO);
  assert.equal(buscar(zonas, (n) => (n.className || "").includes("ra-auto-aca")).length, 0);
});

test("PedirAuto en una ficha fuera de las sedes: el contenedor arranca oculto hasta saber dónde estás", () => {
  const { zonas } = PedirAuto({ lat: 36.1447, lng: -115.1567, name: "The STRAT" }, { aca: true });
  assert.equal(zonas.hidden, true);
});

test("textoAca: dice dónde te levanta si estás en otra sede; nada si estás en el destino o en ningún lado", () => {
  assert.match(textoAca({ lat: 36.0801, lng: -115.1524 }, "venetian"), /^Estás en Aeropuerto LAS, Terminal 1\. El auto te levanta en: Nivel 2/);
  assert.match(textoAca({ lat: 36.102219, lng: -115.169517 }, null), /\(a confirmar\)$/);
  assert.equal(textoAca({ lat: 36.1216, lng: -115.1691 }, "venetian"), "");
  assert.equal(textoAca(null, "venetian"), "");
});

test("DondeTeLevanta marca «a confirmar» y no arma nada sin zonas", () => {
  assert.match(DondeTeLevanta(["mgmGrand"]).textContent, /\(a confirmar\)/);
  assert.equal(DondeTeLevanta([]), null);
  assert.equal(DondeTeLevanta(["noExiste"]), null);
});

test("GoThere suma «Uber» y «Lyft» al lado de «Llevame»", () => {
  const go = GoThere(VENETIAN_EXPO);
  const links = buscar(go, (n) => n.tag === "a" && n.className.includes("ra-btn"));
  assert.deepEqual(links.map((a) => a.textContent), ["Llevame", "Uber", "Lyft"]);
});

test("pedir desde acá: si el celular está en una sede, se muestra la zona de esa sede", async () => {
  // GPS de mentira en Caesars Palace (Node trae un navigator de solo lectura: se lo pisa con defineProperty).
  Object.defineProperty(globalThis, "navigator", { configurable: true, writable: true,
    value: { geolocation: { getCurrentPosition: (ok) => ok({ coords: { latitude: 36.11778, longitude: -115.175 } }) } } });
  const { zonas } = PedirAuto(VENETIAN_EXPO, { aca: true });
  const aca = zonas.children[0];
  for (let i = 0; i < 50 && aca.hidden; i++) await new Promise((r) => setTimeout(r, 10));
  assert.equal(aca.hidden, false, "la zona de acá nunca apareció");
  assert.match(aca.textContent, /^Estás en Caesars Palace\. El auto te levanta en: En el garage/);
});

test("currentPosition: muchas tarjetas a la vez comparten un solo pedido al GPS", async () => {
  // Módulo nuevo (sin la posición cacheada de las pruebas anteriores) y un GPS que cuenta los pedidos.
  let pedidos = 0;
  Object.defineProperty(globalThis, "navigator", { configurable: true, writable: true,
    value: { geolocation: { getCurrentPosition: (ok) => { pedidos++; setTimeout(() => ok({ coords: { latitude: 36.1, longitude: -115.1 } }), 5); } } } });
  const loc = await import("../../web/js/location.js?gps-compartido");
  const posiciones = await Promise.all(Array.from({ length: 30 }, () => loc.currentPosition()));
  assert.equal(pedidos, 1);
  assert.ok(posiciones.every((p) => p.lat === 36.1));
});
