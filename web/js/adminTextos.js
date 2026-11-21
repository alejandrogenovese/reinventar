// Admin: textos y reglas puras (sin DOM), para poder probarlas con node --test (tests/js/adminTextos.test.mjs).

/** Las pestañas del admin: id, etiqueta y ruta. `#/admin` abre Estado. */
export const PESTANAS = [
  ["estado", "Estado", "#/admin"],
  ["usuarios", "Usuarios", "#/admin/usuarios"],
  ["eventos", "Eventos", "#/admin/eventos"],
  ["ofertas", "Ofertas", "#/admin/ofertas"],
  ["llm", "LLM", "#/admin/llm"],
];

export const pestanaDeHash = (hash) => PESTANAS.find(([, , ruta]) => ruta === hash)?.[0] ?? "estado";

const TAREAS = {
  resumen: "Resumen de grabaciones", traduccion: "Traducción en vivo", entrevista: "Entrevista del itinerario",
  itinerario: "Armado del itinerario", razones: "Razones del armado", chat: "Chat de búsqueda",
  filtros: "Filtros en lenguaje natural", temas: "Temas emergentes", briefing: "Ficha del speaker",
  catalogo: "Catálogo (scripts)", "catalogo-traduccion": "Traducción del catálogo",
  "stt-charlas": "Transcripción de charlas", "stt-voz": "Transcripción de voz",
};

/** Nombre legible de la tarea del LLM (la clave puede venir con el prefijo `rx-` del gateway). */
export const nombreTarea = (clave) => TAREAS[String(clave).replace(/^rx-/, "")] ?? clave;

// En el orden en que avanza una grabación; «con error» va al final.
const ESTADOS = [["recording", "grabando"], ["uploading", "subiendo"], ["queued", "en cola"], ["transcribing", "transcribiendo"],
  ["translating", "traduciendo"], ["summarizing", "resumiendo"], ["ready", "listas"], ["error", "con error"]];

/** «3 listas · 1 en cola · 1 con error»: las grabaciones por estado, en castellano. */
export function resumenEstados(porEstado) {
  const conocidos = ESTADOS.filter(([clave]) => porEstado[clave]).map(([clave, texto]) => [clave, `${porEstado[clave]} ${texto}`]);
  const otros = Object.entries(porEstado).filter(([clave, n]) => n && !ESTADOS.some(([k]) => k === clave)).map(([clave, n]) => [clave, `${n} ${clave}`]);
  const orden = [...conocidos.filter(([c]) => c !== "ready" && c !== "error"), ...otros];
  const listas = conocidos.filter(([c]) => c === "ready");
  const error = conocidos.filter(([c]) => c === "error");
  // «listas» primero (lo normal), luego lo que está en proceso y por último los errores.
  return [...listas, ...orden, ...error].map(([, texto]) => texto).join(" · ");
}

export const resumenChequeo = (resultados) => {
  const bien = resultados.filter((r) => r.ok).length;
  return `${bien} bien · ${resultados.length - bien} con falla`;
};

export const TEXTO_CHEQUEO = "Prueba cada parte de la app sin tocar datos reales. Algunas pruebas llaman a servicios externos "
  + "(el tiempo caminando usa Google Routes y puede gastar un poco de cuota). Las del celular (ubicación, mapa, notificaciones) son de este dispositivo.";

/** A qué campo del alta de usuario corresponde el rechazo del servidor. */
export const campoDelError = ({ status, message } = {}) => (status === 409 || /^usuario/i.test(message || "") ? "usuario" : "password");

/** Lo que de verdad hace el servidor al cortar accesos (app/admin_api.py `_cortar_accesos`). */
export const textoCortarAccesos = (username) => `Se cierran todas las sesiones de ${username} y además se borran sus passkeys, `
  + "se dan de baja sus notificaciones y se borra su sede reciente. Para volver a entrar va a necesitar su contraseña.";
