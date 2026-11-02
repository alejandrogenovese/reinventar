// Passkeys (Face ID / huella) con la API WebAuthn del navegador. El servidor arma las opciones y verifica la firma.
import { Passkeys } from "./api.js";
import { Button, h, toast } from "./ui.js";

const OFFER_DISMISSED = "reinventar.passkeyOfferDismissed";
const REGISTERED_HERE = "reinventar.passkeyRegistered";

// --- base64url <-> bytes (las opciones vienen en JSON; WebAuthn trabaja con ArrayBuffer) ---------
const toBytes = (b64url) => Uint8Array.from(atob(b64url.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(b64url.length / 4) * 4, "=")), (c) => c.charCodeAt(0));
const toB64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

function creationOptions(o) {
  return { ...o, challenge: toBytes(o.challenge), user: { ...o.user, id: toBytes(o.user.id) },
    excludeCredentials: (o.excludeCredentials || []).map((c) => ({ ...c, id: toBytes(c.id) })) };
}
function requestOptions(o) {
  return { ...o, challenge: toBytes(o.challenge), allowCredentials: (o.allowCredentials || []).map((c) => ({ ...c, id: toBytes(c.id) })) };
}
function credentialJSON(cred) {
  if (typeof cred.toJSON === "function") return cred.toJSON();
  const r = cred.response;
  const response = r.attestationObject
    ? { clientDataJSON: toB64url(r.clientDataJSON), attestationObject: toB64url(r.attestationObject), transports: r.getTransports?.() || [] }
    : { clientDataJSON: toB64url(r.clientDataJSON), authenticatorData: toB64url(r.authenticatorData), signature: toB64url(r.signature),
        userHandle: r.userHandle ? toB64url(r.userHandle) : null };
  return { id: cred.id, rawId: toB64url(cred.rawId), type: cred.type, response,
    clientExtensionResults: cred.getClientExtensionResults?.() || {}, authenticatorAttachment: cred.authenticatorAttachment };
}

/** true si este celular tiene Face ID / huella disponible para la web. */
export async function isSupported() {
  try { return !!window.PublicKeyCredential && (await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()); } catch { return false; }
}

const deviceName = () => {
  const ua = navigator.userAgent;
  if (/iphone/i.test(ua)) return "iPhone";
  if (/ipad/i.test(ua)) return "iPad";
  if (/android/i.test(ua)) return "Android";
  if (/mac/i.test(ua)) return "Mac";
  return "Este dispositivo";
};
const cancelled = (e) => e?.name === "NotAllowedError" || e?.name === "AbortError";

export async function register() {
  const { challenge_id, options } = await Passkeys.registerOptions();
  const cred = await navigator.credentials.create({ publicKey: creationOptions(options) });
  await Passkeys.registerVerify(challenge_id, credentialJSON(cred), deviceName());
  try { localStorage.setItem(REGISTERED_HERE, "1"); } catch {}
}

/** Login con passkey: devuelve la misma respuesta que /api/login, o null si la persona canceló. */
export async function login() {
  const { challenge_id, options } = await Passkeys.loginOptions();
  let cred;
  try { cred = await navigator.credentials.get({ publicKey: requestOptions(options) }); } catch (e) { if (cancelled(e)) return null; throw e; }
  return Passkeys.loginVerify(challenge_id, credentialJSON(cred));
}

async function activate(onDone) {
  try { await register(); toast("Listo: la próxima entrás con Face ID / huella"); onDone?.(); }
  catch (e) { toast(cancelled(e) ? "Cancelado" : e.message || "No se pudo activar"); }
}

// --- UI ----------------------------------------------------------------------
/** Botón "Entrar con Face ID / huella" para la pantalla de login (vacío si el dispositivo no lo soporta). */
export function PasskeyLoginButton(onLogin, onError) {
  const slot = h("div", { class: "actions" });
  isSupported().then((ok) => {
    if (!ok) return;
    slot.append(Button("Entrar con Face ID / huella", { onclick: async () => {
      try { const r = await login(); if (r) onLogin(r); } catch (e) { onError(e.status === 401 ? "Esa passkey no está registrada. Entrá con contraseña y activala en Ajustes." : e.message); }
    } }));
  });
  return slot;
}

/** Aviso en el inicio para activar la passkey en este celular (una vez; se puede descartar). */
export function PasskeyOffer() {
  const slot = h("div");
  try { if (localStorage.getItem(OFFER_DISMISSED) === "1" || localStorage.getItem(REGISTERED_HERE) === "1") return slot; } catch {}
  isSupported().then((ok) => {
    if (!ok) return;
    const dismiss = () => { try { localStorage.setItem(OFFER_DISMISSED, "1"); } catch {} slot.replaceChildren(); };
    slot.append(h("div", { class: "notice stack" },
      h("strong", {}, "Entrá con Face ID / huella"),
      h("span", { class: "caption" }, "Así no tenés que tipear la contraseña en el evento. No se guarda ningún dato biométrico."),
      h("div", { class: "actions" },
        Button("Activar", { onclick: () => activate(dismiss) }),
        Button("Ahora no", { onclick: dismiss }))));
  });
  return slot;
}

/** Sección de Ajustes: passkeys registradas (con borrar) y botón para activar en este dispositivo. */
export function PasskeySettings() {
  const box = h("div", { class: "stack" });
  const when = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString("es-AR") : "nunca");
  async function load() {
    const [{ passkeys }, ok] = await Promise.all([Passkeys.list(), isSupported()]);
    box.replaceChildren(
      h("h2", { class: "label" }, "Face ID / huella"),
      passkeys.length ? "" : h("p", { class: "caption" }, "Todavía no activaste el ingreso con Face ID / huella."),
      ...passkeys.map((p) => h("div", { class: "notice actions", style: { justifyContent: "space-between", alignItems: "center" } },
        h("span", {}, `${p.device || "Dispositivo"} · último uso: ${when(p.last_used_at)}`),
        Button("Quitar", { variant: "danger", onclick: async () => { await Passkeys.remove(p.id); try { localStorage.removeItem(REGISTERED_HERE); } catch {} load(); } }))),
      ok ? h("div", { class: "actions" }, Button("Activar en este dispositivo", { onclick: () => activate(load) }))
         : h("p", { class: "caption" }, "Este navegador no permite Face ID / huella."));
  }
  load().catch((e) => box.replaceChildren(h("div", { class: "notice err" }, e.message)));
  return box;
}
