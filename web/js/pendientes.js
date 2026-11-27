// Pendientes del viaje (#/viajes/pendientes): la checklist de lo que falta antes de salir. La lista sugerida la siembra el
// servidor la primera vez (app/viajes_pendientes.py); todo se tilda, edita y borra. Los avisos de fecha límite y el
// resumen de los días previos los manda el servidor por Web Push (app/viajes_avisos.py) y se apagan en Ajustes.
import { Pendientes } from "./api.js";
import { enVegas } from "./dia.js";
import { icon } from "./icons.js";
import { sandboxNow } from "./sandbox.js";
import { Button, Hint, h, mensajeError, toast, withUndo } from "./ui.js";

const LARGO_MAX = 120;
const DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const dia = (iso) => { const d = new Date(`${iso}T12:00:00`); return `${DIAS[d.getDay()]} ${d.getDate()}/${d.getMonth() + 1}`; };

/** «7/12 listos» con su barra. Se usa acá y en la tarjeta del hub de Viaje. */
export const textoProgreso = ({ hechos, total }) => `${hechos}/${total} listos`;
export function ProgresoPendientes(resumen) {
  const { hechos, total } = resumen;
  const pct = total ? Math.round((hechos / total) * 100) : 0;
  return h("div", { class: "ra-progress", role: "progressbar", "aria-label": "Pendientes listos",
    "aria-valuemin": "0", "aria-valuemax": String(total), "aria-valuenow": String(hechos), "aria-valuetext": textoProgreso(resumen) },
  h("span", { class: "caption" }, textoProgreso(resumen)),
  h("div", { class: "ra-progress-track" }, h("div", { class: "ra-progress-fill", style: { width: `${pct}%` } })));
}

const resumenDe = (items) => ({ hechos: items.filter((x) => x.hecho).length, total: items.length });

/** Si la fecha límite ya pasó (y no está hecho), con la fecha de Las Vegas de `ahora` (la hora de la app). */
export const estaVencido = (p, ahora = sandboxNow()) => Boolean(p.fecha_limite && !p.hecho && p.fecha_limite < enVegas(ahora).fecha);

function Vence(p) {
  if (!p.fecha_limite) return null;
  const vencido = estaVencido(p);
  return h("span", { class: vencido ? "ra-tag is-new" : "caption" }, vencido ? `Venció el ${dia(p.fecha_limite)}` : `Hasta el ${dia(p.fecha_limite)}`);
}

/** Texto y fecha: el mismo formulario para agregar (sin `p`) y editar (con `p`). */
function FormPendiente({ p = null, onGuardar, onCancelar = null }) {
  const sufijo = p ? p.id : "nuevo";
  const texto = h("input", { id: `pend-texto-${sufijo}`, maxlength: LARGO_MAX, required: true, value: p?.texto ?? "",
    placeholder: p ? "" : "Ej.: Comprar adaptador de enchufe", autocomplete: "off" });
  const fecha = h("input", { id: `pend-fecha-${sufijo}`, type: "date", value: p?.fecha_limite ?? "" });
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try { await onGuardar({ texto: texto.value.trim(), fecha_limite: fecha.value || null }); } catch (err) { toast(mensajeError(err)); btn.disabled = false; }
  } },
  h("div", { class: "field" }, h("label", { class: "label", for: texto.id }, "Pendiente"), texto),
  h("div", { class: "field" }, h("label", { class: "label", for: fecha.id }, "Fecha límite (opcional)"), fecha),
  h("div", { class: "actions" },
    h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, p ? "Guardar" : "Agregar"),
    onCancelar ? Button("Cancelar", { onclick: onCancelar }) : null));
  return form;
}

function Fila(p, { onMarcar, onEditar, onBorrar }) {
  const id = `pend-${p.id}`;
  const check = h("input", { type: "checkbox", id, class: "ra-pend-check", checked: p.hecho,
    "aria-describedby": p.fecha_limite ? `${id}-vence` : null, onchange: (e) => onMarcar(e.target.checked) });
  const vence = Vence(p);
  if (vence) vence.id = `${id}-vence`;
  return h("li", { class: `ra-pend${p.hecho ? " is-hecho" : ""}`, id: `${id}-fila` },
    check,
    h("div", { class: "ra-pend-cuerpo" }, h("label", { for: id, class: "ra-pend-texto" }, p.texto), vence),
    h("div", { class: "ra-pend-acciones" },
      Button("Editar", { variant: "ghost", "aria-label": `Editar «${p.texto}»`, onclick: onEditar }),
      h("button", { type: "button", class: "iconbtn", "aria-label": `Borrar «${p.texto}»`, title: "Borrar", onclick: onBorrar }, icon("borrar", 20))));
}

export async function viewPendientes(view) {
  // Contenedor propio: si el usuario ya navegó a otra pantalla, una respuesta tardía no la pisa.
  const raiz = h("div");
  view.append(raiz);
  let items = (await Pendientes.get()).pendientes;
  if (!raiz.isConnected) return;

  const recargar = async () => {
    try { items = (await Pendientes.get()).pendientes; } catch (err) { toast(mensajeError(err)); return; }
    paint();
  };

  const marcar = (p) => async (hecho) => {
    items = items.map((x) => (x.id === p.id ? { ...x, hecho } : x));
    paint({ foco: `pend-${p.id}` });
    try { await Pendientes.marcar(p.id, hecho); } catch (err) {
      toast(mensajeError(err));
      items = items.map((x) => (x.id === p.id ? { ...x, hecho: !hecho } : x));
      paint({ foco: `pend-${p.id}` });
    }
  };

  const borrar = (p) => () => {
    const posicion = items.findIndex((x) => x.id === p.id);
    withUndo("Pendiente borrado.", {
      apply: () => { items = items.filter((x) => x.id !== p.id); paint(); },
      commit: () => Pendientes.borrar(p.id).catch((err) => { toast(mensajeError(err)); void recargar(); }),
      // Vuelve a su lugar sobre la lista de ahora (mientras tanto se pudo tildar otro).
      undo: () => { items = [...items.slice(0, posicion), p, ...items.slice(posicion)]; paint({ foco: `pend-${p.id}` }); },
    });
  };

  const editar = (p) => () => {
    const fila = document.getElementById(`pend-${p.id}-fila`);
    const form = FormPendiente({ p, onCancelar: () => paint({ foco: `pend-${p.id}` }), onGuardar: async (datos) => {
      const nuevo = await Pendientes.editar(p.id, datos);
      items = items.map((x) => (x.id === p.id ? nuevo : x));
      toast("Pendiente actualizado.");
      paint({ foco: `pend-${p.id}` });
    } });
    fila?.replaceChildren(form);
    form.querySelector("input")?.focus();
  };

  const agregar = async (datos) => {
    const nuevo = await Pendientes.agregar(datos);
    items = [...items, nuevo];
    toast("Pendiente agregado.");
    formNuevo.reset();
    formNuevo.querySelector("button[type=submit]").disabled = false;
    paint({ foco: "pend-texto-nuevo" });
  };
  // Se crea una sola vez: tildar o borrar otro pendiente repinta la lista sin perder lo que se estaba escribiendo.
  const formNuevo = FormPendiente({ onGuardar: agregar });

  function paint({ foco = null } = {}) {
    if (!raiz.isConnected) return;
    const resumen = resumenDe(items);
    raiz.replaceChildren(h("div", { class: "stack-lg" },
      h("a", { class: "ra-btn ra-btn-ghost ra-back", href: "#/viaje" }, icon("volver", 16), h("span", {}, "Viaje")),
      h("h1", { class: "title" }, "Pendientes del viaje"),
      h("p", { class: "caption" }, "Lo que conviene tener resuelto antes de salir. Tildá lo que ya hiciste, sumá lo tuyo y ponele fecha límite si querés que te avisemos."),
      ProgresoPendientes(resumen),
      resumen.total && resumen.hechos === resumen.total ? Hint("¡Tenés todo listo para el viaje!", { iconName: "listo" }) : null,
      items.length
        ? h("ul", { class: "ra-pend-lista", "aria-label": "Pendientes" }, items.map((p) => Fila(p, { onMarcar: marcar(p), onEditar: editar(p), onBorrar: borrar(p) })))
        : h("p", { class: "caption" }, "No tenés pendientes. Agregá el primero acá abajo."),
      h("section", { class: "stack" }, h("h2", { class: "label" }, "Agregar un pendiente"), formNuevo)));
    if (foco) document.getElementById(foco)?.focus();
  }
  paint();
}
