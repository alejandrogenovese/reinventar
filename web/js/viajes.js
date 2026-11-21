// Viajes: vuelos y hoteles cargados a mano. Los avisos (check-in web, check-in/out del hotel, demora y puerta) los manda
// el servidor por Web Push (app/viajes_avisos.py); tocar uno abre #/viajes/vuelo/ID o #/viajes/hotel/ID.
import { Viajes } from "./api.js";
import { Button, Hint, h, mensajeError, toast } from "./ui.js";

const ZONA_HOTEL = "America/Los_Angeles"; // los hoteles son de re:Invent: horas de Las Vegas
const DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const dia = (iso) => { const d = new Date(`${iso.slice(0, 10)}T12:00:00`); return `${DIAS[d.getDay()]} ${d.getDate()}/${d.getMonth() + 1}`; };
// El link viene del servidor (aerolínea): solo https, como el resto de la app.
const linkSeguro = (url) => (typeof url === "string" && url.startsWith("https://") ? url : null);
const cuando = (iso) => (iso ? `${dia(iso)} ${iso.slice(11, 16)}` : "");

function estadoDelVuelo(v) {
  if ((v.estado || "").toLowerCase().startsWith("cancel")) return h("span", { class: "ra-tag is-new" }, "Cancelado");
  if (v.demora_min >= 15) return h("span", { class: "ra-tag is-new" }, `Demora ${v.demora_min} min`);
  return null;
}

function VueloCard(v, { detalle = false, onQuitar }) {
  const sale = v.salida ? `${cuando(v.salida)} (${v.zona_nombre})` : `${dia(v.fecha)} · sin hora`;
  const puerta = v.puerta ? `Puerta ${v.puerta}${v.terminal ? ` · Terminal ${v.terminal}` : ""}` : "";
  return h("article", { class: "ra-card", id: `vuelo-${v.id}` },
    h("div", { class: "ra-card-top" },
      h("a", { class: "ra-card-title ra-link", href: `#/viajes/vuelo/${v.id}` }, v.numero, v.aerolinea ? ` · ${v.aerolinea}` : ""),
      estadoDelVuelo(v)),
    h("div", { class: "ra-card-meta" }, h("span", {}, sale), puerta ? h("span", {}, puerta) : null),
    v.checkin_abre ? h("p", { class: "caption" }, `Check-in web desde el ${cuando(v.checkin_abre)} (${v.checkin_horas} h antes)`) : null,
    detalle ? h("div", { class: "actions" },
      linkSeguro(v.checkin_url) ? h("a", { class: "ra-btn ra-btn-secondary", href: linkSeguro(v.checkin_url), target: "_blank", rel: "noopener" }, "Hacer check-in") : null,
      Button("Quitar", { variant: "danger", onclick: onQuitar })) : null);
}

function HotelCard(x, { detalle = false, onQuitar }) {
  return h("article", { class: "ra-card", id: `hotel-${x.id}` },
    h("div", { class: "ra-card-top" }, h("a", { class: "ra-card-title ra-link", href: `#/viajes/hotel/${x.id}` }, x.nombre)),
    x.direccion ? h("div", { class: "ra-card-meta" }, h("span", {}, x.direccion)) : null,
    h("p", { class: "caption" }, `Check-in ${cuando(x.checkin)} · Check-out ${cuando(x.checkout)}`),
    detalle ? h("div", { class: "actions" }, Button("Quitar", { variant: "danger", onclick: onQuitar })) : null);
}

let _campos = 0;
/** Etiqueta asociada al control (for/id), así el lector de pantalla y el toque en el texto llegan al campo. */
const Campo = (etiqueta, control) => {
  control.id = control.id || `viajes-campo-${++_campos}`;
  return h("div", { class: "field" }, h("label", { class: "label", for: control.id }, etiqueta), control);
};

/** Tras guardar: avisa y refresca; si el refresco falla, el alta ya está hecha y se dice. */
async function alGuardar(mensaje, onGuardado, btn) {
  toast(mensaje);
  try { await onGuardado(); } catch (err) { toast(mensajeError(err)); btn.disabled = false; }
}

function FormVuelo(zonas, onGuardado) {
  const numero = h("input", { placeholder: "AR1302", maxlength: 12, required: true, autocapitalize: "characters" });
  const fecha = h("input", { type: "date", required: true });
  const hora = h("input", { type: "time" });
  const aerolinea = h("input", { placeholder: "Opcional", maxlength: 60 });
  const zona = h("select", {}, zonas.map((z) => h("option", { value: z.id }, z.nombre)));
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      await Viajes.agregarVuelo({ numero: numero.value, aerolinea: aerolinea.value, fecha: fecha.value, hora: hora.value || null, zona: zona.value });
    } catch (err) { toast(mensajeError(err)); btn.disabled = false; return; }
    await alGuardar("Vuelo agregado.", onGuardado, btn);
  } },
  Campo("Número de vuelo", numero), Campo("Aerolínea", aerolinea),
  h("div", { class: "actions" }, Campo("Fecha de salida", fecha), Campo("Hora de salida", hora)),
  Campo("Sale de", zona),
  h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Agregar vuelo"));
  return form;
}

function FormHotel(onGuardado) {
  const nombre = h("input", { maxlength: 120, required: true });
  const direccion = h("input", { maxlength: 200 });
  const checkin = h("input", { type: "datetime-local", required: true });
  const checkout = h("input", { type: "datetime-local", required: true });
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      await Viajes.agregarHotel({ nombre: nombre.value, direccion: direccion.value, checkin: checkin.value, checkout: checkout.value, zona: ZONA_HOTEL });
    } catch (err) { toast(mensajeError(err)); btn.disabled = false; return; }
    await alGuardar("Hotel agregado.", onGuardado, btn);
  } },
  Campo("Nombre", nombre), Campo("Dirección", direccion),
  h("div", { class: "actions" }, Campo("Check-in", checkin), Campo("Check-out", checkout)),
  h("p", { class: "caption" }, "Las horas son las del hotel (Las Vegas)."),
  h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Agregar hotel"));
  return form;
}

/** `foco`: { tipo: "vuelo" | "hotel", id } cuando se llega desde un aviso o una tarjeta. */
export async function viewViajes(view, foco = null) {
  // Todo se pinta en un contenedor propio: si el usuario ya navegó a otra pantalla, una respuesta tardía no la pisa.
  const raiz = h("div");
  view.append(raiz);
  async function paint() {
    const data = await Viajes.get();
    if (!raiz.isConnected) return;
    const quitar = (tipo, id) => async () => {
      try { await (tipo === "vuelo" ? Viajes.quitarVuelo(id) : Viajes.quitarHotel(id)); } catch (err) { toast(mensajeError(err)); return; }
      toast("Listo.");
      foco = null; // ya no hay nada que enfocar: si no, el repintado diría «No encontramos ese vuelo»
      location.hash = "#/viajes";
      await paint();
    };
    const elegido = foco && (foco.tipo === "vuelo" ? data.vuelos : data.hoteles).find((x) => x.id === foco.id);
    const vuelos = data.vuelos.map((v) => VueloCard(v, { detalle: elegido === v, onQuitar: quitar("vuelo", v.id) }));
    const hoteles = data.hoteles.map((x) => HotelCard(x, { detalle: elegido === x, onQuitar: quitar("hotel", x.id) }));
    raiz.replaceChildren(h("div", { class: "stack-lg" },
      h("h1", { class: "title" }, "Viajes"),
      foco && !elegido ? Hint("No encontramos ese vuelo u hotel: puede que ya lo hayas quitado.", { tone: "warn" }) : null,
      h("p", { class: "caption" }, "Cargá tus vuelos y hoteles y te avisamos cuándo abre el check-in, cuándo hacer el check-in y el check-out del hotel, y si tu vuelo se demora o cambia de puerta. Los avisos se prenden y apagan en Ajustes."),
      !data.estado_disponible ? Hint("Las alertas de demora y puerta no están activas en este servidor; el resto de los avisos anda igual.") : null,
      h("section", { class: "stack" }, h("h2", { class: "label" }, "Vuelos"),
        vuelos.length ? vuelos : h("p", { class: "caption" }, "Todavía no cargaste vuelos."),
        h("details", { class: "stack", open: !vuelos.length }, h("summary", { class: "label" }, "Agregar un vuelo"), FormVuelo(data.zonas, paint))),
      h("section", { class: "stack" }, h("h2", { class: "label" }, "Hoteles"),
        hoteles.length ? hoteles : h("p", { class: "caption" }, "Todavía no cargaste hoteles."),
        h("details", { class: "stack", open: !hoteles.length }, h("summary", { class: "label" }, "Agregar un hotel"), FormHotel(paint)))));
    if (elegido) document.getElementById(`${foco.tipo}-${foco.id}`)?.scrollIntoView({ block: "center" });
  }
  await paint();
}
