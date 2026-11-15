// Grabaciones que empezaron sin señal (sesiones locales «loc_…» de store.js) en Inicio, arriba de «Tus grabaciones»:
// así no se pierden de vista mientras esperan subir. La lista la arma store.sesionesLocalesPendientes() (de grabación).
import { StatusPill, h } from "./ui.js";

const TITULO_GENERICO = "Grabación sin conexión";

// estado de la sesión local → pastilla ya existente (clases ra-pill-*) y texto.
const ESTADOS = {
  grabando: { status: "recording", texto: "Grabando" },
  pendiente_de_subir: { status: "uploading", texto: "Pendiente de subir" },
  esperando_senal: { status: "queued", texto: "Esperando señal" },
};
const ESTADO_DESCONOCIDO = { status: "queued", texto: "Pendiente" };

/** De la sesión local a lo que se dibuja: título, pastilla y a dónde lleva la tarjeta. */
export function fichaLocal(s) {
  const { status, texto } = ESTADOS[s.estado] ?? ESTADO_DESCONOCIDO;
  return { id: s.id, title: s.title?.trim() || TITULO_GENERICO, status, texto, href: `#/grabar/${s.id}`, at: s.at ?? 0 };
}

/** Las sesiones locales pendientes, más nuevas primero. Nunca rompe Inicio: sin la función o con un error devuelve []. */
export async function cargarLocales(store) {
  if (typeof store?.sesionesLocalesPendientes !== "function") return [];
  try {
    const crudas = await store.sesionesLocalesPendientes();
    if (!Array.isArray(crudas)) return [];
    return crudas.filter((s) => s?.id).map(fichaLocal).sort((a, b) => b.at - a.at);
  } catch (e) {
    console.warn("[locales] no se pudieron leer las grabaciones locales", e);
    return [];
  }
}

/** El bloque de Inicio, o null si no hay nada pendiente (h ignora los null). */
export function LocalesPendientes(fichas) {
  if (!fichas.length) return null;
  return h("section", { class: "stack", "aria-labelledby": "locales-title" },
    h("h2", { class: "label", id: "locales-title" }, "Grabadas en este celular"),
    ...fichas.map((f) => h("button", { type: "button", class: "ra-card ra-reccard", onclick: () => { location.hash = f.href; } },
      h("h3", { class: "ra-card-title" }, f.title), StatusPill(f.status, f.texto))));
}
