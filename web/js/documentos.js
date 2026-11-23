// Documentos de viaje (#/viajes/documentos): pasaporte, ESTA o visa, seguro, reservas, entrada de re:Invent, tarjeta de
// embarque. El servidor los guarda cifrados y solo los entrega con sesión (app/documentos_api.py); acá se ven por fetch →
// blob → objectURL, nunca con un link directo. Sin señal: la lista sale de la última copia (solo metadatos) y el archivo
// solo si la persona lo guardó en este teléfono (docsLocal.js, cifrado).
import { ApiError, Documentos, sinServicio } from "./api.js";
import { confirmDialog } from "./dialog.js";
import { borrarDocsLocales, guardadosLocales, guardarLocal, leerLocal, quitarLocal } from "./docsLocal.js";
import { staleAt } from "./lastgood.js";
import { Button, Hint, h, mensajeError, toast } from "./ui.js";

export const TIPOS = {
  pasaporte: "Pasaporte", esta_visa: "ESTA o visa", seguro: "Seguro de viaje", reserva: "Reserva",
  entrada_reinvent: "Entrada a re:Invent", tarjeta_embarque: "Tarjeta de embarque", otro: "Otro",
};
const ACEPTA = "image/jpeg,image/png,image/webp,application/pdf";
const MAX_BYTES = 8 * 1024 * 1024;
const TITULO_MAX = 80;
const NOTAS_MAX = 500;
const URL_VIVE_MS = 5 * 60 * 1000; // el objectURL de un PDF abierto en otra pestaña se suelta después de un rato

/** «7/12/2026» de un ISO de fecha (sin pasar por zonas horarias). */
export const fechaCorta = (iso) => { const [a, m, d] = String(iso).split("-"); return `${Number(d)}/${Number(m)}/${a}`; };

/** Si la copia del teléfono coincide con el archivo del servidor: «ok», «vieja» o null (no está guardado). */
export const estadoLocal = (doc, locales) => (doc.id in locales ? (locales[doc.id] === doc.sha256 ? "ok" : "vieja") : null);

/** Valida el archivo elegido antes de mandarlo (el servidor igual lo vuelve a validar). Devuelve el error o null. */
export function errorDeArchivo(archivo) {
  if (!archivo) return "Elegí una foto o un PDF.";
  if (archivo.size > MAX_BYTES) return "El archivo pesa más de 8 MB.";
  if (archivo.type && !ACEPTA.split(",").includes(archivo.type)) return "Tiene que ser una foto (JPEG, PNG o WebP) o un PDF.";
  return null;
}

let _campos = 0;
const Campo = (etiqueta, control) => {
  control.id = control.id || `docs-campo-${++_campos}`;
  return h("div", { class: "field" }, h("label", { class: "label", for: control.id }, etiqueta), control);
};

/** Campos de metadatos; con `doc`, precargados para editar. */
function camposMeta(doc = null) {
  const tipo = h("select", { required: true },
    Object.entries(TIPOS).map(([v, t]) => h("option", { value: v, selected: doc?.tipo === v }, t)));
  const titulo = h("input", { required: true, maxlength: TITULO_MAX, value: doc?.titulo ?? "", placeholder: "Ej.: Pasaporte, Seguro Assist Card" });
  const vence = h("input", { type: "date", value: doc?.vence ?? "" });
  const notas = h("textarea", { maxlength: NOTAS_MAX, rows: 2 });
  notas.value = doc?.notas ?? "";
  const valores = () => ({ tipo: tipo.value, titulo: titulo.value.trim(), vence: vence.value || null, notas: notas.value.trim() });
  const nodos = [Campo("Tipo", tipo), Campo("Título", titulo), Campo("Vence (opcional)", vence), Campo("Notas (opcional)", notas),
    Hint("No escribas el número de pasaporte en las notas.", { tone: "warn" })];
  return { nodos, valores };
}

/** Dos maneras de elegir el archivo: sacar una foto (abre la cámara) o elegir uno (foto o PDF). */
function ElegirArchivo() {
  let elegido = null;
  const nombre = h("p", { class: "caption" }, "Todavía no elegiste un archivo.");
  const alElegir = (e) => { elegido = e.target.files?.[0] ?? null; nombre.textContent = elegido ? "Archivo listo para subir." : "Todavía no elegiste un archivo."; };
  const camara = h("input", { type: "file", accept: "image/*", capture: "environment", hidden: true, onchange: alElegir });
  const archivo = h("input", { type: "file", accept: ACEPTA, hidden: true, onchange: alElegir });
  const nodo = h("div", { class: "stack" }, h("div", { class: "actions" },
    Button("Sacar foto", { type: "button", onclick: () => camara.click() }),
    Button("Elegir archivo", { type: "button", onclick: () => archivo.click() })), camara, archivo, nombre);
  return { nodo, archivo: () => elegido };
}

function FormAlta(onGuardado) {
  const meta = camposMeta();
  const eleccion = ElegirArchivo();
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const archivo = eleccion.archivo();
    const error = errorDeArchivo(archivo);
    if (error) { toast(error); return; }
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    const datos = new FormData();
    for (const [k, v] of Object.entries(meta.valores())) datos.append(k, v ?? "");
    datos.append("archivo", archivo, "documento");
    try { await Documentos.create(datos); } catch (err) { toast(mensajeError(err)); btn.disabled = false; return; }
    toast("Documento guardado.");
    await onGuardado();
  } }, ...meta.nodos, eleccion.nodo, h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Subir documento"));
  return form;
}

function FormEdicion(doc, alTerminar) {
  const meta = camposMeta(doc);
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    try { await Documentos.edit(doc.id, meta.valores()); } catch (err) { toast(mensajeError(err)); return; }
    toast("Documento actualizado.");
    await alTerminar();
  } }, ...meta.nodos, h("div", { class: "actions" },
    h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Guardar cambios"),
    Button("Cancelar", { type: "button", onclick: () => alTerminar() })));
  return h("article", { class: "ra-card stack", id: `doc-${doc.id}` }, h("h2", { class: "label" }, "Editar documento"), form);
}

/** Muestra el archivo: imagen en <img>; PDF como link al blob (abrir o descargar). */
function Visor(blob, alCerrar) {
  const url = URL.createObjectURL(blob);
  const cerrar = () => { URL.revokeObjectURL(url); alCerrar(); };
  if (blob.type === "application/pdf") {
    setTimeout(() => URL.revokeObjectURL(url), URL_VIVE_MS);
    return h("div", { class: "stack" },
      h("a", { class: "ra-btn ra-btn-primary", href: url, target: "_blank", rel: "noopener", download: "documento.pdf" }, "Abrir el PDF"),
      Button("Cerrar", { onclick: () => alCerrar() }));
  }
  return h("div", { class: "stack" }, h("img", { src: url, alt: "Documento", style: { maxWidth: "100%", height: "auto" } }),
    Button("Cerrar", { onclick: cerrar }));
}

async function obtenerArchivo(doc, local) {
  if (local === "ok") {
    try { const blob = await leerLocal(doc.id); if (blob) return blob; } catch (err) { console.warn("[documentos] copia local ilegible", err); }
  }
  return Documentos.file(doc.id);
}

function DocCard(doc, { local, sinSenal, acciones }) {
  const visor = h("div");
  const ver = async () => {
    try { visor.replaceChildren(Visor(await obtenerArchivo(doc, local), () => visor.replaceChildren())); }
    catch (err) { toast(sinServicio(err) ? "Sin señal: este documento no está guardado en el teléfono." : mensajeError(err)); }
  };
  const puedeVer = !sinSenal || local === "ok";
  const etiquetaLocal = local === "ok" ? "Disponible sin señal" : local === "vieja" ? "La copia del teléfono es vieja: guardala de nuevo" : null;
  return h("article", { class: "ra-card stack", id: `doc-${doc.id}` },
    h("div", { class: "ra-card-top" }, h("span", { class: "ra-card-title" }, doc.titulo), h("span", { class: "ra-tag" }, TIPOS[doc.tipo] ?? "Otro")),
    h("div", { class: "ra-card-meta" },
      doc.vence ? h("span", {}, `Vence el ${fechaCorta(doc.vence)}`) : null,
      etiquetaLocal ? h("span", { class: "ra-tag" }, etiquetaLocal) : null),
    doc.alerta ? Hint(doc.alerta, { tone: "warn" }) : null,
    doc.notas ? h("p", { class: "caption" }, doc.notas) : null,
    h("div", { class: "actions" },
      puedeVer ? Button("Ver", { onclick: ver }) : h("span", { class: "caption" }, "Sin señal: no está guardado en el teléfono"),
      !sinSenal && local !== "ok" ? Button("Guardar en este teléfono", { onclick: acciones.guardarLocal }) : null,
      local ? Button("Quitar del teléfono", { onclick: acciones.quitarLocal }) : null,
      !sinSenal ? Button("Editar", { onclick: acciones.editar }) : null,
      !sinSenal ? Button("Borrar", { variant: "danger", onclick: acciones.borrar }) : null),
    visor);
}

export async function viewDocumentos(view) {
  const raiz = h("div");
  view.append(raiz);
  async function paint() {
    let data;
    try { data = await Documentos.list(); } catch (err) {
      if (!raiz.isConnected) return;
      const texto = err instanceof ApiError && err.status === 503 ? mensajeError(err) : sinServicio(err)
        ? "Sin señal y sin una copia de tus documentos en este teléfono." : mensajeError(err);
      raiz.replaceChildren(h("div", { class: "stack-lg" }, h("h1", { class: "title" }, "Documentos de viaje"), Hint(texto, { tone: "warn" })));
      return;
    }
    const locales = await guardadosLocales();
    if (!raiz.isConnected) return;
    const sinSenal = staleAt(data) !== null;
    const accionesDe = (doc) => ({
      guardarLocal: async () => {
        try { await guardarLocal(doc.id, await Documentos.file(doc.id), { tipo: doc.archivo_tipo, sha256: doc.sha256 }); }
        catch (err) { toast(mensajeError(err)); return; }
        toast("Guardado en este teléfono: lo vas a poder ver sin señal.");
        await paint();
      },
      quitarLocal: async () => {
        try { await quitarLocal(doc.id); } catch (err) { toast(mensajeError(err)); return; }
        toast("Lo quitamos del teléfono.");
        await paint();
      },
      editar: () => {
        const card = FormEdicion(doc, paint);
        document.getElementById(`doc-${doc.id}`)?.replaceWith(card);
        card.querySelector("input")?.focus();
      },
      borrar: async () => {
        if (!(await confirmDialog("¿Borrar este documento?", { text: "Se borra del servidor y de este teléfono.", confirmLabel: "Borrar", danger: true }))) return;
        try { await Documentos.remove(doc.id); await quitarLocal(doc.id).catch(() => {}); } catch (err) { toast(mensajeError(err)); return; }
        toast("Documento borrado.");
        await paint();
      },
    });
    const borrarTodos = async () => {
      if (!(await confirmDialog("¿Borrar todos tus documentos?", { text: "Se borran del servidor y de este teléfono. No se puede deshacer.", confirmLabel: "Borrar todos", danger: true }))) return;
      try { await Documentos.removeAll(); await borrarDocsLocales(); } catch (err) { toast(mensajeError(err)); return; }
      toast("Borramos todos tus documentos.");
      await paint();
    };
    const docs = data.documentos ?? [];
    const lleno = docs.length >= (data.max ?? Infinity);
    raiz.replaceChildren(h("div", { class: "stack-lg" },
      h("a", { class: "ra-link", href: "#/viajes" }, "← Viajes"),
      h("h1", { class: "title" }, "Documentos de viaje"),
      sinSenal ? Hint("Sin señal: ves la última lista que se cargó. Solo podés abrir los documentos guardados en este teléfono.", { tone: "warn" }) : null,
      h("p", { class: "caption" }, "Solo vos los ves. Se guardan cifrados y se borran solos el ",
        data.borrado_automatico ? fechaCorta(data.borrado_automatico) : "", " (30 días después del viaje). «Guardar en este teléfono» deja una copia cifrada para verla sin señal; se borra al cerrar sesión."),
      h("section", { class: "stack" },
        docs.length ? docs.map((d) => DocCard(d, { local: estadoLocal(d, locales), sinSenal, acciones: accionesDe(d) }))
          : h("p", { class: "caption" }, "Todavía no subiste documentos.")),
      !sinSenal && !lleno ? h("details", { class: "stack", open: !docs.length }, h("summary", { class: "label" }, "Subir un documento"), FormAlta(paint)) : null,
      lleno ? Hint(`Llegaste al máximo de ${data.max} documentos.`) : null,
      !sinSenal && docs.length ? Button("Borrar todos mis documentos", { variant: "danger", onclick: borrarTodos }) : null));
  }
  await paint();
}
