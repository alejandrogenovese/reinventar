// Itinerario guiado, paso 2: armar cada día charla por charla, con traslados, cola y "salí antes".
import { Catalog, Guided, Interview, Itinerary } from "./api.js";
import { refreshCountdown } from "./countdown.js";
import { shortDay } from "./itinerary.js";
import { sandboxNow } from "./sandbox.js";
import { Button, Skeleton, Tag, h, toast } from "./ui.js";

const PAUSA_MIN = 60;                                    // "Hacer una pausa": la próxima, una hora después
const OBJETIVO_POR_DIA = { "3-4": 4, "5-6": 6, todas: 12 }; // "Completá por mí" llena hasta esto
const MAX_VUELTAS = 15;
const LLEGABLES = ["a_tiempo", "justo"];
const ESTADOS = {
  a_tiempo: ["🟢", "a tiempo"], justo: ["🟡", "justo"], salir_antes: ["🟠", "salí antes"], se_superpone: ["🔴", "se superpone"],
};

const toMin = (t) => { const [hh, mm] = t.split(":").map(Number); return hh * 60 + mm; };
const hhmm = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

function viaje(o) {
  if (o.viaje_min == null) return null;
  const t = `${o.viaje_estimado ? "~" : ""}${o.viaje_min} min`;
  return o.misma_sede ? `misma sede (${t})` : `${t} caminando`;
}

/** El aviso de traslado de cada estado (app/guided.py calcula las horas; acá solo se redactan). */
function aviso(o, previa) {
  const anterior = previa ? `«${previa.title}»` : "la anterior";
  switch (o.estado) {
    case "justo": return `Llegás justo para la cola de las ${o.llegada}, sin margen.`;
    case "salir_antes": return `⚠ Empieza mientras estás en ${anterior}. Si te vas ${o.salir_antes_min} min antes (${o.salir_a}), llegás a la cola de las ${o.llegada}.`;
    case "se_superpone": return `Ojo: para llegar tenés que salir a las ${o.salir_a}, así que se superpone ${o.salir_antes_min} min con ${anterior}. Si te interesa más, cambiala.`;
    default: return `Sin reserva: hacé la cola desde las ${o.llegada}.`;
  }
}

function OptionCard(o, previa, { onChoose, onLater }) {
  const c = o.card;
  const [icono, estado] = ESTADOS[o.estado] || ["", o.estado];
  return h("article", { class: `ra-option is-${o.estado}` },
    h("div", { class: "ra-option-head" },
      h("span", { class: "ra-option-time" }, c.start),
      h("span", { class: "ra-kind" }, [c.type, c.level ? `L${c.level}` : null].filter(Boolean).join(" · ")),
      previa ? h("span", { class: "ra-option-state" }, `${icono} ${estado}`) : null),
    h("h3", { class: "ra-minicard-title" }, h("a", { class: "ra-link", href: `#/charla/${c.base}` }, c.title)),
    h("p", { class: "caption" }, ["📍", c.venue?.hotel, viaje(o)].filter(Boolean).join(" ")),
    o.pendiente ? h("p", { class: "ra-pending-tag" }, `☆ La marcaste el ${shortDay(o.pendiente)}`) : null,
    o.motivos?.length ? h("div", { class: "ra-chips" }, o.motivos.map((m) => Tag(`🎯 ${m}`))) : null,
    o.razon ? h("p", { class: "ra-reason" }, `“${o.razon}”`) : null,
    h("p", { class: o.estado === "se_superpone" ? "notice err" : "notice" }, aviso(o, previa)),
    h("div", { class: "actions" },
      Button("Elegir", { variant: o.estado === "se_superpone" ? "secondary" : "primary", onclick: (e) => { e.target.disabled = true; onChoose(o); } }),
      Button("☆ Para otro día", { variant: "ghost", onclick: () => onLater(o) })));
}

/** Lo que ya elegiste ese día, con la marca de reservada (cambia la cola) y quitar. */
function ChosenRow(s, onChanged) {
  const fin = s.salir_antes && s.end ? hhmm(toMin(s.end) - s.salir_antes) : s.end;
  const booked = Button(s.reservada ? "✓ Reservada" : "Marcar reservada", {
    variant: "ghost", "aria-pressed": String(Boolean(s.reservada)),
    title: "Si no la tenés reservada en el portal de AWS, hay que hacer la cola 30 min antes",
    onclick: () => Guided.booked(s.code, !s.reservada).then(onChanged).catch((err) => toast(err.message)) });
  return h("li", { class: "ra-chosen" },
    h("span", { class: "ra-chosen-time" }, `${s.start}–${fin || "?"}`),
    h("span", { class: "ra-chosen-body" },
      h("strong", {}, s.kind === "mine" ? `📌 ${s.title}` : s.title),
      h("span", { class: "caption" }, [s.venue?.hotel, s.salir_antes ? `salís ${fin} (antes de que termine)` : null].filter(Boolean).join(" · "))),
    h("span", { class: "ra-chosen-actions" },
      s.kind === "talk" ? booked : null,
      Button("Quitar", { variant: "ghost", onclick: () => Itinerary.remove(s.code).then(onChanged).catch((err) => toast(err.message)) })));
}

function PendingList(pendientes, onChanged) {
  if (!pendientes.length) return null;
  return h("details", { class: "notice" },
    h("summary", { class: "label" }, `☆ Pendientes para otro día (${pendientes.length})`),
    h("ul", { class: "stack" }, pendientes.map((p) => h("li", {},
      h("a", { class: "ra-link", href: `#/charla/${p.base}` }, p.title),
      h("span", { class: "caption" }, ` · la marcaste el ${shortDay(p.dia_marcada)} · `,
        p.horarios.filter((x) => x.day > p.dia_marcada).map((x) => `${shortDay(x.day)} ${x.start}`).join(", ") || "no se repite"),
      " ", Button("✕", { variant: "ghost", "aria-label": `Sacar ${p.title} de pendientes`,
        onclick: () => Guided.removePending(p.base).then(onChanged).catch((err) => toast(err.message)) })))));
}

// La última charla elegida marca desde dónde seguir. Los eventos (de la sección o propios) no: si alguien cargó primero
// una cena, igual arranca por la mañana; el servidor ya evita proponer charlas encima de ellos.
const ultimo = (items) => items.filter((s) => s.start && s.kind === "talk").sort((a, b) => (a.end || a.start).localeCompare(b.end || b.start)).at(-1);

export async function viewArmar(view) {
  const [meta, entrevista] = await Promise.all([Catalog.meta(), Interview.get()]);
  if (!entrevista.ficha) { location.hash = "#/itinerario/entrevista"; return; }
  const days = meta.dates.map((d) => d.value);
  const today = sandboxNow().toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
  const state = { day: days.includes(today) ? today : days[0], desde: null };
  const objetivo = OBJETIVO_POR_DIA[entrevista.ficha.ritmo?.charlas_por_dia] || OBJETIVO_POR_DIA["5-6"];

  const tabs = h("div", { class: "tabs", role: "tablist" });
  const chosen = h("ul", { class: "ra-chosen-list" });
  const next = h("section", { class: "stack", "aria-live": "polite" });
  const pending = h("div");
  view.replaceChildren(h("div", { class: "stack-lg" },
    h("header", { class: "stack" }, h("h1", { class: "title" }, "Armá tu día"),
      h("p", { class: "caption" }, "Elegí con qué arrancás y te propongo lo que sigue, según tu ficha, la distancia y la cola.")),
    h("div", { class: "actions" },
      Button("Tu ficha", { variant: "ghost", onclick: () => (location.hash = "#/itinerario/ficha") }),
      Button("Ver itinerario", { variant: "ghost", onclick: () => (location.hash = "#/itinerario") })),
    tabs, chosen, next, pending));

  async function paint() {
    tabs.replaceChildren(...days.map((d) => h("button", { class: "ra-tab", role: "tab", "aria-selected": String(d === state.day),
      onclick: () => { state.day = d; state.desde = null; void paint(); } }, shortDay(d))));
    next.replaceChildren(Skeleton(2));
    const [itinerario, { pendientes }] = await Promise.all([Itinerary.get(), Guided.pending()]);
    const items = itinerario.days.find((d) => d.day === state.day)?.sessions || [];
    chosen.replaceChildren(...items.map((s) => ChosenRow(s, paint)));
    pending.replaceChildren(...[PendingList(pendientes, paint)].filter(Boolean));
    await paintNext(items);
  }

  async function paintNext(items) {
    const previa = state.desde ? null : ultimo(items);
    let r;
    try { r = await Guided.next({ day: state.day, after: previa?.code, desde: state.desde }); }
    catch (err) {
      next.replaceChildren(h("p", { class: "notice err" }, err.message));
      if (err.status === 409) next.append(Button("Ir a la entrevista", { variant: "primary", onclick: () => (location.hash = "#/itinerario/entrevista") }));
      return;
    }
    const titulo = previa ? `¿Qué sigue después de las ${r.fin_previa}?`
      : state.desde ? `¿Qué hacés desde las ${state.desde}?` : `¿Con qué arrancás el ${shortDay(state.day)}?`;
    const desde = !previa ? h("label", { class: "caption" }, "Arrancar más tarde: ",
      h("input", { type: "time", value: state.desde || "", onchange: (e) => { state.desde = e.target.value || null; void paint(); } })) : null;
    const pausa = { almuerzo: "🥪 Es la hora del almuerzo: podés hacer una pausa.", libre: "☕ Hay un hueco largo hasta la próxima: buen momento para una pausa o la expo." }[r.pausa];
    // h() aplana listas y descarta null; replaceChildren no (los pintaría como texto).
    next.replaceChildren(h("div", { class: "stack" },
      h("h2", { class: "subtitle" }, titulo), desde,
      pausa ? h("p", { class: "notice" }, pausa) : null,
      r.opciones.length ? r.opciones.map((o) => OptionCard(o, r.previa, { onChoose: (op) => elegir(op, r.previa), onLater: (op) => paraOtroDia(op) }))
        : h("p", { class: "caption" }, "No quedan charlas que calcen en este horario."),
      h("div", { class: "actions" },
        previa ? Button("Hacer una pausa", { onclick: () => { state.desde = hhmm(toMin(r.fin_previa) + PAUSA_MIN); void paint(); } }) : null,
        Button("Terminar el día", { onclick: terminarDia }),
        r.opciones.length ? Button("Completá el resto del día por mí ✨", { onclick: (e) => completar(e.target, items, previa) }) : null)));
  }

  async function elegir(o, previa) {
    try {
      await Itinerary.add(o.card.code, o.razon || undefined);
      if (previa && o.salir_antes_min > 0) await Guided.leaveEarly(previa.code, o.salir_antes_min);
      state.desde = null;
      void refreshCountdown({ force: true });
      await paint();
    } catch (err) { toast(err.message); }
  }

  async function paraOtroDia(o) {
    try {
      await Guided.addPending(o.card.base, state.day);
      toast(`☆ «${o.card.title}» queda en pendientes: vuelve primera si se repite otro día.`);
      await paint();
    } catch (err) { toast(err.message); }
  }

  function terminarDia() {
    const i = days.indexOf(state.day);
    if (i < days.length - 1) { state.day = days[i + 1]; state.desde = null; toast(`Listo el ${shortDay(days[i])}. Sigamos con el ${shortDay(state.day)}.`); void paint(); }
    else location.hash = "#/itinerario";
  }

  /** Elige la mejor opción a la que se llega (verde o amarilla), una tras otra, hasta el ritmo que pidió. */
  async function completar(btn, items, previa) {
    btn.disabled = true;
    let cuenta = items.filter((s) => s.kind === "talk").length;
    let after = previa?.code || null;
    try {
      for (let vuelta = 0; vuelta < MAX_VUELTAS && cuenta < objetivo; vuelta += 1) {
        btn.textContent = `Eligiendo (${cuenta} de ${objetivo})…`;
        const r = await Guided.next({ day: state.day, after, desde: after ? null : state.desde });
        const mejor = r.opciones.find((o) => LLEGABLES.includes(o.estado));
        if (!mejor) break;
        await Itinerary.add(mejor.card.code, mejor.razon || undefined);
        after = mejor.card.code;
        cuenta += 1;
      }
      state.desde = null;
      toast(`Listo: ${cuenta} charlas el ${shortDay(state.day)}. Revisalas y cambiá lo que quieras.`);
    } catch (err) { toast(err.message); }
    void refreshCountdown({ force: true });
    await paint();
  }

  await paint();
}
