// Última copia buena de las pantallas que más se miran en los salones (Hoy, Itinerario, grabaciones), para mostrarla
// cuando no hay señal. Vive en localStorage de este celular, no en el service worker: la API nunca se cachea ahí.
// Cada copia es de quien tenía la sesión abierta (owner) y se borra al cerrar sesión (clearLast).
const PREFIX = "reinventar.last.";

// Lo único que se guarda: las tres pantallas previstas (lista cerrada, no una ruta cualquiera), de un dueño con forma de
// hash y con datos que sean un objeto o una lista y no pasen del tope. Todo lo demás se ignora, al guardar y al leer.
// «/api/me/sandbox» y «/api/me/cuenta» no son rutas del servidor: son las claves de las copias del modo prueba y de quién es
// la persona (usuario e is_admin) que trae /api/me.
const RUTAS_PERMITIDAS = new Set(["/api/today", "/api/itinerary", "/api/sessions", "/api/anuncios", "/api/me/sandbox", "/api/me/cuenta",
  "/api/viajes/documentos"]); // documentos: solo la lista de metadatos, nunca un archivo
const DUENO_VALIDO = /^[0-9a-f]{12}$/;
const MAX_BYTES = 2_000_000; // un itinerario grande pesa decenas de KB; el tope es para que no llene el almacenamiento

const claveDe = (owner, path) => (DUENO_VALIDO.test(owner) && RUTAS_PERMITIDAS.has(path) ? `${PREFIX}${owner}.${path}` : null);
const esDatoValido = (data) => data !== null && typeof data === "object"; // objeto o lista (un texto o un número no entra)
// JSON.parse deja «__proto__» como clave propia; si después alguien mezcla el objeto con otro (spread, merge) contamina
// el prototipo. Se descarta al leer, a cualquier profundidad.
const sinProto = (clave, valor) => (clave === "__proto__" ? undefined : valor);

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
    const copia = JSON.parse(localStorage.getItem(clave) ?? "null", sinProto);
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
export function markStale(data, at) {
  if (esDatoValido(data)) copias.set(data, at);
  return data;
}
/** Hora (ms) en que se guardaron estos datos si son una copia sin señal; null si vienen frescos del servidor. */
export const staleAt = (data) => (data && typeof data === "object" ? copias.get(data) ?? null : null);

/** «14:05»: la hora del celular, en 24 h. */
export const horaCorta = (ms) => new Date(ms).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", hour12: false });

// Última sincronización: cuándo subió bien un gasto o un pedazo de grabación. La muestran la hoja «Avisos» y «Todo subido».
const ULTIMA_SYNC = "reinventar.ultimaSync";

/** Anota que algo subió bien (lo llaman el uploader de grabaciones y el sync de gastos). Sin almacenamiento, no pasa nada. */
export function marcarUltimaSync(ahora = Date.now()) {
  try { localStorage.setItem(ULTIMA_SYNC, String(Math.trunc(ahora))); } catch { /* sin almacenamiento */ }
}

/** Hora (ms) de la última sincronización buena, o null si nunca hubo (o el valor guardado no es un número). */
export function leerUltimaSync() {
  try {
    const valor = Number(localStorage.getItem(ULTIMA_SYNC));
    return Number.isFinite(valor) && valor > 0 ? valor : null;
  } catch { return null; }
}
