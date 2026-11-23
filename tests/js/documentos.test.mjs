// Lógica pura de documentos.js (sin DOM ni IndexedDB): fechas, estado de la copia local y validación del archivo elegido.
import assert from "node:assert/strict";
import test from "node:test";
import { TIPOS, errorDeArchivo, estadoLocal, fechaCorta } from "../../web/js/documentos.js";
import { borrarDocsLocales, guardadosLocales, leerLocal } from "../../web/js/docsLocal.js";

test("los siete tipos del contrato con el servidor", () => {
  assert.deepEqual(Object.keys(TIPOS), ["pasaporte", "esta_visa", "seguro", "reserva", "entrada_reinvent", "tarjeta_embarque", "otro"]);
});

test("fechaCorta no corre la fecha por la zona horaria", () => {
  assert.equal(fechaCorta("2026-12-07"), "7/12/2026");
  assert.equal(fechaCorta("2027-01-01"), "1/1/2027");
});

test("estadoLocal distingue guardado al día, viejo y no guardado", () => {
  const doc = { id: "a", sha256: "x" };
  assert.equal(estadoLocal(doc, { a: "x" }), "ok");
  assert.equal(estadoLocal(doc, { a: "y" }), "vieja");
  assert.equal(estadoLocal(doc, {}), null);
});

test("errorDeArchivo frena lo vacío, lo pesado y lo que no es foto ni PDF", () => {
  assert.match(errorDeArchivo(null), /Elegí/);
  assert.match(errorDeArchivo({ size: 9 * 1024 * 1024, type: "image/jpeg" }), /8 MB/);
  assert.match(errorDeArchivo({ size: 10, type: "text/html" }), /foto/);
  assert.equal(errorDeArchivo({ size: 10, type: "application/pdf" }), null);
  assert.equal(errorDeArchivo({ size: 10, type: "" }), null); // sin tipo: decide el servidor por la firma
});

test("sin IndexedDB (node) la copia local no rompe nada", async () => {
  assert.deepEqual(await guardadosLocales(), {});
  assert.equal(await leerLocal("a"), null);
  await borrarDocsLocales();
});
