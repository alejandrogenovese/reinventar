// Textos de Ajustes y de «Tus grabaciones» sin señal. El aviso «Sin señal · datos de las HH:MM» ya no va en cada pantalla:
// lo muestra el banner de estado global (estadoBanner.js), que se entera por el evento «ra:sin-servicio» de api.js.
import { staleAt } from "./lastgood.js";

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
