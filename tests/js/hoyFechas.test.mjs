// Pruebas de Hoy y las fechas del viaje (node --test): Hoy recalculado sin señal (hoyPlan.js, la cuenta de app/today.py),
// lo que pasa la medianoche, el día libre, «Hoy en re:Invent» (diaPorDia.js) y la hora de Las Vegas en el grabador y en
// los pendientes. Con el DOM mínimo compartido.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import "./domMinimo.mjs";

const { ACCESOS_DIA_LIBRE, COLA_SIN_RESERVA_MIN, conFin, hoySinSenal, mensajeSinCharlas, planDeHoy } = await import("../../web/js/hoyPlan.js");
const { SECCIONES, hoyEnReinvent } = await import("../../web/js/diaPorDia.js");
const { cercaDeAhora } = await import("../../web/js/talkpicker.js");
const { estaVencido } = await import("../../web/js/pendientes.js");

// Una hora de Las Vegas (PST, UTC−8 en noviembre y diciembre) como Date.
const vegas = (fecha, hora = "10:00") => new Date(`${fecha}T${hora}:00-08:00`);
const charla = (code, day, start, end, extra = {}) => ({ code, day, start, end, title: code, kind: "talk", ...extra });
const codigos = (lista) => lista.map((s) => s.code);

const DIAS = [
  { day: "2026-12-01", sessions: [charla("A", "2026-12-01", "09:00", "10:00"), charla("B", "2026-12-01", "11:00", "12:00"),
    charla("C", "2026-12-01", "14:00", "15:00")] },
  { day: "2026-12-02", sessions: [charla("D", "2026-12-02", "10:00", "12:00")] },
];

// ---------- planDeHoy: la misma cuenta que app/today.py ----------

test("durante una charla: Ahora, la siguiente como Próxima y el resto después", () => {
  const r = planDeHoy(DIAS, vegas("2026-12-01", "09:30"));
  assert.equal(r.date, "2026-12-01");
  assert.equal(r.time, "09:30");
  assert.equal(r.now.code, "A");
  assert.equal(r.next.code, "B");
  assert.deepEqual(codigos(r.later), ["C"]);
  assert.equal(r.upcoming, null);
});

test("usa la hora de Las Vegas aunque en UTC ya sea otro día", () => {
  const r = planDeHoy(DIAS, new Date("2026-12-01T22:30:00Z"));  // 14:30 en Las Vegas
  assert.equal(r.now.code, "C");
});

test("sin nada más hoy, upcoming es lo primero del próximo día con algo", () => {
  const r = planDeHoy(DIAS, vegas("2026-12-01", "16:00"));
  assert.equal(r.now, null);
  assert.equal(r.next, null);
  assert.deepEqual({ day: r.upcoming.day, code: r.upcoming.first.code }, { day: "2026-12-02", code: "D" });
});

test("un show de 22:00 a 00:30 sigue en Ahora a las 23:00 (cruza la medianoche)", () => {
  const show = { code: "SHOW", day: "2026-12-04", start: "22:00", end: "00:30", title: "Show", kind: "show" };
  const r = planDeHoy([{ day: "2026-12-04", sessions: [show] }], vegas("2026-12-04", "23:00"));
  assert.equal(r.now?.code, "SHOW");
});

test("conFin suma la cola sin reserva, la salida anticipada y el fin estimado", () => {
  assert.equal(COLA_SIN_RESERVA_MIN, 30);
  assert.deepEqual(conFin(charla("X", "2026-12-01", "00:10", "01:00", { salir_antes: 15 })).cola_desde, "23:40");
  assert.equal(conFin(charla("X", "2026-12-01", "09:00", "10:00", { salir_antes: 15 })).salis_a, "09:45");
  assert.equal(conFin(charla("X", "2026-12-01", "09:00", "10:00", { reservada: true })).cola_desde, null);
  assert.equal(conFin({ code: "E", start: "18:00", kind: "event" }).end, "19:00");
  assert.equal(conFin({ code: "E", start: "18:00", kind: "event" }).cola_desde, null);
});

test("la cola sin reserva coincide con la del servidor (app/guided.py)", () => {
  const guided = readFileSync(new URL("../../app/guided.py", import.meta.url), "utf8");
  assert.match(guided, new RegExp(`^COLA_SIN_RESERVA = ${COLA_SIN_RESERVA_MIN}$`, "m"));
});

// ---------- hoySinSenal: la copia vieja de /api/today ----------

test("sin señal, con el itinerario guardado, recalcula con la hora de ahora (no la de la copia)", () => {
  const copia = { date: "2026-12-01", time: "09:30", now: DIAS[0].sessions[0], next: DIAS[0].sessions[1], later: [], upcoming: null };
  const r = hoySinSenal(copia, { days: DIAS }, vegas("2026-12-01", "11:15"));
  assert.equal(r.sinSenal, true);
  assert.equal(r.now.code, "B");
  assert.equal(r.next.code, "C");
});

test("sin señal, con la copia de otro día e itinerario guardado, muestra el día de hoy", () => {
  const copia = { date: "2026-12-01", time: "09:30", now: DIAS[0].sessions[0], next: null, later: [], upcoming: null };
  const r = hoySinSenal(copia, { days: DIAS }, vegas("2026-12-02", "10:30"));
  assert.equal(r.date, "2026-12-02");
  assert.equal(r.now.code, "D");
});

test("sin señal y sin itinerario, la copia de hoy se recalcula con lo que trae", () => {
  const copia = { date: "2026-12-01", time: "09:30", now: DIAS[0].sessions[0], next: DIAS[0].sessions[1], later: [DIAS[0].sessions[2]], upcoming: null };
  const r = hoySinSenal(copia, null, vegas("2026-12-01", "12:30"));
  assert.equal(r.now, null);
  assert.equal(r.next.code, "C");
  assert.deepEqual(r.later, []);
  assert.equal(r.sinItinerario, undefined);
});

test("sin señal, sin itinerario y con la copia de otro día: nada en Ahora ni Próxima, «mirá tu itinerario»", () => {
  const copia = { date: "2026-12-01", time: "09:30", now: DIAS[0].sessions[0], next: DIAS[0].sessions[1], later: [], upcoming: null };
  const r = hoySinSenal(copia, null, vegas("2026-12-02", "09:30"));
  assert.equal(r.date, "2026-12-02");
  assert.equal(r.now, null);
  assert.equal(r.next, null);
  assert.equal(r.sinItinerario, true);
  assert.deepEqual(mensajeSinCharlas({ sinItinerario: true }), { texto: "Sin señal: mirá tu itinerario.", acciones: [] });
});

// ---------- mensajeSinCharlas: día libre, la próxima, armar itinerario ----------

test("la llegada y los días después de re:Invent son día libre, con Shows, Actividades y Comer", () => {
  for (const tipoDia of ["llegada", "despues"]) {
    const m = mensajeSinCharlas({ tipoDia });
    assert.equal(m.titulo, "Día libre");
    assert.deepEqual(m.acciones.map((a) => a.href), ["#/eventos/shows", "#/actividades", "#/comer"]);
  }
  assert.equal(ACCESOS_DIA_LIBRE.length, 3);
});

test("el día de llegada con charlas al otro día: día libre y cuál es la próxima", () => {
  const upcoming = { day: "2026-11-30", first: { start: "08:30", title: "Charla" } };
  const m = mensajeSinCharlas({ tipoDia: "llegada", upcoming, etiquetaDia: () => "lunes 30 nov" });
  assert.equal(m.titulo, "Día libre");
  assert.equal(m.texto, "La próxima es el lunes 30 nov a las 08:30: Charla.");
});

test("un día de conferencia sin charlas sigue ofreciendo armar el itinerario", () => {
  const m = mensajeSinCharlas({ tipoDia: "conferencia" });
  assert.equal(m.titulo, undefined);
  assert.equal(m.texto, "No tenés charlas en el itinerario para hoy.");
  assert.deepEqual(m.acciones, [{ texto: "Armar itinerario", href: "#/itinerario" }]);
});

test("las rutas del día libre existen en el router", () => {
  const app = readFileSync(new URL("../../web/js/app.js", import.meta.url), "utf8");
  for (const ruta of ["#\\/eventos\\/shows", "#\\/comer", "#\\/actividades", "#\\/viajes"]) assert.ok(app.includes(ruta), ruta);
});

// ---------- hoyEnReinvent: lo propio de cada día, de diaPorDia.js ----------

const textosDe = (fecha) => hoyEnReinvent(fecha).map((i) => `${i.seccion}: ${i.texto}`).join("\n");

test("29 y 30/11: retiro del badge; el 30, la Developer Keynote y la Welcome Reception", () => {
  assert.match(textosDe("2026-11-29"), /Retiro del badge: Aeropuerto Harry Reid/);
  assert.match(textosDe("2026-11-29"), /Shuttles: 9:30 a 20:30, servicio limitado/);
  const lunes = textosDe("2026-11-30");
  assert.match(lunes, /Retiro del badge: Aeropuerto, terminales/);
  assert.match(lunes, /Keynotes: Developer Keynote/);
  assert.match(lunes, /Welcome Reception/);
});

test("1 y 2/12: keynote y networking receptions", () => {
  assert.match(textosDe("2026-12-01"), /CEO Keynote/);
  assert.match(textosDe("2026-12-01"), /Networking receptions/);
  assert.match(textosDe("2026-12-02"), /Data & AI Keynote/);
  assert.match(textosDe("2026-12-02"), /Networking receptions/);
});

test("jueves 3/12: re:Play con su shuttle y el corte de los shuttles comunes a las 17:45", () => {
  const jueves = textosDe("2026-12-03");
  assert.match(jueves, /re:Play: 18:30 a 22:30 en el Allegiant Stadium\. Shuttle de 18:15 a 23:00/);
  assert.match(jueves, /Shuttles: 6:00 a 17:45\. Para re:Play, 18:15 a 23:00/);
  assert.match(jueves, /Technical Innovations Keynote/);
});

test("viernes 4/12: shuttle limitado hasta las 13:00, solo Venetian y Wynn/Encore", () => {
  assert.deepEqual(hoyEnReinvent("2026-12-04"), [{ seccion: "Shuttles", texto: "6:30 a 13:00, servicio limitado: Venetian y Wynn/Encore." }]);
});

test("los días libres y fuera del viaje no tienen nada de re:Invent", () => {
  for (const fecha of ["2026-11-28", "2026-12-05", "2026-12-06", "2026-12-07"]) assert.deepEqual(hoyEnReinvent(fecha), [], fecha);
});

test("cada fecha de los ítems es AAAA-MM-DD y cae dentro de la estadía", () => {
  for (const s of SECCIONES) {
    for (const d of s.items.flatMap((i) => i.dias ?? [])) {
      assert.match(d, /^\d{4}-\d{2}-\d{2}$/, s.id);
      assert.ok(d >= "2026-11-29" && d <= "2026-12-07", `${s.id}: ${d}`);
    }
  }
});

// ---------- hora de Las Vegas en el grabador y en los pendientes ----------

test("«ahora en tu itinerario» del grabador usa la hora de Las Vegas, no la del celular", () => {
  // 17:15 en Buenos Aires (UTC−3) son las 12:15 en Las Vegas: la charla de las 12:00 está en curso.
  const dias = [{ day: "2026-12-01", sessions: [charla("M", "2026-12-01", "12:00", "13:00"), charla("N", "2026-12-01", "17:00", "18:00")] }];
  assert.deepEqual(codigos(cercaDeAhora(dias, new Date("2026-12-01T17:15:00-03:00"))), ["M"]);
  // A las 23:30 de Las Vegas ya es el 2/12 en UTC, pero sigue siendo el 1/12.
  assert.deepEqual(codigos(cercaDeAhora([{ day: "2026-12-01", sessions: [charla("Z", "2026-12-01", "23:45", "23:59")] }],
    new Date("2026-12-02T07:30:00Z"))), ["Z"]);
  assert.deepEqual(cercaDeAhora(undefined, vegas("2026-12-01")), []);
});

test("un pendiente vence según la fecha de Las Vegas", () => {
  const p = { fecha_limite: "2026-12-01", hecho: false };
  assert.equal(estaVencido(p, new Date("2026-12-02T05:00:00Z")), false);  // 21:00 del 1/12 en Las Vegas
  assert.equal(estaVencido(p, vegas("2026-12-02", "00:01")), true);
  assert.equal(estaVencido({ ...p, hecho: true }, vegas("2026-12-03")), false);
  assert.equal(estaVencido({ hecho: false }, vegas("2026-12-03")), false);
});
