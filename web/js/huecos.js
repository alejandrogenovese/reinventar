// Tramos sin audio de una grabación (una llamada o un audio de WhatsApp le saca el micrófono a la app): se detectan al
// grabar, se mandan al servidor al terminar y se muestran en la transcripción. Sin DOM: lo prueba node --test.

// Cuánto sin sonido hace falta para avisar «No llega sonido al micrófono». Es también el mínimo de un hueco: así un hueco
// marcado es exactamente un tramo en el que la app ya avisó, y las pausas del orador en una sala silenciosa no cuentan.
export const SILENCIO_AVISO_S = 8;
export const HUECO_MIN_S = SILENCIO_AVISO_S;
export const CLAVE_TIP = "reinventar.tip-no-molestar";
export const TIP_NO_MOLESTAR = "Tip: poné No molestar. Una llamada o grabar un audio de WhatsApp le saca el micrófono a la app y ese tramo queda sin sonido.";

const decimal = (s) => Math.round(s * 10) / 10;  // los tiempos se guardan con un decimal

/**
 * Detector de tramos sin sonido en segundos del contador de la grabación. `observar(t, silencioso)` se llama con cada
 * muestra del medidor: true = no llega sonido, false = llega, null = no se está grabando (pausa o corte del sistema; el
 * contador está quieto, no suma tiempo). Igual que el aviso de silencio, el sonido o una pausa cortan el tramo. Devuelve
 * true cuando cierra un hueco nuevo (para guardarlo). `inicial` son los huecos de una grabación que se retoma.
 */
export function crearDetectorDeHuecos(inicial = [], minS = HUECO_MIN_S) {
  const cerrados = inicial.map((x) => ({ ...x }));
  let desde = null;
  let ultimo = null;
  const cerrar = (hasta) => {
    const sirve = desde !== null && hasta - desde >= minS;
    if (sirve) cerrados.push({ desde: decimal(desde), hasta: decimal(hasta) });
    desde = null;
    return sirve;
  };
  return {
    observar(t, silencioso) {
      if (silencioso) { desde ??= t; ultimo = t; return false; }
      return silencioso === null && desde !== null ? cerrar(ultimo) : cerrar(t);
    },
    finalizar: () => (desde === null ? false : cerrar(ultimo)),
    huecos: () => cerrados.map((x) => ({ ...x })),
  };
}

// --- en la transcripción ---------------------------------------------------------------------------------------------
const valido = (x) => x && Number.isFinite(x.desde) && Number.isFinite(x.hasta) && x.hasta > x.desde;

/** Los bloques con los huecos intercalados por tiempo: cada hueco va antes del primer bloque que empieza en o después de `desde`. */
export function intercalarHuecos(bloques, huecos) {
  const ordenados = (Array.isArray(huecos) ? huecos : []).filter(valido).toSorted((a, b) => a.desde - b.desde);
  const items = [];
  let i = 0;
  for (const bloque of bloques) {
    while (i < ordenados.length && ordenados[i].desde <= bloque.start_s) items.push({ tipo: "hueco", ...ordenados[i++] });
    items.push({ tipo: "bloque", bloque });
  }
  return [...items, ...ordenados.slice(i).map((x) => ({ tipo: "hueco", ...x }))];
}

const dos = (n) => String(Math.floor(n)).padStart(2, "0");
const mmss = (s) => {
  const total = Math.max(0, Math.floor(s));
  const horas = Math.floor(total / 3600);
  const resto = `${dos((total % 3600) / 60)}:${dos(total % 60)}`;
  return horas ? `${horas}:${resto}` : resto;
};

/** «— sin audio 02:06–02:40 —» */
export const textoHueco = ({ desde, hasta }) => `— sin audio ${mmss(desde)}–${mmss(hasta)} —`;

// --- envío -----------------------------------------------------------------------------------------------------------
const SIN_RED = (status) => !status || status === 401 || status >= 500;

/**
 * Manda los huecos a la sesión real. Sin red, 401 o un error del servidor: hay que reintentar (no se pierden). Cualquier
 * otro error (404 si el backend todavía no tiene el endpoint, 403 si la sesión no es del usuario o es vieja, 422) se
 * descarta en silencio: los huecos son un extra, nunca bloquean cerrar la grabación. `enviar` se inyecta.
 */
export async function mandarHuecos(realId, huecos, enviar) {
  if (!huecos?.length) return { resultado: "ok" };
  try {
    await enviar(realId, huecos);
    return { resultado: "ok" };
  } catch (error) {
    return SIN_RED(error.status) ? { resultado: "reintentar", error } : { resultado: "ok" };
  }
}

// --- tip de «No molestar» --------------------------------------------------------------------------------------------
export function tipNoMolestarVisto() {
  try { return localStorage.getItem(CLAVE_TIP) === "1"; } catch { return false; }
}
export function marcarTipNoMolestarVisto() {
  try { localStorage.setItem(CLAVE_TIP, "1"); } catch { /* sin almacenamiento: el tip puede volver, no se rompe nada */ }
}
