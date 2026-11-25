// Mail obligatorio (#/mail) y recuperación de contraseña con un código por mail (#/olvide). El servidor valida todo
// (app/mail_api.py); acá van los pasos de la pantalla y unas reglas puras que se prueban con node --test.
import { Mail, setDebeCargarMail } from "./api.js";
import { PasswordField, h, mensajeError, toast } from "./ui.js";

const MIN_LENGTH = 8;
const CODIGO_DIGITOS = 6;

/** Como lo guarda el servidor: sin espacios alrededor y en minúsculas. */
export const normalizarEmail = (valor) => String(valor ?? "").trim().toLowerCase();

/** Chequeo rápido antes de mandar (el servidor vuelve a validar): algo@dominio.tld, sin espacios. */
export const pareceEmail = (valor) => {
  const email = normalizarEmail(valor);
  return email.length <= 254 && /^[a-z0-9._%+-]{1,64}@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$/.test(email);
};

/** El código tal como lo tipeó o pegó («123 456», «123-456»): solo los dígitos. */
export const limpiarCodigo = (valor) => String(valor ?? "").replace(/\D/g, "").slice(0, CODIGO_DIGITOS);

const aviso = (texto, { error = true } = {}) => h("div", { class: error ? "notice err" : "notice", role: error ? "alert" : "status" }, texto);

function campo(id, label, attrs) {
  const input = h("input", { id, name: id, required: true, ...attrs });
  return { input, el: h("div", { class: "field" }, h("label", { class: "label", for: id }, label), input) };
}

/** Corre el envío con el botón bloqueado; si falla, muestra el error en `estado` y devuelve false. */
async function enviar(form, estado, accion) {
  const btn = form.querySelector("button[type=submit]");
  btn.disabled = true;
  estado.replaceChildren();
  try { await accion(); return true; } catch (err) { estado.replaceChildren(aviso(mensajeError(err))); return false; } finally { btn.disabled = false; }
}

// --- mail obligatorio ---------------------------------------------------------
export function viewMail(view) {
  const paso = h("div", { class: "stack-lg" });
  view.append(paso);
  pasoEmail(paso);
}

function pasoEmail(paso, previo = "") {
  const email = campo("email", "Tu mail", { type: "email", autocomplete: "email", autocapitalize: "none", inputmode: "email", value: previo, maxlength: 254 });
  const estado = h("div");
  const form = h("form", { class: "stack-lg", novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    const valor = normalizarEmail(email.input.value);
    if (!pareceEmail(valor)) { estado.replaceChildren(aviso("Ese mail no parece válido. Revisalo (ejemplo: nombre@dominio.com).")); email.input.focus(); return; }
    let r;
    if (await enviar(form, estado, async () => { r = await Mail.pedirCodigo(valor); })) pasoCodigo(paso, r.enviado_a, r.vence_minutos);
  } },
    h("h1", { class: "title" }, "Cargá tu mail"),
    h("p", {}, "Lo necesitamos para que puedas recuperar tu contraseña si te la olvidás. Te vamos a mandar un código para confirmar que es tuyo."),
    email.el,
    h("div", { class: "actions" }, h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Mandarme el código")),
    estado);
  paso.replaceChildren(form);
  email.input.focus();
}

function pasoCodigo(paso, destino, minutos) {
  const codigo = campo("codigo", "Código de 6 dígitos", { inputmode: "numeric", autocomplete: "one-time-code", maxlength: 12, pattern: "[0-9 -]*" });
  const estado = h("div");
  const form = h("form", { class: "stack-lg", onsubmit: async (e) => {
    e.preventDefault();
    const valor = limpiarCodigo(codigo.input.value);
    if (valor.length !== CODIGO_DIGITOS) { estado.replaceChildren(aviso(`El código tiene ${CODIGO_DIGITOS} dígitos.`)); return; }
    if (await enviar(form, estado, () => Mail.verificar(valor))) {
      setDebeCargarMail(false);
      toast("Mail confirmado");
      location.hash = "#/";
    }
  } },
    h("h1", { class: "title" }, "Revisá tu mail"),
    h("p", {}, `Te mandamos un código a ${destino}. Vence en ${minutos} minutos. Si no lo ves, buscá en el spam.`),
    codigo.el,
    h("div", { class: "actions" },
      h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Confirmar"),
      h("button", { type: "button", class: "ra-btn ra-btn-ghost", onclick: () => pasoEmail(paso, destino) }, "Cambiar el mail o pedir otro código")),
    estado);
  paso.replaceChildren(form);
  codigo.input.focus();
}

// --- recuperar contraseña: usuario o mail → código y contraseña nueva, en el mismo flujo -----
export function viewOlvide(view) {
  const paso = h("div", { class: "stack-lg" });
  view.append(paso);
  pasoPedirCodigo(paso);
}

function pasoPedirCodigo(paso, previo = "") {
  const usuario = campo("olvide-usuario", "Tu usuario o tu mail", { autocomplete: "username", autocapitalize: "none", maxlength: 254, value: previo });
  const estado = h("div");
  const form = h("form", { class: "stack-lg", onsubmit: async (e) => {
    e.preventDefault();
    const cuenta = usuario.input.value.trim();
    let r;
    if (await enviar(form, estado, async () => { r = await Mail.olvide(cuenta); })) pasoRestablecer(paso, cuenta, r.mensaje);
  } },
    h("h1", { class: "title" }, "Recuperar contraseña"),
    h("p", {}, "Si tu cuenta tiene el mail confirmado, te mandamos un código para elegir una contraseña nueva. Si no, pedile a un admin que te la resetee."),
    usuario.el,
    h("div", { class: "actions" },
      h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Mandarme el código"),
      h("a", { class: "ra-btn ra-btn-ghost", href: "#/login" }, "Volver a entrar")),
    estado);
  paso.replaceChildren(form);
  usuario.input.focus();
}

function pasoRestablecer(paso, cuenta, mensaje) {
  const codigo = campo("rec-codigo", `Código de ${CODIGO_DIGITOS} dígitos`, { inputmode: "numeric", autocomplete: "one-time-code", maxlength: 12, pattern: "[0-9 -]*" });
  const next = PasswordField("rec-next", "Contraseña nueva", { autocomplete: "new-password", minlength: MIN_LENGTH });
  const repeat = PasswordField("rec-repeat", "Repetila", { autocomplete: "new-password", minlength: MIN_LENGTH });
  const estado = h("div");
  const form = h("form", { class: "stack-lg", onsubmit: async (e) => {
    e.preventDefault();
    const error = errorRestablecer(limpiarCodigo(codigo.input.value), next.input.value, repeat.input.value);
    if (error) { estado.replaceChildren(aviso(error)); return; }
    if (await enviar(form, estado, () => Mail.restablecer(cuenta, limpiarCodigo(codigo.input.value), next.input.value))) {
      toast("Contraseña cambiada. Entrá con la nueva.");
      location.hash = "#/login";
    }
  } },
    h("h1", { class: "title" }, "Recuperar contraseña"),
    aviso(mensaje, { error: false }),
    codigo.el, next.el, repeat.el,
    h("p", { class: "caption" }, `Mínimo ${MIN_LENGTH} caracteres. Se cierra la sesión en todos tus dispositivos y se borran tus passkeys.`),
    h("div", { class: "actions" },
      h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Guardar"),
      h("button", { type: "button", class: "ra-btn ra-btn-ghost", onclick: () => pasoPedirCodigo(paso, cuenta) }, "Pedir otro código")),
    estado);
  paso.replaceChildren(form);
  codigo.input.focus();
}

/** Lo que se puede revisar antes de mandar (el servidor vuelve a validar todo). null si está bien. */
export function errorRestablecer(codigo, nueva, repetida) {
  if (codigo.length !== CODIGO_DIGITOS) return `El código tiene ${CODIGO_DIGITOS} dígitos.`;
  if (nueva.length < MIN_LENGTH) return `La contraseña nueva necesita al menos ${MIN_LENGTH} caracteres.`;
  if (nueva !== repetida) return "Las dos contraseñas nuevas no coinciden.";
  return null;
}
