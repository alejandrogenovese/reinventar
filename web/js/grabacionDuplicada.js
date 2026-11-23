// Aviso de grabación duplicada: antes de grabar una charla con código, pregunta si otra persona ya la está grabando
// (GET /api/sessions/activa, app/grabaciones_api.py). Si sí: «{quién} ya está grabando esta charla», con «Grabar igual»
// o «Ver la suya». La consulta nunca frena la grabación: sin señal, lenta o con error, se graba igual.
import { Sessions } from "./api.js";
import { confirmDialog } from "./dialog.js";

export const CONSULTA_TIMEOUT_MS = 3000; // en el salón la señal va y viene: no se hace esperar a nadie para grabar

/** La grabación de otro de esa charla ({id, quien, status}) o null. Nunca tira: cualquier falla es null. */
export async function consultarActiva(code, consultar = (c, signal) => Sessions.activa(c, signal), timeoutMs = CONSULTA_TIMEOUT_MS) {
  if (!code || globalThis.navigator?.onLine === false) return null;
  try {
    const r = await consultar(code, AbortSignal.timeout?.(timeoutMs));
    return r?.activa?.id ? r.activa : null;
  } catch { return null; }
}

export const textoAviso = (activa) => `${activa.quien || "Alguien"} ya está grabando esta charla`;

/**
 * ¿Grabar? Devuelve { grabar: true } o { grabar: false, ver: id } (abrir la grabación de la otra persona).
 * `preguntar(activa)` resuelve true si elige «Grabar igual».
 */
export async function decidirGrabar(code, { consultar, preguntar = preguntarConDialogo } = {}) {
  const activa = await consultarActiva(code, consultar);
  if (!activa) return { grabar: true };
  return (await preguntar(activa)) ? { grabar: true } : { grabar: false, ver: activa.id };
}

function preguntarConDialogo(activa) {
  return confirmDialog(textoAviso(activa), {
    text: "Las grabaciones se comparten en la app: podés ver la suya en vez de grabar dos veces la misma charla.",
    confirmLabel: "Grabar igual", cancelLabel: "Ver la suya",
  });
}
