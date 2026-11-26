// Modo prueba: franja arriba de toda la app y la hora/ubicación simuladas para el resto de la PWA (countdown, Llevame).
// Lo prende un admin por usuario (Admin › Usuarios); el usuario no lo puede apagar.
import { Auth, conTope, duenoDeCopias, getToken, guardarCuenta, ME_TIMEOUT_MS, sinServicio } from "./api.js";
import { loadLast, saveLast } from "./lastgood.js";

// La última respuesta de /api/me (solo el modo prueba) se guarda en este celular por usuario, junto a las otras copias sin
// señal de lastgood.js (se borra al cerrar sesión). Si la app se abre sin red, /api/me falla y sin esto se perdería la
// franja y el reloj simulado (Hoy mostraba «Empieza en 379:15:47» con la hora real del celular).
const RUTA_COPIA = "/api/me/sandbox";

const REFRESH_MS = 30_000;
let info = null;          // /api/me → sandbox: { stt, llm, now, simulated_clock, location }
let offsetMs = 0;         // hora simulada − hora del celular
let fetchedAt = 0;
let ticker = null;

const fmt = (date) => date.toLocaleString("es-AR", {
  timeZone: "America/Los_Angeles", weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit",
  hourCycle: "h23",
}).replaceAll(".", "");

/** La hora "de ahora" para la app: la simulada si el usuario está en modo prueba con reloj fijado. */
export const sandboxNow = () => new Date(Date.now() + offsetMs);

/** Ubicación simulada ({ id, name, lat, lng }) o null: la usa la geolocalización en lugar del GPS. */
export const sandboxLocation = () => info?.location || null;

export const inSandbox = () => Boolean(info);

/** Fija el modo prueba y el desfase del reloj: la hora simulada era `info.now` cuando se pidió (`pedidoEn`, ms del celular). */
function aplicar(sandbox, pedidoEn) {
  info = sandbox;
  offsetMs = info?.simulated_clock ? Date.parse(info.now) - pedidoEn : 0;
}

async function guardarCopia(sandbox, pedidoEn) {
  const dueno = await duenoDeCopias();
  if (dueno) saveLast(dueno, RUTA_COPIA, { sandbox }, pedidoEn);
}

/** Usa la última copia si la hay y tiene la forma esperada; true si la aplicó. */
async function usarCopia() {
  const dueno = await duenoDeCopias();
  const copia = dueno ? loadLast(dueno, RUTA_COPIA) : null;
  if (!copia || !("sandbox" in copia.data)) return false;
  const sandbox = copia.data.sandbox;
  if (sandbox !== null && (typeof sandbox !== "object" || (sandbox.simulated_clock && !Number.isFinite(Date.parse(sandbox.now))))) return false;
  aplicar(sandbox, copia.at);
  return true;
}

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
    // Se espera antes de dibujar (app.js): con tope, para que un Wi-Fi que no responde no deje la pantalla en blanco.
    const me = await Auth.me({ signal: conTope(ME_TIMEOUT_MS) });
    const ahora = Date.now();
    aplicar(me.sandbox || null, ahora);
    fetchedAt = ahora;
    await guardarCopia(me.sandbox || null, ahora);
    await guardarCuenta(me);  // de paso, quién es: Ajustes sin señal sigue diciendo «Conectado como X»
  } catch (e) {
    // Sesión vencida u otro error del servidor: se queda con lo último que sabía. Sin red (o servidor caído, o sin
    // respuesta en ME_TIMEOUT_MS) y sin nada sabido todavía (app recién abierta), se usa la última copia. fetchedAt queda
    // en 0: la próxima navegación reintenta.
    if (info !== null || !sinServicio(e) || !(await usarCopia())) return;
  }
  paint();
  clearInterval(ticker);
  ticker = info?.simulated_clock ? setInterval(paint, REFRESH_MS) : null;
}
