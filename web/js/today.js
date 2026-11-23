// Pantalla Hoy: la charla que está pasando, la que sigue y el resto del día, con "Grabar esta charla".
import { Today } from "./api.js";
import { CountdownBadge } from "./countdown.js";
import { diaDeEvento, resumenDelDia } from "./dia.js";
import { empezarSesion } from "./recorder.js";
import { decidirGrabar } from "./grabacionDuplicada.js";
import { decidirPorYoutube } from "./avisoYoutube.js";
import { GoThereParts, startsAt } from "./location.js";
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
    if (!(await decidirPorYoutube(s))) { btn.disabled = false; return; } // la sube AWS: antes de grabar, lo avisa
    const decision = await decidirGrabar(s.code);
    if (!decision.grabar) { location.hash = `#/s/${decision.ver}`; return; }
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

export const destination = (s) => (s.venue?.lat != null
  ? { lat: s.venue.lat, lng: s.venue.lng, name: s.venue.hotel, placeId: s.venue.place_id, approx: s.venue.exact === false } : null);

// "Ahora" es un estado con punto (y la tarjeta lleva borde de marca); "Después"/"Próxima", texto de marca con la
// cuenta regresiva en la misma línea ("Después · Empieza en 1:32:00").
const WhenLabel = (s, label, highlight) => (highlight
  ? h("span", { class: "ra-status is-now" }, h("span", { class: "ra-status-dot", "aria-hidden": "true" }), label)
  : h("span", { class: "ra-soon" }, label, s.day && s.start ? [" · ", CountdownBadge(startsAt(s.day, s.start))] : null));

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
    s.cola_desde ? Hint(`Sin reserva: hacé la cola desde las ${s.cola_desde}.`, { tone: "info" }) : null,
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

const Empty = (text, action) => h("div", { class: "ra-today-empty" }, h("p", { class: "caption" }, text), action);

/**
 * Panel Hoy para el inicio. `sessions` son las grabaciones del usuario (para no duplicar una charla ya grabada).
 * Devuelve { el, hasTalk, data }: hasTalk dice si hay una charla ahora o a continuación; data, lo que trajo /api/today.
 */
export async function TodayPanel(sessions) {
  const data = await Today.get();
  const avisos = await avisosDe(codigosDeCharlas([data.now, data.next]));
  const recorded = new Map(sessions.filter((s) => s.code).map((s) => [s.code, s]));
  const body = [];

  if (data.now) body.push(TalkCard(data.now, { label: "Ahora", recorded, variant: "primary", highlight: true, aviso: avisos[data.now.code] }));
  if (data.next) body.push(TalkCard(data.next, { label: data.now ? "Después" : "Próxima", recorded, variant: data.now ? "secondary" : "primary", aviso: avisos[data.next.code] }));
  body.push(LaterList(data.later));

  if (!data.now && !data.next) {
    const up = data.upcoming;
    body.push(up
      ? Empty(`No tenés más charlas hoy. La próxima es el ${dayLabel(up.day)} a las ${up.first.start}: ${up.first.title}.`,
        Button("Ver itinerario", { onclick: () => (location.hash = "#/itinerario") }))
      : Empty("No tenés charlas en el itinerario para hoy.",
        Button("Armar itinerario", { onclick: () => (location.hash = "#/itinerario") })));
  }

  // La sección se nombra con el título y la fecha («Hoy martes, 2 dic»), aunque se vean separados.
  const el = h("section", { class: "stack", "aria-labelledby": "hoy-title hoy-fecha" },
    h("div", { class: "ra-sec-head" }, h("h2", { class: "label", id: "hoy-title" }, "Hoy"),
      h("span", { class: "caption", id: "hoy-fecha" }, dayLabel(data.date))), body);
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
  ].filter(Boolean);
  return h("p", { class: "dia" }, h("strong", {}, dia.titulo),
    keynote?.enVivo ? h("span", { class: "vivo" }, "Keynote en vivo") : null,
    partes.flatMap((p, i) => (i ? [Sep(), p] : [p])));
}
