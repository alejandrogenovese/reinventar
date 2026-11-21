// Admin: piezas comunes de las pestañas: marco con barra de pestañas, carga independiente (cargando / error con
// Reintentar / vacío), botón ocupado, confirmación y región viva para que los lectores de pantalla oigan los avisos.
import { confirmDialog } from "./dialog.js";
import { PESTANAS } from "./adminTextos.js";
import { Button, h, mensajeError, toast } from "./ui.js";

let regionEstado = null;
let regionAlerta = null;

/** Avisa a los lectores de pantalla (y con el toast, a todos). Los errores se anuncian con más urgencia. */
export function avisar(texto, { error = false } = {}) {
  toast(texto);
  const region = error ? regionAlerta : regionEstado;
  if (!region) return;
  region.textContent = "";
  setTimeout(() => { region.textContent = texto; }, 50); // vaciar y volver a escribir hace que repita un aviso igual
}

/** Barra de pestañas pegada arriba: cada una es una ruta (links, no botones) y la actual lleva aria-current. */
export const AdminTabs = (actual) => h("nav", { class: "tabs admin-tabs", "aria-label": "Secciones de administración" },
  PESTANAS.map(([id, etiqueta, ruta]) => h("a", { class: "ra-tab", href: ruta, "aria-current": id === actual ? "page" : null }, etiqueta)));

/** Marco común: título, pestañas, regiones vivas y el contenido de la pestaña. */
export function AdminShell(view, actual, ...contenido) {
  regionEstado = h("div", { class: "sr-only", role: "status", "aria-live": "polite", "aria-atomic": "true" });
  regionAlerta = h("div", { class: "sr-only", role: "alert", "aria-live": "assertive", "aria-atomic": "true" });
  view.append(h("div", { class: "stack-lg" }, h("h1", { class: "title" }, "Administración"), AdminTabs(actual), regionEstado, regionAlerta, ...contenido));
}

/**
 * Un bloque que carga solo lo suyo: «Cargando…», el contenido, un error con Reintentar o un texto de vacío.
 * `recargar({ silencioso })` repinta; en silencio no muestra «Cargando…» y, si falla, deja lo que ya había.
 */
export function Cargable({ cargar, pintar, esVacio = () => false, textoVacio = "No hay nada para mostrar.", textoCargando = "Cargando…" }) {
  const box = h("div", { class: "stack", "aria-busy": "true" });
  let turno = 0;
  async function recargar({ silencioso = false } = {}) {
    const mio = ++turno;
    if (!silencioso) {
      box.setAttribute("aria-busy", "true");
      box.replaceChildren(h("p", { class: "caption" }, textoCargando));
    }
    try {
      const datos = await cargar();
      if (mio !== turno) return;
      box.replaceChildren(...[esVacio(datos) ? h("p", { class: "caption" }, textoVacio) : pintar(datos)].flat().filter(Boolean));
    } catch (err) {
      if (mio !== turno || silencioso) return;
      box.replaceChildren(h("div", { class: "notice err", role: "alert" },
        h("p", {}, mensajeError(err)), Button("Reintentar", { onclick: () => recargar() })));
    }
    box.setAttribute("aria-busy", "false");
  }
  box.recargar = recargar;
  void recargar();
  return box;
}

/** Corre `accion` con el botón deshabilitado y aria-busy: evita el doble toque. Si ya está ocupado, no hace nada. */
export async function conOcupado(boton, accion) {
  if (boton.disabled) return undefined;
  boton.disabled = true;
  boton.setAttribute("aria-busy", "true");
  try { return await accion(); }
  finally {
    boton.disabled = false;
    boton.removeAttribute("aria-busy");
  }
}

/** Confirmación accesible (<dialog>) antes de algo que no se deshace. */
export const confirmar = (titulo, texto, etiqueta) => confirmDialog(titulo, { text: texto, confirmLabel: etiqueta, danger: true });
