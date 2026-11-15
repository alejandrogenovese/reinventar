// Lógica pura de «Llevame» con el mapa adentro de la app (sin DOM ni red: se prueba con node --test).
// Las coordenadas no salen del celular: el pedido de ruta va directo del navegador a Google con la clave del mapa.

const METROS_POR_KM = 1000;
const MS_POR_MINUTO = 60_000;

/**
 * ¿Se puede mostrar el recorrido adentro de la app? Si no, «Llevame» abre el link externo de Google Maps como siempre.
 * Hace falta un destino con coordenadas exactas, la ubicación (real o simulada) y conexión. La clave y la carga de la
 * API se resuelven después: si fallan, la hoja ofrece el mismo link.
 * @returns {{ embeber: true } | { embeber: false, motivo: "sin-destino"|"zona-aproximada"|"sin-ubicacion"|"sin-senal" }}
 */
export function decidirLlevame({ dest, here, online = true } = {}) {
  if (dest?.lat == null || dest?.lng == null) return { embeber: false, motivo: "sin-destino" };
  if (dest.approx) return { embeber: false, motivo: "zona-aproximada" };
  if (here?.lat == null || here?.lng == null) return { embeber: false, motivo: "sin-ubicacion" };
  if (online === false) return { embeber: false, motivo: "sin-senal" };
  return { embeber: true };
}

/** Pedido a la Routes API (Route.computeRoutes): a pie, de tu ubicación a la sede, con lo justo para dibujar y resumir. */
export function pedidoRuta(here, dest) {
  return {
    origin: { lat: here.lat, lng: here.lng },
    destination: { lat: dest.lat, lng: dest.lng },
    travelMode: "WALKING",
    fields: ["durationMillis", "distanceMeters", "viewport", "path"],
  };
}

/** "350 m" por debajo del kilómetro; "1,4 km" por encima (coma decimal, como el resto de la app). */
export function formatearDistancia(metros) {
  if (metros < METROS_POR_KM) return `${Math.max(10, Math.round(metros / 10) * 10)} m`;
  return `${(metros / METROS_POR_KM).toFixed(1).replace(".", ",")} km`;
}

/**
 * Resumen de una ruta de la Routes API: { minutos, distancia, texto } o null si la respuesta no trae duración (sin ruta).
 * @param {{ durationMillis?: number, distanceMeters?: number } | undefined} ruta
 */
export function resumenRuta(ruta) {
  if (!ruta?.durationMillis) return null;
  const minutos = Math.max(1, Math.ceil(ruta.durationMillis / MS_POR_MINUTO));
  const distancia = ruta.distanceMeters != null ? formatearDistancia(ruta.distanceMeters) : null;
  const texto = [`${minutos} min caminando`, distancia].filter(Boolean).join(" · ");
  return { minutos, distancia, texto };
}
