// «Charlas nuevas»: las que AWS sumó al catálogo en los últimos días y todavía no pasaron (app/charlas_nuevas.py). Acá la
// API, los textos, la tarjeta chica de Inicio y del itinerario y el interruptor del aviso en Ajustes; la pantalla de la
// lista (#/itinerario/nuevas) está en charlasNuevasVista.js. Este archivo no importa itinerary.js: lo usan Ajustes e itinerary.js.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { h, mensajeError, toast } from "./ui.js";

export const RUTA = "#/itinerario/nuevas";

export const CharlasNuevas = {
  list: () => api("/api/charlas-nuevas"),
  add: (code) => api("/api/charlas-nuevas/agregar", { method: "POST", json: { code } }),
  discard: (base) => api(`/api/charlas-nuevas/${encodeURIComponent(base)}/descartar`, { method: "POST" }),
  prefs: () => api("/api/charlas-nuevas/preferencia"),
  savePrefs: (avisar) => api("/api/charlas-nuevas/preferencia", { method: "PUT", json: { avisar } }),
};

/** «1 charla nueva» / «3 charlas nuevas». */
export const textoCantidad = (n) => `${n} charla${n === 1 ? "" : "s"} nueva${n === 1 ? "" : "s"}`;

/** Lo que dice el toast al agregar: si se superpone, con qué. */
export const textoAgregada = (choques = []) => (choques.length
  ? `Agregada a tu agenda. Se superpone con ${choques.join(", ")}.`
  : "Agregada a tu agenda.");

/** Tarjeta chica para Inicio y el itinerario: solo si hay charlas nuevas por ver (si no, o si falla, null). */
export async function CharlasNuevasAviso() {
  try {
    const { total } = await CharlasNuevas.list();
    if (!total) return null;
    return h("a", { class: "notice actions", href: RUTA, "aria-label": `${textoCantidad(total)} en el catálogo. Ver la lista.` },
      icon("itinerario", 20), h("span", {}, h("strong", {}, textoCantidad(total)), " en el catálogo de re:Invent"), icon("seguir", 16));
  } catch { return null; }
}

/** «Avisarme de charlas nuevas» para Ajustes (prendido por defecto). */
export function CharlasNuevasSettings() {
  const input = h("input", { type: "checkbox", id: "push-charlas-nuevas", disabled: true });
  input.onchange = async () => {
    input.disabled = true;
    try { await CharlasNuevas.savePrefs(input.checked); } catch (err) { input.checked = !input.checked; toast(mensajeError(err)); }
    input.disabled = false;
  };
  void CharlasNuevas.prefs().then((p) => { input.checked = p.avisar !== false; input.disabled = false; }).catch(() => {});
  return h("div", { class: "stack" },
    h("label", { class: "actions is-center", for: input.id }, input, "Avisarme de charlas nuevas"),
    h("p", { class: "caption" }, "Un solo aviso cuando AWS suma charlas al catálogo, primero las de tus intereses (nunca de noche)."));
}
