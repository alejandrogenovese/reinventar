// Última copia buena de las pantallas que más se miran en los salones (Hoy, Itinerario, grabaciones), para mostrarla
// cuando no hay señal. Vive en localStorage de este celular, no en el service worker: la API nunca se cachea ahí.
// Cada copia es de quien tenía la sesión abierta (owner) y se borra al cerrar sesión (clearLast).
const PREFIX = "reinventar.last.";

const claveDe = (owner, path) => `${PREFIX}${owner}.${path}`;

/** Guarda la respuesta buena con la hora. Si no hay lugar o el almacenamiento está bloqueado, se sigue sin copia. */
export function saveLast(owner, path, data, now = Date.now()) {
  try { localStorage.setItem(claveDe(owner, path), JSON.stringify({ at: now, data })); } catch { /* sin copia: no pasa nada */ }
}

/** La copia guardada ({ at, data }) o null si no hay o está rota. */
export function loadLast(owner, path) {
  try {
    const copia = JSON.parse(localStorage.getItem(claveDe(owner, path)) ?? "null");
    return copia && Number.isFinite(copia.at) && copia.data != null ? copia : null;
  } catch { return null; }
}

/** Borra todas las copias (al cerrar sesión), sin tocar el resto de lo guardado. */
export function clearLast() {
  try {
    const claves = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i)).filter((k) => k?.startsWith(PREFIX));
    for (const k of claves) localStorage.removeItem(k);
  } catch { /* nada que borrar */ }
}

// Qué respuestas son una copia y de cuándo: se anota en un WeakMap para no cambiar la forma de los datos.
const copias = new WeakMap();
export const markStale = (data, at) => { if (data && typeof data === "object") copias.set(data, at); return data; };
/** Hora (ms) en que se guardaron estos datos si son una copia sin señal; null si vienen frescos del servidor. */
export const staleAt = (data) => (data && typeof data === "object" ? copias.get(data) ?? null : null);

export const sinSenalTexto = (at) =>
  `Sin señal · datos de las ${new Date(at).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
