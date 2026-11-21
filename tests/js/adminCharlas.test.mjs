// Charlas nuevas del admin: agrupar por código, filtrar por búsqueda y track, y paginar (node --test).
import test from "node:test";
import assert from "node:assert/strict";

const { agruparCharlas, trackDe, tracksDe, filtrarCharlas, visibles, VISIBLES_INICIAL } =
  await import("../../web/js/adminCharlas.js");

const c = (base, titulo, extra = {}) => ({ base, titulo, alta: "2026-12-01T10:00:00Z", primero: "2026-12-02T09:00:00", horarios: 1, ...extra });

test("el track es el prefijo de letras del código", () => {
  assert.equal(trackDe("DAT301"), "DAT");
  assert.equal(trackDe("aim204-r1"), "AIM");
  assert.equal(trackDe("123"), "Otros");
  assert.equal(trackDe(""), "Otros");
});

test("una charla con dos horarios es una sola fila con «2 horarios»", () => {
  const filas = agruparCharlas([c("DAT301", "Zero-ETL", { horarios: 2 }), c("AIM204", "Agentes")]);
  assert.equal(filas.length, 2);
  assert.deepEqual(filas.map((f) => [f.base, f.horarios]), [["DAT301", 2], ["AIM204", 1]]);
  assert.equal(filas[0].track, "DAT");
});

test("si el mismo código llega en filas repetidas se junta: suma horarios y deja el primer horario", () => {
  const filas = agruparCharlas([
    c("DAT301", "Zero-ETL", { horarios: 1, primero: "2026-12-03T09:00:00" }),
    c("DAT301", "Zero-ETL", { horarios: 1, primero: "2026-12-02T09:00:00" }),
  ]);
  assert.equal(filas.length, 1);
  assert.equal(filas[0].horarios, 2);
  assert.equal(filas[0].primero, "2026-12-02T09:00:00");
});

test("conserva el orden de llegada (la más reciente primero) y tolera datos vacíos", () => {
  assert.deepEqual(agruparCharlas([c("B1", "b"), c("A1", "a")]).map((f) => f.base), ["B1", "A1"]);
  assert.deepEqual(agruparCharlas(undefined), []);
  assert.deepEqual(agruparCharlas([c("X1", "x", { horarios: 0 })])[0].horarios, 0);
});

test("los tracks con su cantidad: «Otros» al final y el resto alfabético", () => {
  const filas = agruparCharlas([c("DAT1", "a"), c("AIM1", "b"), c("AIM2", "c"), c("1", "d")]);
  assert.deepEqual(tracksDe(filas), [["AIM", 2], ["DAT", 1], ["Otros", 1]]);
});

test("la búsqueda mira código y título sin acentos ni mayúsculas, y el track filtra", () => {
  const filas = agruparCharlas([c("DAT301", "Zero-ETL en la práctica"), c("AIM204", "Agentes con Bedrock"), c("AIM311", "Evaluación de modelos")]);
  assert.deepEqual(filtrarCharlas(filas, { texto: "practica" }).map((f) => f.base), ["DAT301"]);
  assert.deepEqual(filtrarCharlas(filas, { texto: "aim3" }).map((f) => f.base), ["AIM311"]);
  assert.deepEqual(filtrarCharlas(filas, { track: "AIM" }).map((f) => f.base), ["AIM204", "AIM311"]);
  assert.deepEqual(filtrarCharlas(filas, { track: "AIM", texto: "evaluacion" }).map((f) => f.base), ["AIM311"]);
  assert.equal(filtrarCharlas(filas, {}).length, 3);
  assert.equal(filtrarCharlas(filas, { texto: "   " }).length, 3);
});

test("se ven 10 y el resto queda para «Ver las N restantes»", () => {
  const filas = Array.from({ length: 37 }, (_, i) => ({ base: `X${i}` }));
  assert.equal(VISIBLES_INICIAL, 10);
  assert.deepEqual(visibles(filas, false), { filas: filas.slice(0, 10), restantes: 27 });
  assert.deepEqual(visibles(filas, true), { filas, restantes: 0 });
  assert.deepEqual(visibles(filas.slice(0, 4), false), { filas: filas.slice(0, 4), restantes: 0 });
});
