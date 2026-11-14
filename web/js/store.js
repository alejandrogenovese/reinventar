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
