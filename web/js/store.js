// Cola local de pedazos de audio en IndexedDB: nada se borra hasta que el servidor confirma.
const DB = "reinventar", STORE = "chunks", VER = 1;
let dbp;

function open() {
  if (!dbp) dbp = new Promise((res, rej) => {
    const r = indexedDB.open(DB, VER);
    r.onupgradeneeded = () => {
      const s = r.result.createObjectStore(STORE, { keyPath: ["session", "part", "seq"] });
      s.createIndex("session", "session");
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
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
export const countFor = (session) => tx("readonly", (s) => s.index("session").count(session));
export async function persist() { try { return await navigator.storage?.persist?.(); } catch { return false; } }

// Contador de partes y pedazos por sesión (sobrevive a una recarga de la página).
const META = "reinventar.rec.";
export function recMeta(id) { try { return JSON.parse(localStorage.getItem(META + id)) || { parts: {} }; } catch { return { parts: {} }; } }
export function saveRecMeta(id, m) { try { localStorage.setItem(META + id, JSON.stringify(m)); } catch {} }
export function dropRecMeta(id) { try { localStorage.removeItem(META + id); } catch {} }
