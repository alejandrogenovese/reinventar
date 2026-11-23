// «Mi ficha»: reglas puras del front (sin DOM ni almacenamiento). El servidor (app/ficha.py) decide qué falta de lo que
// está en la base; acá se suma lo que depende del dispositivo (las notificaciones: el permiso es de cada navegador), se
// arman los bloques de la pantalla con su completitud y se elige el aviso del banner.
import { CIERRE, PRIORIDAD } from "./estado.js";

// Siempre después de «Próximo» (y de cualquier aviso con fecha, como las charlas nuevas): lo que falta en la ficha puede
// esperar unas horas; lo que está por empezar o lo que acaba de cambiar, no.
export const PRIORIDAD_FICHA = PRIORIDAD.proximo + 1;
export const POSPONER_MS = 24 * 3_600_000;   // «Más tarde»: vuelve al día siguiente
export const RUTA_FICHA = "#/ficha";
export const ID_AVISO_FICHA = "ficha";        // uno solo para todos: posponer uno no hace aparecer el siguiente

const FASES_CON_AVISO = new Set(["antes", "durante"]);
const PRIORIDAD_NOTIFICACIONES = 4;           // entre el hotel (3) y los documentos (5): ver app/ficha.py

const esRuta = (x) => typeof x === "string" && x.startsWith("#/");
const texto = (x) => (typeof x === "string" && x.trim() ? x.trim() : null);
const numero = (x) => (Number.isInteger(x) && x >= 0 ? x : 0);
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

/**
 * Lo que falta de notificaciones en este dispositivo, o null. `notif` = { estado, activo }: estado como estadoPush()
 * (notifications.js); activo true/false, o null si no se pudo saber (ahí no se insiste). Con el permiso denegado no se
 * avisa: desde la app no se puede volver a pedir.
 */
export function faltanteNotificaciones(notif) {
  const base = { id: "notificaciones", prioridad: PRIORIDAD_NOTIFICACIONES, link: "#/ajustes", critico: true, banner: true };
  if (notif?.estado === "ios_sin_instalar") return { ...base, texto: "Instalá la app para recibir avisos" };
  if (notif?.estado !== "ok" || notif.activo !== false || notif.denegado) return null;
  return { ...base, texto: "Activá las notificaciones" };
}

/** Faltantes válidos de la respuesta (los que no tienen texto o link de la app se descartan: no se confía en la respuesta). */
function validos(lista) {
  return (Array.isArray(lista) ? lista : [])
    .filter((f) => texto(f?.texto) && esRuta(f?.link) && Number.isFinite(f?.prioridad));
}

/** Los faltantes de la ficha (los del servidor más el de notificaciones), del más importante al menos. */
export function faltantesDe(ficha, notif) {
  const deNotif = faltanteNotificaciones(notif);
  return [...validos(ficha?.faltantes), ...(deNotif ? [deNotif] : [])].sort((a, b) => a.prioridad - b.prioridad);
}

/** Los que van al banner: lo que filtró el servidor según la fase, más las notificaciones si la fase lo permite. */
export function faltantesParaBanner(ficha, notif) {
  if (!FASES_CON_AVISO.has(ficha?.fase)) return [];
  const deNotif = faltanteNotificaciones(notif);
  return [...validos(ficha?.banner), ...(deNotif ? [deNotif] : [])].sort((a, b) => a.prioridad - b.prioridad);
}

/**
 * El aviso del banner (forma de estado.js), o null. No se muestra en la ficha ni en la pantalla donde se completa: ahí ya
 * se está haciendo. Al cerrarlo («Más tarde») vuelve en 24 h.
 */
export function avisoFicha({ ficha, notificaciones = null, ruta = "" }) {
  const [primero] = faltantesParaBanner(ficha, notificaciones);
  const enRuta = String(ruta ?? "");
  if (!primero || enRuta === RUTA_FICHA || enRuta === primero.link) return null;
  const titulo = texto(primero.texto);
  return {
    id: ID_AVISO_FICHA, prioridad: PRIORIDAD_FICHA, tono: "info", icono: "alerta",
    titulo: [`${titulo}.`], detalle: null,
    accion: { texto: "Completar", tipo: "ir", destino: primero.link },
    cierre: CIERRE.posponer, posponerMs: POSPONER_MS, nombre: "lo que falta en tu ficha (vuelve mañana)",
    hoja: { titulo, texto: "Se completa en un minuto. Si cerrás el aviso, vuelve en 24 h. Todo lo que falta está en Ajustes › Mi ficha." },
  };
}

// ---------- bloques de la pantalla ----------

const dia = (iso) => {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  return m ? `${Number(m[2])}/${Number(m[1])}` : "";
};

function bloquePerfil(p) {
  const rol = [texto(p.rol), texto(p.industria)].filter(Boolean).join(" · ");
  const intereses = (Array.isArray(p.intereses) ? p.intereses : []).map(texto).filter(Boolean);
  return { id: "perfil", titulo: "Perfil", completo: p.completo === true, opcional: false,
    lineas: [rol || "Sin rol cargado", intereses.length ? `Intereses: ${intereses.join(", ")}` : "Sin intereses cargados"],
    link: "#/itinerario/entrevista", boton: p.completo ? "Ver perfil" : "Completar perfil" };
}

function bloqueViaje(v) {
  const vuelos = (Array.isArray(v.vuelos) ? v.vuelos : []).filter((x) => texto(x?.numero));
  const hoteles = (Array.isArray(v.hoteles) ? v.hoteles : []).filter((x) => texto(x?.nombre));
  const faltan = [v.ida ? null : "el vuelo de ida", v.vuelta ? null : "el vuelo de vuelta", hoteles.length ? null : "el hotel"].filter(Boolean);
  return { id: "viaje", titulo: "Viaje", completo: faltan.length === 0, opcional: false,
    lineas: [
      vuelos.length ? `Vuelos: ${vuelos.map((x) => [texto(x.numero), dia(x.fecha)].filter(Boolean).join(" ")).join(", ")}` : "Sin vuelos cargados",
      hoteles.length ? `Hotel: ${hoteles.map((x) => texto(x.nombre)).join(", ")}` : "Sin hotel cargado",
      faltan.length ? `Falta ${faltan.join(", ").replace(/, ([^,]*)$/, " y $1")}.` : null,
    ].filter(Boolean),
    link: "#/viajes", boton: "Vuelos y hoteles" };
}

function bloqueNotificaciones(notif) {
  const soportado = notif?.estado === "ok" || notif?.estado === "ios_sin_instalar";
  const linea = !soportado ? "Este navegador no las soporta."
    : notif.estado === "ios_sin_instalar" ? "En iPhone hace falta instalar la app en la pantalla de inicio."
      : notif.activo === true ? "Activadas en este dispositivo."
        : notif.denegado ? "Bloqueadas en el navegador: se habilitan desde los permisos del sitio."
          : notif.activo === false ? "Apagadas en este dispositivo." : "No se pudo saber si están activadas.";
  return { id: "notificaciones", titulo: "Notificaciones", completo: notif?.activo === true, opcional: !soportado,
    lineas: [linea], link: "#/ajustes", boton: "Ajustes" };
}

function bloquePasskey(n) {
  return { id: "passkey", titulo: "Entrar con huella o cara", completo: n > 0, opcional: true,
    lineas: [n > 0 ? `${plural(n, "passkey guardada", "passkeys guardadas")}.` : "Opcional: entrás sin escribir la contraseña."],
    link: "#/ajustes", boton: "Ajustes" };
}

function bloqueDocumentos(n) {
  return { id: "documentos", titulo: "Documentos", completo: n > 0, opcional: false,
    lineas: [n > 0 ? `${plural(n, "documento guardado", "documentos guardados")}.` : "Todavía no subiste ninguno (pasaporte, ESTA, seguro)."],
    link: "#/viajes/documentos", boton: "Documentos" };
}

function bloquePendientes(p) {
  const hechos = numero(p.hechos);
  const total = numero(p.total);
  return { id: "pendientes", titulo: "Pendientes del viaje", completo: total > 0 && hechos >= total, opcional: false,
    lineas: [total ? `${hechos}/${total} listos.` : "Todavía no abriste la lista."], link: "#/viajes/pendientes", boton: "Pendientes" };
}

function bloqueAgenda(a) {
  const charlas = numero(a.charlas);
  const codigos = numero(a.codigos_excel);
  return { id: "agenda", titulo: "Agenda", completo: charlas > 0 || codigos > 0, opcional: false,
    lineas: [charlas ? `${plural(charlas, "charla", "charlas")} en tu agenda.` : "Sin charlas en tu agenda.",
      codigos ? `${plural(codigos, "código", "códigos")} de tu Excel.` : null].filter(Boolean),
    link: "#/itinerario", boton: "Itinerario" };
}

/** Los bloques de «Mi ficha», en el orden de la pantalla. Cada uno: { id, titulo, completo, opcional, lineas, link, boton }. */
export function bloques(ficha, notif) {
  const f = ficha ?? {};
  return [
    bloquePerfil(f.perfil ?? {}), bloqueViaje(f.viaje ?? {}), bloqueNotificaciones(notif), bloquePasskey(numero(f.passkeys)),
    bloqueDocumentos(numero(f.documentos)), bloquePendientes(f.pendientes ?? {}), bloqueAgenda(f.agenda ?? {}),
  ];
}

/** { hechos, total, pct } sobre los bloques no opcionales. */
export function completitud(lista) {
  const cuentan = lista.filter((b) => !b.opcional);
  const hechos = cuentan.filter((b) => b.completo).length;
  return { hechos, total: cuentan.length, pct: cuentan.length ? Math.round((hechos / cuentan.length) * 100) : 0 };
}
