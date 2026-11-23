// Documentos de viaje guardados en este teléfono para verlos sin señal: solo los que la persona elige, uno por uno.
// Van en IndexedDB cifrados con AES-GCM (WebCrypto) con una clave NO extraíble que también vive en IndexedDB: el
// archivo en claro no queda en el disco y la clave no se puede leer ni exportar desde JavaScript.
// Nunca pasan por la Cache API, el service worker ni lastgood. Se borran todos al cerrar sesión (api.js → setToken("")).
const DB_NOMBRE = "reinventar-documentos";
const DB_VERSION = 1;
const CLAVES = "claves";
const ARCHIVOS = "archivos";
const ID_CLAVE = "aes";
const LARGO_IV = 12;

const hayIndexedDb = () => typeof globalThis.indexedDB !== "undefined" && Boolean(globalThis.crypto?.subtle);

function pedido(req) {
  return new Promise((resolve, reject) => { req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); });
}

function abrir() {
  const req = indexedDB.open(DB_NOMBRE, DB_VERSION);
  req.onupgradeneeded = () => {
    const db = req.result;
    if (!db.objectStoreNames.contains(CLAVES)) db.createObjectStore(CLAVES);
    if (!db.objectStoreNames.contains(ARCHIVOS)) db.createObjectStore(ARCHIVOS, { keyPath: "id" });
  };
  return pedido(req);
}

async function conStore(nombre, modo, fn) {
  const db = await abrir();
  try {
    const tx = db.transaction(nombre, modo);
    const fin = new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error); });
    const resultado = await fn(tx.objectStore(nombre));
    await fin;
    return resultado;
  } finally { db.close(); }
}

/** La CryptoKey del teléfono (no extraíble); se crea la primera vez. */
async function clave() {
  const guardada = await conStore(CLAVES, "readonly", (s) => pedido(s.get(ID_CLAVE)));
  if (guardada) return guardada;
  const nueva = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  await conStore(CLAVES, "readwrite", (s) => pedido(s.put(nueva, ID_CLAVE)));
  return nueva;
}

const aad = (id) => new TextEncoder().encode(`documento:${id}`);

/** Guarda el archivo de un documento, cifrado. `sha256` es el que informa el servidor: dice si la copia quedó vieja. */
export async function guardarLocal(id, blob, { tipo, sha256 }) {
  if (!hayIndexedDb()) throw new Error("Este navegador no permite guardar documentos en el teléfono.");
  const iv = crypto.getRandomValues(new Uint8Array(LARGO_IV));
  const cifrado = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: aad(id) }, await clave(), await blob.arrayBuffer());
  await conStore(ARCHIVOS, "readwrite", (s) => pedido(s.put({ id, iv, cifrado, tipo, sha256, guardado: Date.now() })));
}

/** El archivo descifrado como Blob, o null si no está guardado en este teléfono. */
export async function leerLocal(id) {
  if (!hayIndexedDb()) return null;
  const fila = await conStore(ARCHIVOS, "readonly", (s) => pedido(s.get(id)));
  if (!fila) return null;
  const plano = await crypto.subtle.decrypt({ name: "AES-GCM", iv: fila.iv, additionalData: aad(id) }, await clave(), fila.cifrado);
  return new Blob([plano], { type: fila.tipo });
}

/** {id: sha256} de lo guardado en el teléfono (sin descifrar nada). */
export async function guardadosLocales() {
  if (!hayIndexedDb()) return {};
  try {
    const filas = await conStore(ARCHIVOS, "readonly", (s) => pedido(s.getAll()));
    return Object.fromEntries(filas.map((f) => [f.id, f.sha256]));
  } catch { return {}; }
}

export async function quitarLocal(id) {
  if (!hayIndexedDb()) return;
  await conStore(ARCHIVOS, "readwrite", (s) => pedido(s.delete(id)));
}

/** Borra la base entera (archivos y clave). Al cerrar sesión y con «Borrar todos mis documentos». */
export function borrarDocsLocales() {
  if (!hayIndexedDb()) return Promise.resolve();
  return new Promise((resolve) => {
    try {
      const req = indexedDB.deleteDatabase(DB_NOMBRE);
      req.onsuccess = req.onerror = req.onblocked = () => resolve();
    } catch { resolve(); }
  });
}
