// Pruebas del banner de estado (node --test): qué avisos se muestran, en qué orden y con qué reglas (web/js/estado.js).
import test from "node:test";
import assert from "node:assert/strict";

const {
  CIERRE, CIERRE_SERVICIO_MS, PRIORIDAD, TODO_SUBIDO_MS, avisoDeServicio, avisoProximo, cerradoHasta, cierresVigentes, compararVersiones, contarCosas,
  elegirAvisos, novedadesValidas, progresoDeSubida, seguirSubida,
} = await import("../../web/js/estado.js");

const AHORA = Date.UTC(2026, 11, 1, 22, 0);
const ids = (avisos) => avisos.map((a) => a.id);
const textoDe = (aviso) => aviso.titulo.map((p) => (typeof p === "string" ? p : p.dato ?? p.detalle)).join("");
const base = (extra = {}) => ({ ahora: AHORA, versionLocal: "1.1.2", ...extra });

// Un caso con todos los avisos a la vez (salvo sin señal y «Todo subido», que se prueban aparte).
const todo = (extra = {}) => base({
  fallidos: { gastos: 3 },
  subiendo: { hechos: 2, total: 5, que: "grabaciones y gastos" },
  servicio: [
    { id: "resumenes", nivel: "caido", desde: null, detalle_horas: null },
    { id: "transcripcion", nivel: "demorado", desde: null, detalle_horas: null },
    { id: "eventos", nivel: "atrasado", desde: null, detalle_horas: 7 },
  ],
  versionRemota: "1.1.3",
  actualizadaA: "1.1.2",
  ...extra,
});

test("sin nada que contar no hay avisos", () => {
  assert.deepEqual(elegirAvisos(base()), []);
});

test("el orden sigue la prioridad del mock: caído > falló la cola > subiendo > demorado/atrasado > versión > actualizada", () => {
  const avisos = elegirAvisos(todo());
  assert.deepEqual(ids(avisos), [
    "servicio:resumenes:caido", "fallidos", "subiendo", "servicio:transcripcion:demorado", "servicio:eventos:atrasado",
    "version:1.1.3", "actualizada:1.1.2",
  ]);
  assert.deepEqual(avisos.map((a) => a.prioridad), [2, 3, 4, 5, 5, 6, 7]);
});

test("sin señal va primero, con los pendientes y la hora de los datos", () => {
  const datosDe = new Date(2026, 11, 1, 14, 32).getTime();
  const [primero, ...resto] = elegirAvisos(todo({ online: false, pendientes: { grabaciones: 2, gastos: 3 }, datosDe }));
  assert.equal(primero.id, "sin-senal");
  assert.equal(primero.prioridad, PRIORIDAD.sinSenal);
  assert.equal(primero.tono, "warn");
  assert.equal(textoDe(primero), "Sin señal · datos de las 14:32.");
  assert.equal(primero.detalle, "2 grabaciones y 3 gastos esperan subirse.");
  assert.deepEqual(primero.accion, { texto: "Ver pendientes", tipo: "ir", destino: "#/" });
  assert.equal(primero.cierre, null, "no se cierra: se va solo cuando vuelve la red");
  // sin red no hay «no se pudo subir» ni «subiendo» (eso necesita red); el servicio y la versión siguen en la lista
  assert.ok(!ids(resto).includes("fallidos"));
  assert.ok(!ids(resto).includes("subiendo"));
  assert.ok(ids(resto).includes("version:1.1.3"));
});

test("sin señal y sin pendientes: describe el estado y no ofrece acción", () => {
  const [aviso] = elegirAvisos(base({ online: false }));
  assert.equal(textoDe(aviso), "Sin señal.");
  assert.equal(aviso.detalle, "Lo que hagas se guarda en el celular.");
  assert.equal(aviso.accion, null);
});

test("sin señal con solo gastos pendientes lleva a Gastos, y en singular dice «espera»", () => {
  const [aviso] = elegirAvisos(base({ online: false, pendientes: { gastos: 1 } }));
  assert.equal(aviso.detalle, "1 gasto espera subirse.");
  assert.equal(aviso.accion.destino, "#/gastos");
});

test("con red pero la cola falló: error, «Reintentar» y no se cierra", () => {
  const [aviso] = elegirAvisos(base({ fallidos: { gastos: 3 } }));
  assert.equal(textoDe(aviso), "3 gastos no se pudieron subir.");
  assert.equal(aviso.detalle, "Siguen guardados en este celular.");
  assert.equal(aviso.tono, "error");
  assert.deepEqual(aviso.accion, { texto: "Reintentar", tipo: "reintentar" });
  assert.equal(aviso.cierre, null);
  const [uno] = elegirAvisos(base({ fallidos: { grabaciones: 1 } }));
  assert.equal(textoDe(uno), "1 grabación no se pudo subir.");
});

test("subiendo: info, ícono que gira, «2 de 5» y qué se sube", () => {
  const [aviso] = elegirAvisos(base({ subiendo: { hechos: 2, total: 5, que: "grabaciones y gastos" } }));
  assert.equal(textoDe(aviso), "Volvió la señal · subiendo 2 de 5");
  assert.equal(aviso.detalle, "(grabaciones y gastos)");
  assert.equal(aviso.tono, "info");
  assert.equal(aviso.gira, true);
  assert.equal(aviso.cierre, null);
});

test("«Todo subido» dura 5 s después de terminar la subida, con la última sincronización", () => {
  const ultimaSync = new Date(2026, 11, 1, 14, 41).getTime();
  const [aviso] = elegirAvisos(base({ subidoEn: AHORA - 1000, ultimaSync }));
  assert.equal(aviso.id, "todo-subido");
  assert.equal(aviso.tono, "ok");
  assert.equal(textoDe(aviso), "Todo subido · última sincronización 14:41");
  assert.deepEqual(elegirAvisos(base({ subidoEn: AHORA - TODO_SUBIDO_MS })), [], "a los 5 s se va");
  assert.deepEqual(ids(elegirAvisos(base({ subidoEn: AHORA - 1000, online: false }))), ["sin-senal"]);
});

test("servicio caído: dice qué no anda y qué sí, sin jerga, con «Ver estado» y cierre", () => {
  const caido = avisoDeServicio({ id: "resumenes", nivel: "caido" });
  assert.equal(textoDe(caido), "Los resúmenes y Preguntar no andan por ahora.");
  assert.equal(caido.detalle, "Grabar y transcribir siguen funcionando.");
  assert.equal(caido.tono, "error");
  assert.deepEqual(caido.accion, { texto: "Ver estado", tipo: "avisos" });
  assert.equal(caido.nombre, "resúmenes y Preguntar caídos");
  const todos = ["transcripcion", "resumenes", "eventos", "catalogo"].flatMap((id) => ["caido", "demorado", "atrasado"].map((nivel) => ({ id, nivel })));
  for (const s of todos) {
    const a = avisoDeServicio(s);
    assert.doesNotMatch(`${textoDe(a)} ${a.detalle ?? ""} ${a.hoja.texto}`, /LLM|LiteLLM|Langfuse/, JSON.stringify(s));
  }
});

test("transcripción demorada: warning con el copy del mock", () => {
  const a = avisoDeServicio({ id: "transcripcion", nivel: "demorado" });
  assert.equal(textoDe(a), "Las transcripciones vienen con demora.");
  assert.equal(a.detalle, "Tus grabaciones están guardadas y se procesan solas.");
  assert.equal(a.prioridad, PRIORIDAD.demorado);
  assert.equal(a.tono, "warn");
  assert.equal(a.nombre, "transcripciones con demora");
});

test("eventos y catálogo siempre se muestran como atrasados, con las horas si llegan, sin acción", () => {
  const eventos = avisoDeServicio({ id: "eventos", nivel: "caido", detalle_horas: 7 });
  assert.equal(textoDe(eventos), "Eventos y shows pueden estar desactualizados.");
  assert.equal(eventos.detalle, "La última revisión fue hace 7 h.");
  assert.equal(eventos.prioridad, PRIORIDAD.demorado);
  assert.equal(eventos.accion, null);
  const catalogo = avisoDeServicio({ id: "catalogo", nivel: "atrasado", detalle_horas: null });
  assert.equal(textoDe(catalogo), "Los cambios de AWS en las charlas pueden tardar en aparecer.");
  assert.equal(catalogo.detalle, null);
});

test("servicio con id o nivel desconocidos (o basura) no rompe ni muestra nada", () => {
  for (const s of [{ id: "otro", nivel: "caido" }, { id: "resumenes", nivel: "raro" }, null, "x", {}]) assert.equal(avisoDeServicio(s), null);
  assert.deepEqual(elegirAvisos(base({ servicio: "no es lista" })), []);
  const repetidos = elegirAvisos(base({ servicio: [{ id: "resumenes", nivel: "caido" }, { id: "resumenes", nivel: "caido" }] }));
  assert.equal(repetidos.length, 1);
});

test("versión nueva: neutro con «Ver novedades»; nunca en #/grabar/* ni si no es más nueva", () => {
  const [aviso] = elegirAvisos(base({ versionRemota: "1.1.3" }));
  assert.equal(textoDe(aviso), "Hay una versión nueva 1.1.3");
  assert.equal(aviso.tono, "neutro");
  assert.deepEqual(aviso.accion, { texto: "Ver novedades", tipo: "novedades" });
  assert.equal(aviso.cierre, CIERRE.sesion);
  assert.deepEqual(elegirAvisos(base({ versionRemota: "1.1.3", ruta: "#/grabar/loc_abc" })), []);
  assert.deepEqual(elegirAvisos(base({ versionRemota: "1.1.2" })), []);
  assert.deepEqual(elegirAvisos(base({ versionRemota: "1.0.9" })), []);
  assert.deepEqual(elegirAvisos(base({ versionRemota: "basura" })), []);
});

test("sin señal la hoja dice que la versión se instala cuando vuelva la red", () => {
  const avisos = elegirAvisos(base({ online: false, versionRemota: "1.1.3" }));
  assert.equal(avisos[1].hoja.texto, "Se instala cuando vuelva la señal y recargues.");
});

test("después de actualizar: «Actualizada a X · Qué cambió», que se cierra para siempre", () => {
  const [aviso] = elegirAvisos(base({ actualizadaA: "1.1.2" }));
  assert.equal(textoDe(aviso), "Actualizada a 1.1.2");
  assert.deepEqual(aviso.accion, { texto: "Qué cambió", tipo: "que-cambio" });
  assert.equal(aviso.cierre, CIERRE.siempre);
});

test("con el countdown urgente («Salí ya») solo quedan las prioridades 1 a 3", () => {
  assert.deepEqual(ids(elegirAvisos(todo({ countdownUrgente: true }))), ["servicio:resumenes:caido", "fallidos"]);
  assert.deepEqual(ids(elegirAvisos(todo({ countdownUrgente: true, online: false }))), ["sin-senal", "servicio:resumenes:caido"]);
});

test("lo cerrado no se muestra mientras dure el cierre", () => {
  const avisos = elegirAvisos(todo({ descartados: {
    "servicio:resumenes:caido": AHORA + 1000, "version:1.1.3": Infinity, "servicio:eventos:atrasado": AHORA - 1,
  } }));
  assert.ok(!ids(avisos).includes("servicio:resumenes:caido"));
  assert.ok(!ids(avisos).includes("version:1.1.3"));
  assert.ok(ids(avisos).includes("servicio:eventos:atrasado"), "el cierre venció: vuelve");
});

test("lo que no se cierra no se puede descartar aunque figure en descartados", () => {
  const avisos = elegirAvisos(base({ online: false, descartados: { "sin-senal": Infinity } }));
  assert.deepEqual(ids(avisos), ["sin-senal"]);
});

test("si cambia el nivel del servicio, el cierre anterior ya no aplica", () => {
  const cerrado = { "servicio:transcripcion:demorado": AHORA + CIERRE_SERVICIO_MS };
  const avisos = elegirAvisos(base({ servicio: [{ id: "transcripcion", nivel: "caido" }], descartados: cerrado }));
  assert.deepEqual(ids(avisos), ["servicio:transcripcion:caido"]);
});

test("cerradoHasta: 6 h el servicio, Infinity la versión y «actualizada», null lo que no se cierra", () => {
  assert.equal(cerradoHasta(avisoDeServicio({ id: "resumenes", nivel: "caido" }), AHORA), AHORA + 6 * 3_600_000);
  const [version] = elegirAvisos(base({ versionRemota: "1.1.3" }));
  assert.equal(cerradoHasta(version, AHORA), Infinity);
  const [actualizada] = elegirAvisos(base({ actualizadaA: "1.1.2" }));
  assert.equal(cerradoHasta(actualizada, AHORA), Infinity);
  const [sinSenal] = elegirAvisos(base({ online: false }));
  assert.equal(cerradoHasta(sinSenal, AHORA), null);
});

test("cierresVigentes descarta los vencidos y la basura sin tocar lo guardado", () => {
  const guardados = Object.freeze({ a: AHORA + 1, b: AHORA - 1, c: "mañana", d: null });
  assert.deepEqual(cierresVigentes(guardados, AHORA), { a: AHORA + 1 });
  assert.deepEqual(cierresVigentes(null, AHORA), {});
  assert.deepEqual(cierresVigentes("x", AHORA), {});
});

test("seguirSubida: arranca al volver la red con pendientes, crece si se suma algo y avisa cuando termina", () => {
  assert.deepEqual(seguirSubida(null, { pendientes: 5, online: true, empezar: false, ahora: AHORA }), { subida: null, terminoEn: null },
    "sin que vuelva la red no hay «subiendo»");
  assert.deepEqual(seguirSubida(null, { pendientes: 0, online: true, empezar: true, ahora: AHORA }), { subida: null, terminoEn: null });
  const { subida } = seguirSubida(null, { pendientes: 5, online: true, empezar: true, ahora: AHORA });
  assert.deepEqual(subida, { total: 5 });
  assert.deepEqual(seguirSubida(subida, { pendientes: 3, online: true, ahora: AHORA }).subida, { total: 5 });
  assert.deepEqual(seguirSubida(subida, { pendientes: 7, online: true, ahora: AHORA }).subida, { total: 7 });
  assert.deepEqual(seguirSubida(subida, { pendientes: 0, online: true, ahora: AHORA }), { subida: null, terminoEn: AHORA });
  assert.deepEqual(seguirSubida(subida, { pendientes: 3, online: false, ahora: AHORA }), { subida: null, terminoEn: null },
    "si se corta la red, vuelve «Sin señal»");
});

test("progresoDeSubida: hechos = total − lo que falta, y qué se sube", () => {
  assert.equal(progresoDeSubida(null, { grabaciones: 1 }), null);
  assert.deepEqual(progresoDeSubida({ total: 5 }, { grabaciones: 1, gastos: 2 }), { hechos: 2, total: 5, que: "grabaciones y gastos" });
  assert.deepEqual(progresoDeSubida({ total: 5 }, { gastos: 1 }), { hechos: 4, total: 5, que: "gastos" });
  assert.deepEqual(progresoDeSubida({ total: 5 }, {}), { hechos: 5, total: 5, que: null });
});

test("contarCosas y compararVersiones", () => {
  assert.equal(contarCosas({ grabaciones: 1, gastos: 1 }), "1 grabación y 1 gasto");
  assert.equal(contarCosas({ grabaciones: 2 }), "2 grabaciones");
  assert.equal(contarCosas({}), "");
  assert.equal(compararVersiones("1.10.0", "1.9.9"), 1);
  assert.equal(compararVersiones("1.1.2", "1.1.2"), 0);
  assert.equal(compararVersiones("1.1.2", "1.1.3"), -1);
  assert.equal(compararVersiones(null, "0.0.1"), -1);
});

test("novedadesValidas: arma las secciones en orden y descarta lo que no tiene la forma esperada", () => {
  const respuesta = [
    { version: "1.1.3", fecha: "2026-11-23", secciones: {
      Corregido: [{ titulo: "Arreglo", texto: "Detalle." }],
      Agregado: [{ titulo: "Editar vuelos", texto: "Cada vuelo tiene «Editar»." }, { titulo: "", texto: "sin título" }, { texto: "x" }],
      Otra: [{ titulo: "no se muestra" }],
    } },
    { version: "1.1.4", secciones: { Cambiado: [] } },
    { version: 3, secciones: {} },
    "basura",
  ];
  assert.deepEqual(novedadesValidas(respuesta), [{ version: "1.1.3", secciones: [
    ["Agregado", [{ titulo: "Editar vuelos", texto: "Cada vuelo tiene «Editar»." }]],
    ["Corregido", [{ titulo: "Arreglo", texto: "Detalle." }]],
  ] }]);
  assert.deepEqual(novedadesValidas({ detail: "Not Found" }), []);
  assert.deepEqual(novedadesValidas(null), []);
});


// ---------- «Próximo» (/api/viajes/proximo) ----------

const VUELO = {
  tipo: "vuelo", titulo: "UA1355 a Houston", hora: "13:05", detalle: "puerta D12", url: "#/viajes/vuelo/v1",
  demora_min: 20, cancelado: false, tono: "info", inicio: new Date(AHORA + 3_600_000).toISOString(),
};

test("el vuelo próximo: número, destino, salida con demora y puerta; el botón lleva a la ficha", () => {
  const a = avisoProximo(VUELO, AHORA);
  assert.equal(textoDe(a), "Próximo: UA1355 a Houston · sale 13:05 (+20 min) · puerta D12");
  assert.deepEqual(a.accion, { texto: "Ver vuelo", tipo: "ir", destino: "#/viajes/vuelo/v1" });
  assert.equal(a.tono, "info");
  assert.equal(a.prioridad, PRIORIDAD.proximo);
});

test("lo que falta se omite", () => {
  assert.equal(textoDe(avisoProximo({ ...VUELO, demora_min: 0, detalle: null }, AHORA)), "Próximo: UA1355 a Houston · sale 13:05");
  assert.equal(textoDe(avisoProximo({ ...VUELO, hora: null, demora_min: null }, AHORA)), "Próximo: UA1355 a Houston · puerta D12");
});

test("un vuelo cancelado va con tono de error", () => {
  const a = avisoProximo({ ...VUELO, cancelado: true, tono: "error" }, AHORA);
  assert.equal(a.tono, "error");
  assert.equal(textoDe(a), "Próximo: UA1355 a Houston · cancelado");
});

test("la charla: título, hora y sala", () => {
  const a = avisoProximo({ tipo: "charla", titulo: "Agentes en producción", hora: "14:30", detalle: "Venetian · Sala Lido 3",
    url: "#/charla/ARC407", inicio: VUELO.inicio }, AHORA);
  assert.equal(textoDe(a), "Próximo: Agentes en producción · 14:30 · Venetian · Sala Lido 3");
  assert.equal(a.accion.destino, "#/charla/ARC407");
});

test("lo que ya empezó, lo raro o un destino fuera de la app no se muestra como tal", () => {
  assert.equal(avisoProximo({ ...VUELO, inicio: new Date(AHORA - 1).toISOString() }, AHORA), null);
  assert.equal(avisoProximo({ ...VUELO, tipo: "otro" }, AHORA), null);
  assert.equal(avisoProximo({ ...VUELO, titulo: " " }, AHORA), null);
  assert.equal(avisoProximo(null, AHORA), null);
  assert.equal(avisoProximo({ ...VUELO, url: "https://ejemplo.invalid" }, AHORA).accion, null);
});

test("«Próximo» va debajo de todo: nunca tapa servicio caído, sin señal ni versión", () => {
  assert.deepEqual(ids(elegirAvisos(base({ proximo: VUELO }))), [avisoProximo(VUELO, AHORA).id]);
  const avisos = elegirAvisos(todo({ proximo: VUELO }));
  assert.equal(avisos.at(-1).id, avisoProximo(VUELO, AHORA).id);
  assert.equal(elegirAvisos(base({ online: false, proximo: VUELO }))[0].id, "sin-senal");
  assert.equal(elegirAvisos(base({ versionRemota: "1.1.3", proximo: VUELO }))[0].id, "version:1.1.3");
  assert.deepEqual(elegirAvisos(base({ proximo: VUELO, countdownUrgente: true })), []);  // con «Salí ya», no
});

test("cerrado en la sesión no vuelve, salvo que cambie lo próximo", () => {
  const id = avisoProximo(VUELO, AHORA).id;
  assert.deepEqual(elegirAvisos(base({ proximo: VUELO, descartados: { [id]: Infinity } })), []);
  const otro = { ...VUELO, inicio: new Date(AHORA + 7_200_000).toISOString() };
  assert.equal(elegirAvisos(base({ proximo: otro, descartados: { [id]: Infinity } })).length, 1);
});
