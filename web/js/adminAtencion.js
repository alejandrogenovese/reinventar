// Admin › Estado: qué requiere atención, con los datos que ya devuelven los endpoints (reglas puras, sin DOM:
// se prueban con node --test en tests/js/adminAtencion.test.mjs).
import { NOMBRE_FUENTE } from "./adminTextos.js";

const HORA_MS = 3600e3;
const LIMITE_LANGFUSE = 0.8; // arriba de esto del plan mensual, avisa
const FACTOR_ATRASO = 3; // una fuente está atrasada si pasó 3 veces su intervalo sin revisarse
const HORAS_CATALOGO = 3; // el catálogo oficial de charlas se revisa cada 3 h (app/charlas_auto.py)

const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
const haceTexto = (horas) => (horas < 24 ? `${Math.max(1, Math.round(horas))} h` : plural(Math.floor(horas / 24), "día", "días"));

function avisoGrabaciones(g) {
  const errores = g.por_estado?.error ?? g.errores?.length ?? 0;
  if (!errores) return [];
  const ultima = g.errores?.[0];
  return [{ id: "grabaciones", tono: "error", texto: `${plural(errores, "grabación", "grabaciones")} con error`,
    ruta: ultima ? `#/s/${encodeURIComponent(ultima.id)}` : "#/admin", enlace: ultima ? "Ver la última" : "Ver" }];
}

/** «ok», «atrasada» (pasó 3 veces su intervalo sin revisarse) o «error» (falló la última revisión). `horas` = intervalo de las fuentes. */
export function estadoFuente(r, horas, ahora) {
  if (!r.ok) return "error";
  const esperado = r.fuente === "catalogo" ? HORAS_CATALOGO : horas;
  if (!esperado) return "ok";
  return (ahora - new Date(r.revisado).getTime()) / HORA_MS > esperado * FACTOR_ATRASO ? "atrasada" : "ok";
}

function avisosFuentes(e, ahora) {
  if (!e.activo) return [];
  return (e.revisiones ?? []).flatMap((r) => {
    const nombre = NOMBRE_FUENTE[r.fuente] ?? r.fuente;
    const estado = estadoFuente(r, e.horas, ahora);
    const aviso = { id: `fuente-${r.fuente}`, ruta: "#/admin/eventos", enlace: "Ver eventos" };
    if (estado === "error") return [{ ...aviso, tono: "error", texto: `${nombre} falló en la última revisión` }];
    if (estado === "atrasada") {
      return [{ ...aviso, tono: "warn", texto: `${nombre} sin revisar hace ${haceTexto((ahora - new Date(r.revisado).getTime()) / HORA_MS)}` }];
    }
    return [];
  });
}

function avisosLlm(l) {
  if (!l.disponible) return [];
  const avisos = [];
  if (l.errores_semana > 0) {
    avisos.push({ id: "llm-errores", tono: "warn", texto: `${plural(l.errores_semana, "error", "errores")} del LLM en 7 días`, ruta: "#/admin/llm", enlace: "Ver LLM" });
  }
  const ratio = l.mes.unidades / l.mes.limite_unidades;
  if (ratio > LIMITE_LANGFUSE) {
    avisos.push({ id: "langfuse", tono: "warn", texto: `Langfuse al ${Math.round(ratio * 100)} % del mes`, ruta: "#/admin/llm", enlace: "Ver LLM" });
  }
  return avisos;
}

function avisoModoPrueba(usuarios) {
  const n = usuarios.filter((u) => u.sandbox).length;
  return n ? [{ id: "modo-prueba", tono: "warn", texto: `${n === 1 ? "1 usuario" : `${n} usuarios`} con modo prueba activo`, ruta: "#/admin/usuarios", enlace: "Ver usuarios" }] : [];
}

/**
 * Avisos de «Requiere atención». `datos` = { ahora, grabaciones: {por_estado, errores}, eventos: {activo, horas, revisiones},
 * llm (la respuesta de /api/admin/llm), usuarios }. Un origen en `null` (no cargó) se omite y `incompleto` queda en true:
 * así la pantalla no afirma «todo en orden» sin haber mirado todo. Los errores van antes que las advertencias.
 */
export function atencion({ ahora, grabaciones, eventos, llm, usuarios }) {
  const avisos = [
    ...(grabaciones ? avisoGrabaciones(grabaciones) : []),
    ...(eventos ? avisosFuentes(eventos, ahora) : []),
    ...(llm ? avisosLlm(llm) : []),
    ...(usuarios ? avisoModoPrueba(usuarios) : []),
  ];
  const ordenados = [...avisos.filter((a) => a.tono === "error"), ...avisos.filter((a) => a.tono !== "error")];
  const incompleto = !grabaciones || !eventos || !llm || llm.disponible === false || !usuarios;
  return { avisos: ordenados, incompleto };
}

/** Charlas que la revisión dio de alta en las últimas 24 h. */
export const nuevasUltimas24h = (nuevas, ahora) => (nuevas ?? []).filter((c) => c.alta && ahora - new Date(c.alta).getTime() < 24 * HORA_MS).length;

/** Total de grabaciones y cuántas están con error, a partir de `recordings_by_status`. */
export const resumenKpiGrabaciones = (porEstado = {}) => ({
  total: Object.values(porEstado).reduce((suma, n) => suma + n, 0),
  errores: porEstado.error ?? 0,
});
