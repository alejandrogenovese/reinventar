// Conversor › «Leer con la cámara»: foto de una carta o un cartel → el servidor (POST /api/conversor/foto) la lee y la
// traduce con un LLM, y acá se convierten las unidades con las mismas funciones del conversor manual (unidades.js).
// Necesita señal; el servidor puede tenerla apagada (CONVERSOR_FOTO): entonces la sección no aparece. La foto se achica
// en el celular como la de los tickets de Gastos y no se guarda en ningún lado.
import { ApiError, api } from "./api.js";
import { achicarFoto } from "./gastos.js";
import { MSG_FOTO_SIN_SENAL, estadoLecturaFoto } from "./sinSenal.js";
import { Button, Hint, Tag, h } from "./ui.js";
import { convertirDetectada } from "./unidades.js";

const CLAVE_ESTADO = "reinventar.conversor.foto";   // lo último que dijo el servidor, para saber qué mostrar sin señal
const TIMEOUT_MS = 60_000;
export const MSG_NADA = "No encontré números ni texto legible. Acercate y evitá reflejos.";
export const MSG_ERROR = "No pude leer la foto. Probá de nuevo.";

function leerHabilitada() {
  try {
    const v = localStorage.getItem(CLAVE_ESTADO);
    return v === null ? null : v === "1";
  } catch { return null; }
}
function guardarHabilitada(v) { try { localStorage.setItem(CLAVE_ESTADO, v ? "1" : "0"); } catch {} }

async function pedirConTimeout(ruta, opciones = {}) {
  const corte = new AbortController();
  const timer = setTimeout(() => corte.abort(), TIMEOUT_MS);
  try { return await api(ruta, { ...opciones, signal: corte.signal }); } finally { clearTimeout(timer); }
}

const Resultado = (t, tarjeta) => {
  const conversiones = t.unidades.map((u) => convertirDetectada(u, { tarjeta })).filter(Boolean);
  return h("article", { class: "stack", style: { paddingTop: "var(--space-2)", borderTop: "1px solid var(--line)" } },
    h("p", {}, h("strong", {}, t.traduccion || t.original)),
    t.traduccion && t.original ? h("p", { class: "caption", lang: "en" }, t.original) : null,
    conversiones.length ? h("div", { class: "ra-chips" }, conversiones.map(Tag)) : null);
};

/** La sección de la cámara. `cotiz` da la cotización tarjeta para pasar a pesos los precios en dólares. */
export function SeccionFoto(cotiz) {
  const ctx = { habilitada: leerHabilitada(), leyendo: false, aviso: null, textos: [] };
  const seccion = h("section", { class: "stack", "aria-live": "polite" });
  const archivo = h("input", { type: "file", accept: "image/*", capture: "environment", hidden: true, onchange: () => void leer() });

  async function leer() {
    const elegido = archivo.files?.[0];
    archivo.value = "";
    if (!elegido) return;
    Object.assign(ctx, { leyendo: true, aviso: null, textos: [] });
    pintar();
    try {
      const cuerpo = new FormData();
      cuerpo.append("foto", await achicarFoto(elegido), "foto.jpg");
      const r = await pedirConTimeout("/api/conversor/foto", { method: "POST", body: cuerpo });
      ctx.textos = Array.isArray(r?.textos) ? r.textos : [];
      ctx.aviso = ctx.textos.length ? null : { texto: MSG_NADA, tono: "info" };
    } catch (e) {
      console.warn("[conversor] no se pudo leer la foto", e instanceof ApiError ? e.status : e?.name);
      if (e instanceof ApiError && e.status === 503) { ctx.habilitada = false; guardarHabilitada(false); }
      const sinRed = (e instanceof ApiError && e.status === 0) || navigator.onLine === false;
      ctx.aviso = { texto: sinRed ? MSG_FOTO_SIN_SENAL : MSG_ERROR, tono: "error" };
    } finally {
      ctx.leyendo = false;
      pintar();
    }
  }

  function pintar() {
    const modo = estadoLecturaFoto({ habilitada: ctx.habilitada, enLinea: navigator.onLine !== false });
    if (modo === "oculto") { seccion.replaceChildren(); return; }
    const boton = Button(ctx.leyendo ? "Leyendo la foto…" : "Leer con la cámara", {
      variant: "primary", disabled: modo === "sin-senal" || ctx.leyendo, onclick: () => archivo.click() });
    const tarjeta = cotiz.tarjeta();
    seccion.replaceChildren(...[
      h("h2", { class: "label" }, "Leer con la cámara"),
      h("p", { class: "caption" }, "Sacale una foto a la carta, un cartel o una etiqueta: te lo traduzco y paso las unidades."),
      archivo,
      h("div", { class: "actions" }, boton),
      modo === "sin-senal" ? Hint(MSG_FOTO_SIN_SENAL, { tone: "warn" }) : null,
      ctx.aviso ? Hint(ctx.aviso.texto, { tone: ctx.aviso.tono }) : null,
      ...ctx.textos.map((t) => Resultado(t, tarjeta)),
    ].filter(Boolean));
  }

  async function consultarEstado() {
    if (navigator.onLine === false) return;
    try {
      ctx.habilitada = Boolean((await pedirConTimeout("/api/conversor/estado"))?.foto);
      guardarHabilitada(ctx.habilitada);
    } catch (e) { console.warn("[conversor] no se pudo saber si la lectura con cámara está prendida", e?.status ?? e); }
    pintar();
  }

  const alCambiarRed = () => {
    if (!seccion.isConnected) { quitarOyentes(); return; }
    pintar();
    void consultarEstado();
  };
  function quitarOyentes() { window.removeEventListener("online", alCambiarRed); window.removeEventListener("offline", alCambiarRed); }
  window.addEventListener("online", alCambiarRed);
  window.addEventListener("offline", alCambiarRed);
  pintar();
  void consultarEstado();
  return seccion;
}
