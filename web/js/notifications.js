// Ajustes › Notificaciones en el celular (Web Push): avisos de lo fijado y de cambios aunque la app esté cerrada.
// En iPhone solo con la app instalada en la pantalla de inicio (iOS 16.4 o posterior).
import { Push } from "./api.js";
import { Button, h, toast } from "./ui.js";

const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

// La clave VAPID viene en base64url; pushManager.subscribe la quiere en bytes.
const keyBytes = (b64) => Uint8Array.from(atob(b64.replaceAll("-", "+").replaceAll("_", "/").padEnd(Math.ceil(b64.length / 4) * 4, "=")), (c) => c.codePointAt(0));

async function currentSubscription() {
  const reg = await navigator.serviceWorker.ready;
  return { reg, sub: await reg.pushManager.getSubscription() };
}

async function enable() {
  const { key } = await Push.key();
  if (!key) throw new Error("Las notificaciones todavía no están configuradas en el servidor.");
  if (await Notification.requestPermission() !== "granted") throw new Error("Sin permiso para notificaciones: activalo en los ajustes del navegador.");
  const { reg, sub } = await currentSubscription();
  const subscription = sub || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
  await Push.subscribe(subscription.toJSON());
}

async function disable() {
  const { sub } = await currentSubscription();
  if (!sub) return;
  await Push.unsubscribe(sub.endpoint).catch(() => {});
  await sub.unsubscribe();
}

export function PushSettings() {
  const box = h("div", { class: "stack" }, h("h2", { class: "label" }, "Notificaciones en el celular"));
  if (!supported()) {
    box.append(h("p", { class: "caption" }, "Este navegador no las soporta. En iPhone, instalá la app en la pantalla de inicio y abrila desde ahí."));
    return box;
  }
  const toggle = h("input", { type: "checkbox", id: "push-on", disabled: true });
  const status = h("p", { class: "caption" }, "Te avisamos cuándo salir y cuándo empieza lo que fijaste 📌, y si AWS cambia algo de tu itinerario, aunque la app esté cerrada.");
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
  box.append(h("label", { class: "actions is-center", for: "push-on" }, toggle, "Activar notificaciones"), status, h("div", { class: "actions" }, testBtn));
  return box;
}
