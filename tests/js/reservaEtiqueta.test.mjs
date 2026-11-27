// El estado de reserva de una charla (node --test): con reserva previa, reservada, solo por cola o nada.
import test from "node:test";
import assert from "node:assert/strict";

import "./domMinimo.mjs";

const { ayudaReserva } = await import("../../web/js/reservaEtiqueta.js");

test("la ayuda de la cola solo va si se reserva y no la tenés", () => {
  assert.match(ayudaReserva({ walk_in: false }), /cola 45 min antes/);
  assert.equal(ayudaReserva({ walk_in: false, reservada: true }), null);
  assert.equal(ayudaReserva({ walk_in: true }), null);
  assert.equal(ayudaReserva({ kind: "event", walk_in: false }), null);
});

const { BotonReserva, EstadoEnLinea, InsigniaReserva, LineaHoraReserva, AvisoReserva, RESERVA_LIBERA_MIN, estadoReserva } =
  await import("../../web/js/reservaEtiqueta.js");
const { readFileSync } = await import("node:fs");
const texto = (e) => e.antes + (e.hora ?? "") + e.despues;

test("con reserva y sin tenerla: cola 45 min antes, con la hora concreta", () => {
  const e = estadoReserva({ walk_in: false, seats: 112, start: "08:00" });
  assert.equal(e.estado, "reserva");
  assert.equal(e.titulo, "Reserva previa · 112 lugares");
  assert.equal(texto(e), "Sin tu reserva: cola desde las 07:15, entrás si sobran lugares.");
});

test("reservada: hay que entrar 10 min antes o se libera el lugar", () => {
  const e = estadoReserva({ walk_in: false, reservada: true, start: "08:00" });
  assert.equal(e.estado, "reservada");
  assert.equal(texto(e), "Entrá antes de las 07:50 o se libera tu lugar.");
});

test("por orden de llegada: cola 30 min antes; da la vuelta a la medianoche", () => {
  assert.equal(texto(estadoReserva({ walk_in: true, start: "08:00" })), "Cola desde las 07:30.");
  assert.equal(estadoReserva({ walk_in: true, start: "00:10" }).hora, "23:40");
});

test("sin hora de inicio dice los minutos", () => {
  assert.equal(texto(estadoReserva({ walk_in: false })), "Sin tu reserva: cola desde 45 min antes, entrás si sobran lugares.");
});

test("RESERVA_LIBERA_MIN es el mismo que app/leave.py", () => {
  const leave = readFileSync(new URL("../../app/leave.py", import.meta.url), "utf8");
  assert.match(leave, new RegExp(`^RESERVA_LIBERA_MIN = ${RESERVA_LIBERA_MIN}$`, "m"));
});

test("el botón dice «Ya la reservé», queda pulsado al reservar y no aparece si es por orden de llegada", () => {
  const nada = () => {};
  assert.equal(BotonReserva({ walk_in: false }, nada).textContent, "Ya la reservé");
  assert.equal(BotonReserva({ walk_in: false }, nada).getAttribute("aria-pressed"), "false");
  assert.equal(BotonReserva({ walk_in: false, reservada: true }, nada).getAttribute("aria-pressed"), "true");
  assert.equal(BotonReserva({ walk_in: true }, nada), null);
  assert.equal(BotonReserva({ walk_in: false }, null), null);
});

test("insignia, línea de hora, estado en línea y aviso llevan el estado como clase", () => {
  const s = { walk_in: false, reservada: true, start: "10:00" };
  assert.match(InsigniaReserva(s).className, /is-reservada/);
  assert.equal(LineaHoraReserva(s).textContent, "Entrá antes de las 09:50 o se libera tu lugar.");
  assert.match(EstadoEnLinea({ walk_in: true }).className, /is-libre/);
  const aviso = AvisoReserva({ walk_in: false, start: "10:00" }, async () => {});
  assert.match(aviso.className, /ra-aviso-reserva is-reserva/);
  assert.match(aviso.textContent, /cola desde las 09:15/);
  assert.match(aviso.textContent, /Ya la reservé/);
  assert.equal(AvisoReserva({ kind: "event", walk_in: false }), null);
});
