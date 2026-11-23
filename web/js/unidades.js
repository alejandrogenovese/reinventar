// Conversiones del conversor (#/viaje/conversor): funciones puras, sin DOM ni red, así andan sin señal y se prueban con
// node (tests/js/unidades.test.mjs). La pantalla está en conversor.js y la lectura con cámara en conversorFoto.js.

/** Impuesto de venta de Clark County (Las Vegas), en %. */
export const IMPUESTO_CLARK = 8.375;
export const PROPINAS = [18, 20, 22];
export const DISCOS_LB = [45, 35, 25, 10];

/** Cada unidad con su dimensión y cuánto vale en la unidad base (g, ml, m, km/h). La temperatura va aparte. */
export const UNIDADES = {
  F: { dim: "temperatura", nombre: "°F" },
  C: { dim: "temperatura", nombre: "°C" },
  oz: { dim: "peso", factor: 28.349523125, nombre: "oz" },
  lb: { dim: "peso", factor: 453.59237, nombre: "lb" },
  g: { dim: "peso", factor: 1, nombre: "g" },
  kg: { dim: "peso", factor: 1000, nombre: "kg" },
  floz: { dim: "volumen", factor: 29.5735295625, nombre: "fl oz" },
  cup: { dim: "volumen", factor: 236.5882365, nombre: "cup" },
  pint: { dim: "volumen", factor: 473.176473, nombre: "pint" },
  gal: { dim: "volumen", factor: 3785.411784, nombre: "gallon" },
  ml: { dim: "volumen", factor: 1, nombre: "ml" },
  l: { dim: "volumen", factor: 1000, nombre: "l" },
  in: { dim: "largo", factor: 0.0254, nombre: "in" },
  ft: { dim: "largo", factor: 0.3048, nombre: "ft" },
  yd: { dim: "largo", factor: 0.9144, nombre: "yd" },
  mi: { dim: "largo", factor: 1609.344, nombre: "mi" },
  cm: { dim: "largo", factor: 0.01, nombre: "cm" },
  m: { dim: "largo", factor: 1, nombre: "m" },
  km: { dim: "largo", factor: 1000, nombre: "km" },
  mph: { dim: "velocidad", factor: 1.609344, nombre: "mph" },
  kmh: { dim: "velocidad", factor: 1, nombre: "km/h" },
};

/** Los pares [de, a] que ofrece cada pestaña de unidades (el ⇄ los invierte). */
export const PARES = {
  clima: [["F", "C"]],
  comida: [["oz", "g"], ["lb", "g"], ["floz", "ml"], ["cup", "ml"], ["pint", "ml"], ["gal", "l"]],
  gym: [["lb", "kg"]],
  distancia: [["mi", "km"], ["ft", "m"], ["yd", "m"], ["in", "cm"], ["mph", "kmh"]],
};

export const ATAJOS_COMIDA = [
  { etiqueta: "16 oz steak", valor: 16, de: "oz", a: "g" },
  { etiqueta: "8 oz steak", valor: 8, de: "oz", a: "g" },
  { etiqueta: "1 lb", valor: 1, de: "lb", a: "g" },
  { etiqueta: "12 fl oz lata", valor: 12, de: "floz", a: "ml" },
  { etiqueta: "1 pint cerveza", valor: 1, de: "pint", a: "ml" },
  { etiqueta: "1 cup", valor: 1, de: "cup", a: "ml" },
];

/**
 * Lee un número escrito a mano: acepta coma o punto decimal («72,5» y «72.5»), signo menos y separador de miles cuando
 * hay los dos («1.234,5») o el mismo se repite («1.234.567»). Devuelve null si no es un número.
 * @param {unknown} texto
 * @returns {number | null}
 */
export function parsearNumero(texto) {
  if (typeof texto === "number") return Number.isFinite(texto) ? texto : null;
  const limpio = String(texto ?? "").trim().replace(/\s+/g, "").replace(/^[−–]/, "-").replace(/^\+/, "");
  if (!/^-?[\d.,]*\d[\d.,]*$/.test(limpio)) return null;
  const ultimo = Math.max(limpio.lastIndexOf("."), limpio.lastIndexOf(","));
  const separadores = limpio.match(/[.,]/g) ?? [];
  const mismoRepetido = separadores.length > 1 && new Set(separadores).size === 1;
  const normal = mismoRepetido
    ? limpio.replace(/[.,]/g, "")
    : ultimo < 0 ? limpio : `${limpio.slice(0, ultimo).replace(/[.,]/g, "")}.${limpio.slice(ultimo + 1)}`;
  const n = Number(normal);
  return Number.isFinite(n) ? n : null;
}

const temperatura = (valor, de, a) => {
  if (de === a) return valor;
  return de === "F" ? ((valor - 32) * 5) / 9 : (valor * 9) / 5 + 32;
};

/**
 * Convierte entre dos unidades de la misma dimensión. null si alguna no existe, no son compatibles o el valor no es número.
 * @param {number} valor
 * @param {string} de
 * @param {string} a
 * @returns {number | null}
 */
export function convertir(valor, de, a) {
  const u1 = UNIDADES[de];
  const u2 = UNIDADES[a];
  if (!u1 || !u2 || u1.dim !== u2.dim || !Number.isFinite(valor)) return null;
  if (u1.dim === "temperatura") return temperatura(valor, de, a);
  return (valor * u1.factor) / u2.factor;
}

/** Decimales razonables para mostrar: gramos y mililitros enteros; el resto según el tamaño. */
export function decimalesPara(valor, unidad) {
  if (unidad === "g" || unidad === "ml") return 0;
  const abs = Math.abs(valor);
  if (abs >= 100) return 0;
  return abs >= 10 ? 1 : 2;
}

/** Número en formato argentino (coma decimal), sin ceros de más. */
export function formatear(valor, decimales = 2) {
  return valor.toLocaleString("es-AR", { maximumFractionDigits: decimales, minimumFractionDigits: 0 });
}

/** «454 g», «−40 °C». */
export function conUnidad(valor, unidad) {
  return `${formatear(valor, decimalesPara(valor, unidad))} ${UNIDADES[unidad]?.nombre ?? unidad}`;
}

/**
 * Lo que muestra el conversor para lo que se escribió: { resultado: "454 g" } o { error } si no es un número.
 * Vacío no es error: la pantalla queda en blanco hasta que se escribe algo.
 */
export function resultadoDe(texto, de, a) {
  if (String(texto ?? "").trim() === "") return { resultado: "", error: "" };
  const valor = parsearNumero(texto);
  const r = valor == null ? null : convertir(valor, de, a);
  if (r == null) return { resultado: "", error: "Escribí un número, por ejemplo 72 o 72,5." };
  return { resultado: conUnidad(r, a), error: "" };
}

/** «16 oz steak = 454 g». */
export function textoAtajo({ etiqueta, valor, de, a }) {
  return `${etiqueta} = ${conUnidad(convertir(valor, de, a), a)}`;
}

/** Tira de referencia del clima: de 60 a 95 °F de a 5, con su °C redondeado. */
export function tiraClima(desde = 60, hasta = 95, paso = 5) {
  const filas = [];
  for (let f = desde; f <= hasta; f += paso) filas.push({ f, c: Math.round(temperatura(f, "F", "C")) });
  return filas;
}

/** Los discos del gym en kg, con un decimal. */
export function discos(lista = DISCOS_LB) {
  return lista.map((lb) => ({ lb, kg: Math.round(convertir(lb, "lb", "kg") * 10) / 10 }));
}

const centavos = (n) => Math.round(n * 100) / 100;

/**
 * Cuenta del restaurante: el impuesto va sobre el subtotal y la propina también (antes de impuestos, como se usa allá).
 * @returns {{ subtotal: number, impuesto: number, propina: number, total: number } | null}
 */
export function calcularPropina(subtotal, porcentaje, impuesto = IMPUESTO_CLARK) {
  if (!Number.isFinite(subtotal) || subtotal < 0 || !Number.isFinite(porcentaje)) return null;
  const imp = centavos((subtotal * impuesto) / 100);
  const propina = centavos((subtotal * porcentaje) / 100);
  return { subtotal: centavos(subtotal), impuesto: imp, propina, total: centavos(subtotal + imp + propina) };
}

/** Dólares a pesos con la cotización tarjeta. null sin cotización. */
export function usdAArs(usd, tarjeta) {
  if (!Number.isFinite(usd) || !(tarjeta > 0)) return null;
  return Math.round(usd * tarjeta);
}

// ---------- talles (aproximados) ----------

const filasCalzado = (desde, hasta, sumaEu) => {
  const filas = [];
  for (let us = desde; us <= hasta; us += 0.5) filas.push({ us: String(us), eu: String(us + sumaEu), ar: String(us + sumaEu - 1) });
  return filas;
};

/** Tablas de talles US ↔ AR / EU. Son aproximadas: cada marca corta distinto. */
export const TALLES = {
  hombre: {
    calzado: { titulo: "Calzado", filas: filasCalzado(6, 13, 33) },
    ropa: { titulo: "Remeras y camisas", filas: [
      { us: "XS", ar: "S", eu: "44" }, { us: "S", ar: "M", eu: "46" }, { us: "M", ar: "L", eu: "50" },
      { us: "L", ar: "XL", eu: "54" }, { us: "XL", ar: "XXL", eu: "58" }] },
    pantalon: { titulo: "Pantalón (cintura)", filas: [28, 30, 32, 34, 36, 38, 40].map((us) => ({ us: String(us), ar: String(us + 10), eu: String(us + 16) })) },
  },
  mujer: {
    calzado: { titulo: "Calzado", filas: filasCalzado(5, 10, 31) },
    ropa: { titulo: "Remeras y blusas", filas: [
      { us: "XS", ar: "S", eu: "34" }, { us: "S", ar: "M", eu: "36" }, { us: "M", ar: "L", eu: "40" },
      { us: "L", ar: "XL", eu: "42" }, { us: "XL", ar: "XXL", eu: "44" }] },
    numero: { titulo: "Ropa con número", filas: [0, 2, 4, 6, 8, 10, 12, 14].map((us) => ({ us: String(us), ar: String(us + 34), eu: String(us + 32) })) },
  },
};

const normalizarTalle = (valor) => {
  const n = parsearNumero(valor);
  return n == null ? String(valor ?? "").trim().toUpperCase() : String(n);
};

/**
 * La fila de la tabla donde el sistema `desde` (us, ar o eu) vale `valor`; null si ese talle no tiene equivalencia.
 * @returns {{ us: string, ar: string, eu: string } | null}
 */
export function buscarTalle(tabla, desde, valor) {
  const buscado = normalizarTalle(valor);
  if (!buscado || !tabla?.filas) return null;
  return tabla.filas.find((f) => normalizarTalle(f[desde]) === buscado) ?? null;
}

// ---------- unidades leídas con la cámara ----------

const ALIAS = {
  F: ["f", "°f", "ºf", "fahrenheit", "degf"], oz: ["oz", "ounce", "ounces", "onz"], lb: ["lb", "lbs", "pound", "pounds"],
  floz: ["floz", "fl oz", "fl. oz", "fl.oz", "fluid ounce", "fluid ounces"], cup: ["cup", "cups"], pint: ["pint", "pints", "pt"],
  gal: ["gal", "gallon", "gallons"], in: ["in", "inch", "inches", "\""], ft: ["ft", "feet", "foot", "'"], yd: ["yd", "yard", "yards"],
  mi: ["mi", "mile", "miles"], mph: ["mph", "mi/h"], usd: ["$", "usd", "us$", "dollar", "dollars"],
};
const POR_ALIAS = Object.fromEntries(Object.entries(ALIAS).flatMap(([clave, alias]) => alias.map((a) => [a, clave])));
/** A qué se pasa cada unidad estadounidense que aparece en una foto. */
export const DESTINO = { F: "C", oz: "g", lb: "kg", floz: "ml", cup: "ml", pint: "ml", gal: "l", in: "cm", ft: "m", yd: "m", mi: "km", mph: "kmh" };

/** La clave de la unidad («16 OZ» → oz, «$» → usd) o null si no la conocemos. */
export function unidadConocida(texto) {
  return POR_ALIAS[String(texto ?? "").trim().toLowerCase().replace(/\s+/g, " ")] ?? null;
}

/**
 * Convierte una unidad que leyó el LLM en la foto: «16 oz = 454 g», «US$ 25 = $ 47.125». null si no se puede.
 * @param {{ valor: unknown, unidad: unknown }} detectada
 * @param {{ tarjeta?: number | null }} [opciones]
 * @returns {string | null}
 */
export function convertirDetectada({ valor, unidad }, { tarjeta = null } = {}) {
  const n = parsearNumero(valor);
  const clave = unidadConocida(unidad);
  if (n == null || !clave) return null;
  if (clave === "usd") {
    const ars = usdAArs(n, tarjeta);
    return ars == null ? null : `US$ ${formatear(n, 2)} = $ ${formatear(ars, 0)}`;
  }
  const a = DESTINO[clave];
  return `${conUnidad(n, clave)} = ${conUnidad(convertir(n, clave, a), a)}`;
}
