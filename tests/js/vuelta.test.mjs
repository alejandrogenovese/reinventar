// La vuelta desde Las Vegas (node --test): a qué hora salir del hotel y a qué terminal de LAS pedir el auto.
import test from "node:test";
import assert from "node:assert/strict";
import "./domMinimo.mjs";

const { salirAlAeropuerto, saleDeLasVegas, esInternacional, anticipacionMin, restarMinutos, terminalDeSalida,
  ANTICIPACION_INTERNACIONAL_MIN, ANTICIPACION_DOMESTICO_MIN, TRASLADO_STRIP_MIN } = await import("../../web/js/vuelta.js");
const { SalidaAlAeropuerto } = await import("../../web/js/viajes.js");

const buscar = (nodo, pred) => (pred(nodo) ? [nodo] : (nodo.children || []).flat(Infinity)
  .flatMap((c) => (c && typeof c === "object" ? buscar(c, pred) : [])));

// Lun 7/12, sale 13:00 de Las Vegas (como la vuelta del viaje).
const vuelo = (extra = {}) => ({ id: "v1", numero: "UA1234", zona: "America/Los_Angeles", zona_nombre: "Las Vegas",
  salida: "2026-12-07T13:00", destino_iata: null, terminal: null, estado: null, ...extra });

test("constantes: 3 h internacional, 2 h doméstico y ~25 min de traslado desde el Strip", () => {
  assert.equal(ANTICIPACION_INTERNACIONAL_MIN, 180);
  assert.equal(ANTICIPACION_DOMESTICO_MIN, 120);
  assert.equal(TRASLADO_STRIP_MIN, 25);
});

test("internacional (o destino desconocido): salida − 3 h − 25 min", () => {
  assert.deepEqual(salirAlAeropuerto(vuelo()), { hora: "09:35", local: "2026-12-07T09:35", anticipacionMin: 180, internacional: true });
  assert.equal(salirAlAeropuerto(vuelo({ destino_iata: "PTY" })).hora, "09:35");
});

test("doméstico (destino en EE. UU.): salida − 2 h − 25 min", () => {
  const s = salirAlAeropuerto(vuelo({ destino_iata: "iah" }));
  assert.equal(s.hora, "10:35");
  assert.equal(s.internacional, false);
  assert.equal(anticipacionMin({ destino_iata: "MIA" }), 120);
  assert.equal(esInternacional({ destino_iata: "EZE" }), true);
});

test("cruza la medianoche: un vuelo de la 1:30 pide salir el día anterior", () => {
  assert.equal(salirAlAeropuerto(vuelo({ salida: "2026-12-07T01:30", destino_iata: "DFW" })).local, "2026-12-06T23:05");
});

test("solo los vuelos que salen de Las Vegas, con hora y no cancelados", () => {
  assert.equal(saleDeLasVegas(vuelo({ zona_nombre: "Los Ángeles" })), false, "misma zona, otra ciudad");
  assert.equal(saleDeLasVegas(vuelo({ zona: "America/Argentina/Buenos_Aires", zona_nombre: "Buenos Aires" })), false);
  assert.equal(salirAlAeropuerto(vuelo({ salida: null })), null);
  assert.equal(salirAlAeropuerto(vuelo({ estado: "Canceled" })), null);
  assert.equal(salirAlAeropuerto(null), null);
});

test("restarMinutos ignora lo que no es una fecha", () => {
  assert.equal(restarMinutos("mañana", 10), null);
  assert.equal(restarMinutos(undefined, 10), null);
});

test("terminal: la que informó el vuelo y, si no, la de la aerolínea", () => {
  assert.equal(terminalDeSalida(vuelo({ terminal: "1" })), "lasT1");
  assert.equal(terminalDeSalida(vuelo({ terminal: "T3", numero: "AA100" })), "lasT3");
  assert.equal(terminalDeSalida(vuelo({ numero: "AA100" })), "lasT1");
  assert.equal(terminalDeSalida(vuelo({ numero: "CM300" })), "lasT3");
  assert.equal(terminalDeSalida(vuelo({ numero: "XX1" })), null);
});

test("la tarjeta muestra la hora de salir y, en la ficha, Uber y Lyft a la terminal", () => {
  const linea = SalidaAlAeropuerto(vuelo({ numero: "UA1234" }));
  assert.match(linea.textContent, /Salí del hotel antes de las 09:35/);

  const ficha = SalidaAlAeropuerto(vuelo({ numero: "UA1234" }), { detalle: true });
  const links = buscar(ficha, (n) => n.tag === "a" && /uber|lyft/.test(n.attrs?.href ?? ""));
  assert.equal(links.length, 2, "Uber y Lyft a una sola terminal");
  assert.match(ficha.textContent, /Terminal 3/);
  assert.match(links[0].attrs.href, /36\.0857/);
});

test("sin terminal ni aerolínea conocida, ofrece las dos terminales", () => {
  const ficha = SalidaAlAeropuerto(vuelo({ numero: "XX1" }), { detalle: true });
  const links = buscar(ficha, (n) => n.tag === "a" && /uber|lyft/.test(n.attrs?.href ?? ""));
  assert.equal(links.length, 4);
});

test("el banner muestra «Próximo: Salí al aeropuerto» con la hora y el link al vuelo", async () => {
  const { avisoProximo } = await import("../../web/js/estado.js");
  const aviso = avisoProximo({ tipo: "aeropuerto", titulo: "Salí al aeropuerto", hora: "09:35", detalle: "UA1234 sale 13:00",
    url: "#/viajes/vuelo/v1", inicio: "2026-12-07T17:35:00+00:00" }, Date.parse("2026-12-07T15:00:00Z"));
  assert.match(aviso.hoja.texto, /09:35 · UA1234 sale 13:00/);
  assert.deepEqual(aviso.accion, { texto: "Ver vuelo", tipo: "ir", destino: "#/viajes/vuelo/v1" });
});

test("un vuelo que no sale de Las Vegas no muestra nada", () => {
  assert.equal(SalidaAlAeropuerto(vuelo({ zona: "America/Argentina/Buenos_Aires", zona_nombre: "Buenos Aires" })), null);
});
