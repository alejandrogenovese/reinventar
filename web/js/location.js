// Ubicación del celular, distancias y "Llevame". La ubicación no sale del celular: se usa acá y en el link a Google Maps.
// En modo prueba se usa la sede simulada en lugar del GPS (web/js/sandbox.js).
import { loadGoogleMaps } from "./map.js";
import { sandboxLocation, sandboxNow } from "./sandbox.js";
import { icon } from "./icons.js";
import { h } from "./ui.js";

const SETTING = "ra.location";           // "off" = el usuario no quiere usar la ubicación
const POSITION_MAX_AGE_MS = 60_000;
const ETA_CACHE_MS = 5 * 60_000;
const WALK_M_PER_MIN = 75;               // sin Routes API: línea recta a paso tranquilo, con desvío
const DETOUR = 1.3;
const ALERTS = "ra.alerts";

/** { leaveMarginMin, startNoticeMin }: margen para salir (atravesar el hotel hasta la sala) y aviso de inicio.
 *  Se cambian en Ajustes › Alertas; los usan "Llevame" y el countdown. */
export const alertSettings = () => {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(ALERTS)) || {}; } catch {}
  return { leaveMarginMin: 10, startNoticeMin: 5, ...saved };
};
export const saveAlertSettings = (s) => { try { localStorage.setItem(ALERTS, JSON.stringify({ ...alertSettings(), ...s })); } catch {} };

let lastPosition = null;                 // { lat, lng, at }
let denied = false;
const etaCache = new Map();

export const locationEnabled = () => { try { return localStorage.getItem(SETTING) !== "off"; } catch { return true; } };
export const setLocationEnabled = (on) => { try { localStorage.setItem(SETTING, on ? "on" : "off"); } catch {} };

/** { lat, lng, simulated } o null (sin permiso, apagado en Ajustes o sin GPS). Nunca tira error. */
export async function currentPosition() {
  const simulated = sandboxLocation();
  if (simulated?.lat != null) return { lat: simulated.lat, lng: simulated.lng, simulated: true };
  if (!locationEnabled() || denied || !navigator.geolocation) return null;
  if (lastPosition && Date.now() - lastPosition.at < POSITION_MAX_AGE_MS) return lastPosition;
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (p) => { lastPosition = { lat: p.coords.latitude, lng: p.coords.longitude, at: Date.now() }; resolve(lastPosition); },
      (err) => {
        if (err.code === err.PERMISSION_DENIED) { denied = true; }
        resolve(null);
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: POSITION_MAX_AGE_MS });
  });
}

/** Distancia en línea recta, en metros (haversine). */
export function distanceMeters(a, b) {
  const rad = (d) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat), dLng = rad(b.lng - a.lng);
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(x));
}

export const formatDistance = (m) => (m < 1000 ? `a ${Math.round(m / 10) * 10} m` : `a ${(m / 1000).toFixed(1).replace(".", ",")} km`);

/**
 * Minutos caminando con la Routes API de Google (misma clave que el mapa), con caché de 5 min.
 * Si la API no está habilitada o falla, estima con la línea recta: { minutes, estimated }.
 */
export async function walkingMinutes(origin, dest) {
  const key = `${origin.lat.toFixed(3)},${origin.lng.toFixed(3)}>${dest.lat},${dest.lng}`;
  const hit = etaCache.get(key);
  if (hit && Date.now() - hit.at < ETA_CACHE_MS) return hit.value;
  let value;
  try {
    await loadGoogleMaps();
    const { Route } = await google.maps.importLibrary("routes");
    const { routes } = await Route.computeRoutes({
      origin: { lat: origin.lat, lng: origin.lng }, destination: { lat: dest.lat, lng: dest.lng },
      travelMode: "WALKING", fields: ["durationMillis", "distanceMeters"],
    });
    const ms = routes?.[0]?.durationMillis;
    if (!ms) throw new Error("sin ruta");
    value = { minutes: Math.ceil(ms / 60000), estimated: false };
  } catch {
    // Routes API no disponible (sin clave, sin red o sin ruta): se estima por distancia.
    value = { minutes: Math.ceil((distanceMeters(origin, dest) * DETOUR) / WALK_M_PER_MIN), estimated: true };
  }
  etaCache.set(key, { at: Date.now(), value });
  return value;
}

/** Link a Google Maps con la navegación a pie. En el celular abre la app de Maps. */
export function directionsUrl(dest, origin) {
  const params = new URLSearchParams({ api: "1", destination: `${dest.lat},${dest.lng}`, travelmode: "walking" });
  if (dest.placeId) params.set("destination_place_id", dest.placeId);
  if (origin?.simulated) params.set("origin", `${origin.lat},${origin.lng}`); // en modo prueba, desde la sede simulada
  return `https://www.google.com/maps/dir/?${params}`;
}

/** Inicio de una charla del itinerario como Date ("2026-12-01" + "14:00", hora de Las Vegas: PST en diciembre). */
export const startsAt = (day, hhmm) => new Date(`${day}T${hhmm}:00-08:00`);

const hhmm = (date) => date.toLocaleTimeString("es-AR", { timeZone: "America/Los_Angeles", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

/**
 * "(ubicación) a 1,4 km · 18 min caminando · salí 13:40  [Llevame]". Se completa sola cuando hay ubicación.
 * dest: { lat, lng, name, placeId?, approx? }; opts.start: Date del inicio (para "salí a las"); opts.eta: pedir tiempo a pie.
 * approx = la fuente solo da una zona (Luma muestra la dirección al anotarte): no se muestran distancia ni horarios.
 */
export function GoThere(dest, opts = {}) {
  const parts = GoThereParts(dest, opts);
  if (!parts) return null;
  return h("div", { class: "ra-go" }, parts.info, parts.link);
}

/**
 * Las dos piezas de GoThere por separado, para ponerlas en lugares distintos (en Hoy, el link va como botón de solo
 * ícono al lado de "Grabar"). `iconOnly`: el link muestra solo el ícono (48 px) y su nombre queda en aria-label.
 * @returns {{ info: HTMLElement, link: HTMLElement|null } | null}
 */
export function GoThereParts(dest, { start = null, eta = false, iconOnly = false } = {}) {
  if (dest?.lat == null) return null;
  const text = h("span", {});
  const info = h("span", { class: "ra-go-info ra-icotext" }, icon("ubicacion", 16), text);
  if (dest.approx) {
    text.textContent = "dirección exacta al anotarte";
    return { info, link: null };
  }
  const label = `Llevame a ${dest.name || "la sede"} con Google Maps`;
  const link = h("a", { class: `ra-btn ra-btn-secondary ra-go-btn${iconOnly ? " ra-btn-icon" : ""}`, href: directionsUrl(dest), target: "_blank",
    rel: "noopener", "aria-label": label, title: iconOnly ? "Llevame" : null }, icon("llevar", 20), iconOnly ? null : "Llevame");
  info.hidden = true; // sin ubicación no hay nada que decir: queda solo el botón
  void (async () => {
    const here = await currentPosition();
    if (!here) return;
    link.href = directionsUrl(dest, here);
    const parts = [formatDistance(distanceMeters(here, dest))];
    if (eta) {
      const { minutes, estimated } = await walkingMinutes(here, dest);
      parts.push(`${estimated ? "~" : ""}${minutes} min caminando`);
      if (start) {
        const leave = new Date(start.getTime() - (minutes + alertSettings().leaveMarginMin) * 60000);
        if (leave > sandboxNow()) parts.push(`salí ${hhmm(leave)}`);
        else if (start > sandboxNow()) parts.push("salí ya");
      }
    }
    text.textContent = parts.join(" · ");
    info.hidden = false;
  })();
  return { info, link };
}
