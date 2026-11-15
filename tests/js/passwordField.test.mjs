// Pruebas del ojo para mostrar/ocultar la contraseña (node --test), con un DOM mínimo falso.
import test from "node:test";
import assert from "node:assert/strict";

class Nodo {
  constructor(tag) { this.tag = tag; this.nodeType = 1; this.attrs = {}; this.children = []; this.oyentes = {}; this.className = ""; this.type = ""; this.form = null; this.classList = { add: (c) => { this.className = `${this.className} ${c}`.trim(); } }; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "type") this.type = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(tipo, f) { (this.oyentes[tipo] ??= []).push(f); }
  removeEventListener(tipo, f) { this.oyentes[tipo] = (this.oyentes[tipo] ?? []).filter((x) => x !== f); }
  append(...hijos) { this.children.push(...hijos); }
  replaceChildren(...hijos) { this.children = hijos; }
  dispara(tipo) { for (const f of [...(this.oyentes[tipo] ?? [])]) f({ type: tipo, preventDefault() {} }); }
  hijos(tag) { return this.children.flatMap((c) => (c.tag === tag ? [c] : c.children ? c.hijos(tag) : [])); }
}
globalThis.document = { createElement: (tag) => new Nodo(tag), createElementNS: (_ns, tag) => new Nodo(tag) };
globalThis.window = new Nodo("window");

const { PasswordField, estadoOjo } = await import("../../web/js/ui.js");

const nuevoCampo = (id = "password", attrs = {}) => {
  const campo = PasswordField(id, "Contraseña", { autocomplete: "current-password", ...attrs });
  campo.input.form = new Nodo("form"); // el formulario que lo contiene (el campo se arma antes de colgarse de él)
  return { ...campo, ojo: campo.el.hijos("button")[0] };
};

// Como el campo de contraseña de Android (Material): el ícono muestra el estado (oculta → ojo tachado, visible → ojo
// abierto) y el lector de pantalla anuncia lo que hace el botón, con aria-pressed para el estado.
test("el ícono del ojo muestra el estado y la etiqueta dice qué va a hacer el botón", () => {
  assert.deepEqual(estadoOjo(false), { tipo: "password", etiqueta: "Mostrar contraseña", pulsado: "false", icono: "ojoTachado" });
  assert.deepEqual(estadoOjo(true), { tipo: "text", etiqueta: "Ocultar contraseña", pulsado: "true", icono: "ojo" });
});

test("arranca oculta y el botón no envía el formulario ni tapa el id, el name y el autocomplete del input", () => {
  const { input, ojo } = nuevoCampo("password", { name: "password" });
  assert.equal(input.type, "password");
  assert.equal(input.getAttribute("id"), "password");
  assert.equal(input.getAttribute("name"), "password");
  assert.equal(input.getAttribute("autocomplete"), "current-password");
  assert.equal(ojo.getAttribute("type"), "button");
  assert.equal(ojo.getAttribute("aria-label"), "Mostrar contraseña");
  assert.equal(ojo.getAttribute("aria-pressed"), "false");
});

test("sin name explícito, el name es el id (como los demás campos de la cuenta)", () => {
  assert.equal(nuevoCampo("next").input.getAttribute("name"), "next");
});

test("tocar el ojo muestra la contraseña y tocarlo de nuevo la oculta", () => {
  const { input, ojo } = nuevoCampo();
  ojo.dispara("click");
  assert.equal(input.type, "text");
  assert.equal(ojo.getAttribute("aria-label"), "Ocultar contraseña");
  assert.equal(ojo.getAttribute("aria-pressed"), "true");
  ojo.dispara("click");
  assert.equal(input.type, "password");
  assert.equal(ojo.getAttribute("aria-label"), "Mostrar contraseña");
  assert.equal(ojo.getAttribute("aria-pressed"), "false");
});

test("al enviar el formulario vuelve a password (el navegador no la guarda como texto)", () => {
  const { input, ojo } = nuevoCampo();
  ojo.dispara("click");
  assert.equal(input.type, "text");
  input.form.dispara("submit");
  assert.equal(input.type, "password");
  assert.equal(ojo.getAttribute("aria-pressed"), "false");
});

test("al salir de la pantalla (cambio de ruta o cierre de la página) vuelve a password", () => {
  for (const evento of ["hashchange", "pagehide"]) {
    const { input, ojo } = nuevoCampo();
    ojo.dispara("click");
    window.dispara(evento);
    assert.equal(input.type, "password", evento);
  }
});

test("al volver a ocultar no quedan oyentes colgados en la ventana", () => {
  const { ojo } = nuevoCampo();
  const antes = ["hashchange", "pagehide"].map((t) => (window.oyentes[t] ?? []).length);
  ojo.dispara("click");
  ojo.dispara("click");
  assert.deepEqual(["hashchange", "pagehide"].map((t) => (window.oyentes[t] ?? []).length), antes);
});

test("en el cambio de contraseña cada campo tiene su ojo independiente", () => {
  const actual = nuevoCampo("current");
  const nueva = nuevoCampo("next");
  const repetir = nuevoCampo("repeat");
  nueva.ojo.dispara("click");
  assert.deepEqual([actual.input.type, nueva.input.type, repetir.input.type], ["password", "text", "password"]);
  assert.deepEqual([actual.ojo, nueva.ojo, repetir.ojo].map((o) => o.getAttribute("aria-pressed")), ["false", "true", "false"]);
});
