// «Requiere atención» del admin: reglas puras sobre los datos que ya devuelven los endpoints (node --test).
import test from "node:test";
import assert from "node:assert/strict";

const { atencion, nuevasUltimas24h, resumenKpiGrabaciones } = await import("../../web/js/adminAtencion.js");

const AHORA = Date.parse("2026-12-01T20:00:00Z");
const haceHoras = (h) => new Date(AHORA - h * 3600e3).toISOString();
const base = () => ({
  ahora: AHORA,
  grabaciones: { por_estado: { ready: 4 }, errores: [] },
  eventos: { activo: true, horas: 6, revisiones: [{ fuente: "luma", ok: true, revisado: haceHoras(1) }] },
  llm: { disponible: true, errores_semana: 0, mes: { unidades: 1000, limite_unidades: 50000 } },
  usuarios: [{ username: "ale", sandbox: null }],
});

test("sin nada raro no hay avisos y se puede decir «todo en orden»", () => {
  const r = atencion(base());
  assert.deepEqual(r.avisos, []);
  assert.equal(r.incompleto, false);
});

test("grabaciones con error: cuenta el estado y linkea a la más reciente", () => {
  const d = base();
  d.grabaciones = { por_estado: { ready: 3, error: 2 }, errores: [{ id: "abc", title: "Charla" }] };
  const [a] = atencion(d).avisos;
  assert.equal(a.id, "grabaciones");
  assert.equal(a.tono, "error");
  assert.equal(a.texto, "2 grabaciones con error");
  assert.equal(a.ruta, "#/s/abc");
});

test("una sola grabación con error va en singular", () => {
  const d = base();
  d.grabaciones = { por_estado: { error: 1 }, errores: [{ id: "x" }] };
  assert.equal(atencion(d).avisos[0].texto, "1 grabación con error");
});

test("fuente caída y fuente atrasada son avisos distintos", () => {
  const d = base();
  d.eventos.revisiones = [
    { fuente: "luma", ok: false, revisado: haceHoras(1) },
    { fuente: "links", ok: true, revisado: haceHoras(30) },
    { fuente: "conferenceparties", ok: true, revisado: haceHoras(2) },
  ];
  const textos = atencion(d).avisos.map((a) => a.texto);
  assert.deepEqual(textos, ["Luma falló en la última revisión", "Links cargados a mano sin revisar hace 1 día"]);
  assert.ok(atencion(d).avisos.every((a) => a.ruta === "#/admin/eventos"));
});

test("el catálogo se considera atrasado antes que las demás (se revisa cada 3 h)", () => {
  const d = base();
  d.eventos.revisiones = [{ fuente: "catalogo", ok: true, revisado: haceHoras(10) }];
  assert.equal(atencion(d).avisos.length, 1);
});

test("con los eventos automáticos apagados no se avisa de fuentes", () => {
  const d = base();
  d.eventos = { activo: false, horas: 6, revisiones: [{ fuente: "luma", ok: false, revisado: haceHoras(500) }] };
  assert.deepEqual(atencion(d).avisos, []);
});

test("errores del LLM y Langfuse arriba del 80 % avisan; justo en 80 % no", () => {
  const d = base();
  d.llm = { disponible: true, errores_semana: 3, mes: { unidades: 41000, limite_unidades: 50000 } };
  const avisos = atencion(d).avisos;
  assert.deepEqual(avisos.map((a) => a.texto), ["3 errores del LLM en 7 días", "Langfuse al 82 % del mes"]);
  assert.ok(avisos.every((a) => a.ruta === "#/admin/llm"));
  d.llm = { disponible: true, errores_semana: 0, mes: { unidades: 40000, limite_unidades: 50000 } };
  assert.deepEqual(atencion(d).avisos, []);
});

test("el LLM no disponible no genera avisos de LLM pero deja el resultado incompleto", () => {
  const d = base();
  d.llm = { disponible: false, motivo: "sin claves" };
  const r = atencion(d);
  assert.deepEqual(r.avisos, []);
  assert.equal(r.incompleto, true);
});

test("usuarios en modo prueba", () => {
  const d = base();
  d.usuarios = [{ username: "a", sandbox: { stt: "fake" } }, { username: "b", sandbox: null }];
  const [a] = atencion(d).avisos;
  assert.equal(a.texto, "1 usuario con modo prueba activo");
  assert.equal(a.tono, "warn");
  assert.equal(a.ruta, "#/admin/usuarios");
  d.usuarios.push({ username: "c", sandbox: { stt: "real" } });
  assert.equal(atencion(d).avisos[0].texto, "2 usuarios con modo prueba activo");
});

test("un origen que no cargó (null) se omite y marca el resultado como incompleto", () => {
  const d = { ...base(), grabaciones: null, usuarios: null };
  const r = atencion(d);
  assert.deepEqual(r.avisos, []);
  assert.equal(r.incompleto, true);
});

test("los errores van antes que las advertencias", () => {
  const d = base();
  d.usuarios = [{ username: "a", sandbox: { stt: "fake" } }];
  d.grabaciones = { por_estado: { error: 1 }, errores: [{ id: "x" }] };
  assert.deepEqual(atencion(d).avisos.map((a) => a.tono), ["error", "warn"]);
});

test("charlas nuevas de las últimas 24 h", () => {
  const nuevas = [{ alta: haceHoras(2) }, { alta: haceHoras(23) }, { alta: haceHoras(25) }, { alta: null }];
  assert.equal(nuevasUltimas24h(nuevas, AHORA), 2);
  assert.equal(nuevasUltimas24h(undefined, AHORA), 0);
});

test("el total de grabaciones suma todos los estados", () => {
  assert.deepEqual(resumenKpiGrabaciones({ ready: 3, error: 2, queued: 1 }), { total: 6, errores: 2 });
  assert.deepEqual(resumenKpiGrabaciones({}), { total: 0, errores: 0 });
});

test("el estado de cada fuente: al día, atrasada o con error", async () => {
  const { estadoFuente } = await import("../../web/js/adminAtencion.js");
  assert.equal(estadoFuente({ fuente: "luma", ok: true, revisado: haceHoras(1) }, 6, AHORA), "ok");
  assert.equal(estadoFuente({ fuente: "luma", ok: true, revisado: haceHoras(19) }, 6, AHORA), "atrasada");
  assert.equal(estadoFuente({ fuente: "luma", ok: false, revisado: haceHoras(1) }, 6, AHORA), "error");
  assert.equal(estadoFuente({ fuente: "catalogo", ok: true, revisado: haceHoras(10) }, 6, AHORA), "atrasada");
  assert.equal(estadoFuente({ fuente: "luma", ok: true, revisado: haceHoras(500) }, undefined, AHORA), "ok");
});
