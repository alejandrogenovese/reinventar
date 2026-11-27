// re:Invent día por día (#/viaje/reinvent): badge, keynotes, shuttles, Expo, re:Play, comidas y tips de Las Vegas.
// Es texto fijo, como salas.js: anda sin señal (el service worker precachea este archivo). Lo único que se pide a la red
// es el pronóstico de la sección de clima (el mismo de Hoy, clima.js); sin señal va la última copia y, si no hay, nada.
// Cada sección dice de dónde sale y cuándo se consultó. Lo que no se pudo respaldar con una fuente no está.
import { cargarClima } from "./clima.js";
import { icon } from "./icons.js";
import { h } from "./ui.js";

export const CONSULTA = "25/11/2026";

/** Fuentes, todas consultadas el 25/11/2026. */
export const FUENTES = Object.freeze({
  agenda: { nombre: "Agenda de re:Invent 2026 (AWS)", url: "https://aws.amazon.com/events/reinvent/agenda/" },
  faq: { nombre: "Preguntas frecuentes de re:Invent 2026 (AWS)", url: "https://aws.amazon.com/events/reinvent/faqs/" },
  kbyg: { nombre: "Know before you go (AWS)", url: "https://aws.amazon.com/events/reinvent/know-before-you-go/" },
  clima: { nombre: "Climatología de diciembre en Las Vegas, normales 1991–2020 (NWS)",
    url: "https://www.weather.gov/media/vef/Las_Vegas_climate_book_December.pdf" },
  propinas: { nombre: "Las Vegas Tipping Guide (Vegas411, guía de terceros, 2020)",
    url: "https://vegas411.com/list/las-vegas-tipping-guide-who-gets-what" },
  enchufes: { nombre: "Enchufes y tensión en Estados Unidos (Walkabout Travel Gear, guía de terceros)",
    url: "https://www.walkabouttravelgear.com/countries/united_states.html" },
});

/** Livestream oficial de las keynotes (gratis, con registro). Lo usa también la tarjeta de anuncios (anuncios.js). */
export const LIVESTREAM_URL = "https://aws.amazon.com/events/reinvent/livestream/";
/** Lo que dice el FAQ sobre traducción en las keynotes (no aclara cómo se accede). */
export const TRADUCCION_KEYNOTES = "Traducción al español (latinoamericano), sin pedirla antes";

/**
 * Secciones de la ficha: { id, titulo, items, nota?, fuentes }. Cada item es { cuando?, dias?, texto }: `cuando` es el día
 * (o la etiqueta) que va en negrita adelante; `dias` (fechas de Las Vegas, «2026-12-03»), los días en que el ítem sale
 * también en «Hoy en re:Invent» de Inicio (hoyEnReinvent). `fuentes` son claves de FUENTES.
 */
export const SECCIONES = Object.freeze([
  {
    id: "badge", titulo: "Retiro del badge",
    items: [
      { cuando: "Dom 29/11", dias: ["2026-11-29"], texto: "Aeropuerto Harry Reid, terminales 1 y 3: 7:00 a 23:59. MGM Grand y Venetian: 10:00 a 20:00." },
      { cuando: "Lun 30/11", dias: ["2026-11-30"], texto: "Aeropuerto, terminales 1 y 3: 7:00 a 23:59. Venetian: 6:30 a 17:30. MGM Grand: 6:30 a 21:00." },
      { cuando: "Mar 1/12 a jue 3/12", texto: "MGM Grand y Venetian: 6:30 a 20:00." },
      { cuando: "Vie 4/12", texto: "No hay retiro de badge." },
      { texto: "Llevá un documento con foto emitido por un gobierno (el pasaporte) y usá el badge toda la semana." },
      { texto: "Subí tu foto al portal de registro antes de viajar: el retiro es más rápido." },
    ],
    fuentes: ["agenda", "kbyg"],
  },
  {
    id: "keynotes", titulo: "Keynotes",
    items: [
      { cuando: "Lun 30/11", dias: ["2026-11-30"], texto: "Developer Keynote, 19:30 a 20:45." },
      { cuando: "Mar 1/12", dias: ["2026-12-01"], texto: "CEO Keynote con Matt Garman, 8:30 a 10:45." },
      { cuando: "Mié 2/12", dias: ["2026-12-02"], texto: "Data & AI Keynote, 8:30 a 10:00. Partner Keynote, 15:00 a 16:00." },
      { cuando: "Jue 3/12", dias: ["2026-12-03"], texto: "Technical Innovations Keynote, 8:30 a 10:00." },
      { texto: "Todas en el Venetian. No hace falta reservar lugar." },
      { texto: `${TRADUCCION_KEYNOTES}; también hay japonés, coreano y mandarín. La fuente no dice cómo se accede.` },
      { texto: "Livestream gratis del 29/11 al 3/12, con registro." },
    ],
    links: [{ texto: "Ver el livestream", url: LIVESTREAM_URL }],
    fuentes: ["agenda", "faq"],
  },
  {
    id: "shuttles", titulo: "Shuttles",
    items: [
      { cuando: "Dom 29/11", dias: ["2026-11-29"], texto: "9:30 a 20:30, servicio limitado: Caesars Forum, MGM Grand y Venetian." },
      { cuando: "Lun 30/11", texto: "6:00 a 21:15." },
      { cuando: "Mar 1/12 y mié 2/12", texto: "6:00 a 20:30." },
      { cuando: "Jue 3/12", dias: ["2026-12-03"], texto: "6:00 a 17:45. Para re:Play, 18:15 a 23:00." },
      { cuando: "Vie 4/12", dias: ["2026-12-04"], texto: "6:30 a 13:00, servicio limitado: Venetian y Wynn/Encore." },
      { texto: "Shuttles y monorail son gratis con el badge. Entre sedes calculá de 30 a 45 minutos." },
    ],
    fuentes: ["agenda", "faq", "kbyg"],
  },
  {
    id: "expo", titulo: "Expo (Venetian)",
    items: [
      { cuando: "Lun 30/11", dias: ["2026-11-30"], texto: "Welcome Reception, 16:00 a 19:00." },
      { cuando: "Mar 1/12", texto: "10:00 a 18:00." },
      { cuando: "Mié 2/12", texto: "10:00 a 18:00, con happy hour de 16:30 a 18:00." },
      { cuando: "Jue 3/12", texto: "10:00 a 16:00." },
      { cuando: "Vie 4/12", texto: "La agenda no la lista." },
    ],
    fuentes: ["agenda", "kbyg"],
  },
  {
    id: "certificacion", titulo: "Certificaciones",
    items: [
      { texto: "AWS Certification Lounge en Caesars Forum, de domingo a viernes. Mesa «Verify my AWS Certification» en el Venetian, domingo y lunes. No publicaron horarios." },
      { texto: "Con la entrada tenés 50 % de descuento en los exámenes de certificación de AWS (con condiciones)." },
    ],
    fuentes: ["faq", "kbyg"],
  },
  {
    id: "replay", titulo: "re:Play",
    items: [
      { cuando: "Jue 3/12", dias: ["2026-12-03"], texto: "18:30 a 22:30 en el Allegiant Stadium. Shuttle de 18:15 a 23:00. Entrás con el badge." },
    ],
    fuentes: ["agenda", "faq"],
  },
  {
    id: "comidas", titulo: "Comidas",
    items: [
      { texto: "Desayuno, almuerzo y snacks los días completos de conferencia. Halal y kosher hasta agotar: se piden antes por soporte." },
      { cuando: "Mar 1/12 y mié 2/12", dias: ["2026-12-01", "2026-12-02"], texto: "Networking receptions con comida y bebida, 18:00 a 20:00." },
    ],
    fuentes: ["faq", "agenda"],
  },
  {
    id: "propinas", titulo: "Propinas en Las Vegas",
    items: [
      { texto: "Restaurante: 15 a 20 %. Tragos en el casino: US$ 1 a 2. Mucama: unos US$ 2 por día." },
      { texto: "Maletero: US$ 1 a 2 por valija. Taxi o Uber: 10 % como mínimo. Valet: de US$ 2 a 5." },
    ],
    nota: "Son costumbres, no reglas: es una guía de terceros.",
    fuentes: ["propinas"],
  },
  {
    id: "clima", titulo: "Clima en diciembre",
    items: [
      { texto: "Del 1 al 7/12, la normal es de 14 a 16 °C de máxima (58–60 °F) y de 4 a 6 °C de mínima (40–42 °F)." },
      { texto: "De día puede estar templado y a la noche refresca. El aire es muy seco: llevá botella para cargar agua." },
    ],
    fuentes: ["clima", "kbyg"],
  },
  {
    id: "enchufes", titulo: "Enchufes",
    items: [
      { texto: "Tipo A y tipo B (patas planas), 120 V y 60 Hz. Si tu cargador tiene ficha argentina, llevá un adaptador tipo A." },
    ],
    fuentes: ["enchufes"],
  },
]);

/** Lo propio de re:Invent en esa fecha de Las Vegas («2026-12-03»): [{ seccion, texto }], en el orden de la ficha. */
export function hoyEnReinvent(fecha, secciones = SECCIONES) {
  return secciones.flatMap((s) => s.items.filter((i) => i.dias?.includes(fecha)).map((i) => ({ seccion: s.titulo, texto: i.texto })));
}

const LinkExterno = (texto, url) =>
  h("a", { class: "ra-link", href: url, target: "_blank", rel: "noopener noreferrer" }, texto, icon("externo", 16));

function Item({ cuando, texto }) {
  return h("li", {}, cuando ? h("strong", {}, `${cuando}: `) : null, texto);
}

function Fuentes(claves) {
  return h("p", { class: "caption ra-dxd-fuente" }, `Fuente (consultada el ${CONSULTA}): `,
    claves.flatMap((k, i) => [i ? " · " : null, LinkExterno(FUENTES[k].nombre, FUENTES[k].url)]).filter(Boolean));
}

/** Una sección de la ficha, con su título, lo `extra` (el pronóstico en la de clima), la lista, los links y las fuentes. */
export function Seccion(s, extra = null) {
  const idTitulo = `dxd-${s.id}`;
  return h("section", { class: "ra-card stack", "aria-labelledby": idTitulo },
    h("h2", { class: "ra-card-title", id: idTitulo }, s.titulo),
    extra,
    h("ul", { class: "ra-dxd-lista" }, s.items.map(Item)),
    s.nota ? h("p", { class: "caption" }, s.nota) : null,
    s.links?.length ? h("div", {}, s.links.map((l) =>
      h("a", { class: "ra-btn ra-btn-ghost", href: l.url, target: "_blank", rel: "noopener noreferrer" }, l.texto, icon("externo", 16)))) : null,
    Fuentes(s.fuentes));
}

export function viewDiaPorDia(view) {
  const pronostico = h("div", { class: "ra-optional" });
  void cargarClima(pronostico);
  view.append(h("div", { class: "stack-lg" },
    h("div", { class: "stack" },
      h("h1", { class: "title" }, "re:Invent día por día"),
      h("p", { class: "caption" }, "Lo que conviene tener a mano durante la estadía en Las Vegas. Anda sin señal.")),
    h("div", { class: "stack" }, SECCIONES.map((s) => Seccion(s, s.id === "clima" ? pronostico : null)))));
}
