// «Personas que conocí»: lógica pura (validar, buscar, mezclar con la cola, vCard) y la cola sin señal. Nada acá toca el DOM
// ni la red: se prueba con node (tests/js/personas.test.mjs). La pantalla y el envío están en personas.js.
//
// La cola es como la de gastos (gastosCola.js) pero más chica: cada cambio es un PUT o un DELETE idempotente por id (el
// id lo genera el teléfono), así que alcanza con guardar la última operación de cada persona. Vive en localStorage con
// el prefijo de la última copia (lastgood.js) y el dueño de la sesión: al cerrar sesión clearLast() la borra junto con
// las copias, y nunca se manda a la cuenta de otra persona.

export const LARGOS = { nombre: 80, empresa: 80, cargo: 80, linkedin: 200, donde: 120, charla_titulo: 200, nota: 1000 };
export const CAMPOS = ["nombre", "empresa", "cargo", "linkedin", "donde", "charla_code", "charla_titulo", "nota"];
// Igual que app/personas.py: https, el dominio exacto y sin espacios ni comillas.
const LINKEDIN = /^https:\/\/www\.linkedin\.com\/[^\s<>"']*$/;
const PREFIJO = "reinventar.last.";
const DUENO_VALIDO = /^[0-9a-f]{12}$/;

export const linkedinValido = (url) => typeof url === "string" && url.length <= LARGOS.linkedin && LINKEDIN.test(url);

/** Lo que el servidor rechazaría, en castellano, o null si está bien. Se corre antes de guardar en la cola. */
export function validarPersona(p) {
  if (!String(p.nombre ?? "").trim()) return "Escribí el nombre.";
  for (const [campo, max] of Object.entries(LARGOS)) {
    if (String(p[campo] ?? "").length > max) return `«${campo}» pasa de ${max} letras.`;
  }
  if (p.linkedin && !linkedinValido(p.linkedin)) return "El LinkedIn tiene que ser un link https://www.linkedin.com/…";
  return null;
}

/** Solo los campos del contrato (lo demás —pendiente, error— es del teléfono). */
export const aDatos = (p) => Object.fromEntries(CAMPOS.map((k) => [k, p[k] ?? (k === "charla_code" ? null : "")]));

/** Sin tildes ni mayúsculas: «gómez» encuentra «Gomez». */
const normal = (t) => String(t ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

/** Las que tienen todas las palabras de `q` en algún campo. Sin `q`, todas. */
export function filtrar(personas, q) {
  const palabras = normal(q).split(/\s+/).filter(Boolean);
  if (!palabras.length) return personas;
  return personas.filter((p) => {
    const texto = normal([p.nombre, p.empresa, p.cargo, p.donde, p.charla_titulo, p.charla_code, p.nota].join(" "));
    return palabras.every((w) => texto.includes(w));
  });
}

// ---------- cola ----------

/** La cola con `op` al final y sin otra operación de la misma persona (la última manda). */
export const encolar = (cola, op) => [...cola.filter((x) => x.id !== op.id), op];

/** Lo que se ve: lo del servidor con la cola encima (altas y ediciones sin subir marcadas `pendiente`, borrados afuera). */
export function aplicarCola(servidor, cola) {
  const ops = new Map(cola.map((op) => [op.id, op]));
  const vistas = servidor.filter((p) => !ops.has(p.id));
  const nuevas = cola.filter((op) => op.op === "put").map((op) => ({ ...op.datos, id: op.id, actualizado: op.at, pendiente: true }));
  return [...nuevas.reverse(), ...vistas];
}

/** Qué hacer con la respuesta de una operación: «listo» (sale de la cola), «esperar» (sin señal o servidor caído: queda)
 * o «rechazado» (el servidor no la acepta: sale y se avisa). Un DELETE que da 404 ya está hecho. */
export function resultadoDe(op, error) {
  if (!error) return "listo";
  const status = error.status ?? 0;
  if (status === 0 || status >= 500 || status === 429) return "esperar";
  if (op.op === "del" && status === 404) return "listo";
  return "rechazado";
}

const claveCola = (dueno) => (DUENO_VALIDO.test(dueno ?? "") ? `${PREFIJO}${dueno}.personas-cola` : null);

export function leerCola(dueno) {
  const clave = claveCola(dueno);
  if (!clave) return [];
  try {
    const cola = JSON.parse(localStorage.getItem(clave) ?? "[]");
    return Array.isArray(cola) ? cola.filter((op) => op && typeof op.id === "string" && (op.op === "put" || op.op === "del")) : [];
  } catch { return []; }
}

export function guardarCola(dueno, cola) {
  const clave = claveCola(dueno);
  if (!clave) return false;
  try {
    if (cola.length) localStorage.setItem(clave, JSON.stringify(cola)); else localStorage.removeItem(clave);
    return true;
  } catch { return false; }
}

/** Manda la cola en orden con `enviar(op)`. Corta en el primer «esperar» (sin señal no tiene sentido seguir probando).
 * Devuelve { cola: lo que queda, rechazados: [{ op, error }] }. */
export async function vaciarCola(cola, enviar) {
  const rechazados = [];
  let i = 0;
  for (; i < cola.length; i += 1) {
    let error = null;
    try { await enviar(cola[i]); } catch (e) { error = e; }
    const r = resultadoDe(cola[i], error);
    if (r === "esperar") break;
    if (r === "rechazado") rechazados.push({ op: cola[i], error });
  }
  return { cola: cola.slice(i), rechazados };
}

// ---------- vCard ----------

const escaparV = (t) => String(t ?? "").replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/([,;])/g, "\\$1");

/** vCard 3.0 de todas (para importarlas a los contactos del teléfono). */
export function aVCard(personas) {
  return personas.map((p) => [
    "BEGIN:VCARD", "VERSION:3.0",
    `FN:${escaparV(p.nombre)}`,
    p.empresa ? `ORG:${escaparV(p.empresa)}` : null,
    p.cargo ? `TITLE:${escaparV(p.cargo)}` : null,
    linkedinValido(p.linkedin) ? `URL:${p.linkedin}` : null,
    [p.donde, p.charla_titulo, p.nota].some(Boolean)
      ? `NOTE:${escaparV([p.donde && `Nos conocimos: ${p.donde}`, p.charla_titulo && `Charla: ${p.charla_titulo}`, p.nota].filter(Boolean).join("\n"))}`
      : null,
    "END:VCARD",
  ].filter(Boolean).join("\r\n")).join("\r\n");
}
