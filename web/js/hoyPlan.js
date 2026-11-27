// Hoy calculado en el celular. Es la misma cuenta que app/today.py (plan), para cuando /api/today viene de la copia sin
// señal: esa copia dice qué pasaba cuando se guardó y, sin recalcular, mostraba como «Ahora» una charla que ya terminó
// (o la de otro día). Todo puro, sin DOM: lo dibuja today.js. Siempre en hora de Las Vegas (dia.js).
import { enVegas } from "./dia.js";

export const COLA_SIN_RESERVA_MIN = 30;   // charla solo por cola, walk-up (app/guided.py COLA_SIN_RESERVA)
export const COLA_SIN_LUGAR_MIN = 45;     // se reserva y no la tenés reservada: a ver si queda lugar (COLA_SIN_LUGAR)
const DURACION_POR_DEFECTO_MIN = 60;      // app/itinerary.py _DEFAULT_MINUTES
const MINUTOS_DIA = 24 * 60;

const dos = (n) => String(n).padStart(2, "0");
const minutos = (hhmm) => { const [h, m] = String(hhmm).split(":").map(Number); return h * 60 + m; };
/** HH:MM dando la vuelta al día (como app/leave.py: 00:05 menos 30 min da 23:35). */
const hora = (total) => { const t = ((total % MINUTOS_DIA) + MINUTOS_DIA) % MINUTOS_DIA; return `${dos(Math.floor(t / 60))}:${dos(t % 60)}`; };

/** La hora HH:MM que queda restando minutos a otra (para «cola desde las…» y «entrá antes de las…»). */
export const horaMenos = (hhmm, min) => hora(minutos(hhmm) - min);

/** Minutos antes del inicio en que hay que estar en la puerta (app/guided.py cola_min). */
export function colaMin(card) {
  if ((card?.kind ?? "talk") !== "talk" || card.reservada) return 0;
  return card.walk_in ? COLA_SIN_RESERVA_MIN : COLA_SIN_LUGAR_MIN;
}

/** La tarjeta con fin, la hora de la cola (charla sin reserva) y la de salida si eligió irse antes (app/today.py _with_end). */
export function conFin(card) {
  if (!card?.start) return card;
  const end = card.end || hora(minutos(card.start) + DURACION_POR_DEFECTO_MIN);
  const haceCola = (card.kind ?? "talk") === "talk" && !card.reservada;
  return {
    ...card, end,
    cola_desde: haceCola ? hora(minutos(card.start) - colaMin(card)) : null,
    salis_a: card.salir_antes ? hora(minutos(end) - card.salir_antes) : null,
  };
}

/** Si está pasando a este minuto del día. Lo que pasa la medianoche cuenta hasta el final del día (itinerary._span). */
export function enCurso(card, minuto) {
  const inicio = minutos(card.start);
  const fin = minutos(card.end);
  return inicio <= minuto && minuto < (fin > inicio ? fin : MINUTOS_DIA);
}

/**
 * Lo mismo que devuelve /api/today ({ date, time, now, next, later, upcoming }) a partir del itinerario
 * (`[{ day, sessions }]`, ordenado por día) y de `ahora` (Date), en hora de Las Vegas.
 */
export function planDeHoy(days, ahora) {
  const { fecha, hora: hhmm } = enVegas(ahora);
  const minuto = minutos(hhmm);
  const dias = Array.isArray(days) ? days : [];
  const deHoy = dias.filter((d) => d.day === fecha).flatMap((d) => d.sessions ?? []).filter((s) => s?.start).map(conFin);
  const actuales = deHoy.filter((s) => enCurso(s, minuto));
  const pendientes = deHoy.filter((s) => minutos(s.start) > minuto);
  let upcoming = null;
  if (!actuales.length && !pendientes.length) {
    const futuro = dias.find((d) => d.day > fecha && d.sessions?.length);
    if (futuro) upcoming = { day: futuro.day, first: conFin(futuro.sessions[0]) };
  }
  return { date: fecha, time: hhmm, now: actuales.at(-1) ?? null, next: pendientes[0] ?? null, later: pendientes.slice(1), upcoming };
}

const porInicio = (a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : 0);

/**
 * Hoy cuando /api/today vino de la copia sin señal (`copia`). Con el itinerario guardado (`itinerario`, la copia de
 * /api/itinerary) se recalcula todo. Sin él, si la copia es de hoy se recalcula con lo que trae (lo de ahora, lo que
 * sigue y lo de después); si es de otro día no se muestra nada como actual (sinItinerario: «mirá tu itinerario»).
 * Siempre lleva sinSenal: true.
 */
export function hoySinSenal(copia, itinerario, ahora) {
  if (Array.isArray(itinerario?.days)) return { ...planDeHoy(itinerario.days, ahora), sinSenal: true };
  const { fecha } = enVegas(ahora);
  if (copia?.date !== fecha) return { ...planDeHoy([], ahora), sinSenal: true, sinItinerario: true };
  const sesiones = [copia.now, copia.next, ...(copia.later ?? [])].filter((s) => s?.start).sort(porInicio);
  const plan = planDeHoy([{ day: fecha, sessions: sesiones }], ahora);
  return { ...plan, upcoming: plan.now || plan.next ? null : copia.upcoming ?? null, sinSenal: true };
}

/** Accesos de un día sin conferencia (rutas del router de app.js). */
export const ACCESOS_DIA_LIBRE = Object.freeze([
  Object.freeze({ texto: "Shows", href: "#/eventos/shows" }),
  Object.freeze({ texto: "Actividades", href: "#/actividades" }),
  Object.freeze({ texto: "Comer", href: "#/comer" }),
]);
const DIAS_LIBRES = new Set(["llegada", "despues"]);  // tipos de dia.js diaDeEvento sin charlas de re:Invent
const VER_ITINERARIO = Object.freeze({ texto: "Ver itinerario", href: "#/itinerario" });

/**
 * Qué decir cuando no hay nada ahora ni a continuación: { titulo?, texto, acciones: [{ texto, href }] }.
 * `tipoDia` es el tipo de diaDeEvento (llegada y después son días libres); `etiquetaDia(iso)` da «lunes, 30 nov».
 */
export function mensajeSinCharlas({ tipoDia = null, upcoming = null, sinItinerario = false, etiquetaDia = (d) => d }) {
  if (sinItinerario) return { texto: "Sin señal: mirá tu itinerario.", acciones: [] };
  const proxima = upcoming ? `La próxima es el ${etiquetaDia(upcoming.day)} a las ${upcoming.first.start}: ${upcoming.first.title}.` : "";
  if (DIAS_LIBRES.has(tipoDia)) {
    return { titulo: "Día libre", texto: proxima || "Hoy no hay re:Invent: aprovechá Las Vegas.", acciones: ACCESOS_DIA_LIBRE };
  }
  if (upcoming) return { texto: `No tenés más charlas hoy. ${proxima}`, acciones: [VER_ITINERARIO] };
  return { texto: "No tenés charlas en el itinerario para hoy.", acciones: [{ texto: "Armar itinerario", href: "#/itinerario" }] };
}
