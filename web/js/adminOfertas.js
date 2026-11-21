// Admin › Ofertas (#/admin/ofertas): las vigentes primero, y «Cargar oferta» (plegado) para sumar a mano una oferta (comida, happy hour, outlet)
// con su vigencia. Se da de baja con confirmación. El push sale cuando arranca la vigencia. Las bajas de precio de shows entran solas
// (app/ofertas.py). Solo admin: el servidor lo exige.
import { api } from "./api.js";
import { AdminShell, Cargable, Plegable, avisar, confirmar, conOcupado, sinDoble } from "./adminUi.js";
import { Tag, h, mensajeError } from "./ui.js";

const CATEGORIAS = { comida: "Comida", compras: "Compras y outlets", shows: "Shows", otros: "Otros" };
const cuando = (iso) => new Date(iso).toLocaleString("es-AR", { timeZone: "America/Los_Angeles", weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }).replaceAll(".", "");

const campo = (id, label, attrs = {}) => {
  const el = h("input", { id, name: id, ...attrs });
  return { el, row: h("div", { class: "field" }, h("label", { class: "label", for: id }, label), el) };
};

function Formulario(onSaved) {
  const titulo = campo("of-titulo", "Título", { required: true, minlength: 2, maxlength: 120, placeholder: "2x1 en tragos" });
  const categoria = h("select", { id: "of-categoria", name: "of-categoria", class: "ra-adm-select" }, Object.entries(CATEGORIAS).map(([v, n]) => h("option", { value: v }, n)));
  const lugar = campo("of-lugar", "Lugar", { maxlength: 120, placeholder: "Bar del lobby, Venetian" });
  const desde = campo("of-desde", "Empieza (hora de Las Vegas)", { type: "datetime-local", required: true });
  const hasta = campo("of-hasta", "Termina (hora de Las Vegas)", { type: "datetime-local" });
  const link = campo("of-link", "Link (opcional)", { type: "url", inputmode: "url", placeholder: "https://…", pattern: "https://.*" });
  const nota = h("textarea", { id: "of-nota", rows: 3, maxlength: 400 });
  const guardar = h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Guardar oferta");
  const form = h("form", { class: "ra-adm-form", "aria-label": "Cargar oferta", onsubmit: async (e) => {
    e.preventDefault();
    guardar.disabled = true;
    const datos = { titulo: titulo.el.value.trim(), categoria: categoria.value, lugar: lugar.el.value.trim() || null, desde: desde.el.value,
      hasta: hasta.el.value || null, link: link.el.value.trim() || null, nota: nota.value.trim() || null };
    try {
      await api("/api/ofertas/admin", { method: "POST", json: datos });
      avisar(`Guardada: ${datos.titulo}`);
      form.reset();
      onSaved();
    } catch (err) { avisar(mensajeError(err), { error: true }); }
    guardar.disabled = false;
  } },
    h("p", { class: "ra-adm-cap" }, "El aviso sale cuando arranca la vigencia, a quienes tienen las alertas de esa categoría."),
    titulo.row, h("div", { class: "field" }, h("label", { class: "label", for: "of-categoria" }, "Categoría"), categoria),
    lugar.row, desde.row, hasta.row, link.row,
    h("div", { class: "field" }, h("label", { class: "label", for: "of-nota" }, "Nota (opcional)"), nota),
    guardar);
  return form;
}

function Fila(o, onDeleted) {
  const borrar = h("button", { type: "button", class: "ra-btn ra-btn-ghost ra-adm-btn-s ra-adm-btn-err", "aria-label": `Dar de baja ${o.titulo}`, onclick: () => sinDoble(borrar, async () => {
    if (!await confirmar(`¿Dar de baja «${o.titulo}»?`, "La oferta deja de verse para todos y no se puede recuperar.", "Dar de baja")) return;
    await conOcupado(borrar, async () => {
      try { await api(`/api/ofertas/admin/${encodeURIComponent(o.id)}`, { method: "DELETE" }); avisar("Oferta dada de baja."); fila.remove(); onDeleted(); }
      catch (err) { avisar(mensajeError(err), { error: true }); }
    });
  }) }, "Dar de baja");
  const fila = h("li", { class: "ra-adm-fila" },
    h("span", { class: "ra-adm-fila-cuerpo" },
      h("a", { class: "ra-adm-fila-nombre ra-link", href: `#/ofertas/${encodeURIComponent(o.id)}` }, o.titulo),
      h("span", { class: "ra-g-marcas" }, Tag(o.categoria_nombre), Tag(o.fuente === "manual" ? "cargada a mano" : "baja de precio")),
      h("span", { class: "ra-adm-fila-sub" }, `${cuando(o.desde)}${o.hasta ? ` → ${cuando(o.hasta)}` : ""}${o.lugar ? ` · ${o.lugar}` : ""}`)),
    borrar);
  return fila;
}

export function viewAdminOfertas(view) {
  const pasadas = h("input", { type: "checkbox", id: "of-pasadas" });
  const lista = Cargable({
    cargar: () => api(`/api/ofertas/admin/lista${pasadas.checked ? "?pasadas=true" : ""}`),
    pintar: (d) => [
      h("div", { class: "ra-sec-head" }, h("h2", { class: "label" }, `${pasadas.checked ? "Vigentes y vencidas" : "Vigentes"} · ${d.ofertas.length}`)),
      h("ul", { class: "ra-adm-lista" }, d.ofertas.map((o) => Fila(o, () => { if (!ul().querySelector("li")) void lista.recargar(); }))),
    ],
    esVacio: (d) => !d.ofertas.length,
    textoVacio: "No hay ofertas vigentes.",
    textoCargando: "Cargando ofertas…",
  });
  const ul = () => lista.querySelector("ul") ?? h("ul");
  pasadas.addEventListener("change", () => void lista.recargar());
  AdminShell(view, "ofertas",
    h("a", { class: "ra-link ra-adm-link", href: "#/ofertas" }, "← Ofertas"),
    lista,
    h("label", { class: "ra-adm-check-row" }, pasadas, "Mostrar también las vencidas"),
    Plegable("Cargar oferta", Formulario(() => void lista.recargar({ silencioso: true }))));
}
