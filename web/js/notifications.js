// Ajustes › Notificaciones en el celular (Web Push): avisos de lo fijado y de cambios aunque la app esté cerrada.
// En iPhone solo con la app instalada en la pantalla de inicio (iOS 16.4 o posterior).
import { getToken, Push, Ubicacion, Viajes } from "./api.js";
import { locationEnabled, reportVenue, setLocationEnabled, setVenueReportEnabled } from "./location.js";
import { OfertasSettings } from "./ofertas.js";
import { Button, h, mensajeError, toast } from "./ui.js";

const esIOS = ({ navigator: n }) => /iPhone|iPad|iPod/.test(n.userAgent ?? "") || (n.platform === "MacIntel" && n.maxTouchPoints > 1); // el iPad se presenta como Mac
const estaInstalada = (env) => env.navigator.standalone === true || env.matchMedia?.("(display-mode: standalone)")?.matches === true;

/** "ok" | "ios_sin_instalar" (iPhone/iPad en una pestaña de Safari: ahí iOS no deja activar push) | "no_soportado". */
export function estadoPush(env = globalThis) {
  if (!("serviceWorker" in (env.navigator ?? {})) || !("PushManager" in env) || !("Notification" in env)) return "no_soportado";
  return esIOS(env) && !estaInstalada(env) ? "ios_sin_instalar" : "ok";
}
const supported = () => estadoPush() === "ok";

// Con el service worker que no contesta (iOS sin instalar, Safari trabado) `.ready` o getSubscription no resuelven nunca:
// sin tope el interruptor quedaba deshabilitado para siempre y nadie se enteraba.
export const READY_TIMEOUT_MS = 5000;
const MSG_SW_INSTALANDO = "La app todavía se está instalando: cerrala y abrila de nuevo.";
const MSG_SIN_PUSH = "Este dispositivo no deja suscribirse a notificaciones.";
const MSG_SW_NO_RESPONDE = "El servicio de notificaciones del celular no responde. Cerrá y abrí la app y probá de nuevo.";

function conTope(promesa, ms, mensaje = MSG_SW_NO_RESPONDE) {
  let timer;
  const tope = new Promise((_, rechazar) => { timer = setTimeout(() => rechazar(new Error(mensaje)), ms); });
  return Promise.race([promesa, tope]).finally(() => clearTimeout(timer));
}

// La clave VAPID viene en base64url; pushManager.subscribe la quiere en bytes.
const keyBytes = (b64) => Uint8Array.from(atob(b64.replaceAll("-", "+").replaceAll("_", "/").padEnd(Math.ceil(b64.length / 4) * 4, "=")), (c) => c.codePointAt(0));

/**
 * El registro del service worker y la suscripción actual (o null), con tope. Si falla, el mensaje dice cuál de los dos:
 * el service worker todavía no está activo (la app se está instalando) o el navegador no deja suscribirse (pushManager).
 */
export async function currentSubscription(sw = navigator.serviceWorker, timeoutMs = READY_TIMEOUT_MS) {
  const reg = await conTope(Promise.resolve(sw.ready), timeoutMs, MSG_SW_INSTALANDO).catch(() => { throw new Error(MSG_SW_INSTALANDO); });
  const sub = await conTope(Promise.resolve().then(() => reg.pushManager.getSubscription()), timeoutMs, MSG_SIN_PUSH)
    .catch(() => { throw new Error(MSG_SIN_PUSH); }); // un rechazo del navegador o que no conteste: el detalle técnico no le sirve a nadie
  return { reg, sub };
}

/** El texto que reemplaza al interruptor cuando las notificaciones no se pueden activar desde acá. */
export function textoNoSoportado(estado) {
  return estado === "ios_sin_instalar"
    ? "Para recibir avisos en iPhone, agregá la app a la pantalla de inicio con «Abrir como app web» prendido y abrila desde el ícono."
    : "Este navegador no las soporta. En iPhone, instalá la app en la pantalla de inicio y abrila desde ahí.";
}

// El SW no ve localStorage: le dejamos el token en la Cache API para que, si el navegador rota la suscripción con la app
// cerrada (pushsubscriptionchange), pueda mandar la nueva al servidor. Si no alcanza, syncSubscription lo hace al abrir.
const SW_DATOS = "sw-datos";
const ENDPOINT_KEY = "reinventar.pushEndpoint";

async function guardarTokenParaSw() {
  const cache = await caches.open(SW_DATOS);
  const token = getToken();
  if (token) await cache.put("/__token", new Response(token)); else await cache.delete("/__token");
}

const lastEndpoint = () => { try { return localStorage.getItem(ENDPOINT_KEY); } catch { return null; } };
const rememberEndpoint = (v) => { try { v ? localStorage.setItem(ENDPOINT_KEY, v) : localStorage.removeItem(ENDPOINT_KEY); } catch {} };

/** Al abrir la app: renueva el token que lee el SW y, si la suscripción cambió desde la última vez, la manda al servidor. */
export async function syncSubscription() {
  if (!supported() || !getToken() || Notification.permission !== "granted") return;
  const { sub } = await currentSubscription();
  if (!sub) return;
  await guardarTokenParaSw();
  if (sub.endpoint === lastEndpoint()) return;
  await Push.subscribe(sub.toJSON());
  rememberEndpoint(sub.endpoint);
}
if (supported()) {
  // Al cargar y cada vez que la app vuelve a primer plano: así el token del SW se renueva aunque el login haya sido
  // después de cargar el módulo, o la contraseña/sesión haya cambiado.
  const sync = () => void syncSubscription().catch(() => {});
  sync();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") sync(); });
  // setToken (api.js) avisa en cada login: el token nuevo le llega al service worker en el momento, no en la próxima apertura.
  window.addEventListener("reinventar:token", sync);
}

async function enable() {
  // El permiso se pide primero y sin ningún await antes: iOS solo lo muestra si sale directo del toque del usuario.
  if (await Notification.requestPermission() !== "granted") throw new Error("Sin permiso para notificaciones: activalo en los ajustes del navegador.");
  const { key } = await Push.key();
  if (!key) throw new Error("Las notificaciones todavía no están configuradas en el servidor.");
  const { reg, sub } = await currentSubscription();
  const subscription = sub || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
  await Push.subscribe(subscription.toJSON());
  rememberEndpoint(subscription.endpoint);
  await guardarTokenParaSw();
}

/** Da de baja las notificaciones de este dispositivo (también al cerrar sesión: que no le lleguen al próximo). */
export async function disable({ timeoutMs = READY_TIMEOUT_MS } = {}) {
  rememberEndpoint(null);
  await caches.delete(SW_DATOS).catch(() => {});
  // getRegistration y no .ready: .ready no resuelve nunca si no hay service worker. Con tope: si el service worker no
  // contesta, no se cuelga el cierre de sesión (ya borramos lo nuestro; la baja del push la limpia el servidor al fallar).
  let sub = null;
  try {
    const reg = await conTope(Promise.resolve(navigator.serviceWorker?.getRegistration()), timeoutMs);
    sub = await conTope(Promise.resolve(reg?.pushManager?.getSubscription()), timeoutMs);
  } catch { return; }
  if (!sub) return;
  await Push.unsubscribe(sub.endpoint).catch(() => {});
  await sub.unsubscribe();
}

const Switch = (id, label) => {
  const input = h("input", { type: "checkbox", id, disabled: true });
  return { input, row: h("label", { class: "actions is-center", for: id }, input, label) };
};

/**
 * Prende «Usar en qué sede estoy»: sin la ubicación no sirve, así que si «Usar mi ubicación» está apagada se prende
 * también (antes saltaba un aviso y la casilla se destildaba sola: parecía que no se podía tildar). Si después no se
 * puede leer la ubicación, todo vuelve a como estaba.
 */
export async function prenderSede(d) {
  const ubicacionYaPrendida = d.ubicacionPrendida();
  if (!ubicacionYaPrendida) d.prenderUbicacion();
  d.marcarSede(true);
  await d.guardar();
  if (await d.leerSede()) return;
  d.marcarSede(false);
  if (!ubicacionYaPrendida) d.apagarUbicacion();
  await d.guardar();
  throw new Error("No pudimos leer tu ubicación: revisá el permiso del navegador.");
}

/** Avisos de Viajes (vuelos y hoteles que cargaste en #/viajes): check-in web, hotel y estado del vuelo. */
function ViajesSettings() {
  const campos = [["viajes_checkin", "Avisarme cuándo abre el check-in de mis vuelos"],
    ["viajes_hoteles", "Avisarme el check-in y el check-out del hotel"],
    ["viajes_estado", "Avisarme demoras y cambios de puerta de mis vuelos"],
    ["viajes_pendientes", "Recordarme los pendientes del viaje (fecha límite y los días antes de salir)"]];
  const switches = campos.map(([clave, texto]) => ({ clave, ...Switch(`push-${clave}`, texto) }));
  const save = () => Viajes.savePrefs(Object.fromEntries(switches.map((s) => [s.clave, s.input.checked])));
  for (const sw of switches) {
    sw.input.onchange = async () => {
      sw.input.disabled = true;
      try { await save(); } catch (err) { sw.input.checked = !sw.input.checked; toast(mensajeError(err)); }
      sw.input.disabled = false;
    };
  }
  void Viajes.prefs().then((p) => { for (const sw of switches) { sw.input.checked = p[sw.clave] !== false; sw.input.disabled = false; } }).catch(() => {});
  return h("div", { class: "stack" }, ...switches.map((s) => s.row),
    h("p", { class: "caption" }, "Los vuelos, hoteles y pendientes se cargan en Viaje. Las alertas de demora y puerta necesitan que el servidor tenga activado el estado de vuelos."));
}

/** "Recordarme grabar" y "Avisarme de eventos nuevos" (prendidos) y "Usar en qué sede estoy para los avisos" (apagado;
 *  pide el permiso al prenderlo). */
function ReminderSettings() {
  const grabar = Switch("push-grabar", "Recordarme grabar");
  const nuevos = Switch("push-eventos-nuevos", "Avisarme de eventos nuevos");
  const sede = Switch("push-sede", "Usar en qué sede estoy para los avisos");
  const save = () => Push.savePrefs({ grabar: grabar.input.checked, ubicacion: sede.input.checked, eventos_nuevos: nuevos.input.checked });
  const toggleSimple = (sw) => async () => {
    sw.input.disabled = true;
    try { await save(); } catch (err) { sw.input.checked = !sw.input.checked; toast(mensajeError(err)); }
    sw.input.disabled = false;
  };

  grabar.input.onchange = toggleSimple(grabar);
  nuevos.input.onchange = toggleSimple(nuevos);
  // «Usar mi ubicación» está en otra parte de la pantalla (app.js): se prende y se apaga desde acá también, con su casilla.
  const casillaUbicacion = (on) => { const c = document.getElementById("use-location"); if (c) c.checked = on; };
  const sedeConUbicacion = {
    ubicacionPrendida: locationEnabled,
    prenderUbicacion: () => { setLocationEnabled(true); casillaUbicacion(true); },
    apagarUbicacion: () => { setLocationEnabled(false); casillaUbicacion(false); },
    guardar: save,
    marcarSede: (on) => { sede.input.checked = on; setVenueReportEnabled(on); },
    leerSede: () => reportVenue({ force: true, ask: true }),
  };
  sede.input.onchange = async () => {
    sede.input.disabled = true;
    const on = sede.input.checked;
    try {
      if (on) await prenderSede(sedeConUbicacion);
      else { await save(); setVenueReportEnabled(false); await Ubicacion.clear(); }
      toast(on ? "Listo: los avisos van a tener en cuenta en qué sede estás." : "Listo: borramos la sede guardada.");
    } catch (err) {
      if (on) sede.input.checked = false;
      toast(mensajeError(err));
    }
    sede.input.disabled = false;
  };
  const viajes = ViajesSettings();
  void Push.prefs().then((p) => {
    grabar.input.checked = p.grabar;
    sede.input.checked = p.ubicacion;
    nuevos.input.checked = p.eventos_nuevos !== false;
    setVenueReportEnabled(p.ubicacion);
    grabar.input.disabled = false;
    nuevos.input.disabled = false;
    sede.input.disabled = false;
  }).catch(() => {});
  return h("div", { class: "stack" },
    grabar.row,
    h("p", { class: "caption" }, "Cuando empieza una charla de tu itinerario y nadie la está grabando, te avisamos. Tocás el aviso y queda lista para grabar."),
    nuevos.row,
    h("p", { class: "caption" }, "Un aviso cuando aparecen eventos nuevos (nunca de noche). Si se cancela uno de tu itinerario, te avisamos igual."),
    sede.row,
    h("p", { class: "caption" }, "Solo cuando la app está abierta. Mandamos el nombre de la sede, no tu posición. Deja de usarse a los 45 min y se borra a las 2 h."),
    viajes);
}

/** «Avisarme de ofertas» (web/js/ofertas.js): se muestra también donde el push no anda (iPhone sin instalar), para explicar por qué. */
const ofertas = () => OfertasSettings({ estado: estadoPush, permiso: () => globalThis.Notification?.permission, activarDispositivo: enable });

export function PushSettings() {
  void syncSubscription().catch(() => {});
  const box = h("div", { class: "stack" }, h("h2", { class: "label" }, "Notificaciones en el celular"));
  const estado = estadoPush();
  if (estado !== "ok") {
    box.append(h("p", { class: "caption" }, textoNoSoportado(estado)), ofertas());
    return box;
  }
  const toggle = h("input", { type: "checkbox", id: "push-on", disabled: true });
  const status = h("p", { class: "caption" }, "Te avisamos cuándo salir y cuándo empieza lo que fijaste, y si AWS cambia algo de tu itinerario, aunque la app esté cerrada.");
  const testBtn = Button("Probar una notificación", { onclick: async () => {
    try { const r = await Push.test(); toast(`Enviada a ${r.devices} dispositivo${r.devices === 1 ? "" : "s"}.`); } catch (err) { toast(mensajeError(err)); }
  } });
  testBtn.hidden = true; // solo con una suscripción confirmada: antes de saberlo no se ofrece una prueba que no puede andar
  toggle.onchange = async () => {
    toggle.disabled = true;
    try {
      if (toggle.checked) { await enable(); toast("Notificaciones activadas."); } else { await disable(); toast("Notificaciones apagadas."); }
    } catch (err) { toggle.checked = !toggle.checked; toast(mensajeError(err, "No se pudieron activar las notificaciones. Probá de nuevo.")); }
    toggle.disabled = false;
    testBtn.hidden = !toggle.checked;
  };
  void currentSubscription().then(({ sub }) => {
    toggle.checked = Boolean(sub) && Notification.permission === "granted";
    toggle.disabled = false;
    testBtn.hidden = !toggle.checked;
  }).catch((err) => {
    // El service worker no contestó: el interruptor queda disponible (apagado, sin prueba) y se explica por qué.
    toggle.checked = false;
    toggle.disabled = false;
    testBtn.hidden = true;
    status.textContent = mensajeError(err);
  });
  box.append(h("label", { class: "actions is-center", for: "push-on" }, toggle, "Activar notificaciones"), status, h("div", { class: "actions" }, testBtn),
    ReminderSettings(), ofertas());
  return box;
}
