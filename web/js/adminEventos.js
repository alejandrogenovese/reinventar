// Cuenta → Admin → Eventos automáticos: la última revisión de cada fuente (Luma, conferenceparties, links y el catálogo
// oficial de charlas), «Revisar ahora», «Agregar evento por link» (vista previa con el LLM, corregible, y guardar) y las
// «Charlas nuevas» que encontró la revisión. Ver app/eventos_auto.py y app/charlas_auto.py.
import { Admin } from "./api.js";
import { Button, Hint, h, toast } from "./ui.js";

const FUENTE = { luma: "Luma", conferenceparties: "conferenceparties", links: "Links cargados a mano", catalogo: "Catálogo oficial de charlas", ticketmaster: "Ticketmaster (shows)" };
const ESPERA_MS = 5000;

const hace = (iso) => {
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "recién";
  if (min < 60) return `hace ${min} min`;
  return `hace ${Math.round(min / 60)} h`;
};
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

function RevisionRow(r) {
  const unidad = { catalogo: "horarios futuros", ticketmaster: "funciones" }[r.fuente] || "eventos";
  const partes = [`${r.total} ${unidad}`, plural(r.nuevos, "nuevo", "nuevos"), plural(r.cambiados, "cambiado", "cambiados"),
    plural(r.cancelados, "cancelado", "cancelados"), r.pendientes ? `${r.pendientes} sin resumen todavía` : null].filter(Boolean);
  return h("div", { class: "stack" },
    h("p", {}, h("strong", {}, FUENTE[r.fuente] || r.fuente), ` · ${hace(r.revisado)} · `, r.ok ? partes.join(" · ") : "falló"),
    r.detalle ? h("p", { class: "caption" }, r.detalle) : null);
}

const input = (id, label, value, attrs = {}) => {
  const el = h("input", { id, name: id, value: value ?? "", ...attrs });
  return { el, row: h("div", { class: "field" }, h("label", { class: "label", for: id }, label), el) };
};

/** La vista previa editable: lo que sacó el LLM, para corregir antes de guardar. */
function Preview(p, onSaved) {
  const nombre = input("ev-nombre", "Nombre", p.nombre, { required: true, maxlength: 200 });
  const fecha = input("ev-fecha", "Fecha", p.fecha, { type: "date", required: true, min: "2026-11-28", max: "2026-12-06" });
  const inicio = input("ev-inicio", "Empieza", p.inicio, { type: "time", required: true });
  const fin = input("ev-fin", "Termina", p.fin, { type: "time" });
  const lugar = input("ev-lugar", "Lugar", p.lugar, { maxlength: 120 });
  const direccion = input("ev-direccion", "Dirección u hotel", p.direccion, { maxlength: 200 });
  const resumen = h("textarea", { id: "ev-resumen", rows: 4, maxlength: 1200 }, p.resumen_es || "");
  const guardar = h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Guardar evento");
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    guardar.disabled = true;
    const datos = {
      url: p.url, nombre: nombre.el.value.trim(), fecha: fecha.el.value, inicio: inicio.el.value, fin: fin.el.value || null,
      lugar: lugar.el.value.trim() || null, direccion: direccion.el.value.trim() || null, imagen: p.imagen,
      descripcion: p.descripcion, resumen_es: resumen.value.trim() || null, tipo: p.tipo, temas: p.temas, organizadores: p.organizadores,
    };
    try {
      await Admin.eventosGuardarLink(datos);
      toast(`Guardado: ${datos.nombre}`);
      onSaved();
    } catch (err) { toast(err.message); guardar.disabled = false; }
  } },
    p.ya_cargado ? Hint(`Ya está cargado: ${p.ya_cargado}`, { tone: "error" }) : null,
    nombre.row, fecha.row, h("div", { class: "actions" }, inicio.row, fin.row), lugar.row, direccion.row,
    h("div", { class: "field" }, h("label", { class: "label", for: "ev-resumen" }, "Resumen"), resumen),
    h("p", { class: "caption" }, [p.tipo, ...(p.organizadores || [])].filter(Boolean).join(" · ")),
    h("div", { class: "actions" }, guardar));
  return form;
}

function AddLink(onSaved) {
  const url = input("ev-link", "Link del evento", "", { type: "url", required: true, placeholder: "https://…", pattern: "https://.*" });
  const preview = h("div");
  const mirar = h("button", { type: "submit", class: "ra-btn" }, "Ver cómo queda");
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    mirar.disabled = true;
    preview.replaceChildren(h("p", { class: "caption" }, "Leyendo la página…"));
    try {
      const p = await Admin.eventosVistaPrevia(url.el.value.trim());
      preview.replaceChildren(Preview(p, () => { form.reset(); preview.replaceChildren(); onSaved(); }));
    } catch (err) { preview.replaceChildren(); toast(err.message); }
    mirar.disabled = false;
  } },
    h("h3", { class: "label" }, "Agregar evento por link"),
    h("p", { class: "caption" }, "Para los que no están en Luma ni en conferenceparties. Revisá la fecha y la hora antes de guardar."),
    url.row, h("div", { class: "actions" }, mirar));
  return h("div", { class: "stack" }, form, preview);
}

const diaHora = (iso) => (iso ? new Date(iso).toLocaleString("es-AR", { weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) : "sin horario");

/** Las charlas que entraron solas desde el catálogo oficial (con el resumen en inglés): para revisarlas. */
function CharlasNuevas(nuevas) {
  if (!nuevas?.length) return null;
  return h("div", { class: "stack" },
    h("h3", { class: "label" }, "Charlas nuevas"),
    h("p", { class: "caption" }, "Las agregó la revisión desde el catálogo oficial, con el resumen en inglés hasta la próxima carga manual."),
    h("ul", { class: "stack" }, nuevas.map((c) => h("li", {},
      h("a", { class: "ra-link", href: `#/charla/${encodeURIComponent(c.base)}` }, `${c.base} · ${c.titulo}`),
      h("span", { class: "caption" }, ` · ${diaHora(c.primero)} · encontrada ${hace(c.alta)}`)))));
}

export function EventosPanel() {
  const box = h("div", { class: "stack" });
  async function paint() {
    let d;
    try { d = await Admin.eventos(); } catch (err) { box.replaceChildren(h("p", { class: "caption" }, err.message)); return; }
    const revisar = Button(d.ocupado ? "Revisando…" : "Revisar ahora", { onclick: async () => {
      revisar.disabled = true;
      try { await Admin.eventosRevisar(); toast("Revisando las fuentes: tarda un par de minutos."); setTimeout(paint, ESPERA_MS); }
      catch (err) { toast(err.message); revisar.disabled = false; }
    } });
    revisar.disabled = d.ocupado || !d.activo || d.migracion_pendiente;
    if (d.ocupado) setTimeout(paint, ESPERA_MS);
    box.replaceChildren(
      !d.activo ? Hint("Apagado en este entorno: se prende con EVENTOS_AUTO=1 (solo en producción).") : null,
      d.migracion_pendiente ? Hint("Falta la migración 007 en la base.", { tone: "error" }) : null,
      d.activo ? h("p", { class: "caption" }, `Revisa Luma, conferenceparties${d.ticketmaster ? ", Ticketmaster" : ""} y los links cada ${d.horas} h; el catálogo oficial de charlas, cada 3 h (cada 30 min durante el evento).`) : null,
      !d.ticketmaster ? h("p", { class: "caption" }, "Ticketmaster apagado: falta TICKETMASTER_API_KEY (sin key no aparece la pestaña Shows).") : null,
      ...d.revisiones.map(RevisionRow),
      h("div", { class: "actions" }, revisar),
      d.links.length ? h("ul", { class: "stack" }, d.links.map((l) => h("li", {},
        h("a", { class: "ra-link", href: `#/evento/${encodeURIComponent(l.id)}` }, l.nombre), l.cancelado ? " · cancelado" : ""))) : null,
      CharlasNuevas(d.charlas_nuevas),
      d.activo && !d.migracion_pendiente ? AddLink(paint) : null);
  }
  void paint();
  return h("div", { class: "stack" }, h("h2", { class: "label" }, "Eventos automáticos"), box);
}
