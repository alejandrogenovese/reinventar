// La etiqueta de reserva de una charla (node --test): con reserva previa, reservada, solo por cola o nada.
import test from "node:test";
import assert from "node:assert/strict";

import "./domMinimo.mjs";

const { EtiquetaReserva, ayudaReserva, textoReserva } = await import("../../web/js/reservaEtiqueta.js");

test("una charla que se reserva lo dice, con los lugares de la sala", () => {
  assert.equal(textoReserva({ kind: "talk", walk_in: false, seats: 112 }), "Con reserva previa · 112 lugares");
  assert.equal(textoReserva({ walk_in: false }), "Con reserva previa");
  assert.match(ayudaReserva({ walk_in: false }), /cola 45 min antes/);
});

test("si ya la reservaste dice Reservada y no da la ayuda de la cola", () => {
  assert.equal(textoReserva({ walk_in: false, reservada: true }), "Reservada");
  assert.equal(ayudaReserva({ walk_in: false, reservada: true }), null);
});

test("solo por cola dice que es por orden de llegada", () => {
  assert.equal(textoReserva({ walk_in: true }), "Sin reserva · por orden de llegada");
  assert.equal(ayudaReserva({ walk_in: true }), null);
});

test("eventos, shows o datos sin walk_in no llevan etiqueta", () => {
  assert.equal(EtiquetaReserva({ kind: "event", walk_in: false }), null);
  assert.equal(EtiquetaReserva({ kind: "talk" }), null);
  assert.equal(EtiquetaReserva({ walk_in: false, seats: 112 }).textContent, "Con reserva previa · 112 lugares");
});
