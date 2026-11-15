// Pruebas de las grabaciones locales en Inicio (node --test): lo que se grabó sin señal no se pierde de vista.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { cargarLocales, fichaLocal } = await import("../../web/js/locales.js");

test("cada estado se ve con su pastilla y su texto", () => {
  assert.deepEqual(
    ["grabando", "pendiente_de_subir", "esperando_senal"].map((estado) => {
      const { status, texto } = fichaLocal({ id: "loc_1", title: "x", estado, at: 1 });
      return [status, texto];
    }),
    [["recording", "Grabando"], ["uploading", "Pendiente de subir"], ["queued", "Esperando señal para procesar"]],
  );
});

test("una grabación ya terminada no es un link: #/grabar/<id> la mandaría al inicio", () => {
  assert.equal(fichaLocal({ id: "loc_1", title: "x", estado: "esperando_senal", at: 1 }).href, null);
  assert.equal(fichaLocal({ id: "loc_1", title: "x", estado: "pendiente_de_subir", at: 1 }).href, "#/grabar/loc_1");
});

test("si la sesión quedó trabada con un error, va con la pastilla de error y el motivo", () => {
  const f = fichaLocal({ id: "loc_1", title: "x", estado: "pendiente_de_subir", at: 1, error: "El servidor rechazó la sesión" });
  assert.equal(f.status, "error");
  assert.equal(f.texto, "Error");
  assert.equal(f.detalle, "El servidor rechazó la sesión");
  assert.equal(fichaLocal({ id: "loc_1", title: "x", estado: "grabando", at: 1 }).detalle, null);
});

test("tocar la tarjeta lleva a grabar con el id local", () => {
  assert.equal(fichaLocal({ id: "loc_ab12", title: "x", estado: "grabando", at: 1 }).href, "#/grabar/loc_ab12");
});

test("un estado que no conozco no rompe: se muestra como pendiente", () => {
  const f = fichaLocal({ id: "loc_1", title: "x", estado: "algo_nuevo", at: 1 });
  assert.equal(f.status, "queued");
  assert.equal(f.texto, "Pendiente");
});

test("sin título se muestra un nombre genérico, no «undefined»", () => {
  assert.equal(fichaLocal({ id: "loc_1", estado: "grabando", at: 1 }).title, "Grabación sin conexión");
  assert.equal(fichaLocal({ id: "loc_1", title: "  ", estado: "grabando", at: 1 }).title, "Grabación sin conexión");
});

test("sin la función de store.js (todavía no está mergeada) devuelve vacío sin error", async () => {
  assert.deepEqual(await cargarLocales({}), []);
});

test("si store.js falla, Inicio sigue y simplemente no muestra locales", async () => {
  const roto = { sesionesLocalesPendientes: async () => { throw new Error("IndexedDB no anda"); } };
  assert.deepEqual(await cargarLocales(roto), []);
});

test("lo que no es un array o no tiene id se descarta", async () => {
  assert.deepEqual(await cargarLocales({ sesionesLocalesPendientes: async () => null }), []);
  const store = { sesionesLocalesPendientes: async () => [{ title: "sin id", estado: "grabando", at: 1 }] };
  assert.deepEqual(await cargarLocales(store), []);
});

test("las más nuevas van primero", async () => {
  const store = { sesionesLocalesPendientes: async () => [
    { id: "loc_a", title: "A", estado: "pendiente_de_subir", at: 100 },
    { id: "loc_b", title: "B", estado: "grabando", at: 300 },
    { id: "loc_c", title: "C", estado: "esperando_senal", at: 200 },
  ] };
  assert.deepEqual((await cargarLocales(store)).map((f) => f.id), ["loc_b", "loc_c", "loc_a"]);
});
