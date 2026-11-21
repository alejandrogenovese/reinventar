// Admin › Usuarios (#/admin/usuarios): alta, y por usuario reseteo de contraseña, cierre de sesiones, desactivar y modo prueba.
// Cada acción repinta solo la fila de ese usuario (lo abierto sigue abierto y el scroll no salta) y bloquea su botón mientras corre.
import { Admin } from "./api.js";
import { AdminShell, Cargable, avisar, confirmar, conOcupado } from "./adminUi.js";
import { campoDelError, textoCortarAccesos } from "./adminTextos.js";
import { promptDialog } from "./dialog.js";
import { refreshSandbox } from "./sandbox.js";
import { Button, h, mensajeError } from "./ui.js";

const MIN_LENGTH = 8;
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" }) : "nunca");
const lvTime = (iso) => (iso ? iso.slice(0, 16) : "2026-12-01T09:00"); // "now" ya viene en hora de Las Vegas

async function askPassword(username) {
  const pwd = await promptDialog(`Resetear la contraseña de ${username}`,
    { label: `Contraseña temporal (mínimo ${MIN_LENGTH} caracteres)`, minlength: MIN_LENGTH },
    { text: "Se le va a pedir cambiarla al entrar. También se cierran sus sesiones y se borran sus passkeys.", confirmLabel: "Resetear" });
  if (pwd == null) return null;
  if (pwd.length < MIN_LENGTH) { avisar(`Necesita al menos ${MIN_LENGTH} caracteres.`, { error: true }); return null; }
  return pwd;
}

/** Corre la acción con su botón ocupado y, si anduvo, avisa y repinta la fila; si falló, avisa el error y deja todo como estaba. */
async function ejecutar(boton, accion, okMsg, despues) {
  await conOcupado(boton, async () => {
    try { await accion(); avisar(okMsg); await despues(); }
    catch (err) { avisar(mensajeError(err), { error: true }); }
  });
}

function SandboxPanel(u, venues, repintar) {
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
  const despues = async () => { await repintar(); await refreshSandbox({ force: true }); };
  const guardar = (b) => ejecutar(b, () => Admin.setSandbox(u.username, settings()),
    active.checked ? `Modo prueba de ${u.username} guardado` : `Modo prueba de ${u.username} apagado`, despues);
  const adelantar = (b, minutes) => ejecutar(b, () => Admin.advanceSandbox(u.username, minutes), `Reloj de ${u.username} +${minutes} min`, despues);
  const row = (label, control) => h("label", { class: "field" }, h("span", { class: "label" }, label), control);

  const summary = sb
    ? ["Modo prueba: activo", sb.simulated_clock ? sb.now.slice(0, 16).replace("T", " ") : "reloj real", sb.location?.name].filter(Boolean).join(" · ")
    : "Modo prueba: apagado";
  const boton = (texto, accion, extra = {}) => { const b = Button(texto, { ...extra, "aria-label": `${texto} de ${u.username}`, onclick: () => accion(b) }); return b; };
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
        boton("Guardar", guardar, { variant: "primary", "data-accion": "sb-guardar" }),
        sb?.simulated_clock ? boton("+15 min", (b) => adelantar(b, 15), { "data-accion": "sb-15" }) : null,
        sb?.simulated_clock ? boton("+1 h", (b) => adelantar(b, 60), { "data-accion": "sb-60" }) : null)));
}

/** Repinta solo la fila `fila` con los datos nuevos del usuario: conserva lo abierto y el foco (por data-accion). */
async function refrescarFila(fila, username, venues) {
  const { users } = await Admin.users();
  const u = users.find((x) => x.username === username);
  if (!u) { fila.remove(); return; }
  const abiertos = [...fila.querySelectorAll("details")].map((d) => d.open);
  const accionConFoco = fila.contains(document.activeElement) ? document.activeElement.dataset?.accion : null;
  const nueva = UserRow(u, venues);
  nueva.querySelectorAll("details").forEach((d, i) => { d.open = abiertos[i] ?? false; });
  fila.replaceWith(nueva);
  if (accionConFoco) nueva.querySelector(`[data-accion="${accionConFoco}"]`)?.focus();
}

export function UserRow(u, venues) {
  const tags = [u.is_admin ? "admin" : null, u.is_active ? null : "desactivado", u.must_change_password ? "debe cambiar contraseña" : null].filter(Boolean);
  const repintar = () => refrescarFila(fila, u.username, venues);
  const reset = async (b) => {
    const pwd = await askPassword(u.username);
    if (pwd) await ejecutar(b, () => Admin.resetPassword(u.username, pwd), `Contraseña de ${u.username} reseteada`, repintar);
  };
  const revoke = async (b) => {
    if (!await confirmar(`¿Cerrar las sesiones de ${u.username}?`, textoCortarAccesos(u.username), "Cerrar sesiones")) return;
    await ejecutar(b, () => Admin.revokeSessions(u.username), `Sesiones de ${u.username} cerradas`, repintar);
  };
  const toggle = async (b) => {
    if (u.is_active && !await confirmar(`¿Desactivar a ${u.username}?`,
      `No va a poder entrar hasta que lo actives de nuevo. ${textoCortarAccesos(u.username)}`, "Desactivar")) return;
    await ejecutar(b, () => Admin.setActive(u.username, !u.is_active), u.is_active ? `${u.username} desactivado` : `${u.username} activado`, repintar);
  };
  const boton = (texto, accion, attrs) => { const b = Button(texto, { ...attrs, "aria-label": `${texto} de ${u.username}`, onclick: () => accion(b) }); return b; };

  const fila = h("div", { class: "ra-card" },
    h("div", { class: "ra-card-top" }, h("h3", { class: "ra-card-title" }, u.username), tags.length ? h("span", { class: "ra-kind" }, tags.join(" · ")) : null),
    h("div", { class: "ra-card-meta" },
      h("span", {}, `Último ingreso: ${when(u.last_login)}`),
      h("span", {}, `${u.open_sessions} sesiones abiertas`),
      h("span", {}, `${u.itinerary_items} charlas en el itinerario`)),
    h("div", { class: "actions" },
      boton("Resetear contraseña", reset, { "data-accion": "reset" }),
      u.open_sessions ? boton("Cerrar sesiones", revoke, { "data-accion": "revocar" }) : null,
      u.is_admin ? null : boton(u.is_active ? "Desactivar" : "Activar", toggle, { variant: u.is_active ? "danger" : "secondary", "data-accion": "activo" })),
    SandboxPanel(u, venues, repintar));
  return fila;
}

/** «Nuevo usuario»: si el servidor lo rechaza, no se vacía y el error queda junto al campo (aria-describedby). */
function NewUserForm(alCrear) {
  const campo = (id, label, attrs) => {
    const error = h("p", { class: "ra-hint is-error", id: `${id}-error`, hidden: true });
    const input = h("input", { id, name: id, required: true, ...attrs });
    return { input, error, el: h("div", { class: "field" }, h("label", { class: "label", for: id }, label), input, error) };
  };
  const user = campo("new-username", "Usuario", { autocapitalize: "none", autocomplete: "off", pattern: "[a-z0-9_.\\-]{2,40}" });
  const pwd = campo("new-password", "Contraseña temporal", { type: "text", autocomplete: "off", minlength: MIN_LENGTH });
  const limpiar = () => [user, pwd].forEach((c) => { c.error.hidden = true; c.error.textContent = ""; c.input.removeAttribute("aria-invalid"); c.input.removeAttribute("aria-describedby"); });
  const marcar = (c, texto) => { c.error.textContent = texto; c.error.hidden = false; c.input.setAttribute("aria-invalid", "true"); c.input.setAttribute("aria-describedby", c.error.id); c.input.focus(); };
  const crear = h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Crear");
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    limpiar();
    await conOcupado(crear, async () => {
      const nombre = user.input.value.trim().toLowerCase();
      try {
        await Admin.createUser(nombre, pwd.input.value);
        avisar(`Usuario ${nombre} creado`);
        form.reset();
        alCrear();
      } catch (err) {
        const texto = mensajeError(err);
        marcar(campoDelError(err) === "usuario" ? user : pwd, texto);
        avisar(texto, { error: true });
      }
    });
  } },
    h("h2", { class: "label" }, "Nuevo usuario"), user.el, pwd.el,
    h("p", { class: "caption" }, `Usuario: 2 a 40 caracteres, minúsculas, números, punto, guion o guion bajo. Contraseña: al menos ${MIN_LENGTH}. Al primer ingreso va a tener que elegir la suya.`),
    h("div", { class: "actions" }, crear));
  return form;
}

export async function viewAdminUsuarios(view) {
  let venues = [];
  try { ({ venues } = await Admin.venues()); } catch { /* sin catálogo: el modo prueba anda igual, sin ubicación */ }
  const lista = Cargable({
    cargar: () => Admin.users(),
    pintar: ({ users }) => users.map((u) => UserRow(u, venues)),
    esVacio: ({ users }) => !users.length,
    textoVacio: "Todavía no hay usuarios.",
    textoCargando: "Cargando usuarios…",
  });
  AdminShell(view, "usuarios",
    h("div", { class: "stack" }, h("h2", { class: "label" }, "Usuarios"), lista),
    NewUserForm(() => lista.recargar({ silencioso: true })));
}
