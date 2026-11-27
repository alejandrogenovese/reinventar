// Si una charla se reserva en el portal de AWS o es solo por cola (walk-up), según el catálogo oficial (walk_in, seats).
// Lo usan la tarjeta de charla (itinerary.js SessionMiniCard) y cada horario de la ficha (knowledge.js). Las horas de
// cola son las de app/guided.py (cola_min): 45 min si se reserva y no la tenés, 30 si es solo por cola.
import { COLA_SIN_LUGAR_MIN, COLA_SIN_RESERVA_MIN } from "./hoyPlan.js";
import { h } from "./ui.js";

const esCharla = (s) => (s?.kind ?? "talk") === "talk" && typeof s?.walk_in === "boolean";

/** El texto de la etiqueta, o null si no es una charla del catálogo. */
export function textoReserva(s) {
  if (!esCharla(s)) return null;
  if (s.walk_in) return "Sin reserva · por orden de llegada";
  if (s.reservada) return "Reservada";
  return ["Con reserva previa", s.seats ? `${s.seats} lugares` : null].filter(Boolean).join(" · ");
}

/** Qué hacer si se reserva y no la tenés reservada (null en los demás casos). */
export function ayudaReserva(s) {
  if (!esCharla(s) || s.walk_in || s.reservada) return null;
  return `Se reserva en el portal de AWS. Si no la reservaste, hacé la cola ${COLA_SIN_LUGAR_MIN} min antes: entrás con los lugares que sobren.`;
}

export function EtiquetaReserva(s) {
  const texto = textoReserva(s);
  if (!texto) return null;
  const clase = s.walk_in ? "ra-tag" : s.reservada ? "ra-tag is-new" : "ra-tag is-reserva";
  const title = s.walk_in ? `Sin reserva: hacé la cola ${COLA_SIN_RESERVA_MIN} min antes.` : ayudaReserva(s);
  return h("span", { class: clase, title }, texto);
}
