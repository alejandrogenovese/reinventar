// Última copia buena de las pantallas que más se miran en los salones (Hoy, Itinerario, grabaciones), para mostrarla
// cuando no hay señal. Vive en localStorage de este celular, no en el service worker: la API nunca se cachea ahí.
// Cada copia es de quien tenía la sesión abierta (owner) y se borra al cerrar sesión (clearLast).
const PREFIX = "reinventar.last.";

// Lo único que se guarda: las tres pantallas previstas (lista cerrada, no una ruta cualquiera), de un dueño con forma de
// hash y con datos que sean un objeto o una lista y no pasen del tope. Todo lo demás se ignora, al guardar y al leer.
const RUTAS_PERMITIDAS = new Set(["/api/today", "/api/itinerary", "/api/sessions"]);
const DUENO_VALIDO = /^[0-9a-f]{12}$/;
const MAX_BYTES = 2_000_000; // un itinerario grande pesa decenas de KB; el tope es para que no llene el almacenamiento

const claveDe = (owner, path) => (DUENO_VALIDO.test(owner) && RUTAS_PERMITIDAS.has(path) ? `${PREFIX}${owner}.${path}` : null);
const esDatoValido = (data) => data !== null && typeof data === "object"; // objeto o lista (un texto o un número no entra)

/** Guarda la respuesta buena con la hora. Si no es válida, no hay lugar o el almacenamiento está bloqueado, se sigue sin copia. */
export function saveLast(owner, path, data, now = Date.now()) {
  const clave = claveDe(owner, path);
  if (!clave || !esDatoValido(data) || !Number.isFinite(now)) return;
  try {
    const texto = JSON.stringify({ at: Math.trunc(now), data });
    if (texto.length <= MAX_BYTES) localStorage.setItem(clave, texto);
  } catch { /* sin copia: no pasa nada */ }
}

/** La copia guardada ({ at, data }) o null si no hay, está rota o no tiene la forma esperada. */
export function loadLast(owner, path) {
  const clave = claveDe(owner, path);
  if (!clave) return null;
  try {
    const copia = JSON.parse(localStorage.getItem(clave) ?? "null");
    return esDatoValido(copia) && Number.isFinite(copia.at) && esDatoValido(copia.data) ? { at: copia.at, data: copia.data } : null;
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
