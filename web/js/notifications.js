// Ajustes › Notificaciones en el celular (Web Push): avisos de lo fijado y de cambios aunque la app esté cerrada.
// En iPhone solo con la app instalada en la pantalla de inicio (iOS 16.4 o posterior).
import { getToken, Push, Ubicacion } from "./api.js";
import { locationEnabled, reportVenue, setVenueReportEnabled } from "./location.js";
import { Button, h, toast } from "./ui.js";

const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

// La clave VAPID viene en base64url; pushManager.subscribe la quiere en bytes.
const keyBytes = (b64) => Uint8Array.from(atob(b64.replaceAll("-", "+").replaceAll("_", "/").padEnd(Math.ceil(b64.length / 4) * 4, "=")), (c) => c.codePointAt(0));

async function currentSubscription() {
  const reg = await navigator.serviceWorker.ready;
  return { reg, sub: await reg.pushManager.getSubscription() };
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
if (supported()) void syncSubscription().catch(() => {});

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
export async function disable() {
  // getRegistration y no .ready: .ready no resuelve nunca si no hay service worker (y el logout quedaría colgado).
  const reg = await navigator.serviceWorker?.getRegistration();
  const sub = await reg?.pushManager?.getSubscription();
  rememberEndpoint(null);
  await caches.delete(SW_DATOS).catch(() => {});
  if (!sub) return;
  await Push.unsubscribe(sub.endpoint).catch(() => {});
  await sub.unsubscribe();
}

const Switch = (id, label) => {
  const input = h("input", { type: "checkbox", id, disabled: true });
  return { input, row: h("label", { class: "actions is-center", for: id }, input, label) };
};

/** "Recordarme grabar" y "Avisarme de eventos nuevos" (prendidos) y "Usar en qué sede estoy para los avisos" (apagado;
 *  pide el permiso al prenderlo). */
function ReminderSettings() {
  const grabar = Switch("push-grabar", "Recordarme grabar");
  const nuevos = Switch("push-eventos-nuevos", "Avisarme de eventos nuevos");
  const sede = Switch("push-sede", "Usar en qué sede estoy para los avisos");
  const save = () => Push.savePrefs({ grabar: grabar.input.checked, ubicacion: sede.input.checked, eventos_nuevos: nuevos.input.checked });
  const toggleSimple = (sw) => async () => {
    sw.input.disabled = true;
    try { await save(); } catch (err) { sw.input.checked = !sw.input.checked; toast(err.message); }
    sw.input.disabled = false;
  };

  grabar.input.onchange = toggleSimple(grabar);
  nuevos.input.onchange = toggleSimple(nuevos);
  sede.input.onchange = async () => {
    sede.input.disabled = true;
    const on = sede.input.checked;
    try {
      if (on && !locationEnabled()) throw new Error("Primero prendé «Usar mi ubicación».");
      await save();
      setVenueReportEnabled(on);
      if (on && !(await reportVenue({ force: true, ask: true }))) {
        sede.input.checked = false;
        setVenueReportEnabled(false);
        await save();
        throw new Error("No pudimos leer tu ubicación: revisá el permiso del navegador.");
      }
      if (!on) await Ubicacion.clear();
      toast(on ? "Listo: los avisos van a tener en cuenta en qué sede estás." : "Listo: borramos la sede guardada.");
    } catch (err) {
      if (on) sede.input.checked = false;
      toast(err.message);
    }
    sede.input.disabled = false;
  };
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
    h("p", { class: "caption" }, "Solo cuando la app está abierta. Mandamos el nombre de la sede, no tu posición. Deja de usarse a los 45 min y se borra a las 2 h."));
}

export function PushSettings() {
  const box = h("div", { class: "stack" }, h("h2", { class: "label" }, "Notificaciones en el celular"));
  if (!supported()) {
    box.append(h("p", { class: "caption" }, "Este navegador no las soporta. En iPhone, instalá la app en la pantalla de inicio y abrila desde ahí."));
    return box;
  }
  const toggle = h("input", { type: "checkbox", id: "push-on", disabled: true });
  const status = h("p", { class: "caption" }, "Te avisamos cuándo salir y cuándo empieza lo que fijaste, y si AWS cambia algo de tu itinerario, aunque la app esté cerrada.");
  const testBtn = Button("Probar una notificación", { onclick: async () => {
    try { const r = await Push.test(); toast(`Enviada a ${r.devices} dispositivo${r.devices === 1 ? "" : "s"}.`); } catch (err) { toast(err.message); }
  } });
  toggle.onchange = async () => {
    toggle.disabled = true;
    try {
      if (toggle.checked) { await enable(); toast("Notificaciones activadas."); } else { await disable(); toast("Notificaciones apagadas."); }
    } catch (err) { toggle.checked = !toggle.checked; toast(err.message); }
    toggle.disabled = false;
    testBtn.hidden = !toggle.checked;
  };
  void currentSubscription().then(({ sub }) => {
    toggle.checked = Boolean(sub) && Notification.permission === "granted";
    toggle.disabled = false;
    testBtn.hidden = !toggle.checked;
  });
  box.append(h("label", { class: "actions is-center", for: "push-on" }, toggle, "Activar notificaciones"), status, h("div", { class: "actions" }, testBtn),
    ReminderSettings());
  return box;
}
