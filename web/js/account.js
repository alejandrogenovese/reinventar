// Cuenta: cambio de contraseña (obligatorio en el primer ingreso). El admin vive en admin*.js.
import { Auth, setMustChangePassword } from "./api.js";
import { PasswordField, h, mensajeError, toast } from "./ui.js";

const MIN_LENGTH = 8;

const errorNotice = (msg) => h("div", { class: "notice err" }, msg);

// --- contraseña --------------------------------------------------------------
export function viewPassword(view, { forced }) {
  // Cada campo tiene su propio ojo (PasswordField): mostrar uno no muestra los otros.
  const current = PasswordField("current", forced ? "Contraseña que te pasaron" : "Contraseña actual", { autocomplete: "current-password" });
  const next = PasswordField("next", "Contraseña nueva", { autocomplete: "new-password", minlength: MIN_LENGTH });
  const repeat = PasswordField("repeat", "Repetila", { autocomplete: "new-password", minlength: MIN_LENGTH });
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
      status.append(errorNotice(err.status === 422 ? `La contraseña nueva necesita al menos ${MIN_LENGTH} caracteres.` : mensajeError(err)));
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
