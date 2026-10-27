// Mapa interactivo de venues (Leaflet + OpenStreetMap vía CDN, se carga sólo cuando hace falta).
let leafletPromise;

function loadLeaflet() {
  if (leafletPromise) return leafletPromise;
  leafletPromise = new Promise((resolve, reject) => {
    if (window.L) return resolve(window.L);
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.append(link);
    const script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.onload = () => resolve(window.L);
    script.onerror = () => reject(new Error("No se pudo cargar el mapa"));
    document.head.append(script);
  });
  return leafletPromise;
}

const DAY_COLORS = ["#ff2e88", "#a98bff", "#ffb547", "#3ee8c8", "#ff8a3d"];

export async function renderMap(el, { days } = {}) {
  const L = await loadLeaflet();
  el.replaceChildren();
  const map = L.map(el, { scrollWheelZoom: false }).setView([36.115, -115.173], 14);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap", maxZoom: 19 }).addTo(map);
  return { map, update: (dayIndex) => _paintDay(map, L, days, dayIndex) };
}

function _paintDay(map, L, days, dayIndex) {
  map.eachLayer((layer) => { if (layer._itinerary) map.removeLayer(layer); });
  const day = days[dayIndex];
  if (!day) return;

  const withCoords = day.sessions.filter((s) => s.venue?.lat != null);
  const byHotel = new Map();
  for (const s of withCoords) byHotel.set(s.venue.hotel, (byHotel.get(s.venue.hotel) || []).concat(s));

  const points = [];
  for (const [hotel, sessions] of byHotel) {
    const { lat, lng } = sessions[0].venue;
    const marker = L.marker([lat, lng]).addTo(map);
    marker._itinerary = true;
    marker.bindPopup(`<strong>${hotel}</strong><br>${sessions.map((s) => `${s.start} · ${s.title}`).join("<br>")}`);
    points.push([lat, lng]);
  }

  const path = [];
  let lastHotel;
  for (const s of withCoords) {
    if (s.venue.hotel !== lastHotel) { path.push([s.venue.lat, s.venue.lng]); lastHotel = s.venue.hotel; }
  }
  if (path.length > 1) {
    const line = L.polyline(path, { color: DAY_COLORS[dayIndex % DAY_COLORS.length], weight: 3, dashArray: "6 6" }).addTo(map);
    line._itinerary = true;
  }
  if (points.length) map.fitBounds(points, { padding: [24, 24] });
}
