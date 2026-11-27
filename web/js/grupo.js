// «También van» (app/grupo_api.py): en la ficha de una charla, quién más del grupo tiene ese horario en su itinerario, para
// coordinar quién graba qué. Y el interruptor de Ajustes para no mostrar la propia agenda. Solo se ven nombres de usuario.
import { api } from "./api.js";
import { h, mensajeError, toast } from "./ui.js";

const CODIGOS_POR_PEDIDO = 20;  // el tope del servidor

export const Grupo = {
  tambienVan: (codes) => api(`/api/grupo/tambien-van?codes=${codes.map(encodeURIComponent).join(",")}`),
  prefs: () => api("/api/grupo/preferencia"),
  savePrefs: (agendaVisible) => api("/api/grupo/preferencia", { method: "PUT", json: { agenda_visible: agendaVisible } }),
};

/** {código: [usuarios]} de los horarios de una charla. Es accesorio: sin señal o con error, vacío (la ficha se ve igual). */
export async function tambienVanDe(codes) {
  const lista = [...new Set(codes)].slice(0, CODIGOS_POR_PEDIDO);
  if (!lista.length) return {};
  try { return await Grupo.tambienVan(lista); } catch { return {}; }
}

/** «Ana», «Ana y Beto», «Ana, Beto y Caro». */
export function listaDeNombres(nombres) {
  if (nombres.length <= 1) return nombres.join("");
  return `${nombres.slice(0, -1).join(", ")} y ${nombres.at(-1)}`;
}

/** El renglón del horario, o null si no va nadie más del grupo. */
export const TambienVan = (nombres) => (nombres?.length
  ? h("span", { class: "caption" }, `También van: ${listaDeNombres(nombres)}`)
  : null);

/** «No mostrar mi agenda al grupo» para Ajustes (apagado por defecto: la agenda se ve). */
export function GrupoSettings() {
  const input = h("input", { type: "checkbox", id: "grupo-ocultar-agenda", disabled: true });
  input.onchange = async () => {
    input.disabled = true;
    try { await Grupo.savePrefs(!input.checked); toast(input.checked ? "Listo: el grupo ya no ve tus charlas." : "Listo: el grupo ve qué charlas tenés."); }
    catch (err) { input.checked = !input.checked; toast(mensajeError(err)); }
    input.disabled = false;
  };
  void Grupo.prefs().then((p) => { input.checked = p.agenda_visible === false; input.disabled = false; }).catch(() => {});
  return h("div", { class: "stack" },
    h("h2", { class: "label" }, "Grupo"),
    h("label", { class: "actions is-center", for: input.id }, input, "No mostrar mi agenda al grupo"),
    h("p", { class: "caption" }, "En la ficha de cada charla, los demás ven tu usuario si tenés ese horario en tu itinerario (así se reparten quién graba qué). Nada más de tu agenda."));
}
