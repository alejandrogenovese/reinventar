// Admin › Estado (#/admin): grabaciones, chequeo funcional, recarga del catálogo y borrado de datos de prueba.
// Cada bloque anda por su cuenta: si falla el pedido de grabaciones, el chequeo funcional (lo que sirve para diagnosticar) sigue ahí.
import { Admin } from "./api.js";
import { AdminShell, Cargable, avisar, confirmar, conOcupado } from "./adminUi.js";
import { TEXTO_CHEQUEO, resumenChequeo, resumenEstados } from "./adminTextos.js";
import { icon } from "./icons.js";
import { currentPosition, walkingMinutes } from "./location.js";
import { loadGoogleMaps } from "./map.js";
import { Button, h, mensajeError } from "./ui.js";

const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" }) : "nunca");

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

function FunctionalCheck() {
  const list = h("ul", { class: "ra-check-list" });
  const resumen = h("p", { class: "caption", role: "status" });
  const correr = async () => {
    list.replaceChildren(h("li", { class: "caption" }, "Corriendo…"));
    resumen.textContent = "";
    let server = [];
    try { ({ checks: server } = await Admin.check()); } catch (err) { server = [{ name: "Servidor", ok: false, detail: err.message, ms: 0 }]; }
    const all = [...server, ...await deviceChecks()];
    list.replaceChildren(...all.map((c) => h("li", { class: c.ok ? "is-ok" : "is-fail" },
      h("strong", {}, icon(c.ok ? "listo" : "cerrar", 16), h("span", { class: "sr-only" }, c.ok ? "Bien: " : "Falla: "), c.name), h("span", { class: "caption" }, ` ${c.detail} · ${c.ms} ms`))));
    resumen.textContent = resumenChequeo(all);
  };
  const btn = Button("Correr todo", { variant: "primary", onclick: () => conOcupado(btn, correr) });
  return h("div", { class: "stack" },
    h("h2", { class: "label" }, "Chequeo funcional"),
    h("p", { class: "caption" }, TEXTO_CHEQUEO),
    h("div", { class: "actions" }, btn), resumen, list);
}

// --- grabaciones -----------------------------------------------------------------
const Grabaciones = () => Cargable({
  cargar: () => Admin.usage(),
  textoCargando: "Cargando grabaciones…",
  pintar: (usage) => {
    const estados = resumenEstados(usage.recordings_by_status);
    return h("div", { class: "stack" },
      h("h2", { class: "label" }, "Grabaciones"),
      h("p", {}, estados || "Todavía no hay grabaciones."),
      usage.recent_errors.length
        ? h("div", { class: "stack" }, usage.recent_errors.map((e) =>
            h("a", { class: "notice err is-plain", href: `#/s/${e.id}` }, `${e.title}: ${e.error || "error"} (${when(e.updated_at)})`)))
        : null);
  },
});

// --- catálogo y datos de prueba ----------------------------------------------------
function Catalogo() {
  const btn = Button("Recargar catálogo", { onclick: () => conOcupado(btn, async () => {
    try { const r = await Admin.reloadCatalog(); avisar(`Catálogo recargado: ${r.sessions} sesiones`); } catch (err) { avisar(mensajeError(err), { error: true }); }
  }) });
  return h("div", { class: "stack" },
    h("h2", { class: "label" }, "Catálogo"),
    h("p", { class: "caption" }, "Después de subir la base con scripts/sync_to_railway.sh, recargala acá sin reiniciar la app."),
    h("div", { class: "actions" }, btn));
}

function DatosDePrueba() {
  const btn = Button("Borrar datos de prueba", { variant: "danger", onclick: async () => {
    const ok = await confirmar("¿Borrar los datos de prueba?",
      "Se borran las grabaciones e itinerarios creados en modo prueba, de todos los usuarios. Los datos reales no se tocan.", "Borrar");
    if (!ok) return;
    await conOcupado(btn, async () => {
      try { const r = await Admin.clearSandboxData(); avisar(`Datos de prueba borrados (${r.rows} filas)`); } catch (err) { avisar(mensajeError(err), { error: true }); }
    });
  } });
  return h("div", { class: "stack" },
    h("h2", { class: "label" }, "Modo prueba"),
    h("p", { class: "caption" }, "Se prende por usuario, en su tarjeta (pestaña Usuarios). Lo que hacen en modo prueba queda aparte y se puede borrar entero."),
    h("div", { class: "actions" }, btn));
}

export function viewAdminEstado(view) {
  AdminShell(view, "estado", Grabaciones(), FunctionalCheck(), Catalogo(), DatosDePrueba());
}
