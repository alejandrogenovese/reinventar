// Gastos: control de gastos del viaje. Se carga en segundos y sin señal: el gasto se guarda en el celular (gastosCola.js)
// y se manda solo al volver la red. Pantalla #/gastos: resumen contra presupuesto, cotizaciones, categorías y lista.
import { ApiError, api, getToken, sinServicio } from "./api.js";
import { Bars, dayLong, dec, int } from "./charts.js";
import { confirmDialog } from "./dialog.js";
import { icon } from "./icons.js";
import {
  CALIDAD_JPEG, CATEGORIAS, TOPE_FOTO_BYTES, aCambio, borrarFoto, borrarGasto, contarIntentoFoto, crearGasto, editarGasto, escalarLado, fechaLocal,
  fotosPendientes, gastosPendientes, guardarFoto, guardarGasto, guardarGastos, guardarMeta, leerGasto, leerMeta, listarGastos, marcarAplicado,
  mezclarServidor, parsearMonto, partirEnLotes, reemplazarPerdido, totales, usdDe, visibles,
} from "./gastosCola.js";
import { Button, Hint, h, mensajeError, toast, toastOnError } from "./ui.js";

const SYNC_CADA_MS = 60_000;
const LOTE_SYNC = 200;             // tope de gastos por pedido de /sync del servidor
const AVISO_AMBAR = 0.8;           // desde acá la barra se pone ámbar; al pasarse del 100 %, roja
const MAX_INTENTOS_FOTO = 5;       // con un error del servidor (4xx) la foto se abandona tras tantos intentos
const CALIDAD_MINIMA = 0.3;
const PASO_CALIDAD = 0.1;
const ACTIVO = "reinventar.gastos";  // marca que el usuario ya usó Gastos: desde entonces la app sincroniza sola al abrir

const ETIQUETAS = { comida: "Comida", transporte: "Transporte", shows: "Shows", compras: "Compras", otros: "Otros" };
const MSG_SIN_SENAL = "Sin señal: los gastos quedan en el celular y se mandan solos cuando vuelva la red.";
const MSG_NO_DISPONIBLE = "Gastos todavía no está disponible en el servidor.";

const usd = (n) => `US$ ${dec(n, 2)}`;
const ars = (n) => `$ ${int(Math.round(n))}`;
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const textoError = (e) => (e instanceof ApiError && e.status === 404 ? MSG_NO_DISPONIBLE : mensajeError(e));

// ---------- sincronización ----------

const oyentes = new Set();
let enCurso = null;
let iniciado = false;

const avisar = () => { for (const f of [...oyentes]) f(); };

async function subirFotos() {
  for (const foto of await fotosPendientes()) {
    const gasto = await leerGasto(foto.client_id);
    if (!gasto || gasto.pendiente) continue;                       // el gasto todavía no llegó al servidor: la foto va después
    if (gasto.deleted_at) { await borrarFoto(foto.client_id); continue; }
    try {
      const cuerpo = new FormData();
      cuerpo.append("foto", foto.blob, "ticket.jpg");
      const r = await api(`/api/gastos/${foto.client_id}/foto`, { method: "POST", body: cuerpo });
      await guardarGasto({ ...(await leerGasto(foto.client_id)), foto_url: r.foto_url });
      await borrarFoto(foto.client_id);
    } catch (e) {
      const rechazada = e instanceof ApiError && e.status >= 400 && e.status < 500 && ![401, 403, 408, 429].includes(e.status);
      if (rechazada && foto.intentos + 1 >= MAX_INTENTOS_FOTO) { await borrarFoto(foto.client_id); toast(`No se pudo subir la foto de un ticket: ${textoError(e)}`); }
      else await contarIntentoFoto(foto);
    }
  }
}

/** Aplica la respuesta de un /sync: marca los aplicados, reemplaza los que perdieron el conflicto y mezcla lo nuevo del servidor. */
async function aplicarRespuesta(lote, r) {
  const enviados = new Map(lote.map((g) => [g.client_id, g]));
  const aplicados = new Set(r.aplicados ?? []);
  for (const id of aplicados) {
    const actual = await leerGasto(id);
    if (actual && enviados.has(id)) await guardarGasto(marcarAplicado(actual, enviados.get(id)));
  }
  const nuevos = [];
  for (const delServidor of r.cambios ?? []) {
    const local = await leerGasto(delServidor.client_id);
    const enviado = enviados.get(delServidor.client_id);
    const resultado = enviado && !aplicados.has(delServidor.client_id) ? reemplazarPerdido(local, enviado, delServidor) : mezclarServidor(local, delServidor);
    if (resultado) nuevos.push(resultado);
  }
  await guardarGastos(nuevos);
}

async function hacerSync() {
  if (!getToken()) return;
  let desde = await leerMeta("ultimoSync");
  const lotes = partirEnLotes(await gastosPendientes(), LOTE_SYNC);
  for (const lote of lotes.length ? lotes : [[]]) {
    const r = await api("/api/gastos/sync", { method: "POST", json: { cambios: lote.map(aCambio), desde } });
    await aplicarRespuesta(lote, r);
    desde = r.ahora;  // el cursor es el reloj del servidor (`ahora`), nunca el del teléfono
  }
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

/** Hoja que sube desde abajo en el celular (la misma de los filtros): título, cuerpo con scroll y pie con acciones. */
function Hoja(idTitulo, titulo, cuerpo, pie) {
  const opener = document.activeElement;
  const dlg = h("dialog", { class: "ra-sheet", "aria-labelledby": idTitulo },
    h("div", { class: "ra-sheet-head" },
      h("h2", { class: "ra-dialog-title", id: idTitulo }, titulo),
      h("button", { type: "button", class: "iconbtn", "aria-label": `Cerrar ${titulo.toLowerCase()}`, onclick: () => dlg.close() }, icon("cerrar", 24))),
    h("div", { class: "ra-sheet-body" }, cuerpo),
    h("div", { class: "ra-sheet-foot actions" }, pie));
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener("close", () => { dlg.remove(); if (opener?.isConnected) opener.focus(); });
  document.body.append(dlg);
  dlg.showModal();
  return dlg;
}

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

  const monto = h("input", { id: "g-monto", type: "text", inputmode: "decimal", autocomplete: "off", "aria-label": "Monto", placeholder: "0",
    value: gasto ? String(gasto.monto).replace(".", ",") : "", oninput: () => estimar() });
  const estimado = h("p", { class: "ra-g-estimado", "aria-live": "polite" });
  const nota = h("input", { id: "g-nota", type: "text", maxlength: 200, autocomplete: "off", value: gasto?.nota ?? "" });
  const fecha = h("input", { id: "g-fecha", type: "date", value: gasto?.fecha ?? fechaLocal() });
  const error = h("p", { class: "notice err", role: "alert", hidden: true });
  const miniatura = h("span", { class: "caption" });
  let cerrada = false;
  const urlsDeFotos = [];   // blobs de las fotos que se muestran: se sueltan al cerrar la hoja
  const archivo = h("input", { type: "file", accept: "image/*", capture: "environment", id: "g-foto", tabindex: "-1", "aria-hidden": "true",
    onchange: async () => {
      const elegido = archivo.files?.[0];
      if (!elegido) return;
      try {
        foto = await achicarFoto(elegido);
        if (vistaPrevia) URL.revokeObjectURL(vistaPrevia);
        vistaPrevia = URL.createObjectURL(foto);
        miniatura.replaceChildren(h("img", { src: vistaPrevia, alt: "Foto del ticket" }), `${dec(foto.size / 1024, 0)} KB`);
        error.hidden = true;
      } catch (e) { mostrarError(mensajeError(e, "No se pudo leer la foto. Probá con otra.")); }
    } });

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
    if (Number.isNaN(n)) { mostrarError("Poné un monto mayor a cero, por ejemplo 14,10."); monto.focus(); return; }
    const datos = { fecha: fecha.value || fechaLocal(), monto: n, moneda, categoria, nota: nota.value.trim(), reintegrable, compartido };
    const nuevo = gasto ? editarGasto(gasto, datos) : crearGasto(datos);
    try {
      await guardarGasto(nuevo);
      if (foto) await guardarFoto(nuevo.client_id, foto);
    } catch (e) { mostrarError(mensajeError(e, "No se pudo guardar en el celular. Revisá el espacio y probá de nuevo.")); return; }
    dlg.close();
    alGuardar();
    sincronizarEnSilencio();
  }

  async function borrar() {
    if (!await confirmDialog("¿Borrar este gasto?", { text: "Se saca de la lista y del total.", confirmLabel: "Borrar", danger: true })) return;
    await guardarGasto(borrarGasto(gasto));
    dlg.close();
    alGuardar();
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
      h("label", { class: "ra-btn ra-btn-secondary", for: "g-foto" }, "Foto del ticket", archivo),
      miniatura),
    error);

  const dlg = Hoja("g-carga-titulo", gasto ? "Editar gasto" : "Nuevo gasto", cuerpo, [
    gasto ? Button("Borrar", { variant: "danger", onclick: () => toastOnError(borrar()) }) : Button("Cancelar", { onclick: () => dlg.close() }),
    Button("Guardar gasto", { variant: "primary", onclick: () => toastOnError(guardar()) })]);
  dlg.addEventListener("close", () => {
    cerrada = true;
    for (const url of [vistaPrevia, ...urlsDeFotos]) if (url) URL.revokeObjectURL(url);
  });
  if (gasto?.foto_url) mostrarFotoGuardada(gasto.foto_url);
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
  const url = URL.createObjectURL(await r.blob());
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
  return h("section", { class: "stack" },
    h("div", { class: "ra-sec-head" }, h("h2", { class: "label" }, "Cotización"), h("span", { class: "caption" }, hora ? `ARS por USD · ${hora}` : "ARS por USD · sin datos")),
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
  if (gasto.pendiente) marcas.push(h("span", { class: "ra-g-marca is-pendiente" }, "Sin sincronizar"));
  return h("button", { type: "button", class: "ra-g-fila", onclick: alTocar },
    h("span", { class: "ra-g-fila-titulo" }, gasto.nota || ETIQUETAS[gasto.categoria]),
    h("span", { class: "ra-g-fila-monto" }, u == null ? "Sin cotización" : usd(u)),
    h("span", { class: "ra-g-marcas" }, marcas),
    h("span", { class: "ra-g-fila-sub" }, gasto.moneda === "ARS" ? ars(gasto.monto) : ""));
}

function Lista(gastos, t, ctx) {
  if (!gastos.length) {
    return h("div", { class: "empty" }, h("p", {}, "Todavía no cargaste gastos."), h("p", { class: "caption" }, "Tocá «Cargar gasto»: anda también sin señal."));
  }
  const dias = Map.groupBy(gastos, (g) => g.fecha);
  return [...dias].map(([dia, items]) => h("div", { class: "ra-g-dia" },
    h("div", { class: "ra-g-dia-head" }, h("h2", { class: "label" }, capital(dayLong(dia))), h("span", { class: "caption" }, usd(t.porDia[dia] ?? 0))),
    items.map((g) => Fila(g, { tarjeta: ctx.tarjeta, conFotoPendiente: ctx.fotos.has(g.client_id), alTocar: () => abrirCarga({ gasto: g, tarjeta: ctx.tarjeta, alGuardar: ctx.recargar }) }))));
}

// ---------- pantalla ----------

export async function viewGastos(view) {
  activarSync();
  const raiz = h("div", { class: "ra-g" });
  view.append(raiz);
  const ctx = { gastos: [], fotos: new Set(), cotiz: null, presupuesto: null, tarjeta: null, aviso: "", sincronizando: false, recargar };

  async function recargar() {
    const [todos, fotos, cotiz, presupuesto] = await Promise.all([listarGastos(), fotosPendientes(), leerMeta("cotizacion"), leerMeta("presupuesto")]);
    Object.assign(ctx, { gastos: todos, fotos: new Set(fotos.map((f) => f.client_id)), cotiz, presupuesto, tarjeta: cotiz?.tarjeta ?? null });
    pintar();
  }

  function pintar() {
    const lista = visibles(ctx.gastos);
    const t = totales(lista, ctx.tarjeta);
    const pendientes = lista.filter((g) => g.pendiente).length;
    raiz.replaceChildren(...[
      h("a", { class: "ra-btn ra-btn-ghost ra-back", href: "#/ajustes" }, icon("volver", 16), h("span", {}, "Ajustes")),
      h("div", { class: "ra-g-head" }, h("h1", { class: "title" }, "Gastos"),
        Button("Cargar gasto", { variant: "primary", onclick: () => abrirCarga({ tarjeta: ctx.tarjeta, alGuardar: recargar }) })),
      ctx.aviso ? Hint(ctx.aviso, { tone: "warn" }) : null,
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
    pintar();
    const hoy = fechaLocal();
    const [sync, cotizacion, resumen] = await Promise.allSettled([
      sincronizar(), api("/api/gastos/cotizacion"), api(`/api/gastos?desde=${hoy}&hasta=${hoy}`)]);
    if (cotizacion.status === "fulfilled") await guardarMeta("cotizacion", cotizacion.value);
    if (resumen.status === "fulfilled" && resumen.value.presupuesto) await guardarMeta("presupuesto", resumen.value.presupuesto);
    const falla = [sync, cotizacion, resumen].find((r) => r.status === "rejected");
    ctx.aviso = !falla ? "" : sinServicio(falla.reason) && falla.reason.status === 0 ? MSG_SIN_SENAL : textoError(falla.reason);
    ctx.sincronizando = false;
    await recargar();
  }

  const alCambiar = () => { if (raiz.isConnected) recargar().catch(console.warn); else oyentes.delete(alCambiar); };
  oyentes.add(alCambiar);
  await recargar();
  refrescar().catch((e) => { ctx.aviso = textoError(e); ctx.sincronizando = false; pintar(); });
}
