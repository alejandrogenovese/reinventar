// Filtros de la lista de Eventos (puro, sin DOM): día o "Todas las fechas", tipo, "Más cerca" y "Desde las 17".
// Se separa de events.js para poder probarlo con node y para recordar lo elegido en la sesión.

export const TODAS = "todas";
export const TODOS_LOS_TIPOS = "todos";
export const HORA_DE_FIESTAS = 17;
export const CLAVE_FILTROS = "reinventar.eventos.filtros";

/** Hora de inicio ("18:30") en horas decimales, o null si no está cargada o no se entiende. */
function horaDeInicio(evento) {
  const m = /^(\d{1,2}):(\d{2})/.exec(evento.start ?? "");
  return m ? Number(m[1]) + Number(m[2]) / 60 : null;
}

const aLoUltimoSiCancelado = (a, b) => Number(Boolean(a.cancelled)) - Number(Boolean(b.cancelled));

/**
 * Eventos a mostrar, agrupados por día: [{ day, events }]. No muta la entrada y omite los días sin eventos.
 * `day` es un día ISO o TODAS; `desde` es una hora (17) o null; "Más cerca" ordena dentro de cada día y necesita `here` y `distance`.
 */
export function filtrarEventos(days, { day, type = TODOS_LOS_TIPOS, desde = null, near = false, here = null, distance = null }) {
  return days
    .filter((d) => day === TODAS || d.day === day)
    .map((d) => {
      let events = d.events.filter((e) => type === TODOS_LOS_TIPOS || e.type === type);
      if (desde != null) events = events.filter((e) => (horaDeInicio(e) ?? -1) >= desde);
      if (near && here && distance) events = [...events].sort((a, b) => distance(here, a.venue) - distance(here, b.venue));
      return { day: d.day, events: [...events].sort(aLoUltimoSiCancelado) };
    })
    .filter((g) => g.events.length);
}

/** Lo que eligió el usuario en esta sesión, o null si no hay nada (o el storage está bloqueado o roto). */
export function leerFiltros() {
  try {
    const crudo = sessionStorage.getItem(CLAVE_FILTROS);
    if (!crudo) return null;
    const f = JSON.parse(crudo);
    if (!f || typeof f !== "object") return null;
    return {
      day: typeof f.day === "string" ? f.day : null,
      type: typeof f.type === "string" ? f.type : TODOS_LOS_TIPOS,
      near: f.near === true,
      desde: typeof f.desde === "number" ? f.desde : null,
    };
  } catch {
    return null;
  }
}

export function guardarFiltros({ day, type, near, desde }) {
  try { sessionStorage.setItem(CLAVE_FILTROS, JSON.stringify({ day, type, near, desde })); } catch {}
}
