// «Personas que conocí» y «También van» (node --test): validación, búsqueda, cola sin señal, vCard y el renglón del grupo.
import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";

const memoria = new Map();
await import("./domMinimo.mjs");  // deja document y window; el localStorage de abajo lo reemplaza por uno con memoria
globalThis.localStorage = {
  getItem: (k) => (memoria.has(k) ? memoria.get(k) : null),
  setItem: (k, v) => { memoria.set(k, String(v)); },
  removeItem: (k) => { memoria.delete(k); },
  key: (i) => [...memoria.keys()][i] ?? null,
  get length() { return memoria.size; },
};

const cola = await import("../../web/js/personasCola.js");
const { clearLast } = await import("../../web/js/lastgood.js");
const { TambienVan, listaDeNombres, tambienVanDe } = await import("../../web/js/grupo.js");

const DUENO = "0123456789ab";
const ana = { id: "a", nombre: "Ana Gómez", empresa: "Globant", cargo: "Arquitecta", linkedin: "https://www.linkedin.com/in/ana", donde: "Almuerzo", nota: "", charla_titulo: "" };
const beto = { id: "b", nombre: "Beto", empresa: "AWS", cargo: "", linkedin: "", donde: "", nota: "Bedrock", charla_titulo: "Agentes en producción" };

beforeEach(() => memoria.clear());

// ---------- validación ----------

test("linkedinValido acepta solo https://www.linkedin.com/", () => {
  assert.equal(cola.linkedinValido("https://www.linkedin.com/in/ana"), true);
  for (const malo of ["http://www.linkedin.com/in/ana", "https://linkedin.com/in/ana", "https://www.linkedin.com.evil.com/",
    "javascript:alert(1)", "https://www.linkedin.com/in/a b", `https://www.linkedin.com/${"a".repeat(200)}`, null]) {
    assert.equal(cola.linkedinValido(malo), false, malo);
  }
});

test("validarPersona pide nombre, respeta los largos y el LinkedIn", () => {
  assert.equal(cola.validarPersona(ana), null);
  assert.match(cola.validarPersona({ ...ana, nombre: "  " }), /nombre/);
  assert.match(cola.validarPersona({ ...ana, nota: "x".repeat(1001) }), /1000/);
  assert.match(cola.validarPersona({ ...ana, linkedin: "https://evil.com" }), /LinkedIn/);
  assert.equal(cola.validarPersona({ ...ana, linkedin: "" }), null);
});

test("aDatos deja solo los campos del contrato", () => {
  assert.deepEqual(Object.keys(cola.aDatos({ ...ana, pendiente: true, id: "x" })), cola.CAMPOS);
  assert.equal(cola.aDatos({ nombre: "X" }).charla_code, null);
});

// ---------- búsqueda ----------

test("filtrar busca sin tildes ni mayúsculas en todos los campos, con todas las palabras", () => {
  const todas = [ana, beto];
  assert.deepEqual(cola.filtrar(todas, ""), todas);
  assert.deepEqual(cola.filtrar(todas, "gomez"), [ana]);
  assert.deepEqual(cola.filtrar(todas, "BEDROCK"), [beto]);
  assert.deepEqual(cola.filtrar(todas, "agentes aws"), [beto]);
  assert.deepEqual(cola.filtrar(todas, "ana aws"), []);
});

// ---------- cola ----------

test("encolar deja solo la última operación de cada persona", () => {
  let c = cola.encolar([], { op: "put", id: "a", datos: ana, at: "1" });
  c = cola.encolar(c, { op: "put", id: "b", datos: beto, at: "2" });
  c = cola.encolar(c, { op: "del", id: "a", at: "3" });
  assert.deepEqual(c.map((x) => [x.op, x.id]), [["put", "b"], ["del", "a"]]);
});

test("aplicarCola muestra lo pendiente arriba, pisa ediciones y saca borrados", () => {
  const servidor = [ana, beto];
  const c = [{ op: "put", id: "n", datos: { nombre: "Nueva" }, at: "t" }, { op: "put", id: "b", datos: { nombre: "Beto editado" }, at: "t" }, { op: "del", id: "a", at: "t" }];
  const vista = cola.aplicarCola(servidor, c);
  assert.deepEqual(vista.map((p) => [p.id, p.nombre, Boolean(p.pendiente)]), [["b", "Beto editado", true], ["n", "Nueva", true]]);
});

test("resultadoDe: sin señal espera, 404 de un borrado ya está, 422 se rechaza", () => {
  const put = { op: "put", id: "a" };
  const del = { op: "del", id: "a" };
  assert.equal(cola.resultadoDe(put, null), "listo");
  assert.equal(cola.resultadoDe(put, { status: 0 }), "esperar");
  assert.equal(cola.resultadoDe(put, { status: 503 }), "esperar");
  assert.equal(cola.resultadoDe(put, { status: 429 }), "esperar");
  assert.equal(cola.resultadoDe(del, { status: 404 }), "listo");
  assert.equal(cola.resultadoDe(put, { status: 422 }), "rechazado");
});

test("vaciarCola corta sin señal y conserva lo que falta, en orden", async () => {
  const c = [{ op: "put", id: "a" }, { op: "put", id: "b" }, { op: "put", id: "c" }];
  const enviados = [];
  const r = await cola.vaciarCola(c, async (op) => { enviados.push(op.id); if (op.id === "b") throw { status: 0 }; });
  assert.deepEqual(enviados, ["a", "b"]);
  assert.deepEqual(r.cola.map((x) => x.id), ["b", "c"]);
  assert.deepEqual(r.rechazados, []);
});

test("vaciarCola saca los rechazados y sigue con el resto", async () => {
  const c = [{ op: "put", id: "a" }, { op: "put", id: "b" }];
  const r = await cola.vaciarCola(c, async (op) => { if (op.id === "a") throw { status: 422 }; });
  assert.deepEqual(r.cola, []);
  assert.deepEqual(r.rechazados.map((x) => x.op.id), ["a"]);
});

test("la cola es del dueño de la sesión y se borra al cerrar sesión", () => {
  const c = [{ op: "put", id: "a", datos: ana, at: "1" }];
  assert.equal(cola.guardarCola(DUENO, c), true);
  assert.deepEqual(cola.leerCola(DUENO), c);
  assert.deepEqual(cola.leerCola("fedcba987654"), []);  // otra cuenta en el mismo celular no la ve
  assert.equal(cola.guardarCola("no-es-un-dueño", c), false);
  clearLast();
  assert.deepEqual(cola.leerCola(DUENO), []);
});

test("leerCola ignora basura guardada", () => {
  localStorage.setItem(`reinventar.last.${DUENO}.personas-cola`, JSON.stringify([{ op: "rm", id: "a" }, null, { op: "put", id: 3 }, { op: "del", id: "b" }]));
  assert.deepEqual(cola.leerCola(DUENO), [{ op: "del", id: "b" }]);
  localStorage.setItem(`reinventar.last.${DUENO}.personas-cola`, "{roto");
  assert.deepEqual(cola.leerCola(DUENO), []);
});

test("guardar una cola vacía borra la clave", () => {
  cola.guardarCola(DUENO, [{ op: "del", id: "a", at: "1" }]);
  cola.guardarCola(DUENO, []);
  assert.equal(memoria.size, 0);
});

// ---------- vCard ----------

test("aVCard arma una tarjeta por persona y escapa comas, punto y coma y saltos", () => {
  const v = cola.aVCard([ana, { ...beto, empresa: "AWS; Inc, Arg", nota: "línea 1\nlínea 2" }]);
  assert.equal(v.match(/BEGIN:VCARD/g).length, 2);
  assert.match(v, /FN:Ana Gómez/);
  assert.match(v, /URL:https:\/\/www\.linkedin\.com\/in\/ana/);
  assert.match(v, /ORG:AWS\\; Inc\\, Arg/);
  assert.match(v, /NOTE:Charla: Agentes en producción\\nlínea 1\\nlínea 2/);
  assert.doesNotMatch(v, /URL:\r\n/);
});

test("aVCard no exporta un LinkedIn inválido", () => {
  assert.doesNotMatch(cola.aVCard([{ ...ana, linkedin: "javascript:alert(1)" }]), /URL:/);
});

// ---------- También van ----------

test("listaDeNombres arma la lista en castellano", () => {
  assert.equal(listaDeNombres(["ana"]), "ana");
  assert.equal(listaDeNombres(["ana", "beto"]), "ana y beto");
  assert.equal(listaDeNombres(["ana", "beto", "caro"]), "ana, beto y caro");
});

test("TambienVan no muestra nada si no va nadie más", () => {
  assert.equal(TambienVan(undefined), null);
  assert.equal(TambienVan([]), null);
  assert.equal(TambienVan(["ana", "beto"]).textContent, "También van: ana y beto");
});

test("tambienVanDe pide los códigos una vez y sin señal devuelve vacío", async () => {
  const pedidos = [];
  globalThis.fetch = async (url) => { pedidos.push(url); return { ok: true, status: 200, json: async () => ({ "A-1": ["ana"] }) }; };
  assert.deepEqual(await tambienVanDe(["A-1", "A-1", "A-2"]), { "A-1": ["ana"] });
  assert.deepEqual(pedidos, ["/api/grupo/tambien-van?codes=A-1,A-2"]);
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  assert.deepEqual(await tambienVanDe(["A-1"]), {});
  assert.deepEqual(await tambienVanDe([]), {});
});
