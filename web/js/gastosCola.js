// Gastos: cola sin señal en IndexedDB (gastos pendientes, fotos como Blob, metadatos) y la lógica pura que la rodea.
// Nada acá toca el DOM ni la red, así se prueba con node (tests/js/gastos.test.mjs). La pantalla y el sync están en gastos.js.

export const CATEGORIAS = ["comida", "transporte", "shows", "compras", "otros"];
export const MONEDAS = ["USD", "ARS"];
export const LADO_MAYOR_PX = 1600;   // la foto del ticket se achica a este lado mayor
export const CALIDAD_JPEG = 0.7;
export const TOPE_FOTO_BYTES = 2 * 1024 * 1024;

const CAMPOS_DEL_CAMBIO = ["client_id", "fecha", "monto", "moneda", "categoria", "nota", "reintegrable", "compartido", "updated_at", "deleted_at"];

// ---------- lógica pura ----------

/** AAAA-MM-DD con el reloj local del celular (no UTC: un gasto a las 23 h es del día que se vive). */
export function fechaLocal(fecha = new Date()) {
  const dos = (n) => String(n).padStart(2, "0");
  return `${fecha.getFullYear()}-${dos(fecha.getMonth() + 1)}-${dos(fecha.getDate())}`;
}

/** USD de un monto: los dólares tal cual; los pesos, con la cotización de tarjeta. Sin cotización, null. */
export function estimarUsd(monto, moneda, cotizacionTarjeta) {
  if (moneda === "USD") return monto;
  return cotizacionTarjeta > 0 ? monto / cotizacionTarjeta : null;
}

/** Lee un monto como se escribe en Argentina («1.234,50», «14,10», «19.150») o con punto decimal («14.10»). NaN si no sirve. */
export function parsearMonto(texto) {
  const limpio = String(texto ?? "").replace(/\s/g, "");
  if (!/^\d[\d.,]*$/.test(limpio)) return NaN;
  let normal;
  if (limpio.includes(",")) {
    if (limpio.split(",").length > 2) return NaN;
    normal = limpio.replace(/\./g, "").replace(",", ".");
  } else {
    const puntos = limpio.split(".");
    const esMiles = puntos.length > 2 || (puntos.length === 2 && puntos[1].length === 3);
    normal = esMiles ? limpio.replace(/\./g, "") : limpio;
  }
  const n = Number(normal);
  return Number.isFinite(n) && n > 0 ? n : NaN;
}

/** Tamaño de la foto achicada: el lado mayor a `max`, sin deformar y sin agrandar. */
export function escalarLado(ancho, alto, max = LADO_MAYOR_PX) {
  const mayor = Math.max(ancho, alto);
  if (mayor <= max) return { ancho, alto };
  const razon = max / mayor;
  return { ancho: Math.round(ancho * razon), alto: Math.round(alto * razon) };
}

export const nuevoId = () => crypto.randomUUID();

export function crearGasto(datos, { ahora = new Date().toISOString(), id = nuevoId() } = {}) {
  return {
    client_id: id, fecha: datos.fecha, monto: datos.monto, moneda: datos.moneda, categoria: datos.categoria,
    nota: datos.nota ?? "", reintegrable: Boolean(datos.reintegrable), compartido: Boolean(datos.compartido),
    updated_at: ahora, deleted_at: null, pendiente: true,
  };
}

export const editarGasto = (gasto, cambios, ahora = new Date().toISOString()) => ({ ...gasto, ...cambios, updated_at: ahora, pendiente: true });

export const borrarGasto = (gasto, ahora = new Date().toISOString()) => ({ ...gasto, deleted_at: ahora, updated_at: ahora, pendiente: true });

/** Lo que viaja en POST /api/gastos/sync: solo los campos del contrato. */
export const aCambio = (gasto) => Object.fromEntries(CAMPOS_DEL_CAMBIO.map((k) => [k, gasto[k] ?? null]));

/** Tras un sync exitoso: queda sincronizado salvo que se haya editado mientras viajaba (entonces sigue pendiente). */
export const marcarAplicado = (actual, enviado) => (actual.updated_at === enviado.updated_at ? { ...actual, pendiente: false } : actual);

/** Qué guardar cuando el servidor devuelve un gasto: null si lo local manda (pendiente o más nuevo). */
export function mezclarServidor(local, servidor) {
  // Empate = el eco de lo que acabamos de mandar: se toma, porque trae lo que calculó el servidor (monto_usd, cotizaciones).
  if (local && (local.pendiente || Date.parse(local.updated_at) > Date.parse(servidor.updated_at))) return null;
  return { ...servidor, pendiente: false };
}

/** Un gasto que perdió el conflicto: el servidor no lo da por aplicado y devuelve su versión en `cambios`, que reemplaza
 * a la local. Si se editó mientras viajaba el sync (updated_at distinto del enviado), manda la edición y va en el próximo. */
export function reemplazarPerdido(local, enviado, servidor) {
  if (!local || local.updated_at !== enviado.updated_at) return null;
  return { ...servidor, pendiente: false };
}

export function partirEnLotes(lista, tamano) {
  const lotes = [];
  for (let i = 0; i < lista.length; i += tamano) lotes.push(lista.slice(i, i + tamano));
  return lotes;
}

/** Los que se ven en la lista: sin borrados, por día y hora de carga, lo más nuevo primero. */
export const visibles = (gastos) => gastos.filter((g) => !g.deleted_at)
  .sort((a, b) => String(b.fecha).localeCompare(String(a.fecha)) || String(b.updated_at).localeCompare(String(a.updated_at)));

/** USD de un gasto: el que calculó el servidor o, sin respuesta todavía, la estimación con la tarjeta. */
export const usdDe = (gasto, tarjeta) => gasto.monto_usd ?? estimarUsd(gasto.monto, gasto.moneda, tarjeta);

/** Suma por total, categoría y día. Los pesos sin cotización no suman y se cuentan aparte. */
export function totales(gastos, tarjeta) {
  const salida = { usd: 0, porCategoria: {}, porDia: {}, sinCotizacion: 0 };
  for (const g of gastos) {
    if (g.deleted_at) continue;
    const usd = usdDe(g, tarjeta);
    if (usd == null) { salida.sinCotizacion += 1; continue; }
    salida.usd += usd;
    salida.porCategoria[g.categoria] = (salida.porCategoria[g.categoria] ?? 0) + usd;
    salida.porDia[g.fecha] = (salida.porDia[g.fecha] ?? 0) + usd;
  }
  return salida;
}

// ---------- IndexedDB ----------

const DB_NOMBRE = "reinventar-gastos";
const DB_VERSION = 1;
let conexion = null;

function abrir() {
  conexion ??= new Promise((resolve, reject) => {
    const pedido = indexedDB.open(DB_NOMBRE, DB_VERSION);
    pedido.onupgradeneeded = () => {
      const db = pedido.result;
      db.createObjectStore("gastos", { keyPath: "client_id" });
      db.createObjectStore("fotos", { keyPath: "client_id" });
      db.createObjectStore("meta", { keyPath: "clave" });
    };
    pedido.onsuccess = () => resolve(pedido.result);
    pedido.onerror = () => { conexion = null; reject(pedido.error); };
  });
  return conexion;
}

/** Corre `operacion(store)` en una transacción y resuelve con el resultado del pedido que devuelve. */
async function enStore(nombre, modo, operacion) {
  const db = await abrir();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(nombre, modo);
    const pedido = operacion(tx.objectStore(nombre));
    tx.oncomplete = () => resolve(pedido?.result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

export const listarGastos = () => enStore("gastos", "readonly", (s) => s.getAll());
export const leerGasto = (id) => enStore("gastos", "readonly", (s) => s.get(id));
export const guardarGasto = (gasto) => enStore("gastos", "readwrite", (s) => s.put(gasto));
export const guardarGastos = (gastos) => enStore("gastos", "readwrite", (s) => { for (const g of gastos) s.put(g); });
export const gastosPendientes = async () => (await listarGastos()).filter((g) => g.pendiente);

export const guardarFoto = (clientId, blob) => enStore("fotos", "readwrite", (s) => s.put({ client_id: clientId, blob, intentos: 0 }));
export const leerFoto = (clientId) => enStore("fotos", "readonly", (s) => s.get(clientId));
export const fotosPendientes = () => enStore("fotos", "readonly", (s) => s.getAll());
export const borrarFoto = (clientId) => enStore("fotos", "readwrite", (s) => s.delete(clientId));
export const contarIntentoFoto = (foto) => enStore("fotos", "readwrite", (s) => s.put({ ...foto, intentos: foto.intentos + 1 }));

export async function leerMeta(clave) { return (await enStore("meta", "readonly", (s) => s.get(clave)))?.valor ?? null; }
export const guardarMeta = (clave, valor) => enStore("meta", "readwrite", (s) => s.put({ clave, valor }));
