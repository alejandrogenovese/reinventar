// Clima de Las Vegas en Hoy (GET /api/clima, app/clima.py): ahora, máxima y mínima, mañana y pasado, y un consejo si
// hace falta. El navegador no habla con el National Weather Service: lo pide el servidor y lo guarda un rato. Sin señal
// se ve la última copia (apiConUltimaCopia) con la hora en que se actualizó; si no hay clima, no se muestra nada.
import { Clima } from "./api.js";
import { icon } from "./icons.js";
import { staleAt } from "./lastgood.js";
import { h } from "./ui.js";

const ZONA = "America/Los_Angeles";
const COPIA_MAX_MS = 6 * 60 * 60 * 1000; // una copia sin señal con datos más viejos que esto ya no dice nada útil

const grados = (c) => (Number.isFinite(c) ? `${c}°` : "");

/** «18:44» en hora de Las Vegas, a partir del ISO con offset que manda el servidor. "" si no se entiende. */
export function horaLasVegas(iso) {
  const fecha = new Date(iso ?? "");
  if (Number.isNaN(fecha.getTime())) return "";
  return fecha.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: ZONA });
}

/** «Mañana» para el segundo día y «Vie 27» para el tercero (fecha ISO de Las Vegas). */
export function nombreDia(fecha, indice) {
  if (indice === 1) return "Mañana";
  const texto = new Date(`${fecha}T12:00:00`).toLocaleDateString("es-AR", { weekday: "short", day: "numeric" }).replace(",", "");
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

/** «Máx 20° · Mín 9°», o la que haya (a la noche NWS ya no da la máxima de hoy). */
export function maxMin(dia) {
  return [Number.isFinite(dia?.max_c) ? `Máx ${grados(dia.max_c)}` : null, Number.isFinite(dia?.min_c) ? `Mín ${grados(dia.min_c)}` : null]
    .filter(Boolean).join(" · ");
}

/** «Mañana 20°/11° Soleado · Vie 27 21°/11° Mayormente soleado». "" si no hay días siguientes. */
export function lineaProximos(dias) {
  return (dias || []).slice(1, 3).map((d, i) => {
    const temps = [d.max_c, d.min_c].filter(Number.isFinite).map(grados).join("/");
    return [nombreDia(d.fecha, i + 1), temps, d.descripcion].filter(Boolean).join(" ");
  }).join(" · ");
}

/** ¿Es una copia sin señal con datos de hace más de 6 h (o sin hora)? */
export function copiaVieja(data, ahora = Date.now()) {
  if (staleAt(data) === null) return false;
  const de = Date.parse(data.actualizado ?? "");
  return !Number.isFinite(de) || ahora - de > COPIA_MAX_MS;
}

/** El bloque compacto para Hoy, o null si no hay datos que mostrar (o son una copia vieja). */
export function ClimaHoy(data, ahora = Date.now()) {
  if (!data || typeof data !== "object" || (!data.ahora && !data.dias?.length) || copiaVieja(data, ahora)) return null;
  const hoy = data.dias?.[0];
  const actual = data.ahora;
  const principal = Number.isFinite(actual?.temp_c) ? `${actual.temp_c} °C` : null;
  const descripcion = actual?.descripcion || hoy?.descripcion || "";
  const hora = horaLasVegas(data.actualizado);
  const sinSenal = staleAt(data) !== null;
  const proximos = lineaProximos(data.dias);
  return h("div", { class: "ra-clima", role: "group", "aria-label": "Clima en Las Vegas" },
    h("p", { class: "ra-clima-ahora" }, icon("claro", 20),
      h("span", {}, principal ? h("strong", {}, principal) : null, principal && descripcion ? " · " : null, descripcion),
      hoy && maxMin(hoy) ? h("span", { class: "ra-clima-maxmin" }, maxMin(hoy)) : null),
    (data.consejos || []).map((c) => h("p", { class: "ra-clima-consejo" }, c)),
    proximos ? h("p", { class: "caption" }, proximos) : null,
    hora ? h("p", { class: "caption" }, sinSenal ? `Sin señal: actualizado a las ${hora} (hora de Las Vegas)`
      : `Actualizado a las ${hora} (hora de Las Vegas) · National Weather Service`) : null);
}

/** Pide el clima y lo deja en `slot`. Si falla o no hay, el lugar queda vacío: Hoy sigue igual. */
export async function cargarClima(slot, pedido = Clima.get()) {
  try {
    slot.replaceChildren(ClimaHoy(await pedido) ?? "");
  } catch {
    slot.replaceChildren(""); // sin clima: no es motivo para romper Hoy
  }
}
