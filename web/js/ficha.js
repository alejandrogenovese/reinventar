// «Mi ficha» (#/ficha): todo lo de la persona en una pantalla (perfil, viaje, notificaciones, passkey, documentos,
// pendientes y agenda), cada bloque con su estado y un botón a la pantalla donde se completa. No hay formularios acá: se
// reusan los que ya existen. Los datos vienen de /api/ficha (app/ficha_api.py); las reglas, de fichaReglas.js.
import { api } from "./api.js";
import { bloques, completitud, faltantesDe } from "./fichaReglas.js";
import { icon } from "./icons.js";
import { currentSubscription, estadoPush } from "./notifications.js";
import { Hint, Skeleton, h } from "./ui.js";

/** Lo avisa la ficha al cargar: el banner (estadoBanner.js) se pone al día sin volver a pedir /api/ficha. */
export const EVENTO_FICHA = "ra:ficha";

/** { estado, activo, denegado } de las notificaciones en este dispositivo. activo null = no se pudo saber. */
export async function leerNotificaciones() {
  const estado = estadoPush();
  if (estado !== "ok") return { estado, activo: false, denegado: false };
  const permiso = globalThis.Notification?.permission;
  if (permiso !== "granted") return { estado, activo: false, denegado: permiso === "denied" };
  try {
    const { sub } = await currentSubscription();
    return { estado, activo: Boolean(sub), denegado: false };
  } catch (err) {
    console.warn("[ficha] no se pudo leer la suscripción de notificaciones", err);
    return { estado, activo: null, denegado: false };
  }
}

function Progreso({ hechos, total, pct }) {
  const valor = `${pct}% completa`;
  return h("div", { class: "ra-progress", role: "progressbar", "aria-label": "Ficha completa",
    "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(pct), "aria-valuetext": `${valor} (${hechos} de ${total})` },
  h("span", { class: "caption" }, `${valor} · ${hechos} de ${total}`),
  h("div", { class: "ra-progress-track" }, h("div", { class: "ra-progress-fill", style: { width: `${pct}%` } })));
}

function Estado(b) {
  if (b.completo) return h("span", { class: "ra-tag" }, "Completo");
  return h("span", { class: b.opcional ? "ra-tag" : "ra-tag is-new" }, b.opcional ? "Opcional" : "Falta algo");
}

const Bloque = (b) => h("section", { class: "ra-card", "aria-labelledby": `ficha-${b.id}` },
  h("div", { class: "ra-card-top" }, h("h2", { class: "ra-card-title", id: `ficha-${b.id}` }, b.titulo), Estado(b)),
  b.lineas.map((l) => h("p", { class: "caption" }, l)),
  h("div", { class: "actions" }, h("a", { class: `ra-btn ${b.completo ? "ra-btn-ghost" : "ra-btn-secondary"}`, href: b.link }, b.boton, icon("llevar", 16))));

export async function viewFicha(view) {
  const cuerpo = h("div", { class: "stack" }, Skeleton(3));
  view.append(h("div", { class: "stack-lg" }, h("h1", { class: "title" }, "Mi ficha"), cuerpo));
  let ficha;
  let notif;
  try {
    [ficha, notif] = await Promise.all([api("/api/ficha"), leerNotificaciones()]);
  } catch (err) {
    console.warn("[ficha] no se pudo cargar", err);
    cuerpo.replaceChildren(Hint("No se pudo cargar tu ficha. Revisá la señal y probá de nuevo.", { tone: "warn" }));
    return;
  }
  window.dispatchEvent(new CustomEvent(EVENTO_FICHA, { detail: { ficha, notificaciones: notif } }));
  const lista = bloques(ficha, notif);
  const [primero] = faltantesDe(ficha, notif).filter((f) => f.banner);
  const resumen = primero ? Hint(`Lo más importante: ${primero.texto}.`, { tone: "info" })
    : Hint("Tenés todo lo importante cargado.", { tone: "info", iconName: "ok" });
  const quien = typeof ficha?.usuario === "string" ? h("p", { class: "caption" }, `Conectado como ${ficha.usuario}`) : null;
  // replaceChildren pinta null como texto: se filtra.
  cuerpo.replaceChildren(...[quien, Progreso(completitud(lista)), resumen, ...lista.map(Bloque)].filter(Boolean));
}
