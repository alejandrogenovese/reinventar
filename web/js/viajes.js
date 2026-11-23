// Viajes: vuelos y hoteles cargados a mano. Los avisos (check-in web, check-in/out del hotel, demora y puerta) los manda
// el servidor por Web Push (app/viajes_avisos.py); tocar uno abre #/viajes/vuelo/ID o #/viajes/hotel/ID.
import { Viajes } from "./api.js";
import { Button, Hint, h, mensajeError, toast } from "./ui.js";

const ZONA_HOTEL = "America/Los_Angeles"; // los hoteles son de re:Invent: horas de Las Vegas
const SALIDA_INICIAL = { nombre: "Buenos Aires", pais: "AR", zona: "America/Argentina/Buenos_Aires" };
const BUSCAR_CIUDAD_MS = 200;
const MIN_LETRAS_CIUDAD = 2;
const paises = (() => { try { return new Intl.DisplayNames(["es"], { type: "region" }); } catch { return null; } })();
// Una ciudad guardada en un vuelo no trae el país: se muestra solo el nombre.
const etiquetaCiudad = (c) => (c.pais ? `${c.nombre}, ${paises?.of(c.pais) ?? c.pais}` : c.nombre);
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

/** «A Houston (IAH) · llega 16:40». La hora es la del destino (llegada_local, del desfase que manda AeroDataBox); si no
 * vino, el servidor la da en la zona del vuelo y se aclara de dónde es. Si llega otro día, con el día. */
function llegadaDelVuelo(v) {
  const destino = v.destino_nombre && v.destino_iata ? `${v.destino_nombre} (${v.destino_iata})` : v.destino_nombre || v.destino_iata;
  if (!destino && !v.llegada) return "";
  const otroDia = v.llegada && v.salida && v.llegada.slice(0, 10) !== v.salida.slice(0, 10);
  const hora = v.llegada ? `llega ${otroDia ? cuando(v.llegada) : v.llegada.slice(11, 16)}${v.llegada_local ? "" : ` (hora de ${v.zona_nombre})`}` : "";
  return [destino ? `A ${destino}` : "", hora].filter(Boolean).join(" · ");
}

/** Lo que trajo AeroDataBox además de la salida: avión, mostrador de check-in y llegada (la cinta, solo si ya está). */
function datosDelVuelo(v) {
  const avion = v.aeronave ? `Avión ${v.aeronave}${v.matricula ? ` · matrícula ${v.matricula}` : ""}` : v.matricula ? `Matrícula ${v.matricula}` : "";
  const llegada = [v.llegada_terminal ? `Llega a la terminal ${v.llegada_terminal}` : "", v.llegada_cinta ? `Cinta de equipaje ${v.llegada_cinta}` : ""];
  return [avion, v.checkin_desk ? `Mostrador de check-in ${v.checkin_desk}` : "", llegada.filter(Boolean).join(" · ")].filter(Boolean);
}

function VueloCard(v, { detalle = false, onQuitar, onEditar }) {
  const sale = v.salida ? `${cuando(v.salida)} (${v.zona_nombre})` : `${dia(v.fecha)} · sin hora`;
  const puerta = v.puerta ? `Puerta ${v.puerta}${v.terminal ? ` · Terminal ${v.terminal}` : ""}` : "";
  const llega = llegadaDelVuelo(v);
  return h("article", { class: "ra-card", id: `vuelo-${v.id}` },
    h("div", { class: "ra-card-top" },
      h("a", { class: "ra-card-title ra-link", href: `#/viajes/vuelo/${v.id}` }, v.numero, v.aerolinea ? ` · ${v.aerolinea}` : ""),
      estadoDelVuelo(v)),
    h("div", { class: "ra-card-meta" }, h("span", {}, sale), puerta ? h("span", {}, puerta) : null),
    llega ? h("div", { class: "ra-card-meta" }, h("span", {}, llega)) : null,
    detalle ? datosDelVuelo(v).map((linea) => h("p", { class: "caption" }, linea)) : null,
    v.checkin_abre ? h("p", { class: "caption" }, `Check-in web desde el ${cuando(v.checkin_abre)} (${v.checkin_horas} h antes)`) : null,
    detalle ? h("div", { class: "actions" },
      linkSeguro(v.checkin_url) ? h("a", { class: "ra-btn ra-btn-secondary", href: linkSeguro(v.checkin_url), target: "_blank", rel: "noopener" }, "Hacer check-in") : null,
      Button("Editar", { onclick: onEditar }),
      Button("Quitar", { variant: "danger", onclick: onQuitar })) : null);
}

function HotelCard(x, { detalle = false, onQuitar, onEditar }) {
  return h("article", { class: "ra-card", id: `hotel-${x.id}` },
    h("div", { class: "ra-card-top" }, h("a", { class: "ra-card-title ra-link", href: `#/viajes/hotel/${x.id}` }, x.nombre)),
    x.direccion ? h("div", { class: "ra-card-meta" }, h("span", {}, x.direccion)) : null,
    h("p", { class: "caption" }, `Check-in ${cuando(x.checkin)} · Check-out ${cuando(x.checkout)}`),
    detalle ? h("div", { class: "actions" }, Button("Editar", { onclick: onEditar }),
      Button("Quitar", { variant: "danger", onclick: onQuitar })) : null);
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

/** «Sale de»: escribís y aparecen las ciudades del mundo (GET /api/viajes/ciudades); se guarda su zona horaria.
 * `inicial` es la ciudad con la que arranca (al editar, la del vuelo: no hay que volver a buscarla). */
function CampoCiudad(inicial = SALIDA_INICIAL) {
  const idLista = `viajes-ciudades-${++_campos}`; // único: el alta y la edición pueden estar a la vez en pantalla
  const lista = h("datalist", { id: idLista });
  const conocidas = new Map([[etiquetaCiudad(inicial), inicial]]);
  const input = h("input", { list: idLista, value: etiquetaCiudad(inicial), autocomplete: "off",
    required: true, placeholder: "Escribí la ciudad: Houston, Madrid…", maxlength: 60 });
  let timer;
  let ultimo = 0;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    input.setCustomValidity("");
    if (q.length < MIN_LETRAS_CIUDAD || conocidas.has(input.value)) return;
    timer = setTimeout(async () => {
      const pedido = ++ultimo;
      try {
        const { ciudades } = await Viajes.ciudades(q);
        if (pedido !== ultimo) return; // llegó tarde: ya se escribió otra cosa
        lista.replaceChildren(...ciudades.map((c) => {
          const etiqueta = etiquetaCiudad(c);
          conocidas.set(etiqueta, c);
          return h("option", { value: etiqueta });
        }));
      } catch (err) { console.warn("[viajes] no se pudo buscar la ciudad", err); }
    }, BUSCAR_CIUDAD_MS);
  });
  const elegida = () => conocidas.get(input.value) ?? null;
  return { input, lista, elegida };
}

/** Alta (sin `vuelo`) o edición (con el vuelo a editar, precargado). */
function FormVuelo(onGuardado, vuelo = null) {
  const numero = h("input", { placeholder: "AR1302", maxlength: 12, required: true, autocapitalize: "characters", value: vuelo?.numero ?? "" });
  const fecha = h("input", { type: "date", required: true, value: vuelo?.fecha ?? "" });
  const hora = h("input", { type: "time", value: vuelo?.hora ?? "" });
  const aerolinea = h("input", { placeholder: "Opcional", maxlength: 60, value: vuelo?.aerolinea ?? "" });
  const salida = CampoCiudad(vuelo ? { nombre: vuelo.zona_nombre, zona: vuelo.zona } : SALIDA_INICIAL);
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const ciudad = salida.elegida();
    if (!ciudad) {
      salida.input.setCustomValidity("Elegí la ciudad de la lista que aparece al escribir.");
      salida.input.reportValidity();
      return;
    }
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      const datos = { numero: numero.value, aerolinea: aerolinea.value, fecha: fecha.value, hora: hora.value || null,
        zona: ciudad.zona, ciudad: ciudad.nombre };
      await (vuelo ? Viajes.editarVuelo(vuelo.id, datos) : Viajes.agregarVuelo(datos));
    } catch (err) { toast(mensajeError(err)); btn.disabled = false; return; }
    await alGuardar(vuelo ? "Vuelo actualizado." : "Vuelo agregado.", onGuardado, btn);
  } },
  Campo("Número de vuelo", numero), Campo("Aerolínea", aerolinea),
  h("div", { class: "actions" }, Campo("Fecha de salida", fecha), Campo("Hora de salida", hora)),
  Campo("Sale de", salida.input), salida.lista,
  h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, vuelo ? "Guardar cambios" : "Agregar vuelo"));
  return form;
}

/** Alta (sin `hotel`) o edición (con el hotel a editar, precargado). */
function FormHotel(onGuardado, hotel = null) {
  const nombre = h("input", { maxlength: 120, required: true, value: hotel?.nombre ?? "" });
  const direccion = h("input", { maxlength: 200, value: hotel?.direccion ?? "" });
  const checkin = h("input", { type: "datetime-local", required: true, value: hotel?.checkin ?? "" });
  const checkout = h("input", { type: "datetime-local", required: true, value: hotel?.checkout ?? "" });
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      const datos = { nombre: nombre.value, direccion: direccion.value, checkin: checkin.value, checkout: checkout.value,
        zona: hotel?.zona ?? ZONA_HOTEL };
      await (hotel ? Viajes.editarHotel(hotel.id, datos) : Viajes.agregarHotel(datos));
    } catch (err) { toast(mensajeError(err)); btn.disabled = false; return; }
    await alGuardar(hotel ? "Hotel actualizado." : "Hotel agregado.", onGuardado, btn);
  } },
  Campo("Nombre", nombre), Campo("Dirección", direccion),
  h("div", { class: "actions" }, Campo("Check-in", checkin), Campo("Check-out", checkout)),
  h("p", { class: "caption" }, "Las horas son las del hotel (Las Vegas)."),
  h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, hotel ? "Guardar cambios" : "Agregar hotel"));
  return form;
}

/** La tarjeta en modo edición: el mismo formulario del alta, precargado, con «Cancelar» para volver a la ficha. */
function EdicionCard(tipo, x, alTerminar) {
  const form = tipo === "vuelo" ? FormVuelo(alTerminar, x) : FormHotel(alTerminar, x);
  const titulo = tipo === "vuelo" ? `Editar vuelo ${x.numero}` : `Editar ${x.nombre}`;
  form.append(Button("Cancelar", { onclick: () => alTerminar().catch((err) => toast(mensajeError(err))) }));
  return h("article", { class: "ra-card stack", id: `${tipo}-${x.id}` }, h("h2", { class: "label" }, titulo), form);
}

/** `foco`: { tipo: "vuelo" | "hotel", id } cuando se llega desde un aviso o una tarjeta. */
export async function viewViajes(view, focoInicial = null) {
  let foco = focoInicial;
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
    // Cambia la tarjeta por el formulario precargado; guardar o cancelar repinta todo y vuelve a la ficha.
    const editar = (tipo, x) => () => {
      const card = EdicionCard(tipo, x, paint);
      document.getElementById(`${tipo}-${x.id}`)?.replaceWith(card);
      card.querySelector("input")?.focus();
    };
    const elegido = foco && (foco.tipo === "vuelo" ? data.vuelos : data.hoteles).find((x) => x.id === foco.id);
    const vuelos = data.vuelos.map((v) => VueloCard(v, { detalle: elegido === v, onQuitar: quitar("vuelo", v.id), onEditar: editar("vuelo", v) }));
    const hoteles = data.hoteles.map((x) => HotelCard(x, { detalle: elegido === x, onQuitar: quitar("hotel", x.id), onEditar: editar("hotel", x) }));
    raiz.replaceChildren(h("div", { class: "stack-lg" },
      h("h1", { class: "title" }, "Viajes"),
      foco && !elegido ? Hint("No encontramos ese vuelo u hotel: puede que ya lo hayas quitado.", { tone: "warn" }) : null,
      h("p", { class: "caption" }, "Cargá tus vuelos y hoteles y te avisamos cuándo abre el check-in, cuándo hacer el check-in y el check-out del hotel, y si tu vuelo se demora o cambia de puerta. Los avisos se prenden y apagan en Ajustes."),
      !data.estado_disponible ? Hint("Las alertas de demora y puerta no están activas en este servidor; el resto de los avisos anda igual.") : null,
      h("section", { class: "stack" }, h("h2", { class: "label" }, "Vuelos"),
        vuelos.length ? vuelos : h("p", { class: "caption" }, "Todavía no cargaste vuelos."),
        h("details", { class: "stack", open: !vuelos.length }, h("summary", { class: "label" }, "Agregar un vuelo"), FormVuelo(paint))),
      h("section", { class: "stack" }, h("h2", { class: "label" }, "Hoteles"),
        hoteles.length ? hoteles : h("p", { class: "caption" }, "Todavía no cargaste hoteles."),
        h("details", { class: "stack", open: !hoteles.length }, h("summary", { class: "label" }, "Agregar un hotel"), FormHotel(paint)))));
    if (elegido) document.getElementById(`${foco.tipo}-${foco.id}`)?.scrollIntoView({ block: "center" });
  }
  await paint();
}
