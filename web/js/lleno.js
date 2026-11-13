// «Está llena / hay mucha cola»: lo que avisa la gente en la puerta (app/lleno.py). Va en la ficha de la charla, en las
// tarjetas de Hoy y en las del itinerario.
import { Lleno } from "./api.js";
import { h, toast } from "./ui.js";

const ESTADOS_LLENO = { lleno: "Está llena", cola: "Hay mucha cola" };
const TOPE_CODIGOS = 30; // app/lleno.py CODIGOS_POR_PEDIDO
const NO_SON_CHARLAS = new Set(["event", "mine"]); // eventos y eventos propios no están en el catálogo
const personas = (n) => `${n} persona${n === 1 ? "" : "s"}`;

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
export function LlenoAvisos(code, a, { conPista = true } = {}) {
  if (!a) return null;
  const box = h("div", { class: "ra-lleno" });
  const pintar = (x) => {
    const botones = x.abierto ? h("div", { class: "ra-lleno-avisar" }, h("span", { class: "caption" }, "¿Estás en la puerta?"),
      Object.entries(ESTADOS_LLENO).map(([estado, label]) => {
        const mio = x.mio === estado;
        const btn = h("button", { type: "button", class: mio ? "ra-chip ra-chip-on" : "ra-chip", "aria-pressed": String(mio), onclick: async () => {
          btn.disabled = true;
          try { pintar(mio ? await Lleno.retirar(code) : await Lleno.avisar(code, estado)); if (!mio) toast("Gracias: le avisamos al resto."); }
          catch (e) { toast(e.message); btn.disabled = false; }
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
