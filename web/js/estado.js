// Banner de estado: qué avisos mostrar y en qué orden (demos/diseno/banner-status.html). Todo acá es puro, sin DOM ni
// almacenamiento: lo dibuja y lo alimenta estadoBanner.js. Se muestra un aviso por vez, el de mayor prioridad; el resto
// queda en la hoja «Avisos» (botón «+N»).
import { horaCorta } from "./lastgood.js";

// Prioridad (1 es la más alta), según la tabla del mock.
// «Próximo» (vuelo, hotel o charla) es lo último: nunca tapa un aviso de servicio, de señal ni de versión.
export const PRIORIDAD = { sinSenal: 1, caido: 2, fallidos: 3, subiendo: 4, demorado: 5, version: 6, listo: 7, proximo: 8 };
// Con «Salí ya» (countdown urgente) solo se muestran las prioridades 1 a 3.
export const PRIORIDAD_MAXIMA_URGENTE = 3;
export const CIERRE_SERVICIO_MS = 6 * 3_600_000;  // un aviso de servicio cerrado vuelve a las 6 h (o antes si cambia el nivel)
export const TODO_SUBIDO_MS = 5_000;              // «Todo subido» se va solo: es una confirmación

const RUTA_GRABAR = "#/grabar/";  // ahí no se ofrece actualizar: recargar cortaría la grabación

// Cómo se cierra cada aviso: «6h» (servicio), «sesion» (hasta la próxima vez que se abra la app), «siempre» (no vuelve).
export const CIERRE = { seisHoras: "6h", sesion: "sesion", siempre: "siempre" };

const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
const dato = (texto) => ({ dato: String(texto) });
const total = ({ grabaciones = 0, gastos = 0 } = {}) => grabaciones + gastos;

/** «2 grabaciones y 3 gastos» (lo que haya); "" si no hay nada. */
export function contarCosas({ grabaciones = 0, gastos = 0 } = {}) {
  const partes = [grabaciones ? plural(grabaciones, "grabación", "grabaciones") : null, gastos ? plural(gastos, "gasto", "gastos") : null];
  return partes.filter(Boolean).join(" y ");
}

/** -1, 0 o 1 comparando dos versiones «1.2.3». Lo que no es una versión cuenta como 0.0.0. */
export function compararVersiones(a, b) {
  const partes = (v) => (/^\d+\.\d+\.\d+$/.test(String(v ?? "")) ? String(v).split(".").map(Number) : [0, 0, 0]);
  const [x, y] = [partes(a), partes(b)];
  for (let i = 0; i < 3; i += 1) if (x[i] !== y[i]) return x[i] > y[i] ? 1 : -1;
  return 0;
}

// ---------- servicio (lo informa el servidor en /api/estado) ----------

// Sin jerga («LLM», «LiteLLM», «Langfuse»): qué no anda y qué sí. transcripcion y resumenes pueden estar caídos o demorados;
// eventos y catalogo, solo atrasados (cualquier nivel suyo se muestra como atrasado).
const SERVICIO = {
  transcripcion: {
    caido: { icono: "error", titulo: "Las transcripciones no andan por ahora.",
      detalle: "Tus grabaciones quedan guardadas y se transcriben cuando vuelva.", nombre: "transcripciones caídas" },
    demorado: { icono: "reloj", titulo: "Las transcripciones vienen con demora.",
      detalle: "Tus grabaciones están guardadas y se procesan solas.", nombre: "transcripciones con demora" },
  },
  resumenes: {
    caido: { icono: "error", titulo: "Los resúmenes y Preguntar no andan por ahora.",
      detalle: "Grabar y transcribir siguen funcionando.", nombre: "resúmenes y Preguntar caídos" },
    demorado: { icono: "reloj", titulo: "Los resúmenes y Preguntar vienen con demora.",
      detalle: "Grabar y transcribir siguen funcionando.", nombre: "resúmenes y Preguntar con demora" },
  },
  eventos: { atrasado: { icono: "alerta", titulo: "Eventos y shows pueden estar desactualizados.", nombre: "eventos desactualizados" } },
  catalogo: { atrasado: { icono: "alerta", titulo: "Los cambios de AWS en las charlas pueden tardar en aparecer.", nombre: "charlas desactualizadas" } },
};
const NIVELES = new Set(["caido", "demorado", "atrasado"]);

const detalleHoras = (horas) => (Number.isInteger(horas) && horas > 0 ? `La última revisión fue hace ${horas} h.` : null);

/** El aviso de un elemento de `servicio`, o null si no se conoce (un id o un nivel raros no rompen nada). */
export function avisoDeServicio(s) {
  const copias = SERVICIO[s?.id];
  if (!copias || !NIVELES.has(s.nivel)) return null;
  const atrasable = "atrasado" in copias;
  const clave = atrasable ? "atrasado" : s.nivel === "caido" ? "caido" : "demorado";
  const c = copias[clave];
  const caido = clave === "caido";
  const detalle = atrasable ? detalleHoras(s.detalle_horas) : c.detalle;
  return {
    id: `servicio:${s.id}:${s.nivel}`,  // con el nivel: si cambia, el cierre anterior ya no aplica
    prioridad: caido ? PRIORIDAD.caido : PRIORIDAD.demorado,
    tono: caido ? "error" : "warn",
    icono: c.icono,
    titulo: [c.titulo],
    detalle,
    accion: atrasable ? null : { texto: "Ver estado", tipo: "avisos" },
    cierre: CIERRE.seisHoras,
    nombre: c.nombre,
    hoja: { titulo: c.titulo.replace(/\.$/, ""), texto: detalle ?? "Se revisan solos cada tanto. No hace falta hacer nada." },
  };
}

// ---------- cada aviso ----------

function avisoSinSenal({ pendientes, datosDe }) {
  const n = total(pendientes);
  const detalle = n ? `${contarCosas(pendientes)} ${n === 1 ? "espera" : "esperan"} subirse.` : "Lo que hagas se guarda en el celular.";
  const destino = pendientes?.grabaciones ? "#/" : "#/gastos";  // Inicio › «Grabadas en este celular», o Gastos si solo hay gastos
  const titulo = datosDe ? `Sin señal · datos de las ${horaCorta(datosDe)}` : "Sin señal";
  return {
    id: "sin-senal", prioridad: PRIORIDAD.sinSenal, tono: "warn", icono: "sinsenal",
    titulo: datosDe ? ["Sin señal · datos de las ", dato(horaCorta(datosDe)), "."] : ["Sin señal."],
    detalle,
    accion: n ? { texto: "Ver pendientes", tipo: "ir", destino } : null,
    cierre: null,
    hoja: { titulo, texto: n ? `${detalle} Se suben solos cuando vuelva la red.` : detalle },
  };
}

function avisoFallidos(fallidos) {
  const n = total(fallidos);
  const titulo = `${contarCosas(fallidos)} no se ${n === 1 ? "pudo" : "pudieron"} subir.`;
  return {
    id: "fallidos", prioridad: PRIORIDAD.fallidos, tono: "error", icono: "error",
    titulo: [titulo], detalle: "Siguen guardados en este celular.",
    accion: { texto: "Reintentar", tipo: "reintentar" }, cierre: null,
    hoja: { titulo: titulo.replace(/\.$/, ""), texto: "Siguen guardados en este celular. «Reintentar» vuelve a mandarlos." },
  };
}

function avisoSubiendo({ hechos, total: n, que }) {
  return {
    id: "subiendo", prioridad: PRIORIDAD.subiendo, tono: "info", icono: "subir", gira: true,
    titulo: ["Volvió la señal · subiendo ", dato(`${hechos} de ${n}`)], detalle: que ? `(${que})` : null, accion: null, cierre: null,
    hoja: { titulo: `Subiendo ${hechos} de ${n}`, texto: "Volvió la señal: lo guardado en el celular se está subiendo." },
  };
}

function avisoVersion({ versionRemota, online }) {
  return {
    id: `version:${versionRemota}`, prioridad: PRIORIDAD.version, tono: "neutro", icono: "nuevo",
    titulo: ["Hay una versión nueva ", dato(versionRemota)], detalle: null,
    accion: { texto: "Ver novedades", tipo: "novedades" }, cierre: CIERRE.sesion, nombre: "versión nueva",
    hoja: { titulo: `Hay una versión nueva (${versionRemota})`,
      texto: online ? "Mirá qué trae y actualizá cuando quieras." : "Se instala cuando vuelva la señal y recargues." },
  };
}

function avisoTodoSubido(hora) {
  return {
    id: "todo-subido", prioridad: PRIORIDAD.listo, tono: "ok", icono: "ok",
    titulo: ["Todo subido ", { detalle: "· última sincronización " }, dato(horaCorta(hora))], detalle: null, accion: null, cierre: null,
    hoja: { titulo: "Todo subido", texto: `Última sincronización: ${horaCorta(hora)}.` },
  };
}

function avisoActualizada(version) {
  return {
    id: `actualizada:${version}`, prioridad: PRIORIDAD.listo, tono: "neutro", icono: "ok",
    titulo: ["Actualizada a ", dato(version)], detalle: null,
    accion: { texto: "Qué cambió", tipo: "que-cambio" }, cierre: CIERRE.siempre, nombre: "actualizada",
    hoja: { titulo: `Actualizada a ${version}`, texto: "«Qué cambió» muestra las novedades de esta versión." },
  };
}

// ---------- «Próximo» (/api/viajes/proximo, app/proximo.py) ----------

const TIPOS_PROXIMO = { vuelo: ["viaje", "Ver vuelo"], hotel: ["viaje", "Ver hotel"], charla: ["reloj", "Ver"] };
const texto = (x) => (typeof x === "string" && x.trim() ? x.trim() : null);

/**
 * El aviso de lo próximo, o null si no hay, vino con una forma rara o ya empezó (`inicio`, ISO, ya pasó: la respuesta
 * puede tener hasta 5 min). Vuelo: «Próximo: UA1355 a Houston · sale 13:05 (+20 min) · puerta D12»; hotel y charla:
 * «Próximo: {título} · 14:30 · {sala}». Se omite lo que falte. El destino solo puede ser una ruta de la app (#/…).
 */
export function avisoProximo(p, ahora) {
  const tipo = TIPOS_PROXIMO[p?.tipo] ? p.tipo : null;
  const titulo = texto(p?.titulo);
  if (!tipo || !titulo) return null;
  const inicio = Date.parse(p.inicio ?? "");
  if (Number.isFinite(inicio) && Number.isFinite(ahora) && inicio <= ahora) return null;
  const hora = texto(p.hora);
  const detalle = texto(p.detalle);
  const cancelado = tipo === "vuelo" && p.cancelado === true;
  const demora = tipo === "vuelo" && Number.isInteger(p.demora_min) && p.demora_min > 0 ? ` (+${p.demora_min} min)` : "";
  const conHora = hora ? (tipo === "vuelo" ? [" · sale ", dato(hora), demora] : [" · ", dato(hora)]) : [];
  const partes = cancelado ? [" · cancelado"] : [...conHora, detalle ? ` · ${detalle}` : ""].filter((x) => x !== "");
  const plano = partes.map((x) => (typeof x === "string" ? x : x.dato)).join("");
  const [icono, verTexto] = TIPOS_PROXIMO[tipo];
  const destino = typeof p.url === "string" && p.url.startsWith("#/") ? p.url : null;
  return {
    id: `proximo:${tipo}:${destino ?? titulo}:${p.inicio ?? ""}`,  // con el inicio: si cambia lo próximo, vuelve a aparecer
    prioridad: PRIORIDAD.proximo, tono: cancelado ? "error" : "info", icono: cancelado ? "error" : icono,
    titulo: ["Próximo: ", titulo, ...partes], detalle: null,
    accion: destino ? { texto: verTexto, tipo: "ir", destino } : null,
    cierre: CIERRE.sesion, nombre: "próximo",
    hoja: { titulo: `Próximo: ${titulo}`, texto: plano.replace(/^ · /, "") || "Empieza pronto." },
  };
}

/**
 * Los avisos a mostrar, del más importante al menos. Entrada (todo opcional salvo `ahora`, en ms):
 * - online: hay red y la API contesta (false también cuando una pantalla cayó a la última copia).
 * - pendientes { grabaciones, gastos }: lo que espera subirse. fallidos { grabaciones, gastos }: lo que falló con red.
 * - subiendo { hechos, total, que } | null: la subida en curso al volver la señal. subidoEn: cuándo terminó (ms) o null.
 * - servicio: la lista de /api/estado. versionLocal / versionRemota. actualizadaA: versión recién instalada o null.
 * - descartados { id: hasta (ms; Infinity = no vuelve) }. ruta: location.hash. countdownUrgente: «Salí ya» a la vista.
 * - datosDe: hora (ms) de la última copia que se está mostrando. ultimaSync: hora (ms) de la última subida buena.
 * - proximo: lo de /api/viajes/proximo (o null): siempre va último.
 */
export function elegirAvisos({
  online = true, pendientes = {}, subiendo = null, subidoEn = null, fallidos = {}, servicio = [], versionLocal = null,
  versionRemota = null, actualizadaA = null, descartados = {}, ruta = "", countdownUrgente = false, datosDe = null,
  ultimaSync = null, proximo = null, ahora,
}) {
  const avisos = [];
  if (!online) avisos.push(avisoSinSenal({ pendientes, datosDe }));
  for (const s of Array.isArray(servicio) ? servicio : []) {
    const a = avisoDeServicio(s);
    if (a && !avisos.some((b) => b.id === a.id)) avisos.push(a);
  }
  if (online && total(fallidos)) avisos.push(avisoFallidos(fallidos));
  if (online && subiendo?.total > 0) avisos.push(avisoSubiendo(subiendo));
  const enGrabar = String(ruta ?? "").startsWith(RUTA_GRABAR);
  if (versionRemota && compararVersiones(versionRemota, versionLocal) > 0 && !enGrabar) avisos.push(avisoVersion({ versionRemota, online }));
  if (online && !subiendo && Number.isFinite(subidoEn) && ahora - subidoEn < TODO_SUBIDO_MS) avisos.push(avisoTodoSubido(ultimaSync ?? subidoEn));
  if (actualizadaA) avisos.push(avisoActualizada(actualizadaA));
  const deProximo = proximo ? avisoProximo(proximo, ahora) : null;
  if (deProximo) avisos.push(deProximo);
  return avisos
    .filter((a) => !(a.cierre && descartados?.[a.id] > ahora))
    .filter((a) => !countdownUrgente || a.prioridad <= PRIORIDAD_MAXIMA_URGENTE)
    .sort((a, b) => a.prioridad - b.prioridad);  // sort es estable: a igual prioridad queda el orden de llegada
}

/** Hasta cuándo queda cerrado un aviso que se cierra ahora (ms; Infinity si no vuelve en esta sesión o nunca; null si no se cierra). */
export function cerradoHasta(aviso, ahora) {
  if (aviso.cierre === CIERRE.seisHoras) return ahora + CIERRE_SERVICIO_MS;
  return aviso.cierre ? Infinity : null;
}

/** Los cierres de 6 h guardados que siguen vigentes (descarta los vencidos y los valores rotos). Devuelve un objeto nuevo. */
export function cierresVigentes(guardados, ahora) {
  if (!guardados || typeof guardados !== "object") return {};
  return Object.fromEntries(Object.entries(guardados).filter(([, hasta]) => Number.isFinite(hasta) && hasta > ahora));
}

/**
 * Sigue la subida al volver la señal. `subida` es { total } o null; `pendientes`, cuántas cosas faltan; `empezar`, si
 * acaba de volver la red. Devuelve { subida, terminoEn }: terminoEn (ms) solo cuando la subida acaba de terminar.
 */
export function seguirSubida(subida, { pendientes, online, empezar = false, ahora }) {
  if (!online) return { subida: null, terminoEn: null };
  if (!subida) return { subida: empezar && pendientes > 0 ? { total: pendientes } : null, terminoEn: null };
  if (pendientes <= 0) return { subida: null, terminoEn: ahora };
  return { subida: { total: Math.max(subida.total, pendientes) }, terminoEn: null };  // si se suma algo mientras sube, crece el total
}

/** Lo que muestra «subiendo X de N»: cuántos ya subieron, el total y qué se sube («grabaciones y gastos»). */
export function progresoDeSubida(subida, pendientes) {
  if (!subida) return null;
  const que = [pendientes?.grabaciones ? "grabaciones" : null, pendientes?.gastos ? "gastos" : null].filter(Boolean).join(" y ");
  return { hechos: Math.max(0, subida.total - total(pendientes)), total: subida.total, que: que || null };
}

// ---------- novedades (/api/novedades) ----------

const SECCIONES = ["Agregado", "Cambiado", "Corregido"];

/**
 * Las versiones de /api/novedades con la forma esperada, como [{ version, secciones: [[nombre, items]] }]. Lo que no
 * tiene la forma (versión sin texto, ítems sin título, secciones desconocidas o vacías) se descarta: no se confía en la respuesta.
 */
export function novedadesValidas(respuesta) {
  if (!Array.isArray(respuesta)) return [];
  const esItem = (it) => typeof it?.titulo === "string" && it.titulo.trim() !== "" && (it.texto == null || typeof it.texto === "string");
  return respuesta
    .filter((v) => typeof v?.version === "string" && v.secciones && typeof v.secciones === "object")
    .map((v) => ({ version: v.version, secciones: SECCIONES
      .map((nombre) => [nombre, (Array.isArray(v.secciones[nombre]) ? v.secciones[nombre] : []).filter(esItem)])
      .filter(([, items]) => items.length) }))
    .filter((v) => v.secciones.length);
}
