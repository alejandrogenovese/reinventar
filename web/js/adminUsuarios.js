// Admin › Usuarios (#/admin/usuarios): alta, y por usuario reseteo de contraseña, cierre de sesiones, desactivar y modo prueba.
// Lista compacta: cada usuario es una fila (nombre, etiquetas, último ingreso) que al abrirla muestra sus acciones.
// Cada acción repinta solo la fila de ese usuario (lo abierto sigue abierto y el scroll no salta) y bloquea su botón mientras corre.
import { Admin } from "./api.js";
import { AdminShell, Cargable, Chevron, avisar, confirmar, conOcupado, hace, sinDoble } from "./adminUi.js";
import { campoDelError, textoCortarAccesos } from "./adminTextos.js";
import { promptDialog } from "./dialog.js";
import { icon } from "./icons.js";
import { refreshSandbox } from "./sandbox.js";
import { Tag, h, mensajeError } from "./ui.js";

const MIN_LENGTH = 8;
const lvTime = (iso) => (iso ? iso.slice(0, 16) : "2026-12-01T09:00"); // "now" ya viene en hora de Las Vegas
const ultimoIngreso = (ts) => (ts ? hace(new Date(ts * 1000).toISOString()) : "nunca ingresó");

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
    try { await accion(); } catch (err) { avisar(mensajeError(err), { error: true }); return; }
    avisar(okMsg);
    // La acción ya anduvo: si falla el repintado no se la muestra como fallida.
    try { await despues(); } catch { avisar(`${okMsg}, pero no se pudo actualizar la lista. Recargá la pantalla.`, { error: true }); }
  });
}

/** Botón chico (44 px) de una acción sobre un usuario: el nombre accesible dice a quién afecta. */
function botonDe(username) {
  return (texto, accion, { variante = "secondary", extra = "", nombre = `${texto} de ${username}`, ...attrs } = {}) => {
    const b = h("button", { type: "button", class: `ra-btn ra-btn-${variante} ra-adm-btn-s${extra}`, "aria-label": nombre, ...attrs, onclick: () => sinDoble(b, () => accion(b)) }, texto);
    return b;
  };
}

function SandboxPanel(u, venues, repintar) {
  const sb = u.sandbox;
  const boton = botonDe(u.username);
  const select = (id, options, value) => h("select", { id, class: "ra-adm-select" },
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
  const despues = async () => {
    await repintar();
    // Lo guardado ya anduvo y la fila ya se repintó: si falla solo el banner del modo prueba, se dice eso y no «no se pudo actualizar la lista».
    try { await refreshSandbox({ force: true }); } catch { avisar("Se guardó, pero no se pudo actualizar el modo prueba de esta pantalla. Recargá la pantalla.", { error: true }); }
  };
  const guardar = (b) => ejecutar(b, () => Admin.setSandbox(u.username, settings()),
    active.checked ? `Modo prueba de ${u.username} guardado` : `Modo prueba de ${u.username} apagado`, despues);
  const adelantar = (b, minutes) => ejecutar(b, () => Admin.advanceSandbox(u.username, minutes), `Reloj de ${u.username} +${minutes} min`, despues);
  const row = (label, control) => h("label", { class: "field" }, h("span", { class: "label" }, label), control);
  const check = (control, texto) => h("label", { class: "ra-adm-check-row" }, control, texto);

  const resumen = sb
    ? ["Activo", sb.simulated_clock ? sb.now.slice(0, 16).replace("T", " ") : "reloj real", sb.location?.name].filter(Boolean).join(" · ")
    : "Apagado";
  return h("div", { class: "ra-adm-grupo" },
    h("h3", {}, "Modo prueba"),
    h("p", { class: `ra-hint ${sb ? "is-warn" : ""}` }, icon(sb ? "alerta" : "reloj", 16), h("span", {}, resumen)),
    h("p", { class: "ra-adm-cap" }, "Lo que haga en modo prueba va a otro lugar: sus datos reales no se tocan. Solo un admin lo prende o lo apaga."),
    check(active, "Modo prueba activo"),
    row("Transcripción (STT)", stt), row("Traducción y resúmenes (LLM)", llm),
    check(useClock, "Simular la hora (Las Vegas)"),
    h("div", { class: "field" }, clock),
    row("Ubicación", venue),
    h("div", { class: "ra-adm-acciones" },
      boton("Guardar", guardar, { variante: "primary", "data-accion": "sb-guardar", nombre: `Guardar modo prueba de ${u.username}` }),
      sb?.simulated_clock ? boton("+15 min", (b) => adelantar(b, 15), { "data-accion": "sb-15", nombre: `Adelantar 15 minutos el reloj de ${u.username}` }) : null,
      sb?.simulated_clock ? boton("+1 h", (b) => adelantar(b, 60), { "data-accion": "sb-60", nombre: `Adelantar 1 hora el reloj de ${u.username}` }) : null));
}

/** Repinta solo la fila `fila` con los datos nuevos del usuario: conserva lo abierto y el foco (por data-accion). */
async function refrescarFila(fila, username, venues) {
  const { users } = await Admin.users();
  const u = users.find((x) => x.username === username);
  if (!u) { fila.remove(); return; }
  const abiertos = [fila, ...fila.querySelectorAll("details")].map((d) => d.open);
  const accionConFoco = fila.contains(document.activeElement) ? document.activeElement.dataset?.accion : null;
  const nueva = UserRow(u, venues);
  [nueva, ...nueva.querySelectorAll("details")].forEach((d, i) => { d.open = abiertos[i] ?? false; });
  fila.replaceWith(nueva);
  if (accionConFoco) { // si ese botón ya no existe (p. ej. «Cerrar sesiones» sin sesiones), el foco queda en la fila y no se pierde
    (nueva.querySelector(`[data-accion="${accionConFoco}"]`) ?? nueva.querySelector("summary"))?.focus();
  }
}

const Marcas = (u) => h("span", { class: "ra-g-marcas" },
  u.is_admin ? h("span", { class: "ra-tag is-new" }, "admin") : null,
  u.is_active ? null : Tag("desactivado"),
  u.sandbox ? h("span", { class: "ra-g-marca is-pendiente" }, "modo prueba") : null,
  u.must_change_password ? h("span", { class: "ra-g-marca" }, "debe cambiar contraseña") : null);

export function UserRow(u, venues) {
  const repintar = () => refrescarFila(fila, u.username, venues);
  const boton = botonDe(u.username);
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

  const fila = h("details", { class: "ra-adm-usuario" },
    h("summary", { class: `ra-adm-fila${u.is_active ? "" : " is-off"}` },
      h("span", { class: "ra-adm-fila-cuerpo" }, h("span", { class: "ra-adm-fila-nombre" }, u.username), Marcas(u)),
      h("span", { class: "ra-adm-fila-side" }, h("span", {}, ultimoIngreso(u.last_login)), Chevron())),
    h("div", { class: "ra-adm-usuario-det" },
      h("div", { class: "ra-adm-grupo" },
        h("h3", {}, "Acciones"),
        h("p", { class: "ra-adm-cap" }, `${u.open_sessions} sesiones abiertas · ${u.itinerary_items} charlas en el itinerario`),
        h("div", { class: "ra-adm-acciones" },
          boton("Resetear contraseña", reset, { "data-accion": "reset" }),
          u.open_sessions ? boton("Cerrar sesiones", revoke, { "data-accion": "revocar" }) : null,
          u.is_admin ? null : boton(u.is_active ? "Desactivar" : "Activar", toggle,
            { variante: u.is_active ? "ghost" : "secondary", extra: u.is_active ? " ra-adm-btn-err" : "", nombre: `${u.is_active ? "Desactivar a" : "Activar a"} ${u.username}`, "data-accion": "activo" }))),
      SandboxPanel(u, venues, repintar)));
  return fila;
}

/** «Nuevo usuario»: las reglas a la vista junto a cada campo; si el servidor lo rechaza, no se vacía y el error queda junto al campo. */
function NewUserForm(alCrear, alCancelar) {
  const campo = (id, label, ayuda, attrs) => {
    const aviso = h("p", { class: "ra-hint is-error", id: `${id}-error`, hidden: true });
    const nota = h("span", { class: "ra-adm-ayuda", id: `${id}-ayuda` }, ayuda);
    const input = h("input", { id, name: id, required: true, "aria-describedby": nota.id, ...attrs });
    return { input, error: aviso, ayuda: nota, el: h("div", { class: "field" }, h("label", { class: "label", for: id }, label), input, nota, aviso) };
  };
  const user = campo("new-username", "Usuario", "2 a 40 caracteres: minúsculas, números, punto, guion o guion bajo.",
    { autocapitalize: "none", autocomplete: "off", pattern: "[a-z0-9_.\\-]{2,40}" });
  const pwd = campo("new-password", "Contraseña temporal", `Al menos ${MIN_LENGTH} caracteres. Al primer ingreso va a tener que elegir la suya.`,
    { type: "text", autocomplete: "off", minlength: MIN_LENGTH });
  const limpiar = () => [user, pwd].forEach((c) => { c.error.hidden = true; c.error.textContent = ""; c.input.removeAttribute("aria-invalid"); c.input.setAttribute("aria-describedby", c.ayuda.id); });
  const marcar = (c, texto) => { c.error.textContent = texto; c.error.hidden = false; c.input.setAttribute("aria-invalid", "true"); c.input.setAttribute("aria-describedby", `${c.ayuda.id} ${c.error.id}`); c.input.focus(); };
  const crear = h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Crear usuario");
  const cancelar = h("button", { type: "button", class: "ra-btn ra-btn-ghost", onclick: alCancelar }, "Cancelar");
  const form = h("form", { class: "ra-adm-form", "aria-label": "Nuevo usuario", onsubmit: async (e) => {
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
    user.el, pwd.el, h("div", { class: "ra-adm-acciones" }, crear, cancelar));
  return form;
}

/** Cabecera plegable: «Usuarios · N» y el botón «Nuevo usuario» (es el summary: se abre con toque, Enter o espacio). */
function CabeceraNuevo(total) {
  const mas = icon("agregar", 16);
  mas.classList.add("ra-adm-nuevo-ico");
  return h("summary", {}, h("h2", { class: "label" }, "Usuarios", total), h("span", { class: "ra-btn ra-btn-secondary ra-adm-btn-s" }, mas, "Nuevo usuario"));
}

export function viewAdminUsuarios(view) {
  let venues = null; // se piden adentro de la carga: así el marco ya está armado y no se pisa si cambió de pestaña
  const total = h("span", {});
  const lista = Cargable({
    cargar: async () => {
      if (!venues) venues = await Admin.venues().then((r) => r.venues, () => []); // sin catálogo: el modo prueba anda igual, sin ubicación
      const datos = await Admin.users();
      total.textContent = ` · ${datos.users.length}`;
      return datos;
    },
    pintar: ({ users }) => h("div", { class: "ra-adm-lista" }, users.map((u) => UserRow(u, venues))),
    esVacio: ({ users }) => !users.length,
    textoVacio: "Todavía no hay usuarios.",
    textoCargando: "Cargando usuarios…",
  });
  const nuevo = h("details", { class: "ra-adm-nuevo" });
  const cerrar = () => { nuevo.open = false; };
  nuevo.append(CabeceraNuevo(total), NewUserForm(() => {
    cerrar();
    void lista.recargar({ silencioso: true, alFallar: () => avisar("Usuario creado, pero no se pudo actualizar la lista. Recargá la pantalla.", { error: true }) });
  }, cerrar));
  AdminShell(view, "usuarios", nuevo, lista);
}
