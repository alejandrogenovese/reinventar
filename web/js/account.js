// Cuenta: cambio de contraseña (obligatorio en el primer ingreso) y módulo de admin.
import { Admin, Auth, setMustChangePassword } from "./api.js";
import { LlmPanel } from "./adminLlm.js";
import { confirmDialog, promptDialog } from "./dialog.js";
import { currentPosition, walkingMinutes } from "./location.js";
import { loadGoogleMaps } from "./map.js";
import { refreshSandbox } from "./sandbox.js";
import { icon } from "./icons.js";
import { Button, h, toast } from "./ui.js";

const MIN_LENGTH = 8;

const field = (id, label, attrs = {}) => {
  const input = h("input", { id, name: id, required: true, ...attrs });
  return { input, el: h("div", { class: "field" }, h("label", { class: "label", for: id }, label), input) };
};
const errorNotice = (msg) => h("div", { class: "notice err" }, msg);
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" }) : "nunca");

// --- contraseña --------------------------------------------------------------
export function viewPassword(view, { forced }) {
  const current = field("current", forced ? "Contraseña que te pasaron" : "Contraseña actual", { type: "password", autocomplete: "current-password" });
  const next = field("next", "Contraseña nueva", { type: "password", autocomplete: "new-password", minlength: MIN_LENGTH });
  const repeat = field("repeat", "Repetila", { type: "password", autocomplete: "new-password", minlength: MIN_LENGTH });
  const status = h("div");

  const form = h("form", { class: "stack-lg", onsubmit: async (e) => {
    e.preventDefault();
    status.replaceChildren();
    if (next.input.value !== repeat.input.value) { status.append(errorNotice("Las dos contraseñas nuevas no coinciden.")); return; }
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      await Auth.changePassword(current.input.value, next.input.value);
      setMustChangePassword(false);
      toast("Contraseña actualizada");
      location.hash = "#/";
    } catch (err) {
      status.append(errorNotice(err.status === 422 ? `La contraseña nueva necesita al menos ${MIN_LENGTH} caracteres.` : err.message));
      btn.disabled = false;
    }
  } },
    h("h1", { class: "title" }, forced ? "Elegí tu contraseña" : "Cambiar contraseña"),
    forced ? h("p", {}, "Es tu primer ingreso: reemplazá la contraseña que te pasaron por una propia.") : null,
    current.el, next.el, repeat.el,
    h("p", { class: "caption" }, `Mínimo ${MIN_LENGTH} caracteres. Al cambiarla se cierra la sesión en tus otros dispositivos.`),
    h("div", { class: "actions" }, h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Guardar")),
    status);
  view.append(form);
  current.input.focus();
}

// --- admin -------------------------------------------------------------------
async function run(action, okMsg, reload) {
  try { await action(); toast(okMsg); await reload(); } catch (err) { toast(err.message); }
}

async function askPassword(username) {
  const pwd = await promptDialog(`Resetear la contraseña de ${username}`,
    { label: `Contraseña temporal (mínimo ${MIN_LENGTH} caracteres)`, minlength: MIN_LENGTH },
    { text: "Se le va a pedir cambiarla al entrar.", confirmLabel: "Resetear" });
  if (pwd == null) return null;
  if (pwd.length < MIN_LENGTH) { toast(`Necesita al menos ${MIN_LENGTH} caracteres.`); return null; }
  return pwd;
}

// --- modo prueba (por usuario) ---------------------------------------------------
const lvTime = (iso) => (iso ? iso.slice(0, 16) : "2026-12-01T09:00"); // "now" ya viene en hora de Las Vegas

function SandboxPanel(u, venues, reload) {
  const sb = u.sandbox;
  const select = (id, options, value) => h("select", { id },
    options.map(([v, label]) => h("option", { value: v, selected: String(v) === String(value) }, label)));
  const active = h("input", { type: "checkbox", id: `sb-on-${u.username}`, checked: Boolean(sb) });
  const stt = select(`sb-stt-${u.username}`, [["fake", "fake (gratis)"], ["real", "real (gasta)"]], sb?.stt || "fake");
  const llm = select(`sb-llm-${u.username}`, [["fake", "fake (gratis)"], ["real", "real (gasta)"]], sb?.llm || "fake");
  const useClock = h("input", { type: "checkbox", id: `sb-clk-${u.username}`, checked: Boolean(sb?.simulated_clock) });
  const clock = h("input", { type: "datetime-local", id: `sb-time-${u.username}`, value: lvTime(sb?.simulated_clock ? sb.now : null) });
  const venue = select(`sb-venue-${u.username}`, [["", "GPS real"], ...venues.map((v) => [v.id, v.name])], sb?.location?.id ?? "");

  const settings = () => ({
    active: active.checked, stt: stt.value, llm: llm.value,
    clock: useClock.checked && clock.value ? clock.value : null,
    venue_id: venue.value ? Number(venue.value) : null,
  });
  const after = async () => { await reload(); await refreshSandbox({ force: true }); };
  const save = () => run(() => Admin.setSandbox(u.username, settings()),
    active.checked ? `Modo prueba de ${u.username} guardado` : `Modo prueba de ${u.username} apagado`, after);
  const advance = (minutes) => run(() => Admin.advanceSandbox(u.username, minutes), `Reloj de ${u.username} +${minutes} min`, after);
  const row = (label, control) => h("label", { class: "field" }, h("span", { class: "label" }, label), control);

  const summary = sb
    ? ["Modo prueba: activo", sb.simulated_clock ? sb.now.slice(0, 16).replace("T", " ") : "reloj real", sb.location?.name].filter(Boolean).join(" · ")
    : "Modo prueba: apagado";
  return h("details", { class: "notice" },
    h("summary", {}, summary),
    h("div", { class: "stack" },
      h("p", { class: "caption" }, "Lo que haga en modo prueba va a otro lugar: sus datos reales no se tocan. Solo un admin lo prende o lo apaga."),
      h("label", { class: "actions is-center" }, active, "Modo prueba activo"),
      row("Transcripción (STT)", stt), row("Traducción y resúmenes (LLM)", llm),
      h("label", { class: "actions is-center" }, useClock, "Simular la hora (Las Vegas)"),
      h("div", { class: "field" }, clock),
      row("Ubicación", venue),
      h("div", { class: "actions" },
        Button("Guardar", { variant: "primary", onclick: save }),
        sb?.simulated_clock ? Button("+15 min", { onclick: () => advance(15) }) : null,
        sb?.simulated_clock ? Button("+1 h", { onclick: () => advance(60) }) : null)));
}

function UserRow(u, reload, venues) {
  const tags = [u.is_admin ? "admin" : null, u.is_active ? null : "desactivado", u.must_change_password ? "debe cambiar contraseña" : null].filter(Boolean);
  const reset = async () => {
    const pwd = await askPassword(u.username);
    if (pwd) void run(() => Admin.resetPassword(u.username, pwd), `Contraseña de ${u.username} reseteada`, reload);
  };
  const toggle = () => run(() => Admin.setActive(u.username, !u.is_active), u.is_active ? `${u.username} desactivado` : `${u.username} activado`, reload);
  const revoke = () => run(() => Admin.revokeSessions(u.username), `Sesiones de ${u.username} cerradas`, reload);

  return h("div", { class: "ra-card" },
    h("div", { class: "ra-card-top" }, h("h3", { class: "ra-card-title" }, u.username), tags.length ? h("span", { class: "ra-kind" }, tags.join(" · ")) : null),
    h("div", { class: "ra-card-meta" },
      h("span", {}, `Último ingreso: ${when(u.last_login)}`),
      h("span", {}, `${u.open_sessions} sesiones abiertas`),
      h("span", {}, `${u.itinerary_items} charlas en el itinerario`)),
    h("div", { class: "actions" },
      Button("Resetear contraseña", { onclick: reset }),
      u.open_sessions ? Button("Cerrar sesiones", { onclick: revoke }) : null,
      u.is_admin ? null : Button(u.is_active ? "Desactivar" : "Activar", { variant: u.is_active ? "danger" : "secondary", onclick: toggle })),
    SandboxPanel(u, venues, reload));
}

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
  const run = async () => {
    btn.disabled = true;
    list.replaceChildren(h("li", { class: "caption" }, "Corriendo…"));
    let server = [];
    try { ({ checks: server } = await Admin.check()); } catch (err) { server = [{ name: "Servidor", ok: false, detail: err.message, ms: 0 }]; }
    const all = [...server, ...await deviceChecks()];
    list.replaceChildren(...all.map((c) => h("li", { class: c.ok ? "is-ok" : "is-fail" },
      h("strong", {}, icon(c.ok ? "listo" : "cerrar", 16), h("span", { class: "sr-only" }, c.ok ? "Bien: " : "Falla: "), c.name), h("span", { class: "caption" }, ` ${c.detail} · ${c.ms} ms`))));
    btn.disabled = false;
  };
  const btn = Button("Correr todo", { variant: "primary", onclick: run });
  return h("div", { class: "stack" },
    h("h2", { class: "label" }, "Chequeo funcional"),
    h("p", { class: "caption" }, "Prueba cada parte de la app sin tocar datos reales ni gastar en APIs. Las pruebas del celular (ubicación, mapa, notificaciones) son de este dispositivo."),
    h("div", { class: "actions" }, btn), list);
}

function SandboxData() {
  const clear = async () => {
    const ok = await confirmDialog("¿Borrar los datos de prueba?", {
      text: "Se borran las grabaciones e itinerarios creados en modo prueba, de todos los usuarios. Los datos reales no se tocan.",
      confirmLabel: "Borrar", danger: true });
    if (!ok) return;
    try { const r = await Admin.clearSandboxData(); toast(`Datos de prueba borrados (${r.rows} filas)`); } catch (err) { toast(err.message); }
  };
  return h("div", { class: "stack" },
    h("h2", { class: "label" }, "Modo prueba"),
    h("p", { class: "caption" }, "Se prende por usuario, en su tarjeta. Lo que hacen en modo prueba queda aparte y se puede borrar entero."),
    h("div", { class: "actions" }, Button("Borrar datos de prueba", { variant: "danger", onclick: clear })));
}

function NewUserForm(reload) {
  const user = field("new-username", "Usuario", { autocapitalize: "none", autocomplete: "off", pattern: "[a-z0-9_.\\-]{2,40}" });
  const pwd = field("new-password", "Contraseña temporal", { type: "text", autocomplete: "off", minlength: MIN_LENGTH });
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    await run(() => Admin.createUser(user.input.value.trim().toLowerCase(), pwd.input.value), `Usuario ${user.input.value} creado`, reload);
    form.reset();
  } },
    h("h2", { class: "label" }, "Nuevo usuario"), user.el, pwd.el,
    h("p", { class: "caption" }, "Pasale usuario y contraseña; al primer ingreso va a tener que elegir la suya."),
    h("div", { class: "actions" }, h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Crear")));
  return form;
}

function UsageSummary(usage) {
  const statuses = Object.entries(usage.recordings_by_status);
  return h("div", { class: "stack" },
    h("h2", { class: "label" }, "Grabaciones"),
    h("p", {}, statuses.length ? statuses.map(([s, n]) => `${s}: ${n}`).join(" · ") : "Todavía no hay grabaciones."),
    usage.recent_errors.length
      ? h("div", { class: "stack" }, usage.recent_errors.map((e) =>
          h("a", { class: "notice err is-plain", href: `#/s/${e.id}` }, `${e.title}: ${e.error || "error"} (${when(e.updated_at)})`)))
      : null);
}

export async function viewAdmin(view) {
  const usersBox = h("div", { class: "stack" });
  const usageBox = h("div");
  let venues = [];
  try { ({ venues } = await Admin.venues()); } catch { /* sin catálogo: el modo prueba anda igual, sin ubicación */ }
  async function reload() {
    const [{ users }, usage] = await Promise.all([Admin.users(), Admin.usage()]);
    usersBox.replaceChildren(...users.map((u) => UserRow(u, reload, venues)));
    usageBox.replaceChildren(UsageSummary(usage));
  }
  await reload();
  view.append(h("div", { class: "stack-lg" },
    h("h1", { class: "title" }, "Administración"),
    h("div", { class: "stack" }, h("h2", { class: "label" }, "Usuarios"), usersBox),
    NewUserForm(reload),
    SandboxData(),
    FunctionalCheck(),
    h("div", { class: "stack" },
      h("h2", { class: "label" }, "Catálogo"),
      h("p", { class: "caption" }, "Después de subir la base con scripts/sync_to_railway.sh, recargala acá sin reiniciar la app."),
      h("div", { class: "actions" }, Button("Recargar catálogo", { onclick: async () => {
        try { const r = await Admin.reloadCatalog(); toast(`Catálogo recargado: ${r.sessions} sesiones`); } catch (err) { toast(err.message); }
      } }))),
    usageBox,
    LlmPanel()));
}
