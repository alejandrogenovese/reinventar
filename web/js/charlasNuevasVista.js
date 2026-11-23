// Pantalla «Charlas nuevas» (#/itinerario/nuevas, a donde abre el push): cada charla se agrega a la agenda con el mismo
// agregado del itinerario (avisa si se superpone con algo) o se descarta; ninguna de las dos vuelve a aparecer.
import { CharlasNuevas, textoAgregada } from "./charlasNuevas.js";
import { refreshCountdown } from "./countdown.js";
import { icon } from "./icons.js";
import { SessionMiniCard, forgetItineraryCodes, shortDay } from "./itinerary.js";
import { Button, h, mensajeError, toast } from "./ui.js";

/** Etiqueta del botón de un horario: con un solo horario alcanza «Agregar a mi agenda»; con varios, cuál. */
export const textoBotonHorario = (horario, cantidad) => (cantidad === 1
  ? "Agregar a mi agenda" : `Agregar ${shortDay(horario.day)} ${horario.start}`);

function Tarjeta(c, onDone) {
  const botones = c.horarios.map((hr) => Button(textoBotonHorario(hr, c.horarios.length), {
    variant: "primary",
    title: hr.choques.length ? `Se superpone con ${hr.choques.join(", ")}` : "Agregar este horario a tu itinerario",
    onclick: async (e) => {
      const btn = e.currentTarget;  // después del await currentTarget ya es null
      btn.disabled = true;
      try {
        const r = await CharlasNuevas.add(hr.code);
        toast(textoAgregada(r.choques));
        forgetItineraryCodes();
        void refreshCountdown({ force: true });
        onDone();
      } catch (err) { btn.disabled = false; toast(mensajeError(err)); }
    },
  }));
  const descartar = Button("Descartar", { onclick: async () => {
    try { await CharlasNuevas.discard(c.base); toast("Descartada."); onDone(); } catch (err) { toast(mensajeError(err)); }
  } });
  const choques = c.horarios.filter((hr) => hr.choques.length).map((hr) =>
    h("p", { class: "caption" }, `${shortDay(hr.day)} ${hr.start}: se superpone con ${hr.choques.join(", ")}`));
  return SessionMiniCard(c, { extra: h("div", { class: "stack" },
    c.interes ? h("span", { class: "ra-tag is-new" }, "Coincide con tus intereses") : null,
    choques, h("div", { class: "actions" }, botones, descartar)) });
}

export async function viewCharlasNuevas(view) {
  async function paint() {
    const { charlas } = await CharlasNuevas.list();
    view.replaceChildren(h("div", { class: "stack-lg" },
      h("div", { class: "ra-sec-head" }, h("h1", { class: "title" }, "Charlas nuevas"),
        h("a", { class: "ra-btn ra-btn-ghost ra-sec-action", href: "#/itinerario" }, h("span", {}, "Tu itinerario"), icon("seguir", 16))),
      h("p", { class: "caption" }, "Las que AWS sumó al catálogo en los últimos días y todavía no pasaron. Agregala o descartala: no te vuelve a aparecer."),
      charlas.length
        ? h("div", { class: "daylist" }, charlas.map((c) => Tarjeta(c, () => void paint().catch(mostrarError))))
        : h("div", { class: "empty" }, h("p", {}, "No hay charlas nuevas por ahora."),
          h("p", { class: "caption" }, "Revisamos el catálogo oficial varias veces por día y te avisamos cuando aparece alguna."))));
  }
  const mostrarError = (err) => view.replaceChildren(h("p", { class: "caption" }, `No se pudieron cargar las charlas nuevas: ${mensajeError(err)}`));
  await paint().catch(mostrarError);
}

