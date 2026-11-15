// Franja «Sin señal · datos de las HH:MM» para las pantallas que muestran la última copia guardada (lastgood.js).
import { sinSenalTexto, staleAt } from "./lastgood.js";
import { h } from "./ui.js";

/** La franja si estos datos son una copia sin señal; null si vienen frescos (h ignora los null). */
export function SinSenal(data) {
  const at = staleAt(data);
  return at ? h("div", { class: "notice warn", role: "status" }, sinSenalTexto(at)) : null;
}
