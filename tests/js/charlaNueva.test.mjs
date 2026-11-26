// «Nueva · agregada el …» y «Cancelada» arriba del título (node --test).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import "./domMinimo.mjs";

const { AvisoNueva, EtiquetaEstado } = await import("../../web/js/lleno.js");

test("una charla que sumó AWS dice cuándo", () => {
  const tag = EtiquetaEstado({ added: "2026-11-24" });
  assert.equal(tag.className, "ra-tag is-nueva");
  assert.equal(tag.textContent, "Nueva · agregada el mar 24/11");
});

test("cancelada gana sobre nueva", () => {
  const tag = EtiquetaEstado({ added: "2026-11-24", cancelled: true });
  assert.equal(tag.className, "ra-tag is-cancelada");
  assert.equal(tag.textContent, "Cancelada");
});

test("sin estado no hay etiqueta", () => {
  assert.equal(EtiquetaEstado({}), null);
  assert.equal(EtiquetaEstado(null), null);
});

test("el aviso de la ficha avisa del resumen en inglés solo si no está traducido", () => {
  assert.ok(AvisoNueva({ added: "2026-11-24" }).textContent.includes("en inglés"));
  assert.ok(!AvisoNueva({ added: "2026-11-24", abstract_es: "Hola" }).textContent.includes("en inglés"));
  assert.equal(AvisoNueva({ added: "2026-11-24", cancelled: true }), null);
  assert.equal(AvisoNueva({}), null);
});

test("la tarjeta y la ficha muestran la etiqueta", () => {
  const leer = (f) => readFileSync(new URL(`../../web/js/${f}`, import.meta.url), "utf8");
  assert.ok(leer("itinerary.js").includes("EtiquetaEstado(s)"));
  assert.ok(leer("knowledge.js").includes("EtiquetaEstado(estado)") && leer("knowledge.js").includes("AvisoNueva(estado)"));
});
