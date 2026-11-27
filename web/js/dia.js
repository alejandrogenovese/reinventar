// Franja del día de Inicio (no es un banner): en qué momento del viaje estás. Todo puro, sin DOM: la dibuja today.js.
// Las fechas son las de app/estadia.py (tests/test_estado_front.py verifica que coincidan): re:Invent del 30/11 al 4/12,
// estadía del domingo 29/11 al lunes 7/12 a las 13:00, siempre en hora de Las Vegas.
export const RANGO_REINVENT = {
  llegada: "2026-11-29", inicio: "2026-11-30", fin: "2026-12-04", salida: "2026-12-07", horaSalida: "13:00",
};
export const MARGEN_DIAS = 14;  // fuera de esto (antes de empezar o después de irse) la franja no se muestra
const TZ_VEGAS = "America/Los_Angeles";
const DIA_MS = 86_400_000;

/** Lo que dice la franja el día de salida, con el enlace a Viajes (vuelos y hotel). */
export const VUELTA = Object.freeze({ texto: "Hoy volvés · check-out y vuelo", href: "#/viajes" });

const DIAS = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];

/** Fecha («2026-12-01») y hora («08:05») de `ahora` en Las Vegas. */
export function enVegas(ahora) {
  const partes = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ_VEGAS, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(ahora).map((p) => [p.type, p.value]));
  return { fecha: `${partes.year}-${partes.month}-${partes.day}`, hora: `${partes.hour}:${partes.minute}` };
}

const utc = (fecha) => { const [y, m, d] = fecha.split("-").map(Number); return Date.UTC(y, m - 1, d); };
const diasEntre = (desde, hasta) => Math.round((utc(hasta) - utc(desde)) / DIA_MS);
const corta = (fecha) => { const [, m, d] = fecha.split("-").map(Number); return `${d}/${m}`; };
const diaSemana = (fecha) => DIAS[new Date(utc(fecha)).getUTCDay()];
/** «Martes 1/12». */
export const fechaLarga = (fecha) => `${diaSemana(fecha)} ${corta(fecha)}`;

/**
 * En qué momento del viaje cae `ahora` (Date). Devuelve null fuera del margen, o { tipo, titulo, detalles, dia, total }:
 * - antes: «Faltan 7 días para re:Invent» · «Llegás el domingo 29/11».
 * - llegada (29/11): «Domingo 29/11» · «Llegada» · «re:Invent arranca mañana».
 * - conferencia (30/11 a 4/12): «Martes 1/12», dia 2 de total 5 (la keynote y las charlas las suma quien dibuja).
 * - despues (5/12 y 6/12): «Sábado 5/12» · «re:Invent terminó» · «la estadía sigue hasta…».
 * - el día de salida (7/12): «Lunes 7/12» · «Hoy volvés · check-out y vuelo» (enlace a #/viajes); es despues hasta la
 *   hora de salida (13:00) y terminado después.
 * - terminado (después de irse, dentro del margen): «Martes 8/12» · «re:Invent terminó».
 */
export function diaDeEvento(ahora, rango = RANGO_REINVENT) {
  if (!(ahora instanceof Date) || Number.isNaN(ahora.getTime())) return null;
  const { fecha, hora } = enVegas(ahora);
  const total = diasEntre(rango.inicio, rango.fin) + 1;
  const faltan = diasEntre(fecha, rango.inicio);
  if (fecha < rango.llegada) {
    if (faltan > MARGEN_DIAS) return null;
    return { tipo: "antes", titulo: `${faltan === 1 ? "Falta 1 día" : `Faltan ${faltan} días`} para re:Invent`,
      detalles: [`Llegás el ${diaSemana(rango.llegada).toLowerCase()} ${corta(rango.llegada)}`] };
  }
  if (fecha < rango.inicio) {
    return { tipo: "llegada", titulo: fechaLarga(fecha),
      detalles: ["Llegada", faltan === 1 ? "re:Invent arranca mañana" : `re:Invent arranca en ${faltan} días`] };
  }
  if (fecha <= rango.fin) {
    return { tipo: "conferencia", titulo: fechaLarga(fecha), detalles: [], dia: diasEntre(rango.inicio, fecha) + 1, total };
  }
  if (fecha === rango.salida) {
    return { tipo: hora < rango.horaSalida ? "despues" : "terminado", titulo: fechaLarga(fecha), detalles: [], enlace: VUELTA };
  }
  const sigueLaEstadia = fecha < rango.salida;
  if (sigueLaEstadia) {
    return { tipo: "despues", titulo: fechaLarga(fecha), detalles: ["re:Invent terminó",
      `la estadía sigue hasta el ${diaSemana(rango.salida).toLowerCase()} ${corta(rango.salida)} a las ${rango.horaSalida}`] };
  }
  if (diasEntre(rango.salida, fecha) > MARGEN_DIAS) return null;
  return { tipo: "terminado", titulo: fechaLarga(fecha), detalles: ["re:Invent terminó"] };
}

// La hora sin el cero de adelante: «08:00» → «8:00».
const sinCero = (hhmm) => String(hhmm ?? "").replace(/^0(\d:)/, "$1");

/**
 * Lo que suma la franja en un día de conferencia: la keynote de hoy (de /api/anuncios: nivel 1) y cuántas charlas te
 * quedan hoy en la agenda (de /api/today: la de ahora, la que sigue y las de después). Lo que no llegó queda en null.
 */
export function resumenDelDia({ hoy = null, anuncios = null } = {}) {
  const keynote = anuncios?.is_today ? (anuncios.items ?? []).find((s) => s?.nivel === 1) : null;
  const charlas = hoy ? [hoy.now, hoy.next, ...(hoy.later ?? [])].filter((s) => s && (!s.kind || s.kind === "talk")).length : null;
  return {
    keynote: keynote ? { hora: sinCero(keynote.start), enVivo: Boolean(keynote.en_curso) } : null,
    charlas,
  };
}
