// Si una charla se reserva en el portal de AWS o es solo por cola (walk-up), según el catálogo oficial (walk_in, seats).
// Tres formas, según cuánto lugar hay: el estado en línea (EstadoEnLinea) en listas y horarios de la ficha, la insignia
// con la línea de la hora (InsigniaReserva + LineaHoraReserva) en el itinerario y el aviso con la hora y la acción
// (AvisoReserva) en la tarjeta de Hoy, que es una sola charla. Las horas son las de app/leave.py: cola 45 min antes si se
// reserva y no la tenés, 30 si es solo por cola, y con reserva hay que entrar 10 min antes o se libera el lugar.
import { COLA_SIN_LUGAR_MIN, COLA_SIN_RESERVA_MIN, horaMenos } from "./hoyPlan.js";
import { icon } from "./icons.js";
import { Button, IconText, h, mensajeError, toast } from "./ui.js";

export const RESERVA_LIBERA_MIN = 10;   // app/leave.py RESERVA_LIBERA_MIN

const esCharla = (s) => (s?.kind ?? "talk") === "talk" && typeof s?.walk_in === "boolean";

/** Qué hacer si se reserva y no la tenés reservada (null en los demás casos). */
export function ayudaReserva(s) {
  if (!esCharla(s) || s.walk_in || s.reservada) return null;
  return `Se reserva en el portal de AWS. Si no la reservaste, hacé la cola ${COLA_SIN_LUGAR_MIN} min antes: entrás con los lugares que sobren.`;
}

/** Estado de reserva con la hora concreta: { estado, titulo, antes, hora, despues }. El texto es antes + hora +
 *  despues; sin hora de inicio se dicen los minutos. null si no es una charla del catálogo. */
export function estadoReserva(s) {
  if (!esCharla(s)) return null;
  const a = (min) => (s.start ? { hora: horaMenos(s.start, min), antes: "las " } : { hora: null, antes: `${min} min antes` });
  if (s.walk_in) {
    const t = a(COLA_SIN_RESERVA_MIN);
    return { estado: "libre", titulo: "Por orden de llegada", antes: `Cola desde ${t.antes}`, hora: t.hora, despues: "." };
  }
  if (s.reservada) {
    const t = a(RESERVA_LIBERA_MIN);
    return { estado: "reservada", titulo: "Reservada", antes: `Entrá antes de ${t.antes}`, hora: t.hora,
      despues: " o se libera tu lugar." };
  }
  const t = a(COLA_SIN_LUGAR_MIN);
  return { estado: "reserva", titulo: ["Reserva previa", s.seats ? `${s.seats} lugares` : null].filter(Boolean).join(" · "),
    antes: `Sin tu reserva: cola desde ${t.antes}`, hora: t.hora, despues: ", entrás si sobran lugares." };
}

const ICONO = { reserva: "alerta", reservada: "listo", libre: "reloj" };

/** Estado en línea, con ícono y sin fondo (listas y horarios de la ficha). */
export function EstadoEnLinea(s) {
  const e = estadoReserva(s);
  return e && h("span", { class: `ra-reserva-linea is-${e.estado}`, title: textoAyuda(s) },
    icon(ICONO[e.estado], 14), h("span", {}, e.titulo));
}

/** Insignia en la fila del tipo de sesión (itinerario): se lee antes que el título. */
export function InsigniaReserva(s) {
  const e = estadoReserva(s);
  return e && h("span", { class: `ra-insignia-reserva is-${e.estado}` }, icon(ICONO[e.estado], 14), h("span", {}, e.titulo));
}

const TextoHora = (e) => [e.antes, e.hora ? h("span", { class: "ra-reserva-hora" }, e.hora) : null, e.despues];

/** La línea con la hora concreta, debajo de la tarjeta del itinerario. */
export function LineaHoraReserva(s) {
  const e = estadoReserva(s);
  return e && h("p", { class: `ra-reserva-cuando is-${e.estado}` }, TextoHora(e));
}

const textoAyuda = (s) => (s.walk_in ? `Sin reserva: hacé la cola ${COLA_SIN_RESERVA_MIN} min antes.` : ayudaReserva(s));

/** «Ya la reservé» / «Reservada» (aria-pressed). Las charlas por orden de llegada no lo llevan. */
export function BotonReserva(s, onclick) {
  if (!onclick || !esCharla(s) || s.walk_in) return null;
  return Button(s.reservada ? IconText("listo", "Reservada") : "Ya la reservé", {
    onclick, "aria-pressed": String(Boolean(s.reservada)),
    "aria-label": s.reservada ? "Reservada. Tocá para desmarcarla." : "Ya la reservé en el portal de AWS",
    title: `Si no la tenés reservada, hay que hacer la cola ${COLA_SIN_LUGAR_MIN} min antes a ver si queda lugar` });
}

/** Aviso con la hora y la acción (tarjeta de Hoy): fila tintada con ícono, título, la hora y el botón adentro.
 *  `marcar(reservada)` guarda en el servidor; al volver, el aviso se redibuja con el estado nuevo. */
export function AvisoReserva(s, marcar) {
  const e = estadoReserva(s);
  if (!e) return null;
  const caja = h("div", { class: `ra-aviso-reserva is-${e.estado}` },
    icon(ICONO[e.estado], 16),
    h("div", { class: "ra-aviso-cuerpo" },
      h("strong", {}, e.titulo),
      h("p", {}, TextoHora(e)),
      BotonReserva(s, marcar && (async (ev) => {
        const btn = ev.currentTarget;
        btn.disabled = true;
        try {
          await marcar(!s.reservada);
          caja.replaceWith(AvisoReserva({ ...s, reservada: !s.reservada }, marcar));
        } catch (err) { toast(mensajeError(err)); btn.disabled = false; }
      }))));
  return caja;
}
