// Franja «Sin señal · datos de las HH:MM» para las pantallas que muestran la última copia guardada (lastgood.js).
import { sinSenalTexto, staleAt } from "./lastgood.js";
import { h } from "./ui.js";

/** El texto de Ajustes según lo que se sabe de la cuenta (ver cuentaConCopia en api.js). */
export function textoDeCuenta({ estado, username }) {
  if (estado === "ok" || estado === "copia") return `Conectado como ${username}.`;
  if (estado === "sin_senal") return "Sin señal: tu cuenta se muestra cuando vuelva la red.";
  if (estado === "sin_sesion") return "Sesión no válida.";
  return "No se pudo cargar tu cuenta. Probá de nuevo en un rato.";
}

/** El vacío de «Tus grabaciones». Una lista vacía que es copia sin señal puede estar vieja: no se dice «todavía no grabaste». */
export function textosSinGrabaciones(sessions) {
  return staleAt(sessions)
    ? { titulo: "Sin señal: tus grabaciones se muestran cuando vuelva la red.", detalle: null }
    : { titulo: "Todavía no grabaste ninguna sesión.", detalle: "Conectá el receptor del DJI al celular y tocá Nueva." };
}

/** La franja si estos datos son una copia sin señal; null si vienen frescos (h ignora los null). */
export function SinSenal(data) {
  const at = staleAt(data);
  return at ? h("div", { class: "notice warn", role: "status" }, sinSenalTexto(at)) : null;
}
