// Mis eventos: los que dan los proveedores y no están en la sección Eventos. Cada uno carga los suyos.
import { ApiError, Catalog, MyEvents } from "./api.js";
import { shortDay } from "./itinerary.js";
import { Button, IconText, h, toast } from "./ui.js";

const AUTOCOMPLETE_MIN = 3;
const AUTOCOMPLETE_DEBOUNCE_MS = 350;
const LUGARES = [["sede", "Sede de re:Invent"], ["google", "Buscar lugar"], ["direccion", "Escribir dirección"]];

/** Tarjeta de un evento propio (itinerario, sección Eventos). */
export function MyEventCard(e, actions = []) {
  return h("article", { class: "ra-minicard" },
    h("div", { class: "ra-rail" },
      h("span", { class: "ra-rail-time" }, e.start || "—"),
      h("span", { class: "ra-rail-day" }, shortDay(e.day))),
    h("div", { class: "ra-minicard-body" },
      h("span", { class: "ra-kind" }, ["MI EVENTO", e.end ? `hasta ${e.end}` : null].filter(Boolean).join(" · ")),
      h("h3", { class: "ra-minicard-title" }, e.title),
      e.venue?.hotel || e.venue?.detail
        ? h("div", { class: "ra-minicard-meta" }, IconText("ubicacion", [e.venue?.hotel, e.venue?.detail].filter(Boolean).join(" "))) : null,
      e.note ? h("p", { class: "caption" }, e.note) : null,
      h("div", { class: "actions" },
        Button("Editar", { onclick: () => (location.hash = `#/mi-evento/${encodeURIComponent(e.id)}`) }),
        actions)));
}

/** Lista de los eventos propios con el botón para sumar uno (arriba de la sección Eventos). */
export async function MyEventsSection() {
  const { eventos } = await MyEvents.list();
  return h("section", { class: "stack" },
    h("div", { class: "actions" }, Button(IconText("agregar", "Mi evento"), { variant: "primary", onclick: () => (location.hash = "#/mi-evento/nuevo") }),
      h("span", { class: "caption" }, "¿Te invitó un proveedor a algo que no está acá? Cargalo y entra a tu itinerario.")),
    eventos.length ? h("details", {}, h("summary", { class: "label" }, `Tus eventos (${eventos.length})`),
      h("div", { class: "daylist" }, eventos.map((e) => MyEventCard(e)))) : null);
}

function Autocomplete(inicial) {
  const sesion = crypto.randomUUID?.() || String(Date.now());
  let elegido = inicial;
  let timer;
  const input = h("input", { type: "search", maxlength: "100", placeholder: "Ej: Topgolf, Hakkasan, Wynn Encore Ballroom", autocomplete: "off" });
  const results = h("ul", { class: "ra-suggestions", role: "listbox" });
  const chosen = h("p", { class: "caption", "aria-live": "polite" });
  const paintChosen = () => { chosen.replaceChildren(elegido ? IconText("ubicacion", `${elegido.nombre}${elegido.direccion ? ` · ${elegido.direccion}` : ""}`) : ""); };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < AUTOCOMPLETE_MIN) { results.replaceChildren(); return; }
    timer = setTimeout(async () => {
      try {
        const { lugares } = await MyEvents.autocomplete(q, sesion);
        results.replaceChildren(...lugares.map((l) => h("li", {}, h("button", { type: "button", class: "ra-suggestion", role: "option", onclick: () => {
          elegido = l; results.replaceChildren(); input.value = ""; paintChosen();
        } }, h("strong", {}, l.nombre), h("span", { class: "caption" }, ` ${l.direccion}`)))));
      } catch (err) {
        results.replaceChildren(h("li", { class: "caption" }, err instanceof ApiError && err.status === 503
          ? "El buscador de lugares no está disponible: elegí una sede o escribí la dirección." : err.message));
      }
    }, AUTOCOMPLETE_DEBOUNCE_MS);
  });
  paintChosen();
  const el = h("div", { class: "stack" }, input, results, chosen);
  el.get = () => (elegido ? { place_id: elegido.place_id, sesion } : null);
  return el;
}

export async function viewMiEvento(view, id = null) {
  const [{ sedes }, meta, { eventos }] = await Promise.all([MyEvents.venues(), Catalog.meta(), MyEvents.list()]);
  const ev = id ? eventos.find((e) => e.id === id) : null;
  if (id && !ev) { view.replaceChildren(h("p", { class: "caption" }, "No encontré ese evento.")); return; }
  const v = ev?.venue || {};
  let modo = v.id_sede ? "sede" : v.place_id ? "google" : ev ? "direccion" : "sede";

  const nombre = h("input", { required: true, maxlength: "120", value: ev?.title || "", placeholder: "Ej: Cena con Datadog" });
  const dia = h("select", {}, meta.dates.map((d) => h("option", { value: d.value, selected: d.value === ev?.day }, shortDay(d.value))));
  const inicio = h("input", { type: "time", required: true, value: ev?.start || "19:00" });
  const fin = h("input", { type: "time", value: ev?.end || "" });
  const sede = h("select", {}, sedes.map((s) => h("option", { value: s.id, selected: s.id === v.id_sede }, s.nombre)));
  const google = Autocomplete(v.place_id ? { place_id: v.place_id, nombre: v.hotel, direccion: v.address || "" } : null);
  const direccion = h("input", { maxlength: "200", value: !v.id_sede && !v.place_id ? v.hotel || "" : "", placeholder: "Ej: Suite 1203, Wynn" });
  const nota = h("textarea", { rows: "3", maxlength: "500", placeholder: "Opcional: con quién, qué llevar, código de acceso…" });
  nota.value = ev?.note || "";
  const panes = { sede, google, direccion };
  const modos = h("div", { class: "ra-chips", role: "radiogroup" });
  const lugar = h("div");
  const paintLugar = () => {
    modos.replaceChildren(...LUGARES.map(([k, label]) => h("button", { type: "button", class: `ra-chip${k === modo ? " ra-chip-on" : ""}`,
      "aria-pressed": String(k === modo), onclick: () => { modo = k; paintLugar(); } }, label)));
    lugar.replaceChildren(panes[modo]);
  };
  paintLugar();

  function datos() {
    const base = { nombre: nombre.value.trim(), dia: dia.value, inicio: inicio.value, fin: fin.value || null, nota: nota.value.trim() };
    if (modo === "sede") return { ...base, id_sede: Number(sede.value) };
    if (modo === "google") { const g = google.get(); return g ? { ...base, ...g } : null; }
    return direccion.value.trim() ? { ...base, direccion: direccion.value.trim() } : null;
  }

  const form = h("form", { class: "stack-lg", onsubmit: async (e) => {
    e.preventDefault();
    const body = datos();
    if (!body) { toast("Elegí dónde es."); return; }
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      await (ev ? MyEvents.edit(ev.id, body) : MyEvents.create(body));
      toast(ev ? "Evento actualizado." : "Evento agregado a tu itinerario.");
      location.hash = "#/itinerario";
    } catch (err) { toast(err.message); btn.disabled = false; }
  } },
    h("h1", { class: "title" }, ev ? "Editar tu evento" : "Nuevo evento"),
    h("p", { class: "caption" }, "Queda fijado en tu itinerario: ocupa su horario, aparece en Hoy y te avisa cuándo salir. Solo lo ves vos."),
    h("div", { class: "field" }, h("label", { class: "label" }, "Nombre"), nombre),
    h("div", { class: "field" }, h("label", { class: "label" }, "Día"), dia),
    h("div", { class: "actions" },
      h("div", { class: "field" }, h("label", { class: "label" }, "Desde"), inicio),
      h("div", { class: "field" }, h("label", { class: "label" }, "Hasta (opcional)"), fin)),
    h("div", { class: "field" }, h("span", { class: "label" }, "Dónde"), modos, lugar),
    h("div", { class: "field" }, h("label", { class: "label" }, "Nota"), nota),
    h("div", { class: "actions" },
      h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, ev ? "Guardar" : "Agregar"),
      ev ? Button("Borrar", { variant: "danger", onclick: async () => {
        try { await MyEvents.remove(ev.id); toast("Evento borrado."); location.hash = "#/itinerario"; }
        catch (err) { toast(err.message); }
      } }) : null,
      Button("Cancelar", { variant: "ghost", onclick: () => history.back() })));
  view.replaceChildren(form);
}
