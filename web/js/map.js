// Mapa interactivo de venues (Google Maps JavaScript API, se carga sólo cuando hace falta).
import { Maps } from "./api.js";

let mapsPromise;

function loadGoogleMaps() {
  if (mapsPromise) return mapsPromise;
  mapsPromise = (async () => {
    if (window.google?.maps) return window.google.maps;
    const { key } = await Maps.key();
    if (!key) throw new Error("falta configurar GOOGLE_MAPS_API_KEY en el servidor");
    await new Promise((resolve, reject) => {
      window.__reinventarMapsReady = resolve;
      const script = document.createElement("script");
      script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&callback=__reinventarMapsReady&v=weekly`;
      script.onerror = () => reject(new Error("no se pudo cargar Google Maps"));
      document.head.append(script);
    });
    return window.google.maps;
  })();
  return mapsPromise;
}

const DAY_COLORS = ["#ff2e88", "#a98bff", "#ffb547", "#3ee8c8", "#ff8a3d"];

export async function renderMap(el, { days } = {}) {
  const maps = await loadGoogleMaps();
  el.replaceChildren();
  const map = new maps.Map(el, {
    center: { lat: 36.115, lng: -115.173 },
    zoom: 14,
    mapTypeControl: false,
    streetViewControl: false,
    fullscreenControl: false,
  });
  const infoWindow = new maps.InfoWindow();
  let markers = [];
  let polyline = null;

  function update(dayIndex) {
    markers.forEach((m) => m.setMap(null));
    markers = [];
    polyline?.setMap(null);
    polyline = null;

    const day = days[dayIndex];
    if (!day) return;

    const withCoords = day.sessions.filter((s) => s.venue?.lat != null);
    const byHotel = new Map();
    for (const s of withCoords) byHotel.set(s.venue.hotel, (byHotel.get(s.venue.hotel) || []).concat(s));

    const bounds = new maps.LatLngBounds();
    for (const [hotel, sessions] of byHotel) {
      const position = { lat: sessions[0].venue.lat, lng: sessions[0].venue.lng };
      const marker = new maps.Marker({ position, map, title: hotel });
      marker.addListener("click", () => {
        infoWindow.setContent(`<strong>${hotel}</strong><br>${sessions.map((s) => `${s.start} · ${s.title}`).join("<br>")}`);
        infoWindow.open(map, marker);
      });
      markers.push(marker);
      bounds.extend(position);
    }

    const path = [];
    let lastHotel;
    for (const s of withCoords) {
      if (s.venue.hotel !== lastHotel) { path.push({ lat: s.venue.lat, lng: s.venue.lng }); lastHotel = s.venue.hotel; }
    }
    if (path.length > 1) {
      polyline = new maps.Polyline({ path, map, strokeColor: DAY_COLORS[dayIndex % DAY_COLORS.length], strokeOpacity: 0.9, strokeWeight: 3 });
    }
    if (!bounds.isEmpty()) map.fitBounds(bounds, 40);
  }

  return { update };
}
