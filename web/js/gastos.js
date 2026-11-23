// Gastos: control de gastos del viaje. Se carga en segundos y sin señal: el gasto se guarda en el celular (gastosCola.js)
// y se manda solo al volver la red. Pantalla #/gastos: resumen contra presupuesto, cotizaciones, categorías y lista.
import { ApiError, MSG_SIN_CONEXION, api, cuentaConCopia, getToken, sinServicio } from "./api.js";
import { Bars, dayLong, dec, int } from "./charts.js";
import { sinDoble } from "./adminUi.js";
import { confirmDialog } from "./dialog.js";
import { marcarUltimaSync } from "./lastgood.js";
import { icon } from "./icons.js";
import {
  CALIDAD_JPEG, CATEGORIAS, TOPE_FOTO_BYTES, aCambio, agruparPorDia, borrarFoto, borrarGasto, contarIntentoFoto, crearGasto, decidirDueno,
  edadCotizacion, editarGasto, escalarLado, fechaLocal, fotosPendientes, gastosPendientes, guardarFoto, guardarGasto, guardarMeta, leerGasto,
  leerMeta, listarGastos, nuevoId, parsearMonto, partirEnLotes, resolverRespuesta, separarInvalidos, textoEdad, totales, transaccionarGastos,
  usdDe, validarGasto, vaciarCola, visibles,
} from "./gastosCola.js";
import { Button, Hint, Hoja, h, mensajeError, toast, toastOnError } from "./ui.js";

const SYNC_CADA_MS = 60_000;
const LOTE_SYNC = 200;             // tope de gastos por pedido de /sync del servidor
const MAX_VUELTAS_SYNC = 50;       // tope de pedidos seguidos cuando el servidor dice `hay_mas` (50 x 1000 cambios)
const TIMEOUT_PEDIDO_MS = 20_000;  // un Wi-Fi colgado no puede dejar el sync esperando para siempre
const TIMEOUT_FOTO_MS = 60_000;    // la foto pesa hasta 2 MB: más margen
const AVISO_AMBAR = 0.8;           // desde acá la barra se pone ámbar; al pasarse del 100 %, roja
const MAX_INTENTOS_FOTO = 5;       // con un error del servidor (4xx) la foto se abandona tras tantos intentos
const CALIDAD_MINIMA = 0.3;
const PASO_CALIDAD = 0.1;
const ACTIVO = "reinventar.gastos";  // marca que el usuario ya usó Gastos: desde entonces la app sincroniza sola al abrir

const ETIQUETAS = { comida: "Comida", transporte: "Transporte", shows: "Shows", compras: "Compras", otros: "Otros" };
const MSG_SIN_SENAL = "Sin señal: los gastos quedan en el celular y se mandan solos cuando vuelva la red.";
const MSG_NO_DISPONIBLE = "Gastos todavía no está disponible en el servidor.";
const MSG_SESION_VENCIDA = "Tu sesión venció: los gastos siguen guardados en este celular y se mandan cuando vuelvas a entrar.";

const usd = (n) => `US$ ${dec(n, 2)}`;
const ars = (n) => `$ ${int(Math.round(n))}`;
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const textoError = (e) => (e instanceof ApiError && e.status === 404 ? MSG_NO_DISPONIBLE : mensajeError(e));

// ---------- sincronización ----------

const oyentes = new Set();
let enCurso = null;
let iniciado = false;

// Cada cambio en la cola de gastos (sync, alta, edición, baja) se avisa a la pantalla y, con «ra:gastos», al banner de
// estado (estadoBanner.js), que cuenta los pendientes y los rechazados.
export const EVENTO_GASTOS = "ra:gastos";
const avisarCola = () => { try { window.dispatchEvent(new Event(EVENTO_GASTOS)); } catch { /* sin banner */ } };
const avisar = () => { for (const f of [...oyentes]) f(); avisarCola(); };

/** Pedido a la API con tope de espera: si el servidor no contesta en `ms`, se trata como falta de señal. */
async function apiConTimeout(ruta, opciones = {}, ms = TIMEOUT_PEDIDO_MS) {
  const control = new AbortController();
  const reloj = setTimeout(() => control.abort(), ms);
  try { return await api(ruta, { ...opciones, signal: control.signal }); } catch (e) {
    if (e?.name === "AbortError" || e?.name === "TimeoutError") throw new ApiError(0, MSG_SIN_CONEXION);
    throw e;
  } finally { clearTimeout(reloj); }
}

const esSesionVencida = (e) => e instanceof ApiError && e.status === 401;

async function subirFotos() {
  for (const foto of await fotosPendientes()) {
    const gasto = await leerGasto(foto.client_id);
    if (!gasto || gasto.pendiente) continue;                       // el gasto todavía no llegó al servidor: la foto va después
    if (gasto.deleted_at) { await borrarFoto(foto.client_id); continue; }
    try {
      const cuerpo = new FormData();
      cuerpo.append("foto", foto.blob, "ticket.jpg");
      const r = await apiConTimeout(`/api/gastos/${foto.client_id}/foto`, { method: "POST", body: cuerpo }, TIMEOUT_FOTO_MS);
      await transaccionarGastos((todos) => todos.filter((g) => g.client_id === foto.client_id).map((g) => ({ ...g, foto_url: r.foto_url })));
      await borrarFoto(foto.client_id);
    } catch (e) {
      const rechazada = e instanceof ApiError && e.status >= 400 && e.status < 500 && ![401, 403, 408, 429].includes(e.status);
      if (rechazada && foto.intentos + 1 >= MAX_INTENTOS_FOTO) { await borrarFoto(foto.client_id); toast(`No se pudo subir la foto de un ticket: ${textoError(e)}`); }
      else await contarIntentoFoto(foto);
    }
  }
}

/** Aplica la respuesta de un /sync en una sola transacción: lo que se edite mientras tanto no se pisa. */
const aplicarRespuesta = (lote, r) => transaccionarGastos((todos) => resolverRespuesta(lote, new Map(todos.map((g) => [g.client_id, g])), r));

/** Los gastos que el servidor rechazaría seguro no salen: se marcan rechazados con el motivo y el resto del lote sigue. */
const marcarInvalidos = (invalidos) => aplicarRespuesta(invalidos.map((i) => i.gasto),
  { rechazados: invalidos.map(({ gasto, error }) => ({ client_id: gasto.client_id, error })) });

/** Un pedido de /sync y, mientras el servidor diga `hay_mas`, los que siguen (sin gastos nuevos, desde el cursor que devolvió). */
async function pedirSync(lote, desdeInicial) {
  let desde = desdeInicial;
  let cambios = lote;
  for (let vuelta = 0; vuelta < MAX_VUELTAS_SYNC; vuelta += 1) {
    const r = await apiConTimeout("/api/gastos/sync", { method: "POST", json: { cambios: cambios.map(aCambio), desde } });
    await aplicarRespuesta(cambios, r);
    if (cambios.length) marcarUltimaSync();  // subió algo: es la última sincronización que muestra el banner de estado
    desde = r.ahora;  // el cursor es el reloj del servidor (`ahora`), nunca el del teléfono
    await guardarMeta("ultimoSync", desde);  // por pedido: si se corta a la mitad de una bajada larga, no se empieza de cero
    if (!r.hay_mas) break;
    cambios = [];
  }
  return desde;
}

// ---------- dueño de la cola ----------

let usuarioEnMemoria = { token: "", nombre: null };

/** Quién está conectado: del servidor o, sin señal, de la copia de Ajustes. null si no se sabe. Con sesión vencida tira un 401. */
async function usuarioActual() {
  const token = getToken();
  if (usuarioEnMemoria.token === token && usuarioEnMemoria.nombre) return usuarioEnMemoria.nombre;
  const cuenta = await cuentaConCopia();
  if (cuenta.estado === "sin_sesion") throw new ApiError(401, MSG_SESION_VENCIDA);
  const nombre = cuenta.username ?? null;
  if (cuenta.estado === "ok") usuarioEnMemoria = { token, nombre };
  return nombre;
}

let verificando = null;

async function verificarDueno() {
  const usuario = await usuarioActual();
  if (!usuario) return false;  // sin saber de quién es esta sesión no se manda nada
  const { accion } = decidirDueno(await leerMeta("dueno"), usuario);
  if (accion === "vaciar") {
    const perdidos = (await listarGastos()).filter((g) => g.pendiente).length;
    await vaciarCola();
    if (perdidos) toast(`Había ${perdidos === 1 ? "1 gasto sin sincronizar" : `${perdidos} gastos sin sincronizar`} de otra cuenta en este celular: se descartaron.`);
  }
  if (accion !== "seguir") await guardarMeta("dueno", usuario);
  return true;
}

/** Antes de mostrar o mandar nada: la cola guardada tiene que ser de quien está conectado; si era de otra persona, se vacía. */
function asegurarDueno() {
  verificando ??= verificarDueno().finally(() => { verificando = null; });
  return verificando;
}

async function hacerSync() {
  if (!getToken()) return;
  if (!await asegurarDueno()) return;
  let desde = await leerMeta("ultimoSync");
  const { validos, invalidos } = separarInvalidos(await gastosPendientes());
  if (invalidos.length) await marcarInvalidos(invalidos);
  const lotes = partirEnLotes(validos, LOTE_SYNC);
  for (const lote of lotes.length ? lotes : [[]]) desde = await pedirSync(lote, desde);
  await guardarMeta("ultimoSync", desde);
  await subirFotos();
  avisar();
}

/** Manda lo pendiente y trae lo nuevo. Si ya hay uno en curso, se engancha a ese. */
export function sincronizar() {
  enCurso ??= hacerSync().finally(() => { enCurso = null; });
  return enCurso;
}

const sincronizarEnSilencio = () => sincronizar().catch((e) => { if (!sinServicio(e)) console.warn("[gastos] sync", e); });

/** Al volver la red, al volver a primer plano y cada 60 s mientras haya pendientes. */
function activarSync() {
  try { localStorage.setItem(ACTIVO, "1"); } catch {}
  if (iniciado) return;
  iniciado = true;
  window.addEventListener("online", sincronizarEnSilencio);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") sincronizarEnSilencio(); });
  setInterval(async () => {
    const hayPendientes = (await gastosPendientes().catch(() => [])).length || (await fotosPendientes().catch(() => [])).length;
    if (hayPendientes && navigator.onLine !== false) sincronizarEnSilencio();
  }, SYNC_CADA_MS);
}

let yaUsado = false;
try { yaUsado = localStorage.getItem(ACTIVO) === "1"; } catch {}
if (yaUsado) activarSync();

// ---------- foto del ticket ----------

/** Achica la foto en el celular: lado mayor 1600 px, JPEG ~0,7; si todavía pasa de 2 MB baja la calidad de a poco. */
async function achicarFoto(archivo) {
  const imagen = await createImageBitmap(archivo);
  const { ancho, alto } = escalarLado(imagen.width, imagen.height);
  const lienzo = document.createElement("canvas");
  lienzo.width = ancho;
  lienzo.height = alto;
  lienzo.getContext("2d").drawImage(imagen, 0, 0, ancho, alto);
  imagen.close?.();
  for (let calidad = CALIDAD_JPEG; ; calidad = Math.round((calidad - PASO_CALIDAD) * 10) / 10) {
    const blob = await new Promise((resolve) => lienzo.toBlob(resolve, "image/jpeg", calidad));
    if (!blob) throw new Error("No se pudo preparar la foto. Probá con otra.");
    if (blob.size <= TOPE_FOTO_BYTES) return blob;
    if (calidad <= CALIDAD_MINIMA) throw new Error("La foto pesa más de 2 MB aun achicada. Probá con otra.");
  }
}

// ---------- piezas de pantalla ----------

/** Grupo de botones con aria-pressed. `esActivo(valor)` dice cuál está elegido; `elegir(valor)` lo cambia. */
function Grupo(etiqueta, clase, items, esActivo, elegir, { chip = false } = {}) {
  const botones = items.map(([valor, texto]) => h("button", { type: "button", class: chip ? "ra-chip" : "", "aria-pressed": "false",
    onclick: () => { elegir(valor); pintar(); } }, texto));
  function pintar() {
    botones.forEach((b, i) => {
      const activo = esActivo(items[i][0]);
      b.setAttribute("aria-pressed", String(activo));
      if (chip) b.classList.toggle("ra-chip-on", activo);
    });
  }
  pintar();
  return h("div", { class: clase, role: "group", "aria-label": etiqueta }, botones);
}

const Campo = (id, etiqueta, input) => h("div", { class: "field" }, h("label", { class: "label", for: id }, etiqueta), input);

/** Hoja de carga rápida (o de edición si llega `gasto`). Guarda en el celular y dispara el sync. */
function abrirCarga({ gasto = null, tarjeta, alGuardar }) {
  let moneda = gasto?.moneda ?? "USD";
  let categoria = gasto?.categoria ?? "comida";
  let reintegrable = gasto?.reintegrable ?? false;
  let compartido = gasto?.compartido ?? false;
  let foto = null;
  let vistaPrevia = null;
  let guardando = false;
  const clientId = gasto?.client_id ?? nuevoId();   // fijo al abrir la hoja: tocar «Guardar» dos veces pisa el mismo gasto, no crea otro

  const monto = h("input", { id: "g-monto", type: "text", inputmode: "decimal", autocomplete: "off", "aria-label": "Monto", placeholder: "0",
    value: gasto ? String(gasto.monto).replace(".", ",") : "", oninput: () => estimar() });
  const estimado = h("p", { class: "ra-g-estimado", "aria-live": "polite" });
  const nota = h("input", { id: "g-nota", type: "text", maxlength: 200, autocomplete: "off", value: gasto?.nota ?? "" });
  const fecha = h("input", { id: "g-fecha", type: "date", value: gasto?.fecha ?? fechaLocal() });
  const error = h("p", { class: "notice err", role: "alert", hidden: true });
  const miniatura = h("span", { class: "caption" });
  let cerrada = false;
  const urlsDeFotos = [];   // blobs de las fotos que se muestran: se sueltan al cerrar la hoja
  async function alElegirFoto(entrada) {
    const elegido = entrada.files?.[0];
    entrada.value = "";   // elegir la misma foto otra vez tiene que volver a disparar el cambio
    if (!elegido) return;
    try {
      foto = await achicarFoto(elegido);
      if (vistaPrevia) URL.revokeObjectURL(vistaPrevia);
      vistaPrevia = URL.createObjectURL(foto);
      miniatura.replaceChildren(h("img", { src: vistaPrevia, alt: "Foto del ticket" }), `${dec(foto.size / 1024, 0)} KB`);
      error.hidden = true;
    } catch (e) { mostrarError(mensajeError(e, "No se pudo leer la foto. Probá con otra.")); }
  }
  // Dos entradas ocultas que se abren con botones: se llega con teclado y VoiceOver, y «Elegir de la galería» no fuerza la cámara.
  const archivoCamara = h("input", { type: "file", accept: "image/*", capture: "environment", hidden: true, onchange: () => alElegirFoto(archivoCamara) });
  const archivoGaleria = h("input", { type: "file", accept: "image/*", hidden: true, onchange: () => alElegirFoto(archivoGaleria) });

  function estimar() {
    const n = parsearMonto(monto.value);
    if (moneda === "USD" || Number.isNaN(n)) { estimado.textContent = ""; return; }
    const u = usdDe({ monto: n, moneda }, tarjeta);
    estimado.textContent = u == null ? "Sin cotización todavía: se calcula cuando haya señal." : `≈ ${usd(u)} con la tarjeta (${ars(tarjeta)})`;
  }
  function mostrarError(texto) { error.textContent = texto; error.hidden = false; }

  /** La foto guardada pide sesión: se baja con el token y se muestra desde un blob (un <img src> directo iría sin token). */
  async function mostrarFotoGuardada(ruta) {
    miniatura.textContent = "Cargando la foto…";
    try {
      const url = URL.createObjectURL(await (await api(ruta, { raw: true })).blob());
      if (cerrada) { URL.revokeObjectURL(url); return; }
      urlsDeFotos.push(url);
      miniatura.replaceChildren(h("img", { src: url, alt: "Foto guardada del ticket" }));
    } catch (e) { if (!cerrada) miniatura.textContent = `No se pudo traer la foto: ${textoError(e)}`; }
  }

  async function guardar() {
    const n = parsearMonto(monto.value);
    if (guardando) return;
    if (Number.isNaN(n)) { mostrarError("Poné un monto mayor a cero y menor a mil millones, por ejemplo 14,10."); monto.focus(); return; }
    const datos = { fecha: fecha.value || fechaLocal(), monto: n, moneda, categoria, nota: nota.value.trim(), reintegrable, compartido };
    const motivo = validarGasto({ ...datos });
    if (motivo) { mostrarError(motivo); return; }
    const nuevo = gasto ? editarGasto(gasto, datos) : crearGasto(datos, { id: clientId });
    guardando = true;
    botonGuardar.disabled = true;
    try {
      await guardarGasto(nuevo);
      if (foto) await guardarFoto(nuevo.client_id, foto);
    } catch (e) {
      guardando = false;
      botonGuardar.disabled = false;
      mostrarError(mensajeError(e, "No se pudo guardar en el celular. Revisá el espacio y probá de nuevo."));
      return;
    }
    dlg.close();
    alGuardar();
    avisarCola();
    sincronizarEnSilencio();
  }

  async function borrar() {
    if (!await confirmDialog("¿Borrar este gasto?", { text: "Se saca de la lista y del total.", confirmLabel: "Borrar", danger: true })) return;
    await guardarGasto(borrarGasto(gasto));
    dlg.close();
    alGuardar();
    avisarCola();
    sincronizarEnSilencio();
  }

  const cuerpo = h("div", { class: "ra-g-form" },
    h("div", { class: "ra-g-monto-wrap" }, monto,
      Grupo("Moneda", "ra-g-moneda", [["USD", "USD"], ["ARS", "ARS"]], (v) => v === moneda, (v) => { moneda = v; estimar(); })),
    estimado,
    h("div", { class: "ra-g-fila-campo" }, h("span", { class: "label" }, "Categoría"),
      Grupo("Categoría", "ra-chips", CATEGORIAS.map((c) => [c, ETIQUETAS[c]]), (v) => v === categoria, (v) => { categoria = v; }, { chip: true })),
    Campo("g-nota", "Nota", nota),
    Campo("g-fecha", "Día", fecha),
    h("div", { class: "ra-g-fila-campo" }, h("span", { class: "label" }, "Cómo se paga"),
      Grupo("Reintegrable", "ra-chips", [[true, "Reintegrable"]], () => reintegrable, () => { reintegrable = !reintegrable; }, { chip: true }),
      Grupo("Individual o compartido", "ra-g-dos", [[false, "Individual"], [true, "Compartido"]], (v) => v === compartido, (v) => { compartido = v; })),
    h("div", { class: "ra-g-foto" },
      Button("Sacar foto del ticket", { onclick: () => archivoCamara.click() }),
      Button("Elegir de la galería", { onclick: () => archivoGaleria.click() }),
      archivoCamara, archivoGaleria,
      miniatura),
    error);

  const botonGuardar = Button("Guardar gasto", { variant: "primary", onclick: () => toastOnError(guardar()) });
  // Un doble toque en «Borrar» no apila dos confirmaciones.
  const botonBorrar = gasto ? Button("Borrar", { variant: "danger", onclick: () => toastOnError(sinDoble(botonBorrar, borrar)) }) : null;
  const dlg = Hoja("g-carga-titulo", gasto ? "Editar gasto" : "Nuevo gasto", cuerpo, [
    botonBorrar ?? Button("Cancelar", { onclick: () => dlg.close() }),
    botonGuardar]);
  dlg.addEventListener("close", () => {
    cerrada = true;
    for (const url of [vistaPrevia, ...urlsDeFotos]) if (url) URL.revokeObjectURL(url);
  });
  if (gasto?.rechazado) mostrarError(`Este gasto no se pudo sincronizar: ${gasto.error}`);
  if (gasto?.foto_url) mostrarFotoGuardada(gasto.foto_url).catch((e) => console.warn("[gastos] foto guardada", e));
  estimar();
  monto.focus();
}

/** Hoja del presupuesto: total, por día y tope por categoría, en dólares. */
function abrirPresupuesto({ presupuesto, alGuardar }) {
  const entrada = (id, valor) => h("input", { id, type: "text", inputmode: "decimal", autocomplete: "off", placeholder: "Sin tope",
    value: valor == null ? "" : String(valor).replace(".", ",") });
  const total = entrada("p-total", presupuesto?.total_usd);
  const diario = entrada("p-diario", presupuesto?.diario_usd);
  const porCategoria = Object.fromEntries(CATEGORIAS.map((c) => [c, entrada(`p-${c}`, presupuesto?.por_categoria?.[c])]));
  const error = h("p", { class: "notice err", role: "alert", hidden: true });
  const leer = (input) => (input.value.trim() === "" ? null : parsearMonto(input.value));

  async function guardar() {
    const campos = [total, diario, ...Object.values(porCategoria)];
    if (campos.some((c) => c.value.trim() !== "" && Number.isNaN(parsearMonto(c.value)))) {
      error.textContent = "Revisá los montos: tienen que ser números mayores a cero, o quedar vacíos.";
      error.hidden = false;
      return;
    }
    const nuevo = { total_usd: leer(total), diario_usd: leer(diario),
      por_categoria: Object.fromEntries(CATEGORIAS.map((c) => [c, leer(porCategoria[c])]).filter(([, v]) => v != null)) };
    try { await api("/api/gastos/presupuesto", { method: "PUT", json: nuevo }); } catch (e) { error.textContent = textoError(e); error.hidden = false; return; }
    await guardarMeta("presupuesto", nuevo);
    dlg.close();
    alGuardar();
    toast("Presupuesto guardado");
  }

  const cuerpo = h("div", { class: "ra-g-form" },
    h("p", { class: "caption" }, "En dólares. Los gastos en pesos se pasan a dólares con la cotización de tarjeta."),
    h("div", { class: "ra-g-presu" }, Campo("p-total", "Total del viaje", total), Campo("p-diario", "Por día", diario),
      CATEGORIAS.map((c) => Campo(`p-${c}`, ETIQUETAS[c], porCategoria[c]))),
    error);
  const dlg = Hoja("g-presu-titulo", "Presupuesto", cuerpo, [
    Button("Cancelar", { onclick: () => dlg.close() }), Button("Guardar", { variant: "primary", onclick: () => toastOnError(guardar()) })]);
  total.focus();
}

async function exportarReintegrables() {
  const r = await api("/api/gastos/export.csv", { raw: true });
  const blob = await r.blob();
  // En la app instalada de iPhone un enlace de descarga deja la pantalla trabada en el archivo: ahí se comparte con la hoja del sistema.
  const archivo = typeof File === "function" ? new File([blob], "gastos-reintegrables.csv", { type: "text/csv" }) : null;
  if (archivo && navigator.canShare?.({ files: [archivo] })) {
    try { await navigator.share({ files: [archivo], title: "Gastos reintegrables" }); return; } catch (e) {
      if (e?.name === "AbortError") return;   // cerró la hoja de compartir: no es un error
    }
  }
  const url = URL.createObjectURL(blob);
  const enlace = h("a", { href: url, download: "gastos-reintegrables.csv" });
  document.body.append(enlace);
  enlace.click();
  enlace.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

const tono = (ratio) => (ratio > 1 ? "is-err" : ratio >= AVISO_AMBAR ? "is-warn" : "");

function Avance(gastado, tope, etiqueta) {
  const ratio = tope > 0 ? gastado / tope : 0;
  return h("div", { class: `ra-g-avance ${tono(ratio)}`, role: "img", "aria-label": `${etiqueta}: ${Math.round(ratio * 100)} % de ${usd(tope)}` },
    h("span", { style: { width: `${Math.min(ratio, 1) * 100}%` } }));
}

function Resumen(t, presupuesto, hoy) {
  const deHoy = t.porDia[hoy] ?? 0;
  const diario = presupuesto?.diario_usd;
  const tope = presupuesto?.total_usd;
  return h("div", { class: "ra-g-resumen" },
    h("div", { class: "ra-g-resumen-fila" },
      h("div", { class: "ra-g-dato" }, h("span", { class: "ra-g-dato-label" }, "Hoy"), h("span", { class: "ra-g-grande" }, usd(deHoy))),
      diario ? h("div", { class: "ra-g-dato" }, h("span", { class: "ra-g-dato-label" }, "Presupuesto diario"), h("span", { class: "ra-g-dato-valor" }, usd(diario))) : null),
    diario ? Avance(deHoy, diario, "Hoy") : null,
    h("div", { class: "ra-g-resumen-fila" },
      h("div", { class: "ra-g-dato" }, h("span", { class: "ra-g-dato-label" }, "Total del viaje"),
        h("span", { class: "ra-g-dato-valor" }, tope ? `${usd(t.usd)} de ${usd(tope)}` : usd(t.usd))),
      tope ? h("span", { class: "caption" }, `${int(Math.round((t.usd / tope) * 100))} %`) : null),
    tope ? Avance(t.usd, tope, "Total del viaje") : h("p", { class: "caption" }, "Poné un presupuesto para ver cuánto te queda."));
}

function Cotizaciones(cotiz) {
  const celda = (etiqueta, valor) => h("div", {}, h("span", { class: "ra-g-dato-label" }, etiqueta), h("span", { class: "ra-g-dato-valor" }, valor > 0 ? ars(valor) : "—"));
  const hora = cotiz?.at ? new Date(cotiz.at).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" }) : null;
  const edad = textoEdad(edadCotizacion(cotiz));
  const cuando = [hora, edad ? `(${edad})` : null].filter(Boolean).join(" ");
  return h("section", { class: "stack" },
    h("div", { class: "ra-sec-head" }, h("h2", { class: "label" }, "Cotización"), h("span", { class: "caption" }, cuando ? `ARS por USD · ${cuando}` : "ARS por USD · sin datos")),
    cotiz?.es_respaldo ? Hint("No pudimos traer la cotización del día: se usa un valor de respaldo, aproximado.", { tone: "warn" }) : null,
    h("div", { class: "ra-g-cotiz" }, celda("Oficial", cotiz?.oficial), celda("Blue", cotiz?.blue), celda("Tarjeta", cotiz?.tarjeta)));
}

function PorCategoria(t, presupuesto) {
  if (!Object.keys(t.porCategoria).length) return null;
  const topes = presupuesto?.por_categoria ?? {};
  const max = Math.max(...CATEGORIAS.map((c) => Math.max(t.porCategoria[c] ?? 0, topes[c] ?? 0)));
  return h("section", { class: "stack" },
    h("div", { class: "ra-sec-head" }, h("h2", { class: "label" }, "Por categoría"), h("span", { class: "caption" }, "US$")),
    Bars(CATEGORIAS.map((c) => {
      const valor = t.porCategoria[c] ?? 0;
      const tope = topes[c];
      return { label: ETIQUETAS[c], value: valor, max, text: tope ? `${int(Math.round(valor))} / ${int(tope)}` : int(Math.round(valor)), tone: tope ? tono(valor / tope) : "" };
    })));
}

function Fila(gasto, { tarjeta, conFotoPendiente, alTocar }) {
  const u = usdDe(gasto, tarjeta);
  const marcas = [ETIQUETAS[gasto.categoria], gasto.reintegrable ? "Reintegrable" : null, gasto.compartido ? "Compartido" : null,
    gasto.foto_url ? "Foto" : conFotoPendiente ? "Foto pendiente" : null].filter(Boolean).map((m) => h("span", { class: "ra-g-marca" }, m));
  if (gasto.cotizacion_estimada) marcas.push(h("span", { class: "ra-g-marca" }, "Cotización estimada"));
  if (gasto.rechazado) marcas.push(h("span", { class: "ra-g-marca is-rechazado" }, "No se pudo sincronizar"));
  else if (gasto.pendiente) marcas.push(h("span", { class: "ra-g-marca is-pendiente" }, "Sin sincronizar"));
  return h("button", { type: "button", class: "ra-g-fila", onclick: alTocar },
    h("span", { class: "ra-g-fila-titulo" }, gasto.nota || ETIQUETAS[gasto.categoria]),
    h("span", { class: "ra-g-fila-monto" }, u == null ? "Sin cotización" : usd(u)),
    h("span", { class: "ra-g-marcas" }, marcas),
    h("span", { class: "ra-g-fila-sub" }, gasto.moneda === "ARS" ? ars(gasto.monto) : ""),
    gasto.rechazado ? h("span", { class: "ra-g-fila-error" }, gasto.error) : null);
}

function Lista(gastos, t, ctx) {
  if (!gastos.length) {
    return h("div", { class: "empty" }, h("p", {}, "Todavía no cargaste gastos."), h("p", { class: "caption" }, "Tocá «Cargar gasto»: anda también sin señal."));
  }
  return agruparPorDia(gastos).map(([dia, items]) => h("div", { class: "ra-g-dia" },
    h("div", { class: "ra-g-dia-head" }, h("h2", { class: "label" }, capital(dayLong(dia))), h("span", { class: "caption" }, usd(t.porDia[dia] ?? 0))),
    items.map((g) => Fila(g, { tarjeta: ctx.tarjeta, conFotoPendiente: ctx.fotos.has(g.client_id), alTocar: () => abrirCarga({ gasto: g, tarjeta: ctx.tarjeta, alGuardar: ctx.recargar }) }))));
}

// ---------- pantalla ----------

export async function viewGastos(view) {
  activarSync();
  const raiz = h("div", { class: "ra-g" });
  view.append(raiz);
  const ctx = { gastos: [], fotos: new Set(), cotiz: null, presupuesto: null, tarjeta: null, aviso: "", sesionVencida: false, sincronizando: false, recargar };

  async function recargar() {
    const [todos, fotos, cotiz, presupuesto] = await Promise.all([listarGastos(), fotosPendientes(), leerMeta("cotizacion"), leerMeta("presupuesto")]);
    Object.assign(ctx, { gastos: todos, fotos: new Set(fotos.map((f) => f.client_id)), cotiz, presupuesto, tarjeta: cotiz?.tarjeta ?? null });
    pintar();
  }

  function pintar() {
    const lista = visibles(ctx.gastos);
    const t = totales(lista, ctx.tarjeta);
    const pendientes = lista.filter((g) => g.pendiente && !g.rechazado).length;
    const rechazados = lista.filter((g) => g.rechazado).length;
    raiz.replaceChildren(...[
      h("a", { class: "ra-btn ra-btn-ghost ra-back", href: "#/viaje" }, icon("volver", 16), h("span", {}, "Viaje")),
      h("div", { class: "ra-g-head" }, h("h1", { class: "title" }, "Gastos"),
        Button("Cargar gasto", { variant: "primary", onclick: () => abrirCarga({ tarjeta: ctx.tarjeta, alGuardar: recargar }) })),
      ctx.sesionVencida ? h("div", { class: "stack" }, Hint(MSG_SESION_VENCIDA, { tone: "warn" }),
        h("a", { class: "ra-btn ra-btn-primary", href: "#/login" }, "Volver a entrar")) : null,
      ctx.aviso && !ctx.sesionVencida ? Hint(ctx.aviso, { tone: "warn" }) : null,
      rechazados ? Hint(`${rechazados === 1 ? "1 gasto no se pudo sincronizar" : `${rechazados} gastos no se pudieron sincronizar`}: tocalo para corregirlo o borrarlo.`, { tone: "warn" }) : null,
      pendientes ? h("div", { class: "stack" },
        Hint(`${pendientes === 1 ? "1 gasto sin sincronizar" : `${pendientes} gastos sin sincronizar`}: están guardados en este celular.`, { tone: "info" }),
        Button(ctx.sincronizando ? "Sincronizando…" : "Sincronizar ahora", { disabled: ctx.sincronizando, onclick: () => refrescar() })) : null,
      t.sinCotizacion ? Hint(`${t.sinCotizacion === 1 ? "1 gasto en pesos no suma" : `${t.sinCotizacion} gastos en pesos no suman`} hasta tener la cotización (se baja con señal).`, { tone: "warn" }) : null,
      Resumen(t, ctx.presupuesto, fechaLocal()),
      Cotizaciones(ctx.cotiz),
      PorCategoria(t, ctx.presupuesto),
      Lista(lista, t, ctx),
      h("div", { class: "actions" },
        Button("Presupuesto", { onclick: () => abrirPresupuesto({ presupuesto: ctx.presupuesto, alGuardar: recargar }) }),
        Button("Exportar reintegrables", { onclick: () => toastOnError(exportarReintegrables()) })),
    ].flat().filter(Boolean));
  }

  /** Manda lo pendiente y baja cotización y presupuesto. Cada pedido falla por su cuenta: sin señal la pantalla sigue con lo local. */
  async function refrescar() {
    ctx.sincronizando = true;
    ctx.aviso = "";
    ctx.sesionVencida = false;
    pintar();
    const hoy = fechaLocal();
    const [sync, cotizacion, resumen] = await Promise.allSettled([
      sincronizar(), apiConTimeout("/api/gastos/cotizacion"), apiConTimeout(`/api/gastos?desde=${hoy}&hasta=${hoy}`)]);
    if (cotizacion.status === "fulfilled") await guardarMeta("cotizacion", { ...cotizacion.value, leido_en: Date.now() });
    if (resumen.status === "fulfilled" && resumen.value.presupuesto) await guardarMeta("presupuesto", resumen.value.presupuesto);
    const falla = [sync, cotizacion, resumen].find((r) => r.status === "rejected");
    ctx.sesionVencida = Boolean(falla) && esSesionVencida(falla.reason);
    ctx.aviso = !falla ? "" : sinServicio(falla.reason) && falla.reason.status === 0 ? MSG_SIN_SENAL : textoError(falla.reason);
    ctx.sincronizando = false;
    await recargar();
  }

  const alCambiar = () => { if (raiz.isConnected) recargar().catch(console.warn); else oyentes.delete(alCambiar); };
  oyentes.add(alCambiar);
  await asegurarDueno().catch((e) => { ctx.sesionVencida = esSesionVencida(e); });   // la lista de otra persona no se muestra
  await recargar();
  refrescar().catch((e) => { ctx.aviso = textoError(e); ctx.sincronizando = false; pintar(); });
}
