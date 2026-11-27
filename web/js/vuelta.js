// La vuelta desde Las Vegas: a qué hora salir del hotel para el vuelo que sale de LAS y a qué terminal pedir el auto.
// Lógica pura (sin DOM ni red): la usa la tarjeta del vuelo (viajes.js). El servidor hace la misma cuenta para «Próximo»
// (app/vuelta.py); tests/test_vuelta.py verifica que las constantes coincidan.
//
// Fuentes (consultadas el 26/11/2026):
// - Anticipación: «Please arrive at least 2 hours before your scheduled departure» (doméstico) y «at least 3 hours» (internacional),
//   https://www.harryreidairport.com/get-ready-for-your-flight
// - Terminal por aerolínea: https://www.harryreidairport.com/flights/airlines (T1: American, Delta, Southwest, Allegiant,
//   Sun Country; T3: United, Copa, Aeroméxico, entre otras). LATAM y Aerolíneas Argentinas no vuelan a LAS.
// - Traslado: ~25 min desde el Strip es una estimación propia (sin tránsito pesado), no un dato oficial.

export const ZONA_LAS_VEGAS = "America/Los_Angeles";
export const ANTICIPACION_INTERNACIONAL_MIN = 180;
export const ANTICIPACION_DOMESTICO_MIN = 120;
export const TRASLADO_STRIP_MIN = 25;

// Aeropuertos de EE. UU. por donde suele pasar la vuelta a la Argentina: con destino en uno de estos el vuelo es
// doméstico. Cualquier otro destino, o uno desconocido, cuenta como internacional (3 h: mejor de más que de menos).
export const AEROPUERTOS_EEUU = Object.freeze(["ATL", "BOS", "CLT", "DEN", "DFW", "DTW", "EWR", "IAD", "IAH", "JFK",
  "LAX", "MCO", "MIA", "MSP", "ORD", "PHX", "SAN", "SEA", "SFO", "SLC"]);

// Código IATA de la aerolínea → zona de rideshare de su terminal en LAS (claves de ZONAS en rideshare.js).
export const TERMINAL_POR_AEROLINEA = Object.freeze({
  AA: "lasT1", DL: "lasT1", WN: "lasT1", G4: "lasT1", SY: "lasT1",
  UA: "lasT3", CM: "lasT3", AM: "lasT3",
});

const MS_POR_MIN = 60_000;

/** true si el vuelo sale de Las Vegas: zona del Pacífico y la ciudad elegida es Las Vegas (Los Ángeles comparte zona). */
export function saleDeLasVegas(v) {
  return v?.zona === ZONA_LAS_VEGAS && /las vegas/i.test(v.zona_nombre ?? "");
}

/** true si el destino no es un aeropuerto de EE. UU. conocido (o no se sabe a dónde va). */
export function esInternacional(v) {
  const destino = String(v?.destino_iata ?? "").toUpperCase();
  return !AEROPUERTOS_EEUU.includes(destino);
}

/** Minutos de anticipación en el aeropuerto: 3 h internacional, 2 h doméstico. */
export function anticipacionMin(v) {
  return esInternacional(v) ? ANTICIPACION_INTERNACIONAL_MIN : ANTICIPACION_DOMESTICO_MIN;
}

/** «YYYY-MM-DDTHH:MM» (hora local de la salida) menos `min` minutos, en el mismo formato. null si no es una fecha. */
export function restarMinutos(local, min) {
  if (typeof local !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(local)) return null;
  const ms = Date.parse(`${local.slice(0, 16)}:00Z`); // se trata como UTC: es aritmética de reloj, sin zona
  return Number.isNaN(ms) ? null : new Date(ms - min * MS_POR_MIN).toISOString().slice(0, 16);
}

/**
 * Cuándo salir del hotel para un vuelo que sale de Las Vegas: { hora: "HH:MM", local: "YYYY-MM-DDTHH:MM",
 * anticipacionMin, internacional }. null si el vuelo no sale de Las Vegas, no tiene hora o está cancelado.
 */
export function salirAlAeropuerto(v) {
  if (!saleDeLasVegas(v) || !v.salida || (v.estado || "").toLowerCase().startsWith("cancel")) return null;
  const anticipacion = anticipacionMin(v);
  const local = restarMinutos(v.salida, anticipacion + TRASLADO_STRIP_MIN);
  if (!local) return null;
  return { hora: local.slice(11, 16), local, anticipacionMin: anticipacion, internacional: esInternacional(v) };
}

/** Zona de rideshare de la terminal de salida: la que informó AeroDataBox o, si no, la de la aerolínea. null si no se sabe. */
export function terminalDeSalida(v) {
  const n = String(v?.terminal ?? "").replace(/\D/g, "");
  if (n === "1") return "lasT1";
  if (n === "3") return "lasT3";
  return TERMINAL_POR_AEROLINEA[String(v?.numero ?? "").slice(0, 2).toUpperCase()] ?? null;
}
