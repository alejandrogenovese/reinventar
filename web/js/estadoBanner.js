// Banner de estado (#estado-banner, en .top-banners): junta las fuentes (red, colas de grabaciones y gastos, /api/estado,
// versión) y dibuja el aviso más importante con un «+N» que abre la hoja «Avisos». Qué se muestra lo decide estado.js
// (puro); acá solo se lee el mundo, se guarda lo cerrado y se pinta. Diseño: demos/diseno/banner-status.html.
import { EVENTO_CON_SERVICIO, EVENTO_SIN_SERVICIO, api, getToken } from "./api.js";
import { CIERRE, TODO_SUBIDO_MS, cerradoHasta, cierresVigentes, compararVersiones, elegirAvisos, novedadesValidas, progresoDeSubida, seguirSubida } from "./estado.js";
import { EVENTO_GASTOS, sincronizar } from "./gastos.js";
import { listarGastos } from "./gastosCola.js";
import { icon } from "./icons.js";
import { horaCorta, leerUltimaSync } from "./lastgood.js";
import { uploader } from "./recorder.js";
import * as store from "./store.js";
import { Button, Hoja, h, mensajeError, toast } from "./ui.js";
import { VERSION } from "./version.js";

const CONSULTA_CADA_MS = 10 * 60_000;     // /api/estado: al abrir, al volver a primer plano y cada 10 min (sin red, no)
const RECALCULO_MS = 150;                 // junta varios eventos seguidos (la cola emite muchos) en una sola lectura
const CIERRES = "reinventar.estado.cierres";      // localStorage: { id: hasta (ms) } · sessionStorage: [id]
const VERSION_VISTA = "reinventar.version.vista"; // localStorage: la última versión que se abrió en este celular

// Íconos de cada aviso (estado.js los nombra; acá se dibujan con nombres literales).
const ICONO = {
  sinsenal: () => icon("sinsenal", 20), subir: () => icon("subir", 20), ok: () => icon("ok", 20), error: () => icon("error", 20),
  nuevo: () => icon("nuevo", 20), reloj: () => icon("reloj", 20), alerta: () => icon("alerta", 20),
};

const local = () => localStorage;
const sesion = () => sessionStorage;
function leerJson(almacen, clave, porDefecto) {
  try { return JSON.parse(almacen().getItem(clave)) ?? porDefecto; } catch { return porDefecto; }
}
function escribirJson(almacen, clave, valor) {
  try { almacen().setItem(clave, JSON.stringify(valor)); } catch { /* sin almacenamiento: el cierre dura hasta recargar */ }
}

// Lo que se sabe del mundo. Se reemplaza entero en cada cambio (nunca se modifica en el lugar).
let mundo = {
  sinServicio: false,         // una pantalla cayó a la última copia (red que no contesta, portal, servidor caído)
  datosDe: null,              // hora (ms) de esa copia
  pendientes: { grabaciones: 0, gastos: 0 },
  fallidos: { grabaciones: 0, gastos: 0 },
  subida: null,               // { total } mientras sube lo pendiente al volver la señal
  subidoEn: null,             // cuándo terminó esa subida («Todo subido» por 5 s)
  servicio: [],
  versionRemota: null,
  actualizada: null,          // { nueva, anterior } si esta apertura es la primera de una versión nueva
};
const cambiar = (cambios) => { mundo = { ...mundo, ...cambios }; };

let volvioLaRed = false;      // el próximo recálculo empieza a contar «subiendo X de N»
let temporizador = null;
let ultimaFirma = null;
let consultadoCon = null;     // token con el que ya se consultó /api/estado (al entrar con otra cuenta se vuelve a pedir)

const hayRed = () => navigator.onLine !== false && !mundo.sinServicio;

/** La primera vez que se abre una versión nueva (y no en la primera instalación) se avisa «Actualizada a X», una vez. */
function versionRecienInstalada() {
  const vista = leerJson(local, VERSION_VISTA, null);
  escribirJson(local, VERSION_VISTA, VERSION);
  return typeof vista === "string" && compararVersiones(VERSION, vista) > 0 ? { nueva: VERSION, anterior: vista } : null;
}

function descartados(ahora) {
  const deSesion = leerJson(sesion, CIERRES, []);
  return {
    ...cierresVigentes(leerJson(local, CIERRES, {}), ahora),
    ...Object.fromEntries((Array.isArray(deSesion) ? deSesion : []).map((id) => [id, Infinity])),
  };
}

function countdownUrgente() {
  const cd = document.getElementById("countdown-banner");
  return Boolean(cd && !cd.hidden && cd.classList.contains("is-urgent"));
}

function avisosActuales() {
  if (!getToken()) return [];
  const ahora = Date.now();
  return elegirAvisos({
    online: hayRed(), pendientes: mundo.pendientes, fallidos: mundo.fallidos,
    subiendo: progresoDeSubida(mundo.subida, mundo.pendientes), subidoEn: mundo.subidoEn,
    servicio: mundo.servicio, versionLocal: VERSION, versionRemota: mundo.versionRemota, actualizadaA: mundo.actualizada?.nueva ?? null,
    descartados: descartados(ahora), ruta: location.hash || "#/", countdownUrgente: countdownUrgente(),
    datosDe: mundo.datosDe, ultimaSync: leerUltimaSync(), ahora,
  });
}

// ---------- dibujo ----------

/** El texto del aviso: lo común, los datos en mono («14:32», «2 de 5») y el detalle sin negrita. */
function Texto(aviso) {
  const partes = aviso.titulo.map((p) => (typeof p === "string" ? p
    : p.dato ? h("span", { class: "eb-dato" }, p.dato) : h("span", {}, p.detalle)));
  return h("p", { class: "eb-texto" }, ...partes, aviso.detalle ? [" ", h("span", {}, aviso.detalle)] : null);
}

function Icono(aviso) {
  const svg = (ICONO[aviso.icono] ?? ICONO.alerta)();
  svg.classList.add("eb-ico");
  if (aviso.gira) svg.classList.add("eb-gira");
  return svg;
}

function BotonCerrar(aviso, alCerrar) {
  return h("button", { type: "button", class: "eb-cerrar", "aria-label": `Cerrar aviso: ${aviso.nombre}`,
    onclick: () => { descartar(aviso); alCerrar?.(); } }, icon("cerrar", 20));
}

function Banner(aviso, cuantos) {
  const accion = aviso.accion ? h("button", { type: "button", class: "eb-accion", onclick: () => ejecutar(aviso) }, aviso.accion.texto) : null;
  // Con varios avisos, «+N» abre la hoja (y desde ahí se cierra cada uno); con uno solo, la X si se puede cerrar.
  const lateral = cuantos > 1
    ? h("button", { type: "button", class: "eb-mas", "aria-label": `Ver los ${cuantos} avisos`, onclick: abrirAvisos }, h("span", {}, `+${cuantos - 1}`))
    : aviso.cierre ? BotonCerrar(aviso, () => document.getElementById("view")?.focus({ preventScroll: true })) : null;
  return [Icono(aviso), Texto(aviso), accion, lateral].filter(Boolean); // replaceChildren pinta null como texto
}

/** Pinta el aviso de mayor prioridad. No repinta si no cambió nada (aria-live anunciaría lo mismo otra vez). */
export function paint() {
  const el = document.getElementById("estado-banner");
  if (!el) return;
  const avisos = avisosActuales();
  const primero = avisos[0];
  const firma = primero ? JSON.stringify([primero.id, primero.titulo, primero.detalle, avisos.length]) : "";
  if (firma === ultimaFirma) return;
  // «Subiendo X de N» se anuncia al empezar y al terminar, no con cada número: mientras sigue, la zona queda «ocupada».
  const sigueSubiendo = primero?.id === "subiendo" && Boolean(ultimaFirma?.startsWith('["subiendo"'));
  ultimaFirma = firma;
  el.setAttribute("aria-busy", sigueSubiendo ? "true" : "false");
  el.hidden = !primero;
  if (!primero) { el.replaceChildren(); return; }
  el.className = `estado-banner is-${primero.tono}`;
  el.replaceChildren(...Banner(primero, avisos.length));
}

// ---------- acciones ----------

function descartar(aviso) {
  const ahora = Date.now();
  if (aviso.cierre === CIERRE.seisHoras) {
    escribirJson(local, CIERRES, { ...cierresVigentes(leerJson(local, CIERRES, {}), ahora), [aviso.id]: cerradoHasta(aviso, ahora) });
  } else if (aviso.cierre === CIERRE.sesion) {
    const ids = leerJson(sesion, CIERRES, []);
    escribirJson(sesion, CIERRES, [...(Array.isArray(ids) ? ids : []), aviso.id]);
  } else if (aviso.cierre === CIERRE.siempre) {
    cambiar({ actualizada: null });  // la versión ya quedó como vista al abrir: no vuelve
  }
  paint();
}

async function reintentar() {
  try { await uploader.retryFailed(); } catch (e) { toast(mensajeError(e, "No se pudo reintentar la subida.")); }
  sincronizar().catch(() => { /* sin red: se reintenta solo cuando vuelva */ });
  // Los gastos rechazados por el servidor no se arreglan solos: en Gastos se corrigen o se borran.
  if (mundo.fallidos.gastos) location.hash = "#/gastos";
  programarRecalculo();
}

function ejecutar(aviso) {
  const { tipo, destino } = aviso.accion;
  if (tipo === "ir") location.hash = destino;
  else if (tipo === "avisos") abrirAvisos();
  else if (tipo === "reintentar") void reintentar();
  else if (tipo === "novedades") abrirNovedades({ desde: VERSION, version: mundo.versionRemota, conActualizar: true });
  else if (tipo === "que-cambio") {
    const { anterior, nueva } = mundo.actualizada ?? {};
    descartar(aviso);
    abrirNovedades({ desde: anterior, version: nueva, conActualizar: false });
  }
}

// ---------- hoja «Avisos» ----------

function ItemDeHoja(aviso, dlg) {
  const accion = aviso.accion && aviso.accion.tipo !== "avisos"
    ? h("button", { type: "button", class: "eb-accion", onclick: () => { dlg.close(); ejecutar(aviso); } }, aviso.accion.texto)
    : null;
  return h("li", { class: `eb-item is-${aviso.tono}` }, Icono(aviso),
    h("div", { class: "eb-item-texto" }, h("b", {}, aviso.hoja.titulo), aviso.hoja.texto, accion),
    aviso.cierre ? BotonCerrar(aviso, () => dlg.close()) : null);
}

function abrirAvisos() {
  const ultima = leerUltimaSync();
  const lista = h("ul", { class: "eb-lista" });
  const pie = h("p", { class: "caption eb-pie" },
    `Última sincronización: ${ultima ? horaCorta(ultima) : "todavía ninguna"} · Versión instalada: ${VERSION}`);
  const dlg = Hoja("eb-avisos-titulo", "Avisos", [lista, pie]);
  lista.replaceChildren(...avisosActuales().map((a) => ItemDeHoja(a, dlg)));
}

// ---------- hoja «Novedades» (/api/novedades) ----------

function Novedades(versiones) {
  if (!versiones.length) return [h("p", { class: "caption" }, "No hay novedades para mostrar.")];
  const varias = versiones.length > 1;
  return versiones.map((v) => h("section", { class: "eb-nov" },
    varias ? h("h3", { class: "label" }, `Versión ${v.version}`) : null,
    v.secciones.map(([nombre, items]) => [h("h4", {}, nombre),
      h("ul", {}, items.map((it) => h("li", {}, h("b", {}, it.titulo), it.texto ? ` ${it.texto}` : null)))])));
}

async function actualizarAhora(boton) {
  if (navigator.onLine === false) { toast("Sin señal: la versión nueva se instala cuando vuelva la red."); return; }
  boton.disabled = true;
  // El service worker (sw.js) hace skipWaiting y clients.claim: alcanza con buscar el nuevo y recargar.
  try { await (await navigator.serviceWorker?.getRegistration?.())?.update(); } catch { /* sin SW: se recarga igual */ }
  location.reload();
}

function abrirNovedades({ desde, version, conActualizar }) {
  const cuerpo = h("div", { class: "eb-nov-cuerpo" }, h("p", { class: "caption" }, "Cargando novedades…"));
  const botonActualizar = conActualizar ? Button("Actualizar ahora", { variant: "primary", onclick: () => actualizarAhora(botonActualizar) }) : null;
  const pie = conActualizar
    ? [botonActualizar, Button("Después", { onclick: () => dlg.close() })]
    : [Button("Cerrar", { onclick: () => dlg.close() })];
  const dlg = Hoja("eb-nov-titulo", version ? `Novedades de la ${version}` : "Novedades", cuerpo, pie);
  if (!desde) { cuerpo.replaceChildren(...Novedades([])); return; }
  api(`/api/novedades?desde=${encodeURIComponent(desde)}`)
    .then((r) => cuerpo.replaceChildren(...Novedades(novedadesValidas(r))))
    .catch(() => cuerpo.replaceChildren(h("p", { class: "caption" }, "No se pudieron cargar las novedades. Probá de nuevo en un rato.")));
}

// ---------- fuentes ----------

/** Cuenta lo que espera subirse y lo que falló, de las colas que ya existen (store.js, gastosCola.js y el uploader). */
async function leerColas() {
  const [locales, gastos] = await Promise.all([
    store.sesionesLocalesPendientes().catch(() => []),
    listarGastos().catch(() => []),
  ]);
  const conError = locales.filter((s) => s.error).length;
  return {
    pendientes: {
      grabaciones: locales.filter((s) => !s.error && s.estado !== "grabando").length,  // la que se está grabando no espera
      gastos: gastos.filter((g) => g.pendiente && !g.rechazado).length,
    },
    fallidos: {
      // pedazos que el servidor rechazó (uploader.failed) cuentan como al menos una grabación
      grabaciones: Math.max(conError, uploader.failed > 0 ? 1 : 0),
      gastos: gastos.filter((g) => g.rechazado && !g.deleted_at).length,
    },
  };
}

async function recalcular() {
  const { pendientes, fallidos } = await leerColas();
  const empezar = volvioLaRed;
  volvioLaRed = false;
  const { subida, terminoEn } = seguirSubida(mundo.subida, {
    pendientes: pendientes.grabaciones + pendientes.gastos, online: hayRed(), empezar, ahora: Date.now() });
  cambiar({ pendientes, fallidos, subida, subidoEn: terminoEn ?? mundo.subidoEn });
  if (terminoEn) setTimeout(paint, TODO_SUBIDO_MS + 50);  // «Todo subido» se va solo
  paint();
}

function programarRecalculo() {
  clearTimeout(temporizador);
  temporizador = setTimeout(() => { recalcular().catch((e) => console.warn("[estado] no se pudieron leer las colas", e)); }, RECALCULO_MS);
}

/** /api/estado: servicio y versión del servidor. Si falla (o todavía no existe: 404), esos avisos no se muestran. */
async function consultarEstado() {
  const token = getToken();
  if (!token || navigator.onLine === false) return;
  consultadoCon = token;
  try {
    const r = await api("/api/estado");
    cambiar({ servicio: Array.isArray(r?.servicio) ? r.servicio : [], versionRemota: typeof r?.version === "string" ? r.version : null });
  } catch {
    cambiar({ servicio: [], versionRemota: null });
  }
  paint();
}

function alVolverLaRed() {
  volvioLaRed = true;
  cambiar({ sinServicio: false, datosDe: null });
  programarRecalculo();
}

/** Lo llama el router en cada navegación: recalcula y, si entró otra cuenta, vuelve a consultar /api/estado. */
export function refrescarEstado() {
  if (getToken() && consultadoCon !== getToken()) void consultarEstado();
  programarRecalculo();
}

let iniciado = false;

/** Arranca el banner: escucha las fuentes y consulta /api/estado. Se llama una vez, al cargar la app. */
export function iniciarEstado() {
  if (iniciado) return;
  iniciado = true;
  cambiar({ actualizada: versionRecienInstalada() });
  window.addEventListener("online", alVolverLaRed);
  window.addEventListener("offline", programarRecalculo);
  window.addEventListener(EVENTO_SIN_SERVICIO, (e) => {
    const at = Number(e.detail?.at);
    cambiar({ sinServicio: true, datosDe: Number.isFinite(at) ? Math.max(at, mundo.datosDe ?? 0) : mundo.datosDe });
    programarRecalculo();
  });
  window.addEventListener(EVENTO_CON_SERVICIO, () => { if (mundo.sinServicio) alVolverLaRed(); });
  window.addEventListener(EVENTO_GASTOS, programarRecalculo);
  window.addEventListener("hashchange", paint);
  uploader.addEventListener("change", programarRecalculo);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    void consultarEstado();
    programarRecalculo();
  });
  // Con «Salí ya» solo quedan las prioridades 1 a 3: se repinta cuando el countdown cambia de tono o se oculta.
  const cd = document.getElementById("countdown-banner");
  if (cd && "MutationObserver" in window) new MutationObserver(paint).observe(cd, { attributes: true, attributeFilter: ["class", "hidden"] });
  setInterval(() => { void consultarEstado(); }, CONSULTA_CADA_MS);
  void consultarEstado();
  programarRecalculo();
}
