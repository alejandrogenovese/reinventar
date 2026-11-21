// Lógica pura de gastosCola.js (sin IndexedDB ni DOM): estimar USD, leer montos, achicar fotos, mezclar con el servidor y sumar.
import assert from "node:assert/strict";
import test from "node:test";
import {
  CATEGORIAS, aCambio, borrarGasto, crearGasto, editarGasto, escalarLado, estimarUsd, fechaLocal, marcarAplicado, mezclarServidor,
  parsearMonto, partirEnLotes, reemplazarPerdido, totales, visibles,
} from "../../web/js/gastosCola.js";

const AHORA = "2026-12-01T10:00:00.000Z";
const base = { fecha: "2026-12-01", monto: 14.1, moneda: "USD", categoria: "comida", nota: "Café", reintegrable: true, compartido: false };

test("las cinco categorías del contrato", () => {
  assert.deepEqual(CATEGORIAS, ["comida", "transporte", "shows", "compras", "otros"]);
});

test("estimarUsd deja los dólares como están y pasa los pesos con la cotización de tarjeta", () => {
  assert.equal(estimarUsd(10, "USD", 1358), 10);
  assert.equal(estimarUsd(13580, "ARS", 1358), 10);
});

test("estimarUsd devuelve null para pesos sin cotización", () => {
  assert.equal(estimarUsd(500, "ARS", null), null);
  assert.equal(estimarUsd(500, "ARS", 0), null);
});

test("parsearMonto entiende coma decimal y puntos de miles", () => {
  assert.equal(parsearMonto("14,10"), 14.1);
  assert.equal(parsearMonto("1.234,50"), 1234.5);
  assert.equal(parsearMonto("19.150"), 19150);
  assert.equal(parsearMonto("14.10"), 14.1);
  assert.equal(parsearMonto(" 52 "), 52);
});

test("parsearMonto rechaza lo que no es un monto positivo", () => {
  for (const malo of ["", "abc", "0", "-5", "1,2,3", "NaN"]) assert.ok(Number.isNaN(parsearMonto(malo)), malo);
});

test("escalarLado achica al lado mayor sin deformar y no agranda", () => {
  assert.deepEqual(escalarLado(4000, 3000, 1600), { ancho: 1600, alto: 1200 });
  assert.deepEqual(escalarLado(3000, 4000, 1600), { ancho: 1200, alto: 1600 });
  assert.deepEqual(escalarLado(800, 600, 1600), { ancho: 800, alto: 600 });
});

test("crearGasto arma un gasto pendiente con client_id y updated_at", () => {
  const g = crearGasto(base, { ahora: AHORA, id: "abc" });
  assert.equal(g.client_id, "abc");
  assert.equal(g.updated_at, AHORA);
  assert.equal(g.deleted_at, null);
  assert.equal(g.pendiente, true);
  assert.equal(g.reintegrable, true);
});

test("editarGasto y borrarGasto devuelven copias y dejan el original intacto", () => {
  const g = crearGasto(base, { ahora: AHORA, id: "abc" });
  const nuevo = editarGasto({ ...g, pendiente: false }, { nota: "Café doble" }, "2026-12-01T11:00:00.000Z");
  assert.equal(g.nota, "Café");
  assert.equal(nuevo.nota, "Café doble");
  assert.equal(nuevo.pendiente, true);
  assert.equal(nuevo.updated_at, "2026-12-01T11:00:00.000Z");
  const borrado = borrarGasto(g, "2026-12-01T12:00:00.000Z");
  assert.equal(g.deleted_at, null);
  assert.equal(borrado.deleted_at, "2026-12-01T12:00:00.000Z");
  assert.equal(borrado.pendiente, true);
});

test("aCambio manda solo los campos del contrato", () => {
  const g = { ...crearGasto(base, { ahora: AHORA, id: "abc" }), monto_usd: 14.1, foto_url: null, cotizacion_tarjeta: 1358 };
  assert.deepEqual(Object.keys(aCambio(g)).sort(),
    ["categoria", "client_id", "compartido", "deleted_at", "fecha", "moneda", "monto", "nota", "reintegrable", "updated_at"]);
});

test("marcarAplicado no pisa una edición hecha mientras viajaba el sync", () => {
  const enviado = crearGasto(base, { ahora: AHORA, id: "abc" });
  assert.equal(marcarAplicado(enviado, enviado).pendiente, false);
  const editado = editarGasto(enviado, { nota: "otra" }, "2026-12-01T10:00:05.000Z");
  assert.equal(marcarAplicado(editado, enviado).pendiente, true);
});

test("mezclarServidor no pisa un gasto pendiente ni uno local más nuevo", () => {
  const local = crearGasto(base, { ahora: AHORA, id: "abc" });
  const servidor = { ...base, client_id: "abc", updated_at: "2026-12-01T09:00:00.000Z", deleted_at: null, monto_usd: 14.1 };
  assert.equal(mezclarServidor(local, servidor), null);
  assert.equal(mezclarServidor({ ...local, pendiente: false }, servidor), null);
});

test("mezclarServidor guarda lo nuevo del servidor como sincronizado", () => {
  const servidor = { ...base, client_id: "xyz", updated_at: AHORA, deleted_at: null, monto_usd: 14.1 };
  const nuevo = mezclarServidor(undefined, servidor);
  assert.equal(nuevo.pendiente, false);
  assert.equal(nuevo.monto_usd, 14.1);
  const viejo = { ...servidor, pendiente: false, updated_at: "2026-12-01T08:00:00.000Z", nota: "vieja" };
  assert.equal(mezclarServidor(viejo, servidor).nota, "Café");
});

test("reemplazarPerdido pone la versión del servidor en el gasto que perdió el conflicto", () => {
  const enviado = crearGasto(base, { ahora: AHORA, id: "abc" });
  const servidor = { ...base, client_id: "abc", nota: "del servidor", updated_at: "2026-12-01T12:00:00.000Z", deleted_at: null, monto_usd: 14.1 };
  const nuevo = reemplazarPerdido(enviado, enviado, servidor);
  assert.equal(nuevo.nota, "del servidor");
  assert.equal(nuevo.pendiente, false);
});

test("reemplazarPerdido respeta lo que se editó mientras viajaba el sync", () => {
  const enviado = crearGasto(base, { ahora: AHORA, id: "abc" });
  const editado = editarGasto(enviado, { nota: "más nueva" }, "2026-12-01T10:00:05.000Z");
  const servidor = { ...base, client_id: "abc", updated_at: "2026-12-01T12:00:00.000Z" };
  assert.equal(reemplazarPerdido(editado, enviado, servidor), null);
  assert.equal(reemplazarPerdido(undefined, enviado, servidor), null);
});

test("partirEnLotes corta la lista en pedazos del tamaño pedido", () => {
  assert.deepEqual(partirEnLotes([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
  assert.deepEqual(partirEnLotes([], 200), []);
});

test("visibles oculta los borrados y ordena por fecha y hora, lo más nuevo primero", () => {
  const a = { client_id: "a", fecha: "2026-11-30", updated_at: "2026-11-30T10:00:00Z", deleted_at: null };
  const b = { client_id: "b", fecha: "2026-12-01", updated_at: "2026-12-01T09:00:00Z", deleted_at: null };
  const c = { client_id: "c", fecha: "2026-12-01", updated_at: "2026-12-01T10:00:00Z", deleted_at: null };
  const d = { client_id: "d", fecha: "2026-12-01", updated_at: "2026-12-01T11:00:00Z", deleted_at: "2026-12-01T12:00:00Z" };
  assert.deepEqual(visibles([a, b, c, d]).map((g) => g.client_id), ["c", "b", "a"]);
});

test("totales suma USD del servidor, estima los pesos y cuenta los que no tienen cotización", () => {
  const gastos = [
    { fecha: "2026-12-01", categoria: "comida", monto: 52, moneda: "USD", monto_usd: 52, deleted_at: null },
    { fecha: "2026-12-01", categoria: "comida", monto: 13580, moneda: "ARS", deleted_at: null },
    { fecha: "2026-11-30", categoria: "shows", monto: 100, moneda: "ARS", deleted_at: null },
    { fecha: "2026-11-30", categoria: "shows", monto: 160, moneda: "USD", deleted_at: "2026-12-01T00:00:00Z" },
  ];
  const t = totales(gastos, 1358);
  assert.ok(Math.abs(t.usd - (52 + 10 + 100 / 1358)) < 1e-9);
  assert.equal(t.porCategoria.comida, 62);
  assert.equal(t.porDia["2026-12-01"], 62);
  const sin = totales(gastos, null);
  assert.equal(sin.sinCotizacion, 2);
  assert.equal(sin.usd, 52);
});

test("fechaLocal da AAAA-MM-DD con los números del reloj local", () => {
  assert.equal(fechaLocal(new Date(2026, 11, 1, 23, 59)), "2026-12-01");
});
