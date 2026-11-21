// Admin › Estado (#/admin): lo que requiere atención, KPIs, chequeo funcional, recarga del catálogo y, plegado, el borrado de datos de prueba.
// Cada bloque anda por su cuenta: si falla uno de los pedidos del resumen, los demás se ven y el chequeo funcional (lo que sirve
// para diagnosticar) sigue ahí.
import { Admin, api } from "./api.js";
import { atencion, nuevasUltimas24h, resumenKpiGrabaciones } from "./adminAtencion.js";
import { AdminShell, Cargable, Plegable, avisar, confirmar, conOcupado, hace, sinDoble } from "./adminUi.js";
import { TEXTO_CHEQUEO, resumenChequeo, resumenEstados } from "./adminTextos.js";
import { icon } from "./icons.js";
import { currentPosition, walkingMinutes } from "./location.js";
import { loadGoogleMaps } from "./map.js";
import { Button, Hint, Tag, h, mensajeError } from "./ui.js";

const hora = (ms) => new Date(ms).toLocaleTimeString("es-AR", { timeStyle: "short" });
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
const dinero = (n) => n.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// --- chequeo funcional ---------------------------------------------------------
async function timed(name, fn) {
  const t0 = performance.now();
  try { return { name, ok: true, detail: await fn(), ms: Math.round(performance.now() - t0) }; }
  catch (err) { return { name, ok: false, detail: err?.message || String(err), ms: Math.round(performance.now() - t0) }; }
}

/** Lo que solo se puede probar en el celular: service worker, ubicación, mapa, Routes API y notificaciones. */
const deviceChecks = () => Promise.all([
  timed("Service worker", async () => {
    const r = await navigator.serviceWorker?.getRegistration();
    if (!r) { throw new Error("no registrado"); }
    return "registrado";
  }),
  timed("Ubicación", async () => {
    const p = await currentPosition();
    if (!p) { throw new Error("sin permiso o apagada en Ajustes"); }
    return p.simulated ? "simulada (modo prueba)" : "GPS del celular";
  }),
  timed("Mapa (Google Maps)", async () => { await loadGoogleMaps(); return "cargó"; }),
  timed("Tiempo caminando (Routes API)", async () => {
    const r = await walkingMinutes({ lat: 36.1216, lng: -115.1691 }, { lat: 36.102219, lng: -115.169517 });
    if (r.estimated) throw new Error("Routes API no disponible: se usa la estimación por línea recta");
    return `Venetian → MGM Grand: ${r.minutes} min`;
  }),
  timed("Notificaciones", async () => {
    if (!("Notification" in window)) throw new Error("el navegador no las soporta (en iPhone: instalá la app)");
    const sub = await (await navigator.serviceWorker?.ready)?.pushManager?.getSubscription();
    if (!sub) throw new Error(`no activadas en este celular (permiso: ${Notification.permission})`);
    return "activas en este celular";
  }),
]);

/** Una fila del chequeo: ícono, nombre y estado con texto (no solo color); la falla muestra el detalle debajo. */
const FilaChequeo = (c) => h("li", { class: c.ok ? "is-bien" : "is-falla" },
  icon(c.ok ? "listo" : "alerta", 16),
  h("span", {}, c.name, c.ok ? h("span", { class: "sr-only" }, ": bien") : null),
  h("span", { class: "ra-adm-estado", style: c.ok ? {} : { color: "var(--on-error-soft)" } }, c.ok ? "Bien" : "Falla"),
  h("span", { class: c.ok ? "ra-adm-detalle" : "ra-adm-detalle-falla" }, `${c.detail} · ${c.ms} ms`));

function FunctionalCheck() {
  const list = h("ul", { class: "ra-adm-check" });
  const resumen = h("span", { class: "ra-adm-resumen-check", role: "status" });
  const correr = async () => {
    list.replaceChildren(h("li", { class: "ra-adm-cap" }, h("span"), "Corriendo…"));
    resumen.textContent = "";
    let server = [];
    try { ({ checks: server } = await Admin.check()); } catch (err) { server = [{ name: "Servidor", ok: false, detail: err.message, ms: 0 }]; }
    const all = [...server, ...await deviceChecks()];
    list.replaceChildren(...all.map(FilaChequeo));
    resumen.textContent = resumenChequeo(all);
    btn.className = "ra-btn ra-btn-ghost ra-sec-action"; // ya corrió: pasa de acción principal a «Volver a correr»
    btn.textContent = "Volver a correr";
  };
  const btn = Button("Correr todo", { variant: "primary", onclick: () => conOcupado(btn, correr) });
  return h("section", { class: "ra-num-card", "aria-labelledby": "adm-chequeo" },
    h("div", { class: "ra-sec-head" }, h("h2", { class: "label", id: "adm-chequeo" }, "Chequeo funcional"), resumen),
    h("p", { class: "ra-adm-cap" }, TEXTO_CHEQUEO), list, btn);
}

// --- requiere atención y KPIs ------------------------------------------------------
const valor = (r) => (r.status === "fulfilled" ? r.value : null);

/** Pide lo de las cuatro fuentes por separado: lo que falle queda en null y el resto se muestra igual. */
async function cargarResumen() {
  const resultados = await Promise.allSettled([Admin.usage(), Admin.eventos(), api("/api/admin/llm"), Admin.users()]);
  if (resultados.every((r) => r.status === "rejected")) throw resultados[0].reason;
  const [usage, eventos, llm, users] = resultados.map(valor);
  return { ahora: Date.now(), usage, eventos, llm, usuarios: users?.users ?? null };
}

const fechaCorta = (ts) => (ts ? new Date(ts * 1000).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" }) : "sin fecha");

/** Cada grabación con error (título, mensaje, fecha y link), para llegar a todas y no solo a la última. */
const ListaErrores = (errores) => Plegable(`Ver las ${errores.length} grabaciones con error`,
  h("div", { class: "ra-adm-lista" }, errores.map((e) => h("a", { class: "ra-adm-fila", href: e.ruta },
    h("span", { class: "ra-adm-fila-cuerpo" },
      h("span", { class: "ra-adm-fila-nombre" }, e.title || "Sin título"),
      h("span", { class: "ra-adm-fila-sub" }, `${e.error || "error"} · ${fechaCorta(e.updated_at)}`)),
    icon("seguir", 20)))));

const Aviso = (a) => h("div", { class: "ra-adm-aviso" },
  Hint(a.texto, { tone: a.tono, iconName: "alerta" }),
  h("a", { class: "ra-link ra-adm-link", href: a.ruta }, a.enlace, icon("seguir", 16)),
  a.detalle?.length > 1 ? ListaErrores(a.detalle) : null);

function TarjetaAtencion(d) {
  const { avisos, incompleto } = atencion({
    ahora: d.ahora,
    grabaciones: d.usage ? { por_estado: d.usage.recordings_by_status, errores: d.usage.recent_errors } : null,
    eventos: d.eventos ? { activo: d.eventos.activo, horas: d.eventos.horas, revisiones: d.eventos.revisiones } : null,
    llm: d.llm, usuarios: d.usuarios,
  });
  const cuerpo = avisos.length
    ? h("div", { class: "ra-adm-avisos" }, avisos.map(Aviso))
    : h("p", { class: "ra-adm-ok" }, icon("listo", 16),
      h("span", {}, `${incompleto ? "Sin avisos en lo que se pudo revisar" : "Todo en orden"} · revisado ${hora(d.ahora)}`));
  return h("section", { class: "ra-num-card", "aria-labelledby": "adm-atencion" },
    h("div", { class: "ra-sec-head" }, h("h2", { class: "label", id: "adm-atencion" }, "Requiere atención"),
      avisos.length ? Tag(plural(avisos.length, "aviso", "avisos")) : null),
    cuerpo,
    incompleto && !avisos.length ? h("p", { class: "ra-adm-cap" }, "Algo no cargó: mirá cada pestaña o recargá la pantalla.") : null);
}

const Kpi = (etiqueta, valorKpi, nota, ...extra) => h("div", { class: "ra-kpi" },
  h("span", { class: "ra-kpi-label" }, etiqueta), h("span", { class: "ra-kpi-value" }, valorKpi), h("span", { class: "ra-kpi-note" }, nota), ...extra);

const SIN_DATO = ["—", "no se pudo cargar"];

function KpiGrabaciones(usage) {
  if (!usage) return Kpi("Grabaciones", ...SIN_DATO);
  const g = resumenKpiGrabaciones(usage.recordings_by_status);
  const pill = g.errores
    ? h("span", { class: "ra-pill ra-pill-error ra-adm-kpi-pill", role: "status" }, h("span", { class: "ra-pill-dot", "aria-hidden": "true" }), `${g.errores} con error`)
    : null;
  return Kpi("Grabaciones", String(g.total), resumenEstados(usage.recordings_by_status) || "todavía no hay", pill);
}

function KpiCosto(llm) {
  if (!llm) return Kpi("Costo LLM 7 días", ...SIN_DATO);
  if (!llm.disponible) return Kpi("Costo LLM 7 días", "—", "sin datos de Langfuse");
  return Kpi("Costo LLM 7 días", h("span", {}, dinero(llm.costo_semana), h("small", {}, " US$")), "últimos 7 días");
}

function Kpis(d) {
  const activos = d.usuarios?.filter((u) => u.is_active).length;
  const conSesion = d.usuarios?.filter((u) => u.open_sessions > 0).length;
  const ultima = d.eventos?.revisiones.find((r) => r.fuente === "catalogo");
  return h("section", { "aria-label": "Resumen de actividad" }, h("div", { class: "ra-kpis" },
    d.usuarios ? Kpi("Usuarios activos", String(activos), plural(conSesion, "con sesión abierta", "con sesión abierta")) : Kpi("Usuarios activos", ...SIN_DATO),
    KpiGrabaciones(d.usage),
    d.eventos
      ? Kpi("Charlas nuevas 24 h", String(nuevasUltimas24h(d.eventos.charlas_nuevas, d.ahora)), ultima ? `última revisión ${hace(ultima.revisado, d.ahora)}` : "sin revisión todavía")
      : Kpi("Charlas nuevas 24 h", ...SIN_DATO),
    KpiCosto(d.llm)));
}

function Resumen() {
  const bloque = Cargable({ cargar: cargarResumen, pintar: (d) => [TarjetaAtencion(d), Kpis(d)], textoCargando: "Revisando el estado…" });
  bloque.classList.add("ra-adm-resumen");
  return bloque;
}

// --- catálogo y datos de prueba ----------------------------------------------------
function Catalogo() {
  const btn = Button("Recargar catálogo", { onclick: () => conOcupado(btn, async () => {
    try { const r = await Admin.reloadCatalog(); avisar(`Catálogo recargado: ${r.sessions} sesiones`); } catch (err) { avisar(mensajeError(err), { error: true }); }
  }) });
  return h("section", { class: "ra-num-card", "aria-labelledby": "adm-catalogo" },
    h("h2", { class: "label", id: "adm-catalogo" }, "Catálogo"),
    h("p", { class: "ra-adm-cap" }, "Después de subir la base con scripts/sync_to_railway.sh, recargala acá sin reiniciar la app."),
    btn);
}

function Herramientas() {
  const btn = Button("Borrar datos de prueba", { variant: "danger", onclick: () => sinDoble(btn, async () => {
    const ok = await confirmar("¿Borrar los datos de prueba?",
      "Se borran las grabaciones e itinerarios creados en modo prueba, de todos los usuarios. Los datos reales no se tocan.", "Borrar");
    if (!ok) return;
    await conOcupado(btn, async () => {
      try { const r = await Admin.clearSandboxData(); avisar(`Datos de prueba borrados (${r.rows} filas)`); } catch (err) { avisar(mensajeError(err), { error: true }); }
    });
  }) });
  return Plegable("Herramientas", [
    h("p", { class: "ra-adm-cap" }, "El modo prueba se prende por usuario, en la pestaña Usuarios. Lo que hacen en modo prueba queda aparte y se puede borrar entero. "
      + "No toca datos reales."),
    btn]);
}

export function viewAdminEstado(view) {
  AdminShell(view, "estado", h("div", { class: "ra-adm-desk-grid" },
    h("div", {}, Resumen(), FunctionalCheck()),
    h("div", {}, Catalogo(), Herramientas())));
}
