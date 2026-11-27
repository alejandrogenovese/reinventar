// Pruebas de la franja del día de Inicio (node --test): en qué momento del viaje estás (web/js/dia.js).
import test from "node:test";
import assert from "node:assert/strict";

const { MARGEN_DIAS, RANGO_REINVENT, VUELTA, diaDeEvento, enVegas, fechaLarga, resumenDelDia } = await import("../../web/js/dia.js");

// Una hora de Las Vegas (PST, UTC−8 en noviembre y diciembre) como Date.
const vegas = (fecha, hora = "10:00") => new Date(`${fecha}T${hora}:00-08:00`);

test("enVegas usa la hora de Las Vegas aunque en UTC ya sea otro día", () => {
  assert.deepEqual(enVegas(new Date("2026-12-02T06:30:00Z")), { fecha: "2026-12-01", hora: "22:30" });
});

test("los cinco días de la conferencia: 30/11 es el Día 1 de 5 y 4/12 el Día 5", () => {
  const esperados = [["2026-11-30", "Lunes 30/11", 1], ["2026-12-01", "Martes 1/12", 2], ["2026-12-02", "Miércoles 2/12", 3],
    ["2026-12-03", "Jueves 3/12", 4], ["2026-12-04", "Viernes 4/12", 5]];
  for (const [fecha, titulo, dia] of esperados) {
    assert.deepEqual(diaDeEvento(vegas(fecha)), { tipo: "conferencia", titulo, detalles: [], dia, total: 5 }, fecha);
  }
  assert.equal(diaDeEvento(vegas("2026-11-30", "00:05")).dia, 1, "apenas pasada la medianoche de Las Vegas");
  assert.equal(diaDeEvento(vegas("2026-12-04", "23:59")).dia, 5);
});

test("antes del viaje: «Faltan N días para re:Invent» y cuándo llegás", () => {
  assert.deepEqual(diaDeEvento(vegas("2026-11-23")), {
    tipo: "antes", titulo: "Faltan 7 días para re:Invent", detalles: ["Llegás el domingo 29/11"] });
  assert.equal(diaDeEvento(vegas("2026-11-28")).titulo, "Faltan 2 días para re:Invent");
});

test("el domingo 29/11 es la llegada: re:Invent arranca mañana", () => {
  assert.deepEqual(diaDeEvento(vegas("2026-11-29")), {
    tipo: "llegada", titulo: "Domingo 29/11", detalles: ["Llegada", "re:Invent arranca mañana"] });
});

test("el 5/12 y el 6/12 son después de re:Invent, con la estadía", () => {
  const esperado = (titulo) => ({ tipo: "despues", titulo, detalles: ["re:Invent terminó", "la estadía sigue hasta el lunes 7/12 a las 13:00"] });
  assert.deepEqual(diaDeEvento(vegas("2026-12-05")), esperado("Sábado 5/12"));
  assert.deepEqual(diaDeEvento(vegas("2026-12-06", "23:59")), esperado("Domingo 6/12"));
});

test("el lunes 7/12 (salida) dice «Hoy volvés» con enlace a Viajes, antes y después del check-out", () => {
  const vuelta = { texto: "Hoy volvés · check-out y vuelo", href: "#/viajes" };
  assert.deepEqual(VUELTA, vuelta);
  assert.deepEqual(diaDeEvento(vegas("2026-12-07", "08:00")), { tipo: "despues", titulo: "Lunes 7/12", detalles: [], enlace: vuelta });
  assert.deepEqual(diaDeEvento(vegas("2026-12-07", "13:00")), { tipo: "terminado", titulo: "Lunes 7/12", detalles: [], enlace: vuelta });
  assert.deepEqual(diaDeEvento(vegas("2026-12-08")), { tipo: "terminado", titulo: "Martes 8/12", detalles: ["re:Invent terminó"] });
});

test("fuera del margen (más de 14 días antes o después) no hay franja", () => {
  assert.equal(diaDeEvento(vegas("2026-11-16")).titulo, `Faltan ${MARGEN_DIAS} días para re:Invent`);
  assert.equal(diaDeEvento(vegas("2026-11-15")), null);
  assert.equal(diaDeEvento(vegas("2026-12-21")).tipo, "terminado");
  assert.equal(diaDeEvento(vegas("2026-12-22")), null);
  assert.equal(diaDeEvento(vegas("2027-06-01")), null);
});

test("una fecha inválida no rompe: no hay franja", () => {
  assert.equal(diaDeEvento(new Date("no es fecha")), null);
  assert.equal(diaDeEvento("2026-12-01"), null);
});

test("el rango se puede pasar (no queda atado a 2026)", () => {
  const rango = { llegada: "2027-11-28", inicio: "2027-11-29", fin: "2027-12-03", salida: "2027-12-05", horaSalida: "10:00" };
  assert.equal(diaDeEvento(vegas("2027-12-01"), rango).dia, 3);
  assert.equal(RANGO_REINVENT.inicio, "2026-11-30");
});

test("fechaLarga: día de la semana y d/m", () => {
  assert.equal(fechaLarga("2026-12-01"), "Martes 1/12");
});

test("resumenDelDia: la keynote de hoy (nivel 1) sin el cero y las charlas que te quedan", () => {
  const hoy = { now: { kind: "talk" }, next: { code: "X" }, later: [{ kind: "event" }, { kind: "talk" }] };
  const anuncios = { is_today: true, items: [{ nivel: 2, start: "07:00" }, { nivel: 1, start: "08:00", en_curso: false }] };
  assert.deepEqual(resumenDelDia({ hoy, anuncios }), { keynote: { hora: "8:00", enVivo: false }, charlas: 3 });
});

test("resumenDelDia: keynote en vivo, anuncios de otro día y datos que no llegaron", () => {
  const vivo = { is_today: true, items: [{ nivel: 1, start: "08:00", en_curso: true }] };
  assert.deepEqual(resumenDelDia({ anuncios: vivo }).keynote, { hora: "8:00", enVivo: true });
  assert.equal(resumenDelDia({ anuncios: { is_today: false, items: [{ nivel: 1, start: "08:00" }] } }).keynote, null);
  assert.deepEqual(resumenDelDia({}), { keynote: null, charlas: null });
  assert.equal(resumenDelDia({ hoy: { now: null, next: null, later: [] } }).charlas, 0);
});
