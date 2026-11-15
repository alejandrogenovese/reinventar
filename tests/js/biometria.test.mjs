// Cómo se llama el desbloqueo biométrico en cada celular (node --test): «Face ID» solo en iPhone/iPad.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.window = { dispatchEvent() {}, addEventListener() {} };
globalThis.document = { createElement: () => ({}), getElementById: () => null };

const { etiquetaBiometria, textosBiometria } = await import("../../web/js/passkey.js");

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
const IPAD = "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
const ANDROID = "Mozilla/5.0 (Linux; Android 15; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36";
const MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15";

test("en iPhone y iPad dice Face ID", () => {
  assert.equal(etiquetaBiometria({ userAgent: IPHONE, platform: "iPhone", maxTouchPoints: 5 }), "Face ID");
  assert.equal(etiquetaBiometria({ userAgent: IPAD, platform: "iPad", maxTouchPoints: 5 }), "Face ID");
});

test("un iPad que se hace pasar por Mac (iPadOS, userAgent de escritorio) también dice Face ID", () => {
  assert.equal(etiquetaBiometria({ userAgent: MAC, platform: "MacIntel", maxTouchPoints: 5 }), "Face ID");
});

test("en Android dice huella o rostro", () => {
  assert.equal(etiquetaBiometria({ userAgent: ANDROID, platform: "Linux armv81", maxTouchPoints: 5 }), "huella o rostro");
});

test("en una Mac de escritorio (sin pantalla táctil) o sin datos del navegador, huella o rostro", () => {
  assert.equal(etiquetaBiometria({ userAgent: MAC, platform: "MacIntel", maxTouchPoints: 0 }), "huella o rostro");
  assert.equal(etiquetaBiometria({}), "huella o rostro");
  assert.equal(etiquetaBiometria(undefined), "huella o rostro");
});

test("los textos de la pantalla usan la etiqueta y no dejan «Face ID / huella» en Android", () => {
  const android = textosBiometria({ userAgent: ANDROID, platform: "Linux armv81", maxTouchPoints: 5 });
  assert.equal(android.boton, "Entrar con huella o rostro");
  assert.equal(android.oferta, "Entrá con huella o rostro");
  assert.equal(android.ajustes, "Huella o rostro");
  assert.equal(android.activado, "Listo: la próxima entrás con huella o rostro");
  assert.ok(Object.values(android).every((t) => !/Face ID/.test(t)), JSON.stringify(android));
  const iphone = textosBiometria({ userAgent: IPHONE, platform: "iPhone", maxTouchPoints: 5 });
  assert.equal(iphone.boton, "Entrar con Face ID");
  assert.equal(iphone.oferta, "Entrá con Face ID");
  assert.equal(iphone.ajustes, "Face ID");
  assert.ok(Object.values(iphone).every((t) => !/huella/.test(t)), JSON.stringify(iphone));
});
