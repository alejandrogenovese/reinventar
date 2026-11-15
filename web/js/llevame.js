// «Llevame» con el mapa adentro de la app: una hoja con el recorrido a pie desde tu ubicación hasta la sede, la duración
// y la distancia, y el botón «Abrir en Google Maps» para la navegación paso a paso. Si algo falla (sin clave, sin red,
// sin la Routes API) la hoja lo dice y deja el mismo link externo de siempre. La ubicación no va al servidor: el
// pedido de ruta sale del navegador directo a Google, como walkingMinutes (web/js/location.js).
import { icon } from "./icons.js";
import { decidirLlevame, pedidoRuta, resumenRuta } from "./llevamePuro.js";
import { loadGoogleMaps } from "./map.js";
import { h } from "./ui.js";

const COLOR_RUTA = "#2970bc"; // info de la paleta de Brick, igual que el punto «Vos» de map.js
const PADDING_MAPA_PX = 40;

/** ¿Conviene abrir la hoja? Lo usa location.js en el click: si no, deja que el link abra Google Maps. */
export const sePuedeEmbeber = (dest, here) => decidirLlevame({ dest, here, online: navigator.onLine }).embeber;

/** Dibuja la ruta en `el` y devuelve { minutos, distancia, texto }. Tira error si no hay clave, red o ruta. */
async function dibujarRuta(el, here, dest) {
  const maps = await loadGoogleMaps();
  const { Route } = await maps.importLibrary("routes");
  const { routes } = await Route.computeRoutes(pedidoRuta(here, dest));
  const ruta = routes?.[0];
  const resumen = resumenRuta(ruta);
  if (!resumen) throw new Error("sin ruta");

  const map = new maps.Map(el, { center: dest, zoom: 16, mapTypeControl: false, streetViewControl: false, fullscreenControl: false });
  for (const linea of ruta.createPolylines()) {
    linea.setOptions({ strokeColor: COLOR_RUTA, strokeOpacity: 0.9, strokeWeight: 5 });
    linea.setMap(map);
  }
  const vos = new maps.Marker({ position: { lat: here.lat, lng: here.lng }, title: here.simulated ? "Vos (simulado)" : "Vos", zIndex: 999,
    icon: { path: maps.SymbolPath.CIRCLE, scale: 8, fillColor: COLOR_RUTA, fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 2 } });
  const sede = new maps.Marker({ position: { lat: dest.lat, lng: dest.lng }, title: dest.name || "Sede" });
  vos.setMap(map);
  sede.setMap(map);
  if (ruta.viewport) map.fitBounds(ruta.viewport, PADDING_MAPA_PX);
  return resumen;
}

/**
 * Abre la hoja de «Llevame» con el recorrido.
 * @param {{ dest: {lat:number,lng:number,name?:string}, here: {lat:number,lng:number,simulated?:boolean}, urlExterna: string, opener?: HTMLElement }} args
 */
export function abrirLlevame({ dest, here, urlExterna, opener = document.activeElement }) {
  const nombre = dest.name || "la sede";
  const mapa = h("div", { class: "ra-llevame-mapa", role: "img", "aria-label": `Mapa del recorrido a pie hasta ${nombre}` });
  const estado = h("p", { class: "ra-llevame-estado", role: "status" }, "Calculando el recorrido…");
  const abrir = h("a", { class: "ra-btn ra-btn-primary", href: urlExterna, target: "_blank", rel: "noopener" },
    icon("externo", 20), "Abrir en Google Maps");
  const dlg = h("dialog", { class: "ra-sheet ra-llevame", "aria-labelledby": "llevame-titulo" },
    h("div", { class: "ra-sheet-head" },
      h("button", { type: "button", class: "iconbtn", "aria-label": "Volver", onclick: () => dlg.close() }, icon("volver", 24)),
      h("h2", { class: "ra-dialog-title", id: "llevame-titulo" }, `Llevame a ${nombre}`)),
    h("div", { class: "ra-sheet-body ra-llevame-cuerpo" }, mapa, estado),
    h("div", { class: "ra-sheet-foot actions" }, abrir));
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener("close", () => { dlg.remove(); if (opener?.isConnected) opener.focus(); });
  document.body.append(dlg);
  dlg.showModal();
  abrir.focus();

  dibujarRuta(mapa, here, dest).then(
    (resumen) => { estado.textContent = `${resumen.texto}${here.simulated ? " · desde tu ubicación simulada" : ""}`; },
    (err) => {
      console.error("Llevame: no se pudo dibujar la ruta", err);
      mapa.hidden = true;
      estado.textContent = "No pudimos mostrar el mapa acá. Abrilo en Google Maps para llegar.";
    });
}
