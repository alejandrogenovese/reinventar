// Admin › Ofertas (#/admin/ofertas): cargar a mano una oferta (comida, happy hour, outlet) con su vigencia y darla de baja.
// El push sale cuando arranca la vigencia. Las bajas de precio de shows entran solas (app/ofertas.py). Solo admin: el servidor lo exige.
import { api } from "./api.js";
import { Hint, h, mensajeError, toast } from "./ui.js";

const CATEGORIAS = { comida: "Comida", compras: "Compras y outlets", shows: "Shows", otros: "Otros" };
const cuando = (iso) => new Date(iso).toLocaleString("es-AR", { timeZone: "America/Los_Angeles", weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }).replaceAll(".", "");

const campo = (id, label, attrs = {}) => {
  const el = h("input", { id, name: id, ...attrs });
  return { el, row: h("div", { class: "field" }, h("label", { class: "label", for: id }, label), el) };
};

function Formulario(onSaved) {
  const titulo = campo("of-titulo", "Título", { required: true, minlength: 2, maxlength: 120, placeholder: "2x1 en tragos" });
  const categoria = h("select", { id: "of-categoria", name: "of-categoria" }, Object.entries(CATEGORIAS).map(([v, n]) => h("option", { value: v }, n)));
  const lugar = campo("of-lugar", "Lugar", { maxlength: 120, placeholder: "Bar del lobby, Venetian" });
  const desde = campo("of-desde", "Empieza (hora de Las Vegas)", { type: "datetime-local", required: true });
  const hasta = campo("of-hasta", "Termina (hora de Las Vegas)", { type: "datetime-local" });
  const link = campo("of-link", "Link (opcional)", { type: "url", placeholder: "https://…", pattern: "https://.*" });
  const nota = h("textarea", { id: "of-nota", rows: 3, maxlength: 400 });
  const guardar = h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Guardar oferta");
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    guardar.disabled = true;
    const datos = { titulo: titulo.el.value.trim(), categoria: categoria.value, lugar: lugar.el.value.trim() || null, desde: desde.el.value,
      hasta: hasta.el.value || null, link: link.el.value.trim() || null, nota: nota.value.trim() || null };
    try {
      await api("/api/ofertas/admin", { method: "POST", json: datos });
      toast(`Guardada: ${datos.titulo}`);
      form.reset();
      onSaved();
    } catch (err) { toast(mensajeError(err)); }
    guardar.disabled = false;
  } },
    h("h2", { class: "label" }, "Cargar una oferta"),
    h("p", { class: "caption" }, "El aviso sale cuando arranca la vigencia, a quienes tienen las alertas de esa categoría."),
    titulo.row, h("div", { class: "field" }, h("label", { class: "label", for: "of-categoria" }, "Categoría"), categoria),
    lugar.row, desde.row, hasta.row, link.row,
    h("div", { class: "field" }, h("label", { class: "label", for: "of-nota" }, "Nota (opcional)"), nota),
    h("div", { class: "actions" }, guardar));
  return form;
}

function Fila(o, onDeleted) {
  const borrar = h("button", { type: "button", class: "ra-btn ra-btn-danger", onclick: async () => {
    borrar.disabled = true;
    try { await api(`/api/ofertas/admin/${encodeURIComponent(o.id)}`, { method: "DELETE" }); toast("Oferta dada de baja."); onDeleted(); }
    catch (err) { toast(mensajeError(err)); borrar.disabled = false; }
  } }, "Dar de baja");
  return h("li", { class: "stack" },
    h("p", {}, h("a", { class: "ra-link", href: `#/ofertas/${encodeURIComponent(o.id)}` }, o.titulo),
      ` · ${o.categoria_nombre} · ${o.fuente === "manual" ? "cargada a mano" : "baja de precio"}`),
    h("p", { class: "caption" }, `${cuando(o.desde)}${o.hasta ? ` → ${cuando(o.hasta)}` : ""}${o.lugar ? ` · ${o.lugar}` : ""}`),
    h("div", { class: "actions" }, borrar));
}

export async function viewAdminOfertas(view) {
  const lista = h("ul", { class: "stack" });
  async function pintar() {
    try {
      const d = await api("/api/ofertas/admin/lista");
      lista.replaceChildren(...(d.ofertas.length ? d.ofertas.map((o) => Fila(o, pintar)) : [h("li", { class: "caption" }, "Todavía no hay ofertas.")]));
    } catch (err) { lista.replaceChildren(h("li", {}, Hint(mensajeError(err), { tone: "error" }))); }
  }
  view.append(h("div", { class: "stack-lg" }, h("a", { class: "ra-link", href: "#/ofertas" }, "← Ofertas"), h("h1", { class: "title" }, "Administrar ofertas"),
    Formulario(pintar), h("div", { class: "stack" }, h("h2", { class: "label" }, "Cargadas"), lista)));
  await pintar();
}
