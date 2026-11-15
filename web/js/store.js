// Cola local de pedazos de audio en IndexedDB: nada se borra hasta que el servidor confirma.
//
// Versiones del esquema:
//   1: almacén "chunks" con clave [session, part, seq] e índice "session".
//   2: se agregan los índices "at" (orden de subida: el más viejo primero) y "failed" (pedazos que el
//      servidor rechazó y no se reintentan solos). La migración conserva todo lo pendiente.
const DB = "reinventar", STORE = "chunks", VER = 2;
let dbp;

/**
 * Valor de "at" para un registro que no lo tiene (guardado por una versión muy vieja de la app).
 * Un registro sin "at" válido NO entra en el índice y no se subiría nunca, por eso la migración se lo
 * completa. Usa 0 + posición: queda antes que cualquier Date.now() real, o sea que se sube primero, y la
 * posición respeta el orden de la clave [session, part, seq] en que los recorre la migración.
 */
export function atFaltante(record, posicion) {
  return Number.isFinite(record.at) ? record.at : posicion;
}

function migrar(e, tx) {
  const db = e.target.result;
  const s = e.oldVersion < 1
    ? db.createObjectStore(STORE, { keyPath: ["session", "part", "seq"] })
    : tx.objectStore(STORE);
  if (!s.indexNames.contains("session")) s.createIndex("session", "session");
  if (!s.indexNames.contains("at")) s.createIndex("at", "at");
  if (!s.indexNames.contains("failed")) s.createIndex("failed", "failed");
  if (e.oldVersion < 1) return;
  // Completa "at" donde falte. Corre dentro de la transacción de la migración: si algo falla, se aborta
  // completa y la base queda en la versión 1 con todos los pedazos intactos.
  let n = 0;
  s.openCursor().onsuccess = (ev) => {
    const cur = ev.target.result;
    if (!cur) return;
    const at = atFaltante(cur.value, n++);
    if (at !== cur.value.at) cur.update({ ...cur.value, at });
    cur.continue();
  };
}

function open() {
  if (!dbp) dbp = new Promise((res, rej) => {
    const r = indexedDB.open(DB, VER);
    r.onupgradeneeded = (e) => migrar(e, r.transaction);
    r.onsuccess = () => {
      const db = r.result;
      // Otra pestaña con una versión más nueva quiere migrar: soltamos la conexión para no trabarla.
      db.onversionchange = () => { db.close(); dbp = null; };
      res(db);
    };
    r.onerror = () => { dbp = null; rej(r.error); };
    // Una pestaña vieja abierta frena la migración hasta que se cierre o recargue: queda a la espera.
    r.onblocked = () => console.warn("IndexedDB: hay otra pestaña de ReinventAR con la versión anterior abierta");
  });
  return dbp;
}

async function tx(mode, fn) {
  const db = await open();
  return new Promise((res, rej) => {
    const t = db.transaction(STORE, mode);
    const out = fn(t.objectStore(STORE));
    t.oncomplete = () => res(out?.result ?? out);
    t.onerror = () => rej(t.error);
    t.onabort = () => rej(t.error);
  });
}

export const putChunk = (c) => tx("readwrite", (s) => s.put({ ...c, at: Date.now() }));
export const deleteChunk = (session, part, seq) => tx("readwrite", (s) => s.delete([session, part, seq]));
export const allChunks = () => tx("readonly", (s) => s.getAll());
export const persist = async () => { try { return await navigator.storage?.persist?.(); } catch { return false; } };

/** El pedazo más viejo que se puede subir (salta los marcados como fallidos), o null si no hay. */
export async function nextChunk() {
  const db = await open();
  return new Promise((res, rej) => {
    const req = db.transaction(STORE, "readonly").objectStore(STORE).index("at").openCursor();
    req.onsuccess = () => {
      const cur = req.result;
      if (!cur) return res(null);
      if (cur.value.failed) return cur.continue();
      res(cur.value);
    };
    req.onerror = () => rej(req.error);
  });
}

/** Estado de la cola: cuántos esperan subir, cuántos quedaron fallidos y el motivo del primero. */
export async function queueStatus() {
  const db = await open();
  return new Promise((res, rej) => {
    const t = db.transaction(STORE, "readonly");
    const s = t.objectStore(STORE);
    const total = s.count(), failed = s.index("failed").count(), first = s.index("failed").openCursor();
    t.oncomplete = () => res({
      pending: total.result - failed.result, failed: failed.result, failedError: first.result?.value.error || null,
    });
    t.onerror = () => rej(t.error);
    t.onabort = () => rej(t.error);
  });
}

// Pedazos pendientes de una sesión (sin contar los fallidos, que no se van a subir solos).
export async function countFor(session) {
  const db = await open();
  return new Promise((res, rej) => {
    const t = db.transaction(STORE, "readonly");
    const s = t.objectStore(STORE);
    const total = s.index("session").count(session), failed = s.index("failed").getAllKeys();
    t.oncomplete = () => res(total.result - failed.result.filter((k) => k[0] === session).length);
    t.onerror = () => rej(t.error);
    t.onabort = () => rej(t.error);
  });
}

/** Cuántos pedazos fallidos tiene una sesión (los que el servidor rechazó). */
export async function failedFor(session) {
  // Solo claves primarias [session, part, seq]: no hace falta traer los blobs de audio para contar.
  const failed = await tx("readonly", (s) => s.index("failed").getAllKeys());
  return failed.filter((k) => k[0] === session).length;
}

/** Marca un pedazo como rechazado: queda en la cola (no se pierde el audio) pero no se reintenta solo. */
export const markFailed = (session, part, seq, error) => tx("readwrite", (s) => {
  const g = s.get([session, part, seq]);
  g.onsuccess = () => { if (g.result) s.put({ ...g.result, failed: 1, error }); };
});

/** Vuelve a poner los fallidos en la cola (acción manual del usuario). */
export const retryFailed = () => tx("readwrite", (s) => {
  s.index("failed").openCursor().onsuccess = (ev) => {
    const cur = ev.target.result;
    if (!cur) return;
    const { failed, error, ...rest } = cur.value; // eslint-disable-line no-unused-vars
    cur.update(rest);
    cur.continue();
  };
});

// Contador de partes y pedazos por sesión (sobrevive a una recarga de la página).
const META = "reinventar.rec.";
export function recMeta(id) { try { return JSON.parse(localStorage.getItem(META + id)) || { parts: {} }; } catch { return { parts: {} }; } }
export function saveRecMeta(id, m) { try { localStorage.setItem(META + id, JSON.stringify(m)); } catch {} }
export function dropRecMeta(id) { try { localStorage.removeItem(META + id); } catch {} }

/** Borra todos los pedazos de una sesión (descartar una grabación local que nunca llegó al servidor). */
export const deleteChunksOf = (session) => tx("readwrite", (s) => {
  s.index("session").openCursor(IDBKeyRange.only(session)).onsuccess = (ev) => {
    const cur = ev.target.result;
    if (!cur) return;
    cur.delete();
    cur.continue();
  };
});

// --- Sesiones locales: grabar sin señal ---------------------------------------------------------------------------
// Si no hay red al empezar, la grabación arranca con un id provisorio "loc_…" y los pedazos se guardan en IndexedDB
// con ese id. No se remapean: cuando vuelve la señal el uploader crea la sesión en el servidor, guarda el realId acá
// y sube cada pedazo a la sesión real (ver sesionRemota en recorder.js). Vive en localStorage junto a recMeta.
const LOCAL = "reinventar.sesion-local.";
const LOCAL_INDICE = "reinventar.sesiones-locales";
const ID_LOCAL = /^loc_[0-9a-f]{12}$/;
const ACTIVIDAD_RECIENTE_MS = 60_000;  // sin latido en este rato: la app se cerró o el celular se durmió
const LATIDO_CADA_MS = 5_000;
const ultimoLatido = new Map();

export const esLocal = (id) => typeof id === "string" && ID_LOCAL.test(id);
export function nuevoIdLocal() {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return "loc_" + [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function leer(clave, defecto) { try { return JSON.parse(localStorage.getItem(clave)) ?? defecto; } catch { return defecto; } }
function escribir(clave, valor) { try { localStorage.setItem(clave, JSON.stringify(valor)); return true; } catch { return false; } }
const idsLocales = () => leer(LOCAL_INDICE, []);

function guardarLocal(sesion) {
  if (!escribir(LOCAL + sesion.id, sesion)) throw new Error("No pude guardar la grabación en el celular: revisá el espacio disponible");
  const indice = idsLocales();
  if (!indice.includes(sesion.id)) escribir(LOCAL_INDICE, [...indice, sesion.id]);
  return sesion;
}
function actualizarLocal(id, cambios) {
  const actual = sesionLocal(id);
  return actual ? guardarLocal({ ...actual, ...cambios }) : null;
}

export const sesionLocal = (id) => (esLocal(id) ? leer(LOCAL + id, null) : null);
export function crearSesionLocal(meta) {
  const ahora = Date.now();
  return guardarLocal({ id: nuevoIdLocal(), meta: { ...meta }, creadaEn: ahora, latido: ahora, activa: false, realId: null, terminar: null, error: null });
}
export const marcarCreada = (id, realId) => actualizarLocal(id, { realId });
/** El usuario terminó la grabación: el uploader la cierra (finish) cuando suba todo y vuelva la señal. */
export const pedirTerminar = (id, parts) => actualizarLocal(id, { terminar: { parts: { ...parts }, intentos: 0 }, activa: false });
export function contarIntentoDeCierre(id) {
  const t = sesionLocal(id)?.terminar;
  return t ? actualizarLocal(id, { terminar: { ...t, intentos: t.intentos + 1 } }) : null;
}
export const marcarErrorLocal = (id, error) => actualizarLocal(id, { error });
/** Reintento manual: borra el error de las sesiones locales y les devuelve los intentos de cierre. */
export function reabrirCierres() {
  for (const id of idsLocales()) {
    const s = sesionLocal(id);
    if (s?.error || s?.terminar?.intentos) actualizarLocal(id, { error: null, terminar: s.terminar && { ...s.terminar, intentos: 0 } });
  }
  for (const id of idsReales()) {
    const s = terminarReal(id);
    if (s?.error || s?.terminar.intentos) actualizarReal(id, { error: null, terminar: { ...s.terminar, intentos: 0 } });
  }
}

// --- Cierre diferido de una sesión que ya existe en el servidor --------------------------------------------------------
// Si el usuario toca Terminar sin poder completarlo (sin red o con pedazos por subir), queda pedido el finish por id real
// (partes e intentos, como pedirTerminar) y lo cierra el uploader cuando la cola de esa sesión queda en cero.
const REAL = "reinventar.terminar-real.";
const REAL_INDICE = "reinventar.terminares-reales";
const idsReales = () => leer(REAL_INDICE, []);
export const terminarReal = (id) => leer(REAL + id, null);
export const terminaresReales = () => idsReales().map(terminarReal).filter(Boolean);
function guardarReal(s) {
  if (!escribir(REAL + s.id, s)) throw new Error("No pude guardar la grabación en el celular: revisá el espacio disponible");
  const indice = idsReales();
  if (!indice.includes(s.id)) escribir(REAL_INDICE, [...indice, s.id]);
  return s;
}
const actualizarReal = (id, cambios) => { const actual = terminarReal(id); return actual ? guardarReal({ ...actual, ...cambios }) : null; };
export const pedirTerminarReal = (id, parts, title) =>
  guardarReal({ id, title: title ?? "", creadaEn: Date.now(), terminar: { parts: { ...parts }, intentos: 0 }, error: null });
export function contarIntentoDeCierreReal(id) {
  const t = terminarReal(id)?.terminar;
  return t ? actualizarReal(id, { terminar: { ...t, intentos: t.intentos + 1 } }) : null;
}
export const marcarErrorReal = (id, error) => actualizarReal(id, { error });
export function quitarTerminarReal(id) {
  try { localStorage.removeItem(REAL + id); } catch {}
  escribir(REAL_INDICE, idsReales().filter((x) => x !== id));
  dropRecMeta(id);
}
export function idLocalDe(realId) { return idsLocales().find((id) => sesionLocal(id)?.realId === realId) || null; }

/** Latido de la grabación en curso (con tope de escrituras): distingue "grabando ahora" de "quedó a medias". */
export function registrarActividad(id, activa) {
  if (!esLocal(id)) return;
  const ahora = Date.now();
  if (activa && ahora - (ultimoLatido.get(id) ?? 0) < LATIDO_CADA_MS) return;
  ultimoLatido.set(id, activa ? ahora : 0);
  actualizarLocal(id, { activa, latido: ahora });
}

/** Saca la sesión local, su índice y su recMeta. Los pedazos se borran aparte (deleteChunksOf) o al subirse. */
export function quitarSesionLocal(id) {
  try { localStorage.removeItem(LOCAL + id); } catch {}
  escribir(LOCAL_INDICE, idsLocales().filter((x) => x !== id));
  dropRecMeta(id);
  ultimoLatido.delete(id);
}

/** Sesiones locales que todavía no terminaron de pasar al servidor (síncrono; lo usa el uploader). */
export function sesionesLocales() {
  const ahora = Date.now();
  return idsLocales().map(sesionLocal).filter(Boolean).map((s) => ({
    id: s.id, title: s.meta.title, realId: s.realId, error: s.error, creadaEn: s.creadaEn,
    estado: s.terminar ? "terminada" : s.activa && ahora - s.latido < ACTIVIDAD_RECIENTE_MS ? "grabando" : "pendiente",
  }));
}

const TITULO_POR_DEFECTO = "Grabación sin conexión";
const ESTADO_PUBLICO = { grabando: "grabando", pendiente: "pendiente_de_subir", terminada: "esperando_senal" };

/**
 * Para la lista de Inicio: las grabaciones que nacieron sin señal y todavía no terminaron de pasar al servidor.
 * Siempre un array (vacío si no hay), de la más reciente a la más vieja. `at` = ms de cuando se creó.
 * estado: "grabando" | "pendiente_de_subir" | "esperando_senal" (terminada, falta subir y cerrar).
 */
export async function sesionesLocalesPendientes() {
  const locales = sesionesLocales()
    .map((s) => ({ id: s.id, title: s.title?.trim() || TITULO_POR_DEFECTO, estado: ESTADO_PUBLICO[s.estado], at: s.creadaEn, realId: s.realId, error: s.error }));
  const reales = terminaresReales()
    .map((s) => ({ id: s.id, title: s.title?.trim() || TITULO_POR_DEFECTO, estado: ESTADO_PUBLICO.terminada, at: s.creadaEn, realId: s.id, error: s.error }));
  return [...locales, ...reales].sort((a, b) => b.at - a.at);
}
