// Conversiones del conversor (web/js/unidades.js): funciones puras, sin DOM ni red.
import assert from "node:assert/strict";
import test from "node:test";
import {
  ATAJOS_COMIDA, PARES, TALLES, UNIDADES, buscarTalle, calcularPropina, conUnidad, convertir, convertirDetectada, discos,
  parsearNumero, resultadoDe, textoAtajo, tiraClima, unidadConocida, usdAArs,
} from "../../web/js/unidades.js";

const cerca = (a, b, tolerancia = 1e-9) => assert.ok(Math.abs(a - b) < tolerancia, `${a} ≠ ${b}`);

test("−40 °F es −40 °C, y vuelve", () => {
  cerca(convertir(-40, "F", "C"), -40);
  cerca(convertir(-40, "C", "F"), -40);
  cerca(convertir(212, "F", "C"), 100);
  cerca(convertir(37, "C", "F"), 98.6, 1e-6);
});

test("parsearNumero acepta coma o punto decimal y el signo menos", () => {
  assert.equal(parsearNumero("72,5"), 72.5);
  assert.equal(parsearNumero("72.5"), 72.5);
  assert.equal(parsearNumero(" -40 "), -40);
  assert.equal(parsearNumero("−40"), -40);
  assert.equal(parsearNumero("1.234,5"), 1234.5);
  assert.equal(parsearNumero("1,234.5"), 1234.5);
  assert.equal(parsearNumero("1.234.567"), 1234567);
  assert.equal(parsearNumero(",5"), 0.5);
});

test("parsearNumero devuelve null con lo que no es número", () => {
  for (const malo of ["", "abc", "12a", "-", ",", "1-2", "1_000", "1e3", "0x10", "1.234.5", "1,23,4", "Infinity", null, undefined,
    Number.NaN, Number.POSITIVE_INFINITY, {}, []]) assert.equal(parsearNumero(malo), null, String(malo));
});

test("parsearNumero: miles con punto o coma en grupos de 3; si no, el separador es decimal", () => {
  assert.equal(parsearNumero("1,234"), 1234);
  assert.equal(parsearNumero("1.234"), 1234);
  assert.equal(parsearNumero("12.345"), 12345);
  assert.equal(parsearNumero("0,750"), 0.75);      // con 0 adelante no son miles
  assert.equal(parsearNumero("1234,5"), 1234.5);
  assert.equal(parsearNumero("1,5"), 1.5);
  assert.equal(parsearNumero("1,2345"), 1.2345);  // 4 cifras: decimal
});

test("convertir: peso, volumen, largo y velocidad", () => {
  cerca(convertir(1, "lb", "kg"), 0.45359237);
  cerca(convertir(16, "oz", "g"), 453.59237);
  cerca(convertir(1, "gal", "l"), 3.785411784);
  cerca(convertir(1, "mi", "km"), 1.609344);
  cerca(convertir(1, "in", "cm"), 2.54);
  cerca(convertir(60, "mph", "kmh"), 96.56064);
  cerca(convertir(100, "kg", "lb"), 220.46226218487757);
});

test("convertir devuelve null entre dimensiones distintas o unidades que no existen", () => {
  assert.equal(convertir(1, "lb", "ml"), null);
  assert.equal(convertir(1, "F", "kg"), null);
  assert.equal(convertir(1, "piedra", "kg"), null);
  assert.equal(convertir(1, "constructor", "toString"), null);
  assert.equal(convertir(1, "__proto__", "__proto__"), null);
});

test("convertir devuelve null si el resultado no es finito", () => {
  assert.equal(convertir(Number.MAX_VALUE, "mi", "cm"), null);
  assert.equal(convertir(Number.MAX_VALUE, "C", "F"), null);
  assert.equal(usdAArs(Number.MAX_VALUE, 1885), null);
});

test("todos los pares de las pestañas son convertibles", () => {
  for (const [de, a] of Object.values(PARES).flat()) {
    assert.ok(UNIDADES[de] && UNIDADES[a], `${de}/${a}`);
    assert.notEqual(convertir(1, de, a), null, `${de}→${a}`);
  }
});

test("resultadoDe: vacío sin error, inválido sin resultado y con ayuda, válido con coma decimal", () => {
  assert.deepEqual(resultadoDe("", "F", "C"), { resultado: "", error: "" });
  const malo = resultadoDe("hola", "F", "C");
  assert.equal(malo.resultado, "");
  assert.match(malo.error, /número/);
  assert.equal(resultadoDe("72,5", "F", "C").resultado, "22,5 °C");
  assert.equal(resultadoDe("-40", "F", "C").resultado, "-40 °C");
});

test("atajos de comida: 16 oz steak = 454 g", () => {
  assert.equal(textoAtajo(ATAJOS_COMIDA[0]), "16 oz steak = 454 g");
  assert.ok(ATAJOS_COMIDA.every((a) => convertir(a.valor, a.de, a.a) != null));
});

test("tira del clima de 60 a 95 °F", () => {
  const tira = tiraClima();
  assert.deepEqual(tira.map((t) => t.f), [60, 65, 70, 75, 80, 85, 90, 95]);
  assert.deepEqual(tira[0], { f: 60, c: 16 });
  assert.deepEqual(tira.at(-1), { f: 95, c: 35 });
});

test("discos de 45, 35, 25 y 10 lb en kg", () => {
  assert.deepEqual(discos(), [{ lb: 45, kg: 20.4 }, { lb: 35, kg: 15.9 }, { lb: 25, kg: 11.3 }, { lb: 10, kg: 4.5 }]);
});

test("propina: impuesto de Clark County y propina sobre el subtotal", () => {
  assert.deepEqual(calcularPropina(100, 20), { subtotal: 100, impuesto: 8.38, propina: 20, total: 128.38 });
  assert.equal(calcularPropina(-1, 20), null);
  assert.equal(calcularPropina(Number.NaN, 20), null);
});

test("dólares a pesos con la tarjeta; sin cotización, null", () => {
  assert.equal(usdAArs(10, 1885), 18850);
  assert.equal(usdAArs(10, null), null);
  assert.equal(usdAArs(10, 0), null);
});

test("talles: encuentra la equivalencia con coma o punto y en cualquier sentido", () => {
  const calzado = TALLES.hombre.calzado;
  assert.deepEqual(buscarTalle(calzado, "us", "9"), { us: "9", eu: "42", ar: "41" });
  assert.deepEqual(buscarTalle(calzado, "us", "9,5"), { us: "9.5", eu: "42.5", ar: "41.5" });
  assert.equal(buscarTalle(calzado, "ar", "41").us, "9");
  assert.equal(buscarTalle(TALLES.mujer.ropa, "us", "m").ar, "L");
});

test("talles sin equivalencia devuelven null", () => {
  assert.equal(buscarTalle(TALLES.hombre.calzado, "us", "20"), null);
  assert.equal(buscarTalle(TALLES.hombre.ropa, "us", "XXXL"), null);
  assert.equal(buscarTalle(TALLES.mujer.calzado, "us", ""), null);
});

test("unidades leídas en la foto: alias y conversión al sistema métrico", () => {
  assert.equal(unidadConocida(" OZ "), "oz");
  assert.equal(unidadConocida("fl oz"), "floz");
  assert.equal(unidadConocida("parsecs"), null);
  assert.equal(convertirDetectada({ valor: 16, unidad: "oz" }), "16 oz = 454 g");
  assert.equal(convertirDetectada({ valor: "72", unidad: "°F" }), "72 °F = 22,2 °C");
  assert.equal(convertirDetectada({ valor: 25, unidad: "$" }, { tarjeta: 1885 }), "US$ 25 = $ 47.125");
  assert.equal(convertirDetectada({ valor: 25, unidad: "$" }), null);
  assert.equal(convertirDetectada({ valor: "muchos", unidad: "oz" }), null);
  for (const unidad of ["constructor", "__proto__", "toString", "hasOwnProperty", 16, null]) {
    assert.equal(unidadConocida(unidad), null, String(unidad));
    assert.equal(convertirDetectada({ valor: 1, unidad }), null, String(unidad));
  }
  assert.equal(convertirDetectada({ valor: Number.MAX_VALUE, unidad: "mi" }), null);
  assert.equal(convertirDetectada({ valor: Number.MAX_VALUE, unidad: "$" }, { tarjeta: 1885 }), null);
  assert.equal(conUnidad(0.5, "kg"), "0,5 kg");
});
