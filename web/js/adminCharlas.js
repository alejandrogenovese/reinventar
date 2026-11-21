// Admin › Eventos › Charlas nuevas: agrupar por código, buscar, filtrar por track y paginar (reglas puras, sin DOM:
// se prueban con node --test en tests/js/adminCharlas.test.mjs).

export const VISIBLES_INICIAL = 10;
const OTROS = "Otros";

/** El track es el prefijo de letras del código (DAT301 → DAT); sin letras, «Otros». */
export const trackDe = (base) => /^[A-Za-z]+/.exec(String(base ?? ""))?.[0].toUpperCase() ?? OTROS;

const sinAcentos = (texto) => String(texto ?? "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

/** Una fila por código: si el mismo código llega repetido se suman los horarios y queda el primero. Mantiene el orden de llegada. */
export function agruparCharlas(nuevas) {
  const porCodigo = new Map();
  for (const c of nuevas ?? []) {
    const previa = porCodigo.get(c.base);
    if (!previa) {
      porCodigo.set(c.base, { base: c.base, titulo: c.titulo, alta: c.alta, primero: c.primero, horarios: c.horarios ?? 1, track: trackDe(c.base) });
      continue;
    }
    porCodigo.set(c.base, { ...previa, horarios: previa.horarios + (c.horarios ?? 1),
      primero: [previa.primero, c.primero].filter(Boolean).sort()[0] ?? null });
  }
  return [...porCodigo.values()];
}

/** [[track, cantidad], …]: alfabético y «Otros» al final. */
export function tracksDe(filas) {
  const cuenta = new Map();
  for (const f of filas) cuenta.set(f.track, (cuenta.get(f.track) ?? 0) + 1);
  return [...cuenta].sort(([a], [b]) => (a === OTROS) - (b === OTROS) || a.localeCompare(b));
}

/** Filtra por track y por texto (código o título, sin acentos ni mayúsculas). */
export function filtrarCharlas(filas, { texto = "", track = null } = {}) {
  const q = sinAcentos(texto).trim();
  return filas.filter((f) => (!track || f.track === track) && (!q || sinAcentos(`${f.base} ${f.titulo}`).includes(q)));
}

/** Las filas que se ven y cuántas quedan para «Ver las N restantes». */
export function visibles(filas, todas) {
  if (todas || filas.length <= VISIBLES_INICIAL) return { filas, restantes: 0 };
  return { filas: filas.slice(0, VISIBLES_INICIAL), restantes: filas.length - VISIBLES_INICIAL };
}
