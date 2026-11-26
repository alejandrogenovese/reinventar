// «Está llena / hay mucha cola»: lo que avisa la gente en la puerta (app/lleno.py). Va en la ficha de la charla, en las
// tarjetas de Hoy y en las del itinerario. Si está llena, la ficha sugiere otras charlas cerca (app/lleno_alternativas.py).
import { Lleno } from "./api.js";
import { Hint, h, mensajeError, toast } from "./ui.js";

const ESTADOS_LLENO = { lleno: "Está llena", cola: "Hay mucha cola" };
const TOPE_CODIGOS = 30; // app/lleno.py CODIGOS_POR_PEDIDO
const NO_SON_CHARLAS = new Set(["event", "show", "mine"]); // eventos, shows y eventos propios no están en el catálogo
const personas = (n) => `${n} persona${n === 1 ? "" : "s"}`;

/**
 * Charla que dejó de aparecer en el catálogo oficial (app/charlas_auto.py): primero la duda, después «Cancelada».
 * Va en la tarjeta, en la ficha, en el itinerario y en Hoy. null si está todo bien.
 */
export function AvisoBaja(s) {
  if (s?.cancelled) return Hint("Cancelada: ya no aparece en el catálogo oficial de AWS. Buscá otra charla.", { tone: "error" });
  if (s?.missing_since) return Hint(`No aparece en el catálogo oficial desde las ${s.missing_since}. Puede haberse dado de baja: confirmalo antes de ir.`, { tone: "warn" });
  return null;
}

/** "2026-11-24" → "lun 24/11" (a mediodía, para que la zona horaria no corra el día). */
const diaCorto = (iso) => {
  const d = new Date(`${iso}T12:00:00`);
  const dia = d.toLocaleDateString("es-AR", { weekday: "short" }).replace(/[.,]/g, "");
  return `${dia} ${d.getDate()}/${d.getMonth() + 1}`;
};

/**
 * Etiqueta de estado arriba del título: «Cancelada» si se canceló, «Nueva · agregada el lun 24/11» si AWS la sumó al
 * catálogo hace poco (app/catalog.agregada). null si no hay nada que marcar.
 */
export function EtiquetaEstado(s) {
  if (s?.cancelled) return h("span", { class: "ra-tag is-cancelada" }, "Cancelada");
  if (s?.added) return h("span", { class: "ra-tag is-nueva" }, `Nueva · agregada el ${diaCorto(s.added)}`);
  return null;
}

/** En la ficha de una charla nueva: cuándo la sumó AWS y que el resumen puede estar en inglés. */
export function AvisoNueva(s) {
  if (!s?.added || s.cancelled) return null;
  const resumen = s.abstract_es ? "" : " El resumen está en inglés hasta la próxima traducción.";
  return Hint(`Charla nueva: AWS la sumó al catálogo el ${diaCorto(s.added)}. Fijate que no se superponga con tu agenda.${resumen}`);
}

/** Lo que avisó la gente en la puerta: «Llena según 3 personas · hace 5 min». */
function LlenoResumen(a) {
  const partes = [a.lleno ? `Llena según ${personas(a.lleno)}` : null, a.cola ? `mucha cola según ${personas(a.cola)}` : null].filter(Boolean);
  if (!partes.length) return null;
  const hace = a.hace_min ? `hace ${a.hace_min} min` : "recién";
  const texto = `${partes.join(" · ")} · ${hace}`;
  return h("span", { class: "ra-lleno-dato", role: "status" }, texto[0].toUpperCase() + texto.slice(1));
}

/**
 * Pista del catálogo + lo que avisó la gente + botones para avisar (solo mientras la charla está por empezar o en curso).
 * conPista: false donde la tarjeta ya dice si es sin reserva (Hoy). Sin nada que mostrar, devuelve null.
 */
export function LlenoAvisos(code, a, { conPista = true, onCambio = null } = {}) {
  if (!a) return null;
  const box = h("div", { class: "ra-lleno" });
  const pintar = (x) => {
    const botones = x.abierto ? h("div", { class: "ra-lleno-avisar" }, h("span", { class: "caption" }, "¿Estás en la puerta?"),
      Object.entries(ESTADOS_LLENO).map(([estado, label]) => {
        const mio = x.mio === estado;
        const btn = h("button", { type: "button", class: mio ? "ra-chip ra-chip-on" : "ra-chip", "aria-pressed": String(mio), onclick: async () => {
          btn.disabled = true;
          try {
            const nuevo = mio ? await Lleno.retirar(code) : await Lleno.avisar(code, estado);
            pintar(nuevo);
            onCambio?.(nuevo);
            if (!mio) toast("Gracias: le avisamos al resto.");
          }
          catch (e) { toast(mensajeError(e)); btn.disabled = false; }
        } }, label);
        return btn;
      })) : null;
    box.replaceChildren(...[conPista && x.pista ? h("span", { class: "caption" }, x.pista) : null, LlenoResumen(x), botones].filter(Boolean));
  };
  pintar(a);
  return box.childElementCount ? box : null;
}

/** Códigos de charla (no eventos) de una lista de ítems de Hoy o del itinerario, hasta el tope del pedido. */
export const codigosDeCharlas = (items) => [...new Set(items.filter((s) => s && s.code && !NO_SON_CHARLAS.has(s.kind)).map((s) => s.code))].slice(0, TOPE_CODIGOS);

/** Avisos de esos códigos; si falla (sin conexión) o no hay códigos, {}: las tarjetas se muestran igual. */
export const avisosDe = (codes) => (codes.length ? Lleno.estado(codes).catch(() => ({})) : Promise.resolve({}));

/**
 * «14:30 · Caesars Forum · 9 min caminando»: cuándo, dónde y cuánto se camina desde la sala llena. Si hay una forma
 * mejor de ir (app/rutas.py: shuttle, monorail, puente), va al final: «… · 34 min caminando · o shuttle de re:Invent».
 */
export function detalleAlternativa(a) {
  let camino = `${a.minutos} min caminando`;
  if (a.misma_sede) camino = "en el mismo edificio";
  else if (a.estimado) camino = `unos ${camino}`;
  return [a.en_curso ? `Empezó ${a.start}` : a.start, a.venue?.hotel, camino, a.misma_sede ? null : a.ruta].filter(Boolean).join(" · ");
}

const TITULO_ALTERNATIVAS = { lleno: "Está llena. Cerca y por empezar:", cola: "Hay mucha cola. Cerca y por empezar:" };

/** Las charlas cerca que empiezan ahora o en un rato, cada una con link a su ficha. motivo: «lleno» o «cola». */
export function ListaAlternativas(alternativas, motivo = "lleno") {
  if (!alternativas.length) return h("p", { class: "caption" }, "No encontramos otras charlas cerca que empiecen pronto.");
  return h("div", { class: "stack" },
    h("strong", {}, TITULO_ALTERNATIVAS[motivo] || TITULO_ALTERNATIVAS.lleno),
    h("ul", { class: "ra-people" }, alternativas.map((a) => h("li", {},
      h("a", { class: "ra-link", href: `#/charla/${encodeURIComponent(a.base)}` }, a.title),
      h("span", { class: "caption" }, ` · ${detalleAlternativa(a)}`)))));
}

/** Hay algún aviso de «llena» o «mucha cola» en ese horario. */
const hayAviso = (a) => Boolean(a?.lleno || a?.cola);

/**
 * En la ficha: si avisaron que el horario está lleno o con mucha cola y no estás anotado, otras charlas cerca. Se carga
 * aparte para no demorar la ficha; si falla (sin conexión), no muestra nada. `mostrar(aviso)` la vuelve a pedir cuando
 * cambian los avisos (por ejemplo, al tocar «Está llena» o «Hay mucha cola»). null si estás anotado.
 */
export function SugerenciasLleno(code, aviso, anotado) {
  if (anotado) return null;
  const el = h("div", { class: "ra-lleno-alternativas", "aria-live": "polite" });
  const mostrar = (a) => {
    if (!hayAviso(a)) { el.replaceChildren(); return; }
    void Lleno.alternativas(code)
      .then((r) => el.replaceChildren(...(r.motivo ? [ListaAlternativas(r.alternativas, r.motivo)] : [])))
      .catch(() => el.replaceChildren());
  };
  mostrar(aviso);
  return { el, mostrar };
}
