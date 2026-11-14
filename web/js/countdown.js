// Countdown de lo fijado (charlas y eventos del itinerario) y alertas dentro de la app: "Salí ahora", "Empieza en 5 min".
// Usa la hora simulada en modo prueba. Cualquier elemento con data-countdown-to="<ISO>" se actualiza solo cada segundo.
import { Itinerary, getToken } from "./api.js";
import { alertSettings, currentPosition, startsAt, walkingMinutes } from "./location.js";
import { sandboxNow } from "./sandbox.js";
import { icon } from "./icons.js";
import { h, toast } from "./ui.js";

const REFRESH_MS = 60_000;
const HORIZON_MS = 12 * 3_600_000;          // la franja muestra lo fijado de las próximas 12 h
const NO_LOCATION_LEAD_MIN = 20;           // sin ubicación: avisar 20 min antes
const FIRED = "ra.alerts.fired";           // alertas ya mostradas (no se repiten)
const HIDDEN = "ra.countdown.hidden";      // código cuya franja se ocultó
const MISSED_WINDOW_MS = 45 * 60_000;      // después de que termina una charla fijada, se pregunta si llegaste
const NEXT_PRIORITY_MS = 15 * 60_000;      // pero si lo próximo empieza en menos de esto, gana lo próximo

const QUEUE_MIN = 30;                       // fila de walk-up si la charla no está reservada (app/guided.py)
let pinned = [];                           // [{ code, base, kind, title, start: Date, end: Date, venue }]
let fetchedAt = 0;
let ticker = null;
const leadCache = new Map();               // code → minutos antes del inicio en que hay que salir

const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} };

/** "1:12:40" o "24:13". */
export function formatCountdown(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const hh = Math.floor(total / 3600), mm = Math.floor((total % 3600) / 60), ss = total % 60;
  const two = (n) => String(n).padStart(2, "0");
  return hh ? `${hh}:${two(mm)}:${two(ss)}` : `${mm}:${two(ss)}`;
}

const hhmm = (d) => d.toLocaleTimeString("es-AR", { timeZone: "America/Los_Angeles", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const label = (it) => it.title;
// Ícono de la franja: evento o fijado; el reloj cuando hay que salir ya.
const isEvent = (it) => it.kind === "event" || it.kind === "show";
const bannerIcon = (it, tone) => icon(tone === "urgent" ? "reloj" : isEvent(it) ? "eventos" : "fijar", 16);
const link = (it) => ({ event: `#/evento/${encodeURIComponent(it.code)}`, show: `#/show/${encodeURIComponent(it.show)}`, mine: "#/itinerario" }[it.kind]
  || `#/charla/${it.base}`);

async function loadPinned() {
  const { days } = await Itinerary.get();
  pinned = days.flatMap((d) => d.sessions.filter((s) => s.locked && s.start).map((s) => {
    const start = startsAt(s.day, s.start);
    let end = s.end ? startsAt(s.day, s.end) : new Date(start.getTime() + 3_600_000);
    if (end <= start) end = new Date(end.getTime() + 86_400_000); // termina pasada la medianoche
    // Charla sin reserva: hay que llegar QUEUE_MIN antes por la fila de walk-up (armado guiado).
    const queue = (s.kind || "talk") === "talk" && !s.reservada;
    return { code: s.code, base: s.base, show: s.show, kind: s.kind || "talk", title: s.title, start, end, venue: s.venue, queue };
  })).sort((a, b) => a.start - b.start);
}

/** Minutos antes del inicio en que hay que salir: caminata (Routes API) + margen; sin ubicación, 20. */
async function leadMinutes(it) {
  if (leadCache.has(it.code)) return leadCache.get(it.code);
  let lead = NO_LOCATION_LEAD_MIN;
  const here = it.venue?.lat != null && it.venue.exact !== false ? await currentPosition() : null;
  if (here) lead = (await walkingMinutes(here, { lat: it.venue.lat, lng: it.venue.lng })).minutes + alertSettings().leaveMarginMin;
  leadCache.set(it.code, lead);
  return lead;
}

function fireOnce(key, message) {
  const fired = read(FIRED, {});
  if (fired[key]) return;
  write(FIRED, { ...fired, [key]: Date.now() });
  toast(message);
  navigator.vibrate?.([200, 100, 200]);
}

/** Lo que muestra la franja para el próximo fijado; dispara las alertas que correspondan (una sola vez cada una). */
function state(it, now, lead) {
  const toStart = it.start - now;
  const leave = new Date(it.start.getTime() - (lead + (it.queue ? QUEUE_MIN : 0)) * 60000);
  if (now >= it.start) return { tone: "live", text: `${label(it)} empezó hace ${Math.max(1, Math.round(-toStart / 60000))} min` };
  if (toStart <= alertSettings().startNoticeMin * 60000) fireOnce(`${it.code}:start`, `${it.title} empieza en ${Math.ceil(toStart / 60000)} min.`);
  if (now >= leave) {
    fireOnce(`${it.code}:leave`, it.queue
      ? `Salí ahora para ${it.title}: sin reserva, hacé la cola (empieza a las ${hhmm(it.start)}).`
      : `Salí ahora para ${it.title}: empieza a las ${hhmm(it.start)}.`);
    return { tone: "urgent", text: `Salí ya · ${label(it)} en ${formatCountdown(toStart)}` };
  }
  if (toStart <= 3_600_000) return { tone: isEvent(it) ? "event" : "soon", text: `${label(it)} en ${formatCountdown(toStart)} · salí ${hhmm(leave)}` };
  return { tone: isEvent(it) ? "event" : "calm", text: `${label(it)} a las ${hhmm(it.start)}` };
}

const badgeText = (ms) => (ms > 0 ? `Empieza en ${formatCountdown(ms)}` : "Ya empezó");

async function paint() {
  const now = sandboxNow();
  for (const el of document.querySelectorAll("[data-countdown-to]")) {
    el.textContent = badgeText(Date.parse(el.dataset.countdownTo) - now);
  }
  const bar = document.getElementById("countdown-banner");
  if (!bar) return;
  const next = pinned.find((it) => it.end > now && it.start - now < HORIZON_MS);
  const ended = pinned.find((it) => it.kind === "talk" && it.end <= now && now - it.end < MISSED_WINDOW_MS);
  if (ended && read(HIDDEN, null) !== `missed:${ended.code}` && !(next && next.start - now < NEXT_PRIORITY_MS)) {
    bar.hidden = false;
    bar.className = "countdown-banner is-calm";
    bar.replaceChildren(
      h("a", { class: "countdown-text", href: `#/perdida/${encodeURIComponent(ended.code)}` },
        `¿Llegaste a ${ended.title}? Si te la perdiste, mirá las opciones →`),
      h("button", { type: "button", class: "countdown-close", "aria-label": "Sí, llegué",
        onclick: () => { write(HIDDEN, `missed:${ended.code}`); void paint(); } }, icon("cerrar", 16)));
    return;
  }
  if (!next || read(HIDDEN, null) === next.code) { bar.hidden = true; return; }
  const { tone, text } = state(next, now, await leadMinutes(next));
  bar.hidden = false;
  bar.className = `countdown-banner is-${tone}`;
  bar.replaceChildren(
    bannerIcon(next, tone),
    h("a", { class: "countdown-text", href: link(next) }, text),
    h("button", { type: "button", class: "countdown-close", "aria-label": "Ocultar hasta lo próximo",
      onclick: () => { write(HIDDEN, next.code); bar.hidden = true; } }, icon("cerrar", 16)));
}

/** Arranca (o refresca) el countdown. Llamar al navegar y después de cambiar el itinerario ({ force: true }). */
export async function refreshCountdown({ force = false } = {}) {
  if (!getToken()) { pinned = []; void paint(); return; }
  if (force || Date.now() - fetchedAt > REFRESH_MS) {
    try { await loadPinned(); fetchedAt = Date.now(); if (force) leadCache.clear(); } catch { /* sin red: sigue con lo último */ }
  }
  if (!ticker) ticker = setInterval(() => { void paint(); }, 1000);
  void paint();
}

/** Countdown grande para una tarjeta o ficha: "Empieza en 1:12:40" (lo actualiza el ticker). */
// Nace con el texto puesto (no vacío hasta el próximo tic del ticker).
export const CountdownBadge = (startDate) => h("span", { class: "ra-countdown", "data-countdown-to": startDate.toISOString() },
  badgeText(startDate.getTime() - sandboxNow()));
