// Pruebas de «Cómo llegar a la sala» (node --test): destino de «Llevame» a la entrada de convenciones y los pasos por
// sede y por piso, con el DOM mínimo compartido.
import test from "node:test";
import assert from "node:assert/strict";
import "./domMinimo.mjs";

const { ENTRADAS, GUIAS, GuiaSala, destinoDeSala, destinoDeTarjeta: destination, pasosDeSala } = await import("../../web/js/salas.js");

const MGM = { hotel: "MGM Grand", detail: "Level 3 · Premier 311", lat: 36.102219, lng: -115.169517 };
const textos = (pasos) => pasos.map((p) => p.texto);
const buscar = (nodo, tag) => (nodo.tag === tag ? [nodo] : (nodo.children || []).flatMap((c) => (typeof c === "string" ? [] : buscar(c, tag))));

test("una sede con entrada conocida va al área de convenciones, no al hotel", () => {
  const destino = destinoDeSala(MGM);
  assert.deepEqual(destino, { lat: ENTRADAS["MGM Grand"].lat, lng: ENTRADAS["MGM Grand"].lng, name: "MGM Grand Conference Center" });
  assert.notEqual(destino.lat, MGM.lat);
});

test("una sede sin entrada conocida queda en el punto del hotel", () => {
  const wynn = { hotel: "Wynn/Encore", detail: "Level 1 · Chopin 4", lat: 36.126492, lng: -115.165741 };
  assert.deepEqual(destinoDeSala(wynn), { lat: wynn.lat, lng: wynn.lng, name: "Wynn/Encore" });
});

test("sin coordenadas no hay destino", () => {
  assert.equal(destinoDeSala({ hotel: "Various Locations", lat: null }), null);
  assert.equal(destinoDeSala(null), null);
});

test("todas las entradas quedan cerca de su sede (menos de 1 km): ningún punto mal tipeado", () => {
  const SEDES = { "Venetian": [36.1216, -115.1691], "Caesars Forum": [36.1179, -115.1641],
    "Caesars Palace": [36.11778, -115.175], "MGM Grand": [36.102219, -115.169517] };
  for (const [hotel, [lat, lng]] of Object.entries(SEDES)) {
    const e = ENTRADAS[hotel];
    const metros = Math.hypot((e.lat - lat) * 111_000, (e.lng - lng) * 90_000);
    assert.ok(metros < 1000, `${hotel} está a ${Math.round(metros)} m`);
  }
});

test("los pasos de un piso solo aparecen para salas de ese piso", () => {
  const nivel3 = textos(pasosDeSala("MGM Grand", "Level 3 · Premier 311"));
  const nivel1 = textos(pasosDeSala("MGM Grand", "Level 1 · Grand 111"));
  assert.ok(nivel3.some((t) => t.includes("Level 3")));
  assert.ok(!nivel1.some((t) => t.includes("Level 3")));
  assert.ok(nivel1.length >= 3);
});

test("cada sede con guía tiene entre 2 y 5 pasos para cualquier sala (Wynn/Encore tiene poco respaldado)", () => {
  for (const hotel of Object.keys(GUIAS)) {
    for (const detalle of ["", "Level 1 · x", "Level 2 · x", "Level 3 · x", "Level 5 · x"]) {
      const n = pasosDeSala(hotel, detalle).length;
      assert.ok(n >= 2 && n <= 5, `${hotel} «${detalle}»: ${n} pasos`);
    }
  }
});

test("una sede sin guía no muestra el desplegable", () => {
  assert.deepEqual(pasosDeSala("Allegiant Stadium", ""), []);
  assert.equal(GuiaSala({ hotel: "Allegiant Stadium", detail: "" }), null);
  assert.equal(GuiaSala(null), null);
});

test("el desplegable es un <details> con resumen de texto y los pasos en una lista", () => {
  const guia = GuiaSala(MGM);
  assert.equal(guia.tag, "details");
  const [summary] = buscar(guia, "summary");
  assert.equal(summary.textContent, "Cómo llegar a la sala");
  assert.equal(buscar(guia, "li").length, pasosDeSala("MGM Grand", MGM.detail).length);
  assert.match(guia.textContent, /\(a confirmar\)/);
  assert.match(guia.textContent, /guías de terceros/);
});

test("en Hoy, una charla va a la entrada de convenciones; un evento con su lugar, a su lugar", () => {
  assert.equal(destination({ venue: MGM }).name, "MGM Grand Conference Center");
  const evento = { kind: "event", venue: { ...MGM, hotel: "Venetian", place_id: "abc", exact: true } };
  assert.deepEqual(destination(evento), { lat: MGM.lat, lng: MGM.lng, name: "Venetian", placeId: "abc", approx: false });
});
