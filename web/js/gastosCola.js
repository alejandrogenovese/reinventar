// Gastos: cola sin señal en IndexedDB (gastos pendientes, fotos como Blob, metadatos) y la lógica pura que la rodea.
// Nada acá toca el DOM ni la red, así se prueba con node (tests/js/gastos.test.mjs). La pantalla y el sync están en gastos.js.

import { enVegas } from "./dia.js";

export const CATEGORIAS = ["comida", "transporte", "shows", "compras", "otros"];
export const MONEDAS = ["USD", "ARS"];
export const LADO_MAYOR_PX = 1600;   // la foto del ticket se achica a este lado mayor
export const CALIDAD_JPEG = 0.7;
export const TOPE_FOTO_BYTES = 2 * 1024 * 1024;

export const MONTO_MAX = 1_000_000_000;   // el tope del servidor (app/gastos.py): más es un error de tipeo
export const NOTA_MAX = 500;
const ANIO_MIN = 2000;
const ANIO_MAX = 2100;
const MIN_POR_HORA = 60;
const MIN_POR_DIA = 24 * 60;

const CAMPOS_DEL_CAMBIO = ["client_id", "fecha", "monto", "moneda", "categoria", "nota", "reintegrable", "compartido", "updated_at", "deleted_at"];

// ---------- lógica pura ----------

/** AAAA-MM-DD en hora de Las Vegas, donde se vive el viaje (no UTC ni la zona del celular, que puede seguir en Buenos
 *  Aires: un gasto a las 23 h de Las Vegas es de ese día). */
export function fechaLocal(fecha = new Date()) {
  return enVegas(fecha).fecha;
}

/** USD de un monto: los dólares tal cual; los pesos, con la cotización de tarjeta. Sin cotización, null. */
export function estimarUsd(monto, moneda, cotizacionTarjeta) {
  if (moneda === "USD") return monto;
  return cotizacionTarjeta > 0 ? monto / cotizacionTarjeta : null;
}

/** Con punto y coma a la vez, el que aparece último es el decimal («1.234,50» y «1,234.50» valen lo mismo). NaN si no cierra. */
function normalizarMixto(limpio) {
  const decimal = limpio.lastIndexOf(",") > limpio.lastIndexOf(".") ? "," : ".";
  const miles = decimal === "," ? "." : ",";
  const partes = limpio.split(decimal);
  if (partes.length !== 2 || partes[1].includes(miles)) return NaN;
  return `${partes[0].split(miles).join("")}.${partes[1]}`;
}

/** Lee un monto como se escribe en Argentina («1.234,50», «14,10», «19.150») o con punto decimal («14.10», «1,234.50»). NaN si no sirve. */
export function parsearMonto(texto) {
  const limpio = String(texto ?? "").replace(/\s/g, "");
  if (!/^\d[\d.,]*$/.test(limpio)) return NaN;
  let normal;
  if (limpio.includes(",") && limpio.includes(".")) {
    normal = normalizarMixto(limpio);
    if (typeof normal !== "string") return NaN;
  } else if (limpio.includes(",")) {
    if (limpio.split(",").length > 2) return NaN;
    normal = limpio.replace(",", ".");
  } else {
    const puntos = limpio.split(".");
    const esMiles = puntos.length > 2 || (puntos.length === 2 && puntos[1].length === 3);
    normal = esMiles ? limpio.replace(/\./g, "") : limpio;
  }
  const n = Number(normal);
  return Number.isFinite(n) && n > 0 && n <= MONTO_MAX ? n : NaN;
}

/** AAAA-MM-DD real y de un año razonable (el selector de fecha del celular deja escribir años de seis cifras). */
function fechaValida(texto) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(texto ?? ""));
  if (!m) return false;
  const [anio, mes, dia] = m.slice(1).map(Number);
  const f = new Date(Date.UTC(anio, mes - 1, dia));
  return anio >= ANIO_MIN && anio <= ANIO_MAX && f.getUTCFullYear() === anio && f.getUTCMonth() === mes - 1 && f.getUTCDate() === dia;
}

/** Lo que el servidor rechazaría: el motivo en castellano, o null si el gasto está bien. Se corre antes de guardar y antes de mandar. */
export function validarGasto(g) {
  if (!(Number.isFinite(g.monto) && g.monto > 0 && g.monto <= MONTO_MAX)) return "El monto tiene que ser mayor a cero y menor a mil millones.";
  if (!fechaValida(g.fecha)) return `La fecha no es válida (usá un año entre ${ANIO_MIN} y ${ANIO_MAX}).`;
  if (String(g.nota ?? "").length > NOTA_MAX) return `La nota pasa de ${NOTA_MAX} letras.`;
  if (!MONEDAS.includes(g.moneda) || !CATEGORIAS.includes(g.categoria)) return "La moneda o la categoría no es válida.";
  return null;
}

/** Aparta del lote los gastos que el servidor rechazaría seguro. Los borrados pasan: lo que importa es avisar que se borraron. */
export function separarInvalidos(lote) {
  const validos = [];
  const invalidos = [];
  for (const gasto of lote) {
    const error = gasto.deleted_at ? null : validarGasto(gasto);
    if (error) invalidos.push({ gasto, error }); else validos.push(gasto);
  }
  return { validos, invalidos };
}

/** ¿De quién es la cola guardada? Sin dueño se adopta al actual; con otro, se vacía (nunca se manda a la cuenta de otra persona). */
export function decidirDueno(guardado, actual) {
  if (!guardado) return { accion: "adoptar" };
  return { accion: guardado === actual ? "seguir" : "vaciar" };
}

/** «hace 5 min», «hace 3 h», «hace 2 días». null si no se sabe. */
export function textoEdad(minutos) {
  if (!Number.isFinite(minutos)) return null;
  if (minutos < 1) return "recién";
  if (minutos < MIN_POR_HORA) return `hace ${Math.round(minutos)} min`;
  if (minutos < MIN_POR_DIA) return `hace ${Math.round(minutos / MIN_POR_HORA)} h`;
  const dias = Math.round(minutos / MIN_POR_DIA);
  return `hace ${dias} ${dias === 1 ? "día" : "días"}`;
}

/** Minutos de antigüedad de la cotización: lo que dijo el servidor (`edad_min`) más lo que pasó desde que se bajó. null si no se sabe. */
export function edadCotizacion(cotiz, ahoraMs = Date.now()) {
  if (!Number.isFinite(cotiz?.edad_min)) return null;
  const pasado = Number.isFinite(cotiz.leido_en) ? Math.max(0, (ahoraMs - cotiz.leido_en) / 60_000) : 0;
  return cotiz.edad_min + pasado;
}

/** Junta por día respetando el orden de entrada (el agrupador nativo de Map no existe en iOS 16 ni 17.0 a 17.3). */
export function agruparPorDia(gastos) {
  const dias = new Map();
  for (const g of gastos) dias.set(g.fecha, [...(dias.get(g.fecha) ?? []), g]);
  return [...dias];
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

/** Editar vuelve a poner el gasto en la cola (aunque estuviera rechazado). Si cambia el monto o la moneda, el USD que calculó el
 * servidor ya no vale: se suelta y el total se estima con la cotización hasta el próximo sync. */
export function editarGasto(gasto, cambios, ahora = new Date().toISOString()) {
  const cambiaElUsd = ("monto" in cambios && cambios.monto !== gasto.monto) || ("moneda" in cambios && cambios.moneda !== gasto.moneda);
  return { ...gasto, ...cambios, ...(cambiaElUsd ? { monto_usd: null } : {}), updated_at: ahora, pendiente: true, rechazado: false, error: null };
}

export const borrarGasto = (gasto, ahora = new Date().toISOString()) =>
  ({ ...gasto, deleted_at: ahora, updated_at: ahora, pendiente: true, rechazado: false, error: null });

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

/** Qué guardar tras la respuesta de un /sync: los aplicados quedan sincronizados, los que perdieron el conflicto toman la versión del
 * servidor, lo nuevo se mezcla y los `rechazados` se marcan con su motivo (no se reintentan solos). Devuelve solo lo que cambió.
 * `locales` es el estado actual (client_id → gasto): se resuelve contra eso, no contra lo que se mandó. */
export function resolverRespuesta(lote, locales, r) {
  const enviados = new Map(lote.map((g) => [g.client_id, g]));
  const aplicados = new Set(r.aplicados ?? []);
  const motivos = new Map();
  for (const { client_id: id, error } of r.rechazados ?? []) {
    const destino = id ?? (lote.length === 1 ? lote[0].client_id : null);  // sin client_id solo se sabe cuál es si viajó uno solo
    if (destino) motivos.set(destino, error || "El servidor no aceptó este gasto.");
  }
  const cambiados = new Map();
  const actual = (id) => cambiados.get(id) ?? locales.get(id);
  const poner = (g) => { if (g) cambiados.set(g.client_id, g); };
  for (const id of aplicados) {
    const local = actual(id);
    if (local && enviados.has(id)) poner(marcarAplicado(local, enviados.get(id)));
  }
  for (const delServidor of r.cambios ?? []) {
    const local = actual(delServidor.client_id);
    const enviado = enviados.get(delServidor.client_id);
    poner(enviado && !aplicados.has(delServidor.client_id) ? reemplazarPerdido(local, enviado, delServidor) : mezclarServidor(local, delServidor));
  }
  for (const [id, error] of motivos) {
    const local = actual(id);
    const enviado = enviados.get(id);
    if (local && enviado && local.updated_at === enviado.updated_at) poner({ ...local, rechazado: true, error });  // si se editó mientras viajaba, manda la edición
  }
  return [...cambiados.values()];
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
    pedido.onsuccess = () => {
      const db = pedido.result;
      db.onclose = () => { conexion = null; };                       // iOS la cierra al pasar a segundo plano: la próxima vez se reabre
      db.onversionchange = () => { db.close(); conexion = null; };
      resolve(db);
    };
    pedido.onerror = () => { conexion = null; reject(pedido.error); };
  });
  return conexion;
}

/** Corre `operacion(store)` en una transacción y resuelve con el resultado del pedido que devuelve.
 * Si la conexión estaba cerrada (InvalidStateError), la reabre y reintenta una vez. */
async function enStore(nombre, modo, operacion, reintento = true) {
  const db = await abrir();
  let tx;
  try { tx = db.transaction(nombre, modo); } catch (e) {
    if (reintento && e?.name === "InvalidStateError") { conexion = null; return enStore(nombre, modo, operacion, false); }
    throw e;
  }
  return new Promise((resolve, reject) => {
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
/** Lo que falta mandar. Los rechazados quedan afuera: no se reintentan solos hasta que se editen. */
export const gastosPendientes = async () => (await listarGastos()).filter((g) => g.pendiente && !g.rechazado);

/** Lee todos los gastos y guarda lo que devuelve `resolver(todos)` en una sola transacción: nada se puede colar en el medio
 * (una edición hecha durante un sync no se pisa). `resolver` es síncrono. */
export const transaccionarGastos = (resolver) => enStore("gastos", "readwrite", (s) => {
  const pedido = s.getAll();
  pedido.onsuccess = () => { for (const g of resolver(pedido.result)) s.put(g); };
  return pedido;
});

/** Vacía gastos, fotos y metadatos (cambio de cuenta en el mismo celular). */
export async function vaciarCola() {
  for (const nombre of ["gastos", "fotos", "meta"]) await enStore(nombre, "readwrite", (s) => s.clear());
}

/** Al cerrar sesión: la base local es de esa persona y no se queda en el celular. */
export async function borrarBaseLocal() {
  try { (await conexion)?.close(); } catch { /* ya estaba cerrada */ }
  conexion = null;
  await new Promise((resolve) => {
    const pedido = indexedDB.deleteDatabase(DB_NOMBRE);
    pedido.onsuccess = pedido.onerror = pedido.onblocked = () => resolve();
  });
}

export const guardarFoto = (clientId, blob) => enStore("fotos", "readwrite", (s) => s.put({ client_id: clientId, blob, intentos: 0 }));
export const leerFoto = (clientId) => enStore("fotos", "readonly", (s) => s.get(clientId));
export const fotosPendientes = () => enStore("fotos", "readonly", (s) => s.getAll());
export const borrarFoto = (clientId) => enStore("fotos", "readwrite", (s) => s.delete(clientId));
export const contarIntentoFoto = (foto) => enStore("fotos", "readwrite", (s) => s.put({ ...foto, intentos: foto.intentos + 1 }));

export async function leerMeta(clave) { return (await enStore("meta", "readonly", (s) => s.get(clave)))?.valor ?? null; }
export const guardarMeta = (clave, valor) => enStore("meta", "readwrite", (s) => s.put({ clave, valor }));
