// Pantalla Hoy: la charla que está pasando, la que sigue y el resto del día, con "Grabar esta charla".
import { Guided, Today, duenoDeCopias } from "./api.js";
import { cargarClima } from "./clima.js";
import { CountdownBadge, refreshCountdown } from "./countdown.js";
import { AvisoReserva } from "./reservaEtiqueta.js";
import { diaDeEvento, resumenDelDia } from "./dia.js";
import { hoyEnReinvent } from "./diaPorDia.js";
import { hoySinSenal, mensajeSinCharlas } from "./hoyPlan.js";
import { loadLast, staleAt } from "./lastgood.js";
import { empezarSesion } from "./recorder.js";
import { decidirGrabar } from "./grabacionDuplicada.js";
import { GoThereParts, startsAt } from "./location.js";
import { destinoDeTarjeta } from "./salas.js";
import { sandboxNow } from "./sandbox.js";
import { icon } from "./icons.js";
import { AvisoBaja, LlenoAvisos, avisosDe, codigosDeCharlas } from "./lleno.js";
import { Button, Hint, IconText, h, mensajeError, toast } from "./ui.js";

const LATER_LIMIT = 4;

const dayLabel = (iso) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "short" });

export const place = (s) => [s.venue?.hotel, s.venue?.detail].filter(Boolean).join(" · ");

/** Crea la sesión de grabación con los datos de la charla y abre el grabador. Si otra persona ya la está grabando,
 *  antes lo avisa y deja elegir entre grabar igual o ver la suya. Si AWS la publica en YouTube, también lo avisa. */
export async function recordTalk(s, btn) {
  btn.disabled = true;
  try {
    const decision = await decidirGrabar(s.code, { talk: s });
    if (!decision.grabar) {
      if (decision.ver) location.hash = `#/s/${decision.ver}`; else btn.disabled = false; // «No grabar»: queda como estaba
      return;
    }
    // Sin señal también se puede grabar: empezarSesion arma una sesión local que se sube cuando vuelva la red.
    const rec = await empezarSesion({
      title: s.title.slice(0, 200), kind: s.recording_kind, code: s.code,
      venue: place(s).slice(0, 120) || null,
      speaker: ((s.people || []).map((p) => p.name).join(", ") || s.speakers || "").slice(0, 200) || null,
    });
    location.hash = `#/grabar/${rec.id}`;
  } catch (err) { toast(mensajeError(err, "No pude empezar la grabación. Probá de nuevo.")); btn.disabled = false; }
}

// A dónde lleva tocar un ítem: la charla, el evento, el show, o el itinerario (los eventos propios no tienen ficha).
const itemHref = (s) => ({ event: `#/evento/${encodeURIComponent(s.code)}`, show: `#/show/${encodeURIComponent(s.show)}`, mine: "#/itinerario" }[s.kind] || `#/charla/${s.base}`);
// Eventos, shows y eventos propios llevan su ícono; las charlas, el código en mono.
const KIND_ICON = { event: ["eventos", "Evento"], show: ["eventos", "Show"], mine: ["fijar", "Mi evento"] };
const SHOW_HINT = { canceled: "Cancelado por el organizador. Revisalo antes de ir.", postponed: "Postergado: revisalo antes de ir." };
const itemLabel = (s) => (KIND_ICON[s.kind] ? IconText(...KIND_ICON[s.kind]) : h("span", { class: "ra-mono" }, s.code));
const itemTitle = (s) => (KIND_ICON[s.kind] ? [icon(KIND_ICON[s.kind][0], 16), h("span", {}, s.title)] : s.title);

/** Acción de la charla: si ya hay una grabación con ese código, abrirla; si no, grabar. */
export function TalkAction(s, recorded, variant) {
  if (s.kind === "mine") return s.note ? h("p", { class: "caption" }, s.note) : null;
  if (s.kind === "event") return Button("Ver evento", { variant, onclick: () => (location.hash = `#/evento/${encodeURIComponent(s.code)}`) });
  if (s.kind === "show") return Button("Ver show", { variant, onclick: () => (location.hash = itemHref(s)) });
  const mine = recorded.get(s.code);
  if (mine) {
    const live = mine.status === "recording" || mine.status === "uploading";
    return Button(live ? "Seguir grabando" : "Ver grabación", { onclick: () => (location.hash = live ? `#/grabar/${mine.id}` : `#/s/${mine.id}`) });
  }
  const label = variant === "primary" ? [icon("grabar", 20), "Grabar esta charla"] : "Grabar";
  const btn = Button(label, { variant, onclick: () => recordTalk(s, btn) });
  return btn;
}

// Una charla de re:Invent va a la entrada del área de convenciones de su sede; eventos, shows y lo tuyo, a su lugar.
export const destination = destinoDeTarjeta;

// "Ahora" es un estado con punto (y la tarjeta lleva borde de marca); "Después"/"Próxima", texto de marca con la
// cuenta regresiva en la misma línea ("Después · Empieza en 1:32:00").
const WhenLabel = (s, label, highlight) => (highlight
  ? h("span", { class: "ra-status is-now" }, h("span", { class: "ra-status-dot", "aria-hidden": "true" }), label)
  : h("span", { class: "ra-soon" }, label, s.day && s.start ? [" · ", CountdownBadge(startsAt(s.day, s.start))] : null));

const marcarReservada = (s) => (reservada) =>
  Guided.booked(s.code, reservada).then(() => refreshCountdown({ force: true }));

function TalkCard(s, { label, recorded, variant, highlight, aviso }) {
  // Tiempo a pie (Routes API, paga) solo en estas dos tarjetas: lo que está pasando y lo que sigue.
  const go = GoThereParts(destination(s), { start: s.day && s.start ? startsAt(s.day, s.cola_desde || s.start) : null, eta: true, iconOnly: true });
  return h("article", { class: `ra-today${highlight ? " is-now" : ""}` },
    h("div", { class: "ra-today-when" }, WhenLabel(s, label, highlight), h("span", { class: "ra-time" }, `${s.start}–${s.end}`)),
    h("h3", { class: "ra-card-title" }, h("a", { class: "ra-link", href: itemHref(s) }, s.title)),
    h("div", { class: "ra-card-meta" }, place(s) ? IconText("ubicacion", place(s)) : null, itemLabel(s)),
    s.kind === "event" && s.cancelled ? Hint("Cancelado: ya no aparece en su página. Revisalo antes de ir.", { tone: "error" }) : null,
    s.kind === "talk" ? AvisoBaja(s) : null,
    s.kind === "show" && SHOW_HINT[s.status] ? Hint(SHOW_HINT[s.status], { tone: "error" }) : null,
    // Reserva: aviso con la hora (cola, o hasta cuándo entrar si está reservada) y el botón para marcarla.
    (s.kind === "talk" && AvisoReserva(s, marcarReservada(s)))
      || (s.cola_desde ? Hint(`Hacé la cola desde las ${s.cola_desde}.`, { tone: "info" }) : null),
    s.salis_a ? Hint(`Salí a las ${s.salis_a}, antes de que termine, para llegar a la siguiente.`, { tone: "warn" }) : null,
    go ? go.info : null,
    // Lo que avisa la gente en la puerta (y los botones para avisar). La pista de sin reserva ya está arriba.
    LlenoAvisos(s.code, aviso, { conPista: false }),
    // "Grabar esta charla" ocupa la fila y "Llevame" queda al lado como botón de solo ícono (48 px).
    h("div", { class: "ra-today-actions" }, TalkAction(s, recorded, variant), go ? go.link : null));
}

const LaterList = (items) => items.length ? h("ul", { class: "ra-today-later" },
  items.slice(0, LATER_LIMIT).map((s) => h("li", {}, h("span", { class: "ra-mono" }, s.start),
    h("a", { class: "ra-link", href: itemHref(s) }, itemTitle(s)))),
  items.length > LATER_LIMIT ? h("li", { class: "caption" }, h("a", { class: "ra-link", href: "#/itinerario" }, `y ${items.length - LATER_LIMIT} más en tu itinerario`)) : null) : null;

// Sin nada ahora ni a continuación: el mensaje de hoyPlan.js (día libre, la próxima, sin señal) con sus accesos.
const Empty = ({ titulo, texto, acciones }) => h("div", { class: "ra-today-empty" },
  titulo ? h("p", { class: "ra-card-title" }, titulo) : null, h("p", { class: "caption" }, texto),
  acciones.length ? h("div", { class: "ra-today-actions" },
    acciones.map((a) => h("a", { class: "ra-btn ra-btn-secondary", href: a.href }, a.texto))) : null);

/** Lo propio de re:Invent para esa fecha (badge, keynotes, receptions, re:Play, shuttles), de diaPorDia.js: anda sin señal. */
function HoyEnReinvent(fecha) {
  const items = hoyEnReinvent(fecha);
  if (!items.length) return null;
  return h("section", { class: "stack", "aria-labelledby": "hoy-reinvent" },
    h("h3", { class: "label", id: "hoy-reinvent" }, "Hoy en re:Invent"),
    h("ul", { class: "ra-dxd-lista" }, items.map((i) => h("li", {}, h("strong", {}, `${i.seccion}: `), i.texto))));
}

/** /api/today; si vino la copia sin señal, recalculado con la hora de Las Vegas y el itinerario guardado (hoyPlan.js). */
async function hoyActual() {
  const data = await Today.get();
  if (staleAt(data) === null) return data;
  const dueno = await duenoDeCopias();
  const itinerario = dueno ? loadLast(dueno, "/api/itinerary")?.data ?? null : null;
  return hoySinSenal(data, itinerario, sandboxNow());
}

/**
 * Panel Hoy para el inicio. `sessions` son las grabaciones del usuario (para no duplicar una charla ya grabada).
 * Devuelve { el, hasTalk, data }: hasTalk dice si hay una charla ahora o a continuación; data, lo que trajo /api/today.
 */
export async function TodayPanel(sessions) {
  const climaSlot = h("div", { class: "ra-optional" });
  void cargarClima(climaSlot);  // en paralelo: si tarda o falla, Hoy no lo espera y el lugar queda vacío
  const data = await hoyActual();
  const avisos = await avisosDe(codigosDeCharlas([data.now, data.next]));
  const recorded = new Map(sessions.filter((s) => s.code).map((s) => [s.code, s]));
  const body = [];

  if (data.now) body.push(TalkCard(data.now, { label: "Ahora", recorded, variant: "primary", highlight: true, aviso: avisos[data.now.code] }));
  if (data.next) body.push(TalkCard(data.next, { label: data.now ? "Después" : "Próxima", recorded, variant: data.now ? "secondary" : "primary", aviso: avisos[data.next.code] }));
  body.push(LaterList(data.later));

  if (!data.now && !data.next) {
    body.push(Empty(mensajeSinCharlas({ tipoDia: diaDeEvento(sandboxNow())?.tipo, upcoming: data.upcoming,
      sinItinerario: data.sinItinerario, etiquetaDia: dayLabel })));
  }
  body.push(HoyEnReinvent(data.date));

  // La sección se nombra con el título y la fecha («Hoy martes, 2 dic»), aunque se vean separados.
  const el = h("section", { class: "stack", "aria-labelledby": "hoy-title hoy-fecha" },
    h("div", { class: "ra-sec-head" }, h("h2", { class: "label", id: "hoy-title" }, "Hoy"),
      h("span", { class: "caption", id: "hoy-fecha" }, dayLabel(data.date))), climaSlot, body,
    h("a", { class: "ra-dxd-link", href: "#/viaje/reinvent" }, icon("eventos", 16), h("span", {}, "re:Invent día por día: badge, keynotes y shuttles")));
  return { el, hasTalk: Boolean(data.now || data.next), data };
}

// ---------- franja del día (arriba de Hoy; no es un banner) ----------

const Sep = () => h("span", { class: "sep", "aria-hidden": "true" }, "·");
const Num = (n) => h("span", { class: "num" }, String(n));

/**
 * «Martes 1/12 · Día 2 de 5 · Keynote 8:00 · 3 charlas en tu agenda» con la hora de la app (sandboxNow: la simulada en
 * modo prueba). `hoy` y `anuncios` son promesas de /api/today y /api/anuncios: si fallan, la franja sale sin esos datos.
 * Con la keynote en curso, la pastilla «Keynote en vivo» (lo único naranja). null fuera del rango del viaje.
 */
export async function FranjaDia({ hoy, anuncios }) {
  const dia = diaDeEvento(sandboxNow());
  if (!dia) return null;
  const [h1, a1] = await Promise.allSettled([hoy, anuncios]);
  const valor = (r) => (r.status === "fulfilled" ? r.value : null);
  const { keynote, charlas } = dia.tipo === "conferencia" ? resumenDelDia({ hoy: valor(h1), anuncios: valor(a1) }) : {};
  const partes = [
    dia.tipo === "conferencia" ? h("span", {}, "Día ", Num(dia.dia), ` de ${dia.total}`) : null,
    keynote && !keynote.enVivo ? h("span", {}, "Keynote ", Num(keynote.hora)) : null,
    charlas ? h("span", {}, Num(charlas), charlas === 1 ? " charla en tu agenda" : " charlas en tu agenda") : null,
    ...dia.detalles.map((d) => h("span", {}, d)),
    dia.enlace ? h("a", { class: "ra-link", href: dia.enlace.href }, dia.enlace.texto) : null,
  ].filter(Boolean);
  return h("p", { class: "dia" }, h("strong", {}, dia.titulo),
    keynote?.enVivo ? h("span", { class: "vivo" }, "Keynote en vivo") : null,
    partes.flatMap((p, i) => (i ? [Sep(), p] : [p])));
}
