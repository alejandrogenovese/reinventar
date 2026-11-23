// Aviso de charla que AWS publica en YouTube: antes de grabar una keynote, mainstage o breakout (en_youtube, la regla
// está en app/catalog.py) avisa que sale en el canal AWS Events y que no hace falta grabarla, con «Grabar igual» o
// «No grabar». Una sola vez por charla (se recuerda en este dispositivo) y sin red: no consulta nada. Nunca frena una
// grabación por una falla propia: si algo sale mal, se graba.
import { choiceDialog } from "./dialog.js";
import { h } from "./ui.js";

const CLAVE = "reinventar.aviso-youtube"; // charlas (código base) a las que ya se les mostró el aviso
export const MAX_RECORDADAS = 200; // tope para que la lista no crezca sin fin

export const TITULO_AVISO = "AWS publica esta charla en YouTube";
export const TEXTO_AVISO = "Sale en el canal AWS Events entre 24 y 48 h después. No hace falta grabarla: podés tomar notas.";

/** Etiqueta chica para fichas y tarjetas; null si la charla no se publica. */
export const EtiquetaYoutube = (s) => (s?.en_youtube ? h("span", { class: "ra-tag", title: TEXTO_AVISO }, "Se publica en YouTube") : null);

const claveCharla = (talk) => talk?.base || talk?.code || null;

// Safari con cookies bloqueadas tira SecurityError con solo leer globalThis.localStorage.
function almacenamiento() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

/** Charlas ya avisadas; [] si no hay almacenamiento o el JSON está roto. */
export function leerAvisadas(storage) {
  try {
    const lista = JSON.parse(storage?.getItem(CLAVE) || "[]");
    return Array.isArray(lista) ? lista : [];
  } catch { return []; }
}

export function recordarAvisada(storage, clave) {
  try { storage?.setItem(CLAVE, JSON.stringify([...leerAvisadas(storage), clave].slice(-MAX_RECORDADAS))); } catch {}
}

/**
 * ¿Grabar? true si la charla no sale en YouTube, si ya se avisó antes, si elige «Grabar igual» o si algo falla;
 * false con «No grabar» o si cierra el aviso sin elegir (Esc). Solo una elección explícita queda recordada.
 * `preguntar()` resuelve "ok" («Grabar igual»), "cancel" («No grabar») o "" (cerrado sin elegir).
 */
export async function decidirPorYoutube(talk, { preguntar = preguntarConDialogo, storage = almacenamiento() } = {}) {
  try {
    const clave = claveCharla(talk);
    if (!talk?.en_youtube || !clave || leerAvisadas(storage).includes(clave)) return true;
    const eleccion = await preguntar();
    if (eleccion === "ok" || eleccion === "cancel") recordarAvisada(storage, clave);
    return eleccion === "ok";
  } catch { return true; }
}

function preguntarConDialogo() {
  return choiceDialog(TITULO_AVISO, { text: TEXTO_AVISO, confirmLabel: "Grabar igual", cancelLabel: "No grabar" });
}
