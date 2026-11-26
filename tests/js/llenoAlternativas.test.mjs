// «Está llena»: las charlas cerca que sugiere la ficha (node --test). Texto de cada sugerencia y cuándo se piden.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import "./domMinimo.mjs";

const { ListaAlternativas, SugerenciasLleno, detalleAlternativa } = await import("../../web/js/lleno.js");

const alt = (extra = {}) => ({ code: "CERCA", base: "CERCA", title: "Charla cerca", start: "14:30", minutos: 9, estimado: false,
  misma_sede: false, en_curso: false, venue: { hotel: "Caesars Forum", detail: "Level 2" }, ...extra });

test("cada sugerencia dice a qué hora, dónde y cuánto se camina", () => {
  assert.equal(detalleAlternativa(alt()), "14:30 · Caesars Forum · 9 min caminando");
  assert.equal(detalleAlternativa(alt({ estimado: true })), "14:30 · Caesars Forum · unos 9 min caminando");
  assert.equal(detalleAlternativa(alt({ misma_sede: true })), "14:30 · Caesars Forum · en el mismo edificio");
  assert.equal(detalleAlternativa(alt({ en_curso: true })), "Empezó 14:30 · Caesars Forum · 9 min caminando");
});

test("la lista lleva a la ficha de cada charla", () => {
  const lista = ListaAlternativas([alt(), alt({ base: "MISMA", title: "Otra" })]);
  const links = [];
  const recorrer = (n) => { if (n?.tag === "a") links.push(n.attrs.href); (n?.children || []).forEach(recorrer); };
  recorrer(lista);
  assert.deepEqual(links, ["#/charla/CERCA", "#/charla/MISMA"]);
  assert.ok(lista.textContent.includes("Está llena"));
});

test("sin sugerencias lo dice en lugar de dejar el hueco", () => {
  assert.ok(ListaAlternativas([]).textContent.includes("No encontramos otras charlas cerca"));
});

test("con mucha cola el título lo dice", () => {
  assert.ok(ListaAlternativas([alt()], "cola").textContent.includes("Hay mucha cola. Cerca y por empezar:"));
});

test("si estás anotado no se muestran", () => {
  assert.equal(SugerenciasLleno("X", { lleno: 2 }, true), null);
});

test("sin avisos el lugar queda vacío y no se piden", () => {
  const pedidos = [];
  globalThis.fetch = async (url) => { pedidos.push(String(url)); return new Response("{}"); };
  for (const aviso of [null, { lleno: 0, cola: 0 }]) {
    const s = SugerenciasLleno("X", aviso, false);
    assert.equal(s.el.children.length, 0);
  }
  assert.deepEqual(pedidos.filter((u) => u.includes("/alternativas")), []);
});

test("la ficha las muestra en cada horario y las vuelve a pedir al tocar «Está llena» o «Hay mucha cola»", () => {
  const ficha = readFileSync(new URL("../../web/js/knowledge.js", import.meta.url), "utf8");
  assert.ok(ficha.includes("SugerenciasLleno(i.code, aviso, Boolean(own))"));
  assert.ok(ficha.includes("onCambio: sugerencias?.mostrar"));
});
