// Conversor › «Leer con la cámara» según la red y el kill switch (web/js/sinSenal.js).
import assert from "node:assert/strict";
import test from "node:test";
import { MSG_FOTO_SIN_SENAL, estadoLecturaFoto } from "../../web/js/sinSenal.js";

test("oculta si el servidor la tiene apagada o todavía no se sabe", () => {
  assert.equal(estadoLecturaFoto({ habilitada: false, enLinea: true }), "oculto");
  assert.equal(estadoLecturaFoto({ habilitada: null, enLinea: false }), "oculto");
});

test("prendida y sin señal: deshabilitada con el texto que manda al conversor manual o a Texto en Vivo / Google Lens", () => {
  assert.equal(estadoLecturaFoto({ habilitada: true, enLinea: false }), "sin-senal");
  assert.equal(MSG_FOTO_SIN_SENAL, "La lectura con cámara necesita señal. Usá el conversor de arriba o Texto en Vivo / Google Lens");
});

test("prendida y con red: lista", () => {
  assert.equal(estadoLecturaFoto({ habilitada: true, enLinea: true }), "listo");
});
