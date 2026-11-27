// Pruebas de «re:Invent día por día» (node --test): cada sección con su fuente, los datos clave del evento y la tarjeta
// de keynotes de Inicio con el livestream y la traducción al español. Con el DOM mínimo compartido.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import "./domMinimo.mjs";

const { CONSULTA, CONSULTA_VUELTA, FUENTES, LIVESTREAM_URL, RUTA_DOCUMENTOS, SECCIONES, TRADUCCION_KEYNOTES, Seccion, viewDiaPorDia } =
  await import("../../web/js/diaPorDia.js");

const texto = (id) => SECCIONES.find((s) => s.id === id).items.map((i) => `${i.cuando ?? ""} ${i.texto}`).join("\n");
const buscar = (nodo, tag) => (nodo.tag === tag ? [nodo] : (nodo.children || []).flatMap((c) => (c && typeof c === "object" ? buscar(c, tag) : [])));

test("cada sección cita al menos una fuente conocida, con https", () => {
  for (const s of SECCIONES) {
    assert.ok(s.fuentes.length, s.id);
    for (const f of s.fuentes) assert.match(FUENTES[f]?.url ?? "", /^https:\/\//, `${s.id}: ${f}`);
  }
  assert.equal(CONSULTA, "25/11/2026");
});

test("el badge: aeropuerto el domingo, y el viernes no hay retiro", () => {
  const badge = texto("badge");
  assert.match(badge, /Dom 29\/11.*Aeropuerto.*terminales 1 y 3/);
  assert.match(badge, /Vie 4\/12 No hay retiro/);
});

test("keynotes con traducción al español y livestream oficial", () => {
  const kn = SECCIONES.find((s) => s.id === "keynotes");
  assert.match(texto("keynotes"), /español/);
  assert.deepEqual(kn.links.map((l) => l.url), [LIVESTREAM_URL]);
  assert.match(LIVESTREAM_URL, /^https:\/\/aws\.amazon\.com\/events\/reinvent\//);
});

test("re:Play el jueves en el Allegiant Stadium con su shuttle", () => {
  assert.match(texto("replay"), /Jue 3\/12 18:30 a 22:30 en el Allegiant Stadium\. Shuttle de 18:15 a 23:00/);
});

test("los links externos abren en otra pestaña sin opener", () => {
  const links = buscar(Seccion(SECCIONES.find((s) => s.id === "keynotes")), "a");
  assert.ok(links.length >= 3);  // el livestream y las dos fuentes
  for (const a of links) assert.equal(a.attrs.rel, "noopener noreferrer");
});

test("la pantalla tiene su h1 y una sección por cada entrada", () => {
  const view = globalThis.document.createElement("div");
  viewDiaPorDia(view);
  assert.equal(buscar(view, "h1")[0].textContent, "re:Invent día por día");
  assert.equal(buscar(view, "section").length, SECCIONES.length);
});

test("la tarjeta de keynotes de Inicio suma livestream y traducción", () => {
  const anuncios = readFileSync(new URL("../../web/js/anuncios.js", import.meta.url), "utf8");
  assert.match(anuncios, /import \{ LIVESTREAM_URL, TRADUCCION_KEYNOTES \} from "\.\/diaPorDia\.js"/);
  assert.match(anuncios, /s\.nivel === NIVEL_KEYNOTE \? KeynoteExtras\(\)/);
  assert.match(TRADUCCION_KEYNOTES, /español/);
});

test("emergencias y vuelta van al final, con fuentes oficiales consultadas el 26/11", () => {
  assert.deepEqual(SECCIONES.slice(-2).map((s) => s.id), ["emergencias", "vuelta"]);
  const oficiales = /^https:\/\/(www\.)?(911\.gov|cancilleria\.gob\.ar|walgreens\.com|harryreidairport\.com|arca\.gob\.ar)\//;
  for (const s of SECCIONES.slice(-2)) {
    assert.equal(s.consulta, CONSULTA_VUELTA);
    for (const f of s.fuentes) assert.match(FUENTES[f].url, oficiales, `${s.id}: ${f}`);
  }
  assert.match(Seccion(SECCIONES.at(-1)).textContent, /consultada el 26\/11\/2026/);
  assert.match(Seccion(SECCIONES[0]).textContent, /consultada el 25\/11\/2026/, "las otras siguen con su fecha");
});

test("emergencias: 911, seguro con link a Documentos, farmacia y consulado con guardia", () => {
  const t = texto("emergencias");
  assert.match(t, /^911 /);
  assert.match(t, /Walgreens, 3765 Las Vegas Blvd S/);
  assert.match(t, /\+1 323-954-9155/);
  assert.match(t, /Guardia consular \+1 323-459-9780/);
  assert.match(t, /atiende Nevada/);
  const docs = buscar(Seccion(SECCIONES.find((s) => s.id === "emergencias")), "a").find((a) => a.attrs.href === RUTA_DOCUMENTOS);
  assert.ok(docs, "link a Documentos de viaje");
  assert.equal(docs.attrs.target, undefined, "un link de la app no abre otra pestaña");
});

test("vuelta: anticipación en LAS, terminales y franquicia de ARCA", () => {
  const t = texto("vuelta");
  assert.match(t, /3 h antes si el vuelo es internacional y 2 h si es doméstico/);
  assert.match(t, /Terminal 1: American, Delta y Southwest\. Terminal 3: United/);
  assert.match(t, /US\$ 500 en equipaje, más US\$ 500 en el free shop/);
  assert.match(t, /50 % de lo que excede/);
});
