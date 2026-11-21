// Textos y reglas puras del admin (node --test): nombres legibles, estados en castellano y a qué campo va un error.
import test from "node:test";
import assert from "node:assert/strict";

const { nombreTarea, resumenEstados, resumenChequeo, campoDelError, pestanaDeHash, textoCortarAccesos, TEXTO_CHEQUEO, PESTANAS } =
  await import("../../web/js/adminTextos.js");

test("las tareas del LLM se muestran con nombre legible y las desconocidas quedan como vienen", () => {
  assert.equal(nombreTarea("catalogo"), "Catálogo (scripts)");
  assert.equal(nombreTarea("stt-charlas"), "Transcripción de charlas");
  assert.equal(nombreTarea("rx-resumen"), "Resumen de grabaciones");
  assert.equal(nombreTarea("algo-nuevo"), "algo-nuevo");
});

test("los estados de grabación van en castellano, con el error al final", () => {
  assert.equal(resumenEstados({ ready: 2 }), "2 listas");
  assert.equal(resumenEstados({ error: 1, ready: 3, queued: 1 }), "3 listas · 1 en cola · 1 con error");
  assert.equal(resumenEstados({}), "");
  assert.equal(resumenEstados({ rarisimo: 2 }), "2 rarisimo");
});

test("el resumen del chequeo cuenta lo que anda y lo que falla", () => {
  assert.equal(resumenChequeo([{ ok: true }, { ok: true }, { ok: false }]), "2 bien · 1 con falla");
  assert.equal(resumenChequeo([{ ok: true }]), "1 bien · 0 con falla");
  assert.equal(resumenChequeo([{ ok: false }, { ok: false }]), "0 bien · 2 con falla");
});

test("el chequeo no promete no gastar en APIs: avisa que llama a Google Routes", () => {
  assert.doesNotMatch(TEXTO_CHEQUEO, /sin gastar/);
  assert.match(TEXTO_CHEQUEO, /Google Routes/);
});

test("un error de alta de usuario va al campo que corresponde", () => {
  assert.equal(campoDelError({ status: 409, message: "Ese usuario ya existe" }), "usuario");
  assert.equal(campoDelError({ status: 422, message: "Usuario: 2 a 40 caracteres, solo minúsculas" }), "usuario");
  assert.equal(campoDelError({ status: 422, message: "La contraseña necesita 8 caracteres" }), "password");
  assert.equal(campoDelError({ status: 500, message: "boom" }), "password");
});

test("la pestaña sale de la ruta y #/admin es Estado", () => {
  assert.equal(pestanaDeHash("#/admin"), "estado");
  assert.equal(pestanaDeHash("#/admin/usuarios"), "usuarios");
  assert.equal(pestanaDeHash("#/admin/llm"), "llm");
  assert.deepEqual(PESTANAS.map(([id]) => id), ["estado", "usuarios", "eventos", "ofertas", "llm"]);
});

test("cerrar sesiones dice todo lo que borra de verdad", () => {
  const t = textoCortarAccesos("ana");
  for (const parte of ["sesiones", "passkeys", "notificaciones", "sede reciente", "ana"]) assert.match(t, new RegExp(parte));
});
