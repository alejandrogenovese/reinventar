// Reglas puras del mail obligatorio y la recuperación de contraseña (web/js/mail.js) y su estado en el admin.
import test from "node:test";
import assert from "node:assert/strict";
import "./domMinimo.mjs";

const { normalizarEmail, pareceEmail, limpiarCodigo } = await import("../../web/js/mail.js");
const { textoMail } = await import("../../web/js/adminTextos.js");

test("el mail se normaliza como en el servidor: sin espacios y en minúsculas", () => {
  assert.equal(normalizarEmail("  Ana.Perez@Ejemplo.COM "), "ana.perez@ejemplo.com");
  assert.equal(normalizarEmail(null), "");
});

test("acepta mails con forma razonable", () => {
  for (const ok of ["ana@ejemplo.com", " Ana@Ejemplo.com.ar ", "a+b@sub.dominio.io"]) assert.equal(pareceEmail(ok), true, ok);
});

test("rechaza lo que no tiene forma de mail", () => {
  for (const malo of ["", "ana", "ana@", "ana@ejemplo", "a b@ejemplo.com", "a@@ejemplo.com", "a@ejemplo.c"]) assert.equal(pareceEmail(malo), false, malo);
});

test("el código pegado con espacios o guiones queda en sus 6 dígitos", () => {
  assert.equal(limpiarCodigo("123 456"), "123456");
  assert.equal(limpiarCodigo("123-4567"), "123456");
  assert.equal(limpiarCodigo(undefined), "");
});

test("el admin ve si el mail está verificado", () => {
  assert.equal(textoMail({ email: "ana@ejemplo.com", email_verificado_at: 1 }), "Mail: ana@ejemplo.com (verificado)");
  assert.equal(textoMail({ email: null, email_verificado_at: null }), "Mail: sin verificar todavía");
});
