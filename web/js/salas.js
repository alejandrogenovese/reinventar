// Cómo llegar a la sala ADENTRO de cada sede de re:Invent: el punto del área de convenciones (para «Llevame») y una
// guía corta de pasos por sede y por piso. Es texto fijo: anda sin señal, no pide nada a la red.
//
// Fuentes (públicas, revisadas en noviembre de 2026):
// - Puntos: centro del edificio de convenciones en OpenStreetMap (© colaboradores de OpenStreetMap, ODbL).
// - AWS: https://aws.amazon.com/events/reinvent/know-before-you-go/ y
//   https://builder.aws.com/content/35iYepTKrrpDlEVwLGuPPfJ6X4y/know-before-you-go-attending-reinvent-2025-in-person
//   (puentes Wynn–Venetian, camino temporal Forum–Venetian, Wynn y Encore conectados, monorail gratis con el badge).
// - Venetian: https://www.lasvegashowto.com/venetian-expo y https://www.venetianlasvegas.com/meetings/expo-map-floor-plan.html
// - Caesars Forum: https://www.lasvegashowto.com/caesars-forum
// - MGM Grand: https://djwillgill.com/?p=31852 (guía de terceros: el recorrido va marcado como tal).
// - Caesars Palace: fact sheet de Caesars Palace (las torres Palace y Octavius dan acceso al centro de convenciones).
// - Encore: plano de salas de Encore (Chopin y Brahms en el área de convenciones) y FAQ de Wynn (Business Center
//   frente a Chopin).
// Lo que no se pudo respaldar no está; lo dudoso lleva `aConfirmar`.
import { h } from "./ui.js";

/** Punto del área de convenciones por sede (clave: nombre en reinvent.sede). Sin entrada → queda el punto del hotel. */
export const ENTRADAS = Object.freeze({
  "Venetian": { lat: 36.121898, lng: -115.16623, name: "Venetian Expo" },
  "Caesars Forum": { lat: 36.118937, lng: -115.166189, name: "Caesars Forum" },
  "Caesars Palace": { lat: 36.116389, lng: -115.178808, name: "Centro de convenciones de Caesars Palace" },
  "MGM Grand": { lat: 36.104554, lng: -115.164814, name: "MGM Grand Conference Center" },
});

/**
 * Pasos por sede. `nivel`: el paso solo se muestra si la ubicación de la sala empieza con ese piso ("Level 2 · Hall B").
 * `terceros`: el recorrido sale de una guía que no es oficial (se avisa debajo de los pasos).
 */
export const GUIAS = Object.freeze({
  "Venetian": {
    pasos: [
      { texto: "Desde el casino del Venetian, caminá hasta Restaurant Row, doblá a la derecha y pasá Starbucks y el Venetian Showroom: al fondo de ese pasillo está el centro de convenciones (Venetian Expo). Calculá unos 10 minutos." },
      { texto: "Desde el Palazzo, andá hacia la cascada del Atrium hasta Restaurant Row y ahí doblá a la izquierda." },
      { texto: "Si venís del Wynn, cruzá Sands Ave por el puente peatonal." },
      { nivel: "Level 1", texto: "En el Level 1 están Casanova, Marco Polo, Galileo y el Hall G." },
      { nivel: "Level 2", texto: "En el Level 2 están los Expo Halls (A a D) y los ballrooms del Venetian." },
      { nivel: "Level 3", texto: "En el Level 3 están las salas Murano." },
      { nivel: "Level 5", texto: "En el Level 5 está el Palazzo Ballroom." },
      { texto: "Adentro hay pantallas de orientación (way-finders) en todo el centro de convenciones." },
    ],
  },
  "Caesars Forum": {
    pasos: [
      { texto: "Lo más directo es el puente cubierto (Forum Sky Bridge) que sale de Harrah's y The LINQ. Ahí también para el monorail (estación Harrah's/The LINQ, gratis con el badge)." },
      { texto: "Desde el Venetian, en el horario de la Expo, re:Invent habilita un camino temporal directo al Forum." },
      { texto: "El Forum está todo en una sola planta: no hay que cambiar de piso." },
    ],
  },
  "MGM Grand": {
    terceros: true,
    pasos: [
      { texto: "Desde Las Vegas Blvd, entrá por el casino y caminá hacia CRUSH pasando el teatro de Jabbawockeez; en L'Atelier doblá a la derecha y entrás a The District." },
      { texto: "Seguí por The District pasando Craftsteak, International Smoke y el Grand Garden Arena." },
      { texto: "En el Spa Mezzanine bajá por las escaleras mecánicas al nivel de la pileta, doblá a la derecha y seguí el pasillo hasta el Conference Center." },
      { nivel: "Level 3", texto: "Para el Level 3, subí por las escaleras mecánicas del Conference Center, a la izquierda del pasillo.", aConfirmar: true },
      { texto: "En monorail: la estación MGM Grand es gratis con el badge." },
    ],
  },
  "Caesars Palace": {
    pasos: [
      { texto: "El centro de convenciones queda al fondo del complejo, del lado de las torres Palace y Octavius, cerca de la pileta Garden of the Gods y de Appian Way Shops." },
      { texto: "Seguí los carteles «Conference Center».", aConfirmar: true },
      { texto: "En monorail: la estación Flamingo/Caesars Palace es gratis con el badge." },
    ],
  },
  "Wynn/Encore": {
    pasos: [
      { texto: "Wynn y Encore están conectados por adentro: no hace falta salir a la calle para pasar de uno al otro." },
      { texto: "Desde el Venetian o el Palazzo, cruzá Sands Ave por el puente peatonal hacia el Wynn." },
      { nivel: "Level 1", texto: "Chopin, Brahms, Debussy y Encore Ballroom están en el área de convenciones de Encore; el Business Center queda frente a Chopin.", aConfirmar: true },
    ],
  },
});

// «Level 1» matchea «Level 1 · Chopin 4» pero no «Level 10»: el piso tiene que terminar ahí.
const empiezaCon = (detalle, nivel) => {
  const d = (detalle || "").toLowerCase(), n = nivel.toLowerCase();
  return d.startsWith(n) && !/[\p{L}\p{N}]/u.test(d.charAt(n.length));
};
// Búsquedas por nombre de sede solo en claves propias: «constructor» o «toString» no son sedes.
const propio = (tabla, clave) => (typeof clave === "string" && Object.hasOwn(tabla, clave) ? tabla[clave] : null);

/** Pasos que aplican a una sala: los generales y los de su piso. [] si la sede no tiene guía. */
export function pasosDeSala(hotel, detalle) {
  const guia = propio(GUIAS, hotel);
  if (!guia) return [];
  return guia.pasos.filter((p) => !p.nivel || empiezaCon(detalle, p.nivel));
}

/**
 * Destino de «Llevame» para una sala de re:Invent: la entrada del área de convenciones si la conocemos, si no el punto
 * del hotel. venue: { hotel, lat, lng }. null si no hay coordenadas.
 */
export function destinoDeSala(venue) {
  if (venue?.lat == null) return null;
  const entrada = propio(ENTRADAS, venue.hotel);
  return entrada ? { ...entrada } : { lat: venue.lat, lng: venue.lng, name: venue.hotel };
}

/**
 * Destino de una tarjeta de Hoy/itinerario. Las charlas (kind "talk" o sin kind) en una sede con entrada conocida van al
 * área de convenciones; eventos, shows y lo tuyo van a su lugar (con su place_id).
 */
export function destinoDeTarjeta(s) {
  const v = s?.venue;
  if (v?.lat == null) return null;
  if ((s.kind ?? "talk") === "talk" && propio(ENTRADAS, v.hotel)) return destinoDeSala(v);
  return { lat: v.lat, lng: v.lng, name: v.hotel, placeId: v.place_id, approx: v.exact === false };
}

/** Desplegable «Cómo llegar a la sala» con los pasos de la sede; null si la sede no tiene guía. */
export function GuiaSala(venue) {
  const pasos = pasosDeSala(venue?.hotel, venue?.detail);
  if (!pasos.length) return null;
  const terceros = propio(GUIAS, venue.hotel).terceros;
  return h("details", { class: "ra-guia-sala" },
    h("summary", { class: "label" }, "Cómo llegar a la sala"),
    h("ol", { class: "ra-guia-pasos" }, pasos.map((p) =>
      h("li", {}, p.texto, p.aConfirmar ? h("span", { class: "caption" }, " (a confirmar)") : null))),
    h("p", { class: "caption" }, terceros
      ? "Recorrido según guías de terceros. En el lugar, mandan los carteles de re:Invent."
      : "Armado con fuentes públicas. En el lugar, mandan los carteles de re:Invent."));
}
