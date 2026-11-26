// «Uber» y «Lyft» al lado de «Llevame», con el destino ya cargado, y dónde te levanta el auto en cada sede de re:Invent
// y en el aeropuerto. En Las Vegas cada hotel tiene su zona de rideshare (casi siempre en un garage o una puerta
// lateral, lejos del lobby) y en el aeropuerto hay que ir a un nivel del garage de cada terminal.
//
// Sin API keys ni precios: las APIs de estimación de Uber y Lyft son solo para socios aprobados. Se usan los links
// universales (https): con la app instalada la abren; si no, abren la web. A la URL va solo el destino (coordenadas y,
// en Uber, el nombre del lugar); el punto de partida es la ubicación que el celular le da a la app de Uber o Lyft.
//
// Formato de los links (revisado en noviembre de 2026):
// - Uber: https://m.uber.com/looking?drop[0]={"latitude":…,"longitude":…,"addressLine1":"…"} (JSON codificado).
//   Fuente: https://developer.uber.com/docs/riders/ride-requests/tutorials/deep-links/introduction (Universal Deep
//   Links: «pickup» y «drop[]» son objetos Location con latitude, longitude y addressLine1). Sin «pickup», la app sale
//   de la ubicación actual. /looking figura en https://m.uber.com/.well-known/apple-app-site-association.
// - Lyft: https://www.lyft.com/ride?id=lyft&destination[latitude]=…&destination[longitude]=…
//   Fuente: SDK oficial de Lyft (github.com/lyft/lyft-ios-sdk, Sources/LyftUI/LyftDeepLink.swift, y
//   lyft-android-sdk, deeplink/DeepLink.java: id, destination[latitude], destination[longitude]). /ride figura en
//   https://www.lyft.com/.well-known/apple-app-site-association; sin la app, redirige a ride.lyft.com/u (la web).
//
// Zonas de rideshare: ver ZONAS (cada una con su fuente). Lo que no tiene fuente oficial va con `aConfirmar`.
import { currentPosition, distanceMeters } from "./location.js";
import { icon } from "./icons.js";
import { h } from "./ui.js";

const NOMBRE_MAX = 80;          // el nombre del destino viaja en la URL de Uber: corto y sin saltos de línea
const RADIO_ZONA_M = 300;       // a esta distancia de un punto de la sede se considera que estás (o vas) ahí
const DECIMALES = 6;            // ~10 cm: más precisión no suma y alarga la URL

/** true si lat/lng son números válidos (null, "" o NaN no sirven para un link). */
export function coordenadasValidas(p) {
  if (p?.lat == null || p?.lng == null || p.lat === "" || p.lng === "") return false;
  const lat = Number(p.lat), lng = Number(p.lng);
  return Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180;
}

const redondear = (n) => Number(Number(n).toFixed(DECIMALES));
const nombreLimpio = (nombre) => (typeof nombre === "string" ? nombre.replace(/\s+/g, " ").trim().slice(0, NOMBRE_MAX) : "");

/** Link universal de Uber con el destino cargado y la partida en la ubicación actual. null sin coordenadas. */
export function uberUrl(dest) {
  if (!coordenadasValidas(dest)) return null;
  const nombre = nombreLimpio(dest.name);
  const drop = { latitude: redondear(dest.lat), longitude: redondear(dest.lng), ...(nombre ? { addressLine1: nombre } : {}) };
  return `https://m.uber.com/looking?${encodeURIComponent("drop[0]")}=${encodeURIComponent(JSON.stringify(drop))}`;
}

/** Link universal de Lyft con el destino cargado (Lyft no toma el nombre: solo coordenadas). null sin coordenadas. */
export function lyftUrl(dest) {
  if (!coordenadasValidas(dest)) return null;
  const params = new URLSearchParams({ id: "lyft", "destination[latitude]": String(redondear(dest.lat)),
    "destination[longitude]": String(redondear(dest.lng)) });
  return `https://www.lyft.com/ride?${params}`;
}

/**
 * Zonas de rideshare (Uber y Lyft) por sede y en el aeropuerto. `puntos`: dónde está la sede (hotel y área de
 * convenciones, como en salas.js) para reconocerla por coordenadas. `subida`: dónde te levanta el auto; `bajada`, solo
 * si te deja en otro lado. `fuente`: de dónde sale; `aConfirmar`: la fuente no es oficial.
 */
export const ZONAS = Object.freeze({
  venetian: {
    nombre: "Venetian",
    puntos: [[36.1216, -115.1691], [36.121898, -115.16623], [36.1245, -115.1685]],
    subida: [
      "Nivel 2 del garage de huéspedes del Venetian: desde el casino doblá a la derecha y seguí los carteles «Rideshare» (escalera mecánica a Grand Canal Shoppes y un pasillo hasta el garage).",
      "O en el Lower Porte Cochere del Palazzo: bajá por las escaleras mecánicas frente a la recepción del Palazzo; se espera junto a la fuente.",
    ],
    fuente: "https://www.venetianlasvegas.com/resort/rideshare.html",
  },
  forum: {
    nombre: "Caesars Forum",
    puntos: [[36.1179, -115.1641], [36.118937, -115.166189]],
    subida: ["Frente a la entrada del Forum, sobre Koval Lane (3911 S Koval Ln): pedilo con esa dirección."],
    fuente: "https://affiliatesummit.freshdesk.com/support/solutions/articles/9000232707-how-do-i-get-to-the-venue",
    aConfirmar: true,
  },
  caesarsPalace: {
    nombre: "Caesars Palace",
    puntos: [[36.11778, -115.175], [36.116389, -115.178808]],
    subida: [
      "En el garage (Parking Garage), junto al valet del Colosseum: andá para el lado de la Colosseum Tower y seguí los carteles.",
      "El mapa de octubre de 2026 la marca como zona de Lyft; con Uber, fijate el punto que te marca la app.",
    ],
    fuente: "https://www.caesars.com/content/dam/empire/clv/transportation/maps/clv-property-map-10-29-26.pdf",
  },
  mgmGrand: {
    nombre: "MGM Grand",
    puntos: [[36.102219, -115.169517], [36.104554, -115.164814]],
    subida: ["Planta baja del garage de autoestacionamiento (self-parking) del MGM Grand."],
    fuente: "https://lasvegasthenandnow.com/uber-lyft-pick-up-locations-at-every-las-vegas-strip-resort/",
    aConfirmar: true,
  },
  wynnEncore: {
    nombre: "Wynn/Encore",
    puntos: [[36.126492, -115.165741], [36.129, -115.1652]],
    subida: ["En el valet principal del Wynn o en la entrada principal del Encore."],
    fuente: "https://www.wynnlasvegas.com/about-us/lost-and-found",
  },
  lasT1: {
    nombre: "Aeropuerto LAS, Terminal 1",
    puntos: [[36.08, -115.1523]],
    subida: ["Nivel 2 del garage: desde el retiro de equipaje, tomá el ascensor cerca de la puerta 2 hasta el Level 2, cruzá el puente peatonal y la zona queda a la derecha."],
    bajada: "Te deja en la vereda de salidas (Departures) de la Terminal 1.",
    fuente: "https://www.harryreidairport.com/taxi-and-ride-share/ride-share",
  },
  lasT3: {
    nombre: "Aeropuerto LAS, Terminal 3",
    puntos: [[36.0857, -115.1611]],
    subida: ["Nivel Valet del garage: desde el retiro de equipaje, tomá el ascensor cerca de las puertas 52, 54 o 56 hasta el Level 1, cruzá el puente peatonal y bajá al nivel Valet."],
    bajada: "Te deja en la vereda de salidas (Departures) de la Terminal 3.",
    fuente: "https://www.harryreidairport.com/taxi-and-ride-share/ride-share",
  },
});

/** Clave de la zona más cercana a la posición, si está a menos de `radioM` de alguno de sus puntos; si no, null. */
export function zonaCercana(pos, radioM = RADIO_ZONA_M) {
  if (!coordenadasValidas(pos)) return null;
  let mejor = null;
  for (const [clave, zona] of Object.entries(ZONAS)) {
    for (const [lat, lng] of zona.puntos) {
      const d = distanceMeters({ lat: Number(pos.lat), lng: Number(pos.lng) }, { lat, lng });
      if (d <= radioM && (!mejor || d < mejor.d)) mejor = { clave, d };
    }
  }
  return mejor ? mejor.clave : null;
}

/** Zona de la terminal de llegada a LAS ("1", "3", "T3"…). Sin terminal conocida, null (se muestran las dos). */
export function zonaDeTerminal(terminal) {
  const n = String(terminal ?? "").replace(/\D/g, "");
  return n === "1" ? "lasT1" : n === "3" ? "lasT3" : null;
}

const aConfirmar = (zona) => (zona.aConfirmar ? h("span", { class: "caption" }, " (a confirmar)") : null);

/** Líneas de una zona: dónde te levanta (y dónde te deja, si es otro lado) con la fuente. */
export function DetalleZona(clave) {
  const zona = ZONAS[clave];
  if (!zona) return null;
  return h("div", { class: "ra-auto-zona" },
    h("p", { class: "caption" }, h("strong", {}, zona.nombre)),
    zona.subida.map((linea) => h("p", { class: "caption" }, linea, aConfirmar(zona))),
    zona.bajada ? h("p", { class: "caption" }, zona.bajada) : null,
    h("p", { class: "caption" }, "Fuente: ", h("a", { class: "ra-link", href: zona.fuente, target: "_blank", rel: "noopener" },
      new URL(zona.fuente).hostname.replace(/^www\./, ""))));
}

/** Desplegable «Dónde te levanta el auto» con una o varias zonas; null si no hay ninguna. */
export function DondeTeLevanta(claves, titulo = "Dónde te levanta el auto") {
  const validas = claves.filter((c) => ZONAS[c]);
  if (!validas.length) return null;
  return h("details", { class: "ra-guia-sala ra-auto-zonas" },
    h("summary", { class: "label" }, titulo),
    validas.map(DetalleZona),
    h("p", { class: "caption" }, "Las zonas cambian: en el lugar mandan los carteles «Rideshare» y el punto que marca la app."));
}

const botonAuto = (servicio, href, nombre) => h("a", {
  class: "ra-btn ra-btn-secondary ra-auto-btn", href, target: "_blank", rel: "noopener",
  "aria-label": `Pedir ${servicio} a ${nombre}`,
}, icon("auto", 20), servicio);

/** «Estás en X. El auto te levanta en: …» si la posición cae en una sede o en el aeropuerto distinto del destino. */
export function textoAca(aqui, zonaDestino) {
  const clave = aqui ? zonaCercana(aqui) : null;
  if (!clave || clave === zonaDestino) return "";
  const zona = ZONAS[clave];
  return `Estás en ${zona.nombre}. El auto te levanta en: ${zona.subida[0]}${zona.aConfirmar ? " (a confirmar)" : ""}`;
}

/**
 * Botones «Uber» y «Lyft» con el destino cargado, más dónde te levanta el auto: la zona del destino (para la vuelta)
 * en un desplegable y, con `aca` (solo en las fichas de detalle, no en las listas), la zona de la sede donde estás.
 * dest: { lat, lng, name }. null sin coordenadas o con destino aproximado. `zonas` es null si no hay nada que mostrar.
 * @returns {{ botones: HTMLElement[], zonas: HTMLElement|null } | null}
 */
export function PedirAuto(dest, { aca = false } = {}) {
  if (!coordenadasValidas(dest) || dest.approx) return null;
  const nombre = nombreLimpio(dest.name) || "el destino";
  const botones = [botonAuto("Uber", uberUrl(dest), nombre), botonAuto("Lyft", lyftUrl(dest), nombre)];
  const zonaDestino = zonaCercana(dest);
  const desplegable = zonaDestino ? DondeTeLevanta([zonaDestino], `Dónde te levanta el auto en ${ZONAS[zonaDestino].nombre}`) : null;
  if (!aca) return { botones, zonas: desplegable ? h("div", { class: "ra-auto-info" }, desplegable) : null };
  const lineaAca = h("p", { class: "caption ra-auto-aca" });
  lineaAca.hidden = true; // aparece solo si la app sabe que estás en una sede o en el aeropuerto
  const zonas = h("div", { class: "ra-auto-info" }, lineaAca, desplegable);
  zonas.hidden = !desplegable; // sin desplegable, el contenedor no ocupa lugar hasta que haya un «Estás en…»
  void (async () => {
    const texto = textoAca(await currentPosition(), zonaDestino);
    if (!texto) return;
    lineaAca.textContent = texto;
    lineaAca.hidden = false;
    zonas.hidden = false;
  })();
  return { botones, zonas };
}
