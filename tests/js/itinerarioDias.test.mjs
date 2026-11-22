// Fechas legibles del itinerario: el día llega como 'YYYY-MM-DD' de Las Vegas y no se corre por la zona horaria.
import assert from "node:assert/strict";
import test from "node:test";

const { shortDay, longDay } = await import("../../web/js/itinerary.js");

test("la pestaña del día muestra «lun 30 nov» y no la fecha cruda", () => {
  assert.equal(shortDay("2026-11-30"), "lun 30 nov");
  assert.equal(shortDay("2026-12-04"), "vie 4 dic");
});

test("el encabezado para lector de pantalla dice el día completo", () => {
  assert.equal(longDay("2026-11-30"), "lunes 30 de noviembre");
  assert.equal(longDay("2026-12-01"), "martes 1 de diciembre");
});

test("una fecha vacía no rompe", () => {
  assert.equal(longDay(""), "");
});

test("el día no se corre con otras zonas horarias", () => {
  for (const tz of ["America/Los_Angeles", "Pacific/Auckland"]) {
    const v = process.env.TZ; process.env.TZ = tz;
    assert.equal(longDay("2026-11-30"), "lunes 30 de noviembre");
    process.env.TZ = v ?? "";
  }
});
