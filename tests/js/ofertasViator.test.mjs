// Ofertas de Viator en vivo (node --test): la tarjeta (precio antes/ahora, % y aviso), en qué filtros se ven y que la
// pantalla Ofertas siga como siempre si /api/ofertas/en-vivo falla o no trae nada.
import test from "node:test";
import assert from "node:assert/strict";

import { Nodo } from "./domMinimo.mjs";

// Lo justo que viewOfertas usa del DOM y que domMinimo no trae (cada archivo de node --test corre en su proceso).
Object.defineProperty(Nodo.prototype, "firstChild", { get() { return this.children[0] ?? null; } });
Nodo.prototype.querySelectorAll = () => [];

const { AVISO_VIATOR, TarjetaViator, ofertasViatorVisibles, viewOfertas } = await import("../../web/js/ofertas.js");

const todos = (n) => (typeof n === "string" || !n ? [] : [n, ...n.children.flatMap(todos)]);
const buscar = (raiz, tag, texto) => todos(raiz).filter((n) => n.tag === tag && (!texto || n.textContent.includes(texto)));
const esperar = () => new Promise((r) => setTimeout(r, 10));
const URL_VIATOR = "https://www.viator.com/tours/Las-Vegas/x/d684-5502GRAND?pid=P1&mcid=42&medium=api";
const OFERTA = { codigo: "5502GRAND", titulo: "Grand Canyon West", foto: null, url: URL_VIATOR, moneda: "USD",
  precio_antes: 200, precio_ahora: 120, descuento: 40 };

function conApi(respuestas) {
  globalThis.fetch = async (url) => {
    const r = respuestas[String(url).split("?")[0]];
    if (r instanceof Error) throw r;
    if (r?.status) return { ok: false, status: r.status, statusText: "x", json: async () => ({ detail: "x" }) };
    return { ok: true, status: 200, json: async () => r };
  };
}
const LISTA_VACIA = { ofertas: [], categorias: { shows: "Shows", comida: "Comida", compras: "Compras y outlets", otros: "Otros" }, es_admin: false };

test("la tarjeta muestra precio antes y ahora, el % de descuento, el aviso y el link de afiliado", () => {
  const t = TarjetaViator(OFERTA);
  const texto = t.textContent;
  assert.match(texto, /Grand Canyon West/);
  assert.equal(buscar(t, "s")[0].textContent, "US$ 200");
  assert.equal(buscar(t, "strong")[0].textContent, "US$ 120");
  assert.match(texto, /-40 %/);
  assert.match(texto, /lo fija Viator y puede cambiar/);
  assert.match(AVISO_VIATOR, /Viator/);
  const link = buscar(t, "a", "Ver en Viator")[0];
  assert.equal(link.attrs.href, URL_VIATOR);
  assert.equal(link.attrs.target, "_blank");
});

test("un link que no es https no se muestra", () => {
  assert.equal(buscar(TarjetaViator({ ...OFERTA, url: "javascript:alert(1)" }), "a").length, 0);
});

test("las excursiones salen en «Todas» y «Otros», no en shows, comida o compras", () => {
  assert.deepEqual(ofertasViatorVisibles([OFERTA], "todas"), [OFERTA]);
  assert.deepEqual(ofertasViatorVisibles([OFERTA], "otros"), [OFERTA]);
  assert.deepEqual(ofertasViatorVisibles([OFERTA], "shows"), []);
  assert.deepEqual(ofertasViatorVisibles(undefined, "todas"), []);
});

test("con ofertas de Viator se ve la sección y no el estado vacío", async () => {
  conApi({ "/api/ofertas": LISTA_VACIA, "/api/ofertas/en-vivo": { ofertas: [OFERTA] } });
  const view = new Nodo("main");
  await viewOfertas(view);
  await esperar();
  assert.match(view.textContent, /Excursiones con descuento/);
  assert.match(view.textContent, /Grand Canyon West/);
  assert.doesNotMatch(view.textContent, /Todavía no hay ofertas/);
});

for (const [caso, enVivo] of [["falla", { status: 503 }], ["no trae nada", { ofertas: [] }], ["sin red", new TypeError("Failed to fetch")]]) {
  test(`si Viator ${caso}, Ofertas queda como siempre`, async () => {
    conApi({ "/api/ofertas": LISTA_VACIA, "/api/ofertas/en-vivo": enVivo });
    const view = new Nodo("main");
    await viewOfertas(view);
    await esperar();
    assert.match(view.textContent, /Todavía no hay ofertas/);
    assert.doesNotMatch(view.textContent, /Excursiones con descuento/);
  });
}
