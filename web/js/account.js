// Cuenta: cambio de contraseña (obligatorio en el primer ingreso) y módulo de admin.
import { Admin, Auth, setMustChangePassword } from "./api.js";
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

function askPassword(username) {
  const pwd = prompt(`Contraseña temporal para ${username} (mínimo ${MIN_LENGTH} caracteres). Se le va a pedir cambiarla al entrar.`);
  if (pwd == null) return null;
  if (pwd.length < MIN_LENGTH) { toast(`Necesita al menos ${MIN_LENGTH} caracteres.`); return null; }
  return pwd;
}

function UserRow(u, reload) {
  const tags = [u.is_admin ? "admin" : null, u.is_active ? null : "desactivado", u.must_change_password ? "debe cambiar contraseña" : null].filter(Boolean);
  const reset = () => {
    const pwd = askPassword(u.username);
    if (pwd) run(() => Admin.resetPassword(u.username, pwd), `Contraseña de ${u.username} reseteada`, reload);
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
      u.is_admin ? null : Button(u.is_active ? "Desactivar" : "Activar", { variant: u.is_active ? "danger" : "secondary", onclick: toggle })));
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
          h("a", { class: "notice err", href: `#/s/${e.id}`, style: { textDecoration: "none" } }, `${e.title}: ${e.error || "error"} (${when(e.updated_at)})`)))
      : null);
}

export async function viewAdmin(view) {
  const usersBox = h("div", { class: "stack" });
  const usageBox = h("div");
  async function reload() {
    const [{ users }, usage] = await Promise.all([Admin.users(), Admin.usage()]);
    usersBox.replaceChildren(...users.map((u) => UserRow(u, reload)));
    usageBox.replaceChildren(UsageSummary(usage));
  }
  await reload();
  view.append(h("div", { class: "stack-lg" },
    h("h1", { class: "title" }, "Administración"),
    h("div", { class: "stack" }, h("h2", { class: "label" }, "Usuarios"), usersBox),
    NewUserForm(reload),
    h("div", { class: "stack" },
      h("h2", { class: "label" }, "Catálogo"),
      h("p", { class: "caption" }, "Después de subir la base con scripts/sync_to_railway.sh, recargala acá sin reiniciar la app."),
      h("div", { class: "actions" }, Button("Recargar catálogo", { onclick: async () => {
        try { const r = await Admin.reloadCatalog(); toast(`Catálogo recargado: ${r.sessions} sesiones`); } catch (err) { toast(err.message); }
      } }))),
    usageBox));
}
