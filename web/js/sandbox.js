// Modo prueba: franja arriba de toda la app y la hora/ubicación simuladas para el resto de la PWA (countdown, Llevame).
// Lo prende un admin por usuario (Admin › Usuarios); el usuario no lo puede apagar.
import { Auth, getToken } from "./api.js";

const REFRESH_MS = 30_000;
let info = null;          // /api/me → sandbox: { stt, llm, now, simulated_clock, location }
let offsetMs = 0;         // hora simulada − hora del celular
let fetchedAt = 0;
let ticker = null;

const fmt = (date) => date.toLocaleString("es-AR", {
  timeZone: "America/Los_Angeles", weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit",
  hourCycle: "h23",
}).replace(/\./g, "");

/** La hora "de ahora" para la app: la simulada si el usuario está en modo prueba con reloj fijado. */
export const sandboxNow = () => new Date(Date.now() + offsetMs);

/** Ubicación simulada ({ id, name, lat, lng }) o null: la usa la geolocalización en lugar del GPS. */
export const sandboxLocation = () => info?.location || null;

export const inSandbox = () => Boolean(info);

function paint() {
  const el = document.getElementById("sandbox-banner");
  if (!el) return;
  el.hidden = !info;
  if (!info) return;
  const parts = ["MODO PRUEBA", info.simulated_clock ? fmt(sandboxNow()) : null, info.location?.name,
    `STT ${info.stt} · LLM ${info.llm}`].filter(Boolean);
  el.textContent = parts.join(" · ");
}

/** Relee /api/me cada tanto (al navegar) y repinta la franja; la hora simulada sigue corriendo en el celular. */
export async function refreshSandbox({ force = false } = {}) {
  if (!getToken()) { info = null; paint(); return; }
  if (!force && Date.now() - fetchedAt < REFRESH_MS) { paint(); return; }
  try {
    const me = await Auth.me();
    info = me.sandbox || null;
    offsetMs = info?.simulated_clock ? Date.parse(info.now) - Date.now() : 0;
    fetchedAt = Date.now();
  } catch {
    return; // sin red o sesión vencida: se queda con lo último que sabía
  }
  paint();
  clearInterval(ticker);
  ticker = info?.simulated_clock ? setInterval(paint, REFRESH_MS) : null;
}
