// Instalar la PWA: Android usa el diálogo nativo (beforeinstallprompt); iPhone no tiene API, se explican los pasos.
import { Button, h } from "./ui.js";

const DISMISSED = "reinventar.installDismissed";
let deferredPrompt = null;

// Chrome dispara el evento una sola vez y temprano: se captura al cargar el módulo.
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredPrompt = e; });
window.addEventListener("appinstalled", () => { deferredPrompt = null; });

const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
// Navegadores dentro de otras apps (WhatsApp, Instagram, Gmail...) no permiten instalar.
const isInAppBrowser = () => /FBAN|FBAV|Instagram|Line\/|WhatsApp|GSA\//i.test(navigator.userAgent) || /; wv\)/.test(navigator.userAgent);

function steps() {
  if (isInAppBrowser()) return "Estás en el navegador de otra app. Abrí este link en Chrome (Android) o Safari (iPhone) y volvé a esta pantalla.";
  if (isIOS()) return "En Safari: tocá Compartir (el cuadrado con la flecha hacia arriba) → Agregar a inicio → Agregar.";
  return "En Chrome: menú ⋮ (arriba a la derecha) → Instalar app (o Agregar a pantalla principal).";
}

async function install(status) {
  if (!deferredPrompt) { status.textContent = steps(); return; }
  deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  deferredPrompt = null;
  status.textContent = outcome === "accepted" ? "Listo: la vas a encontrar en la pantalla de inicio." : steps();
}

/** Bloque "Instalar app" o null si ya corre instalada. `dismissible` agrega "Ahora no" (para la pantalla de inicio). */
export function InstallPrompt({ dismissible = false } = {}) {
  if (isStandalone()) return null;
  if (dismissible) { try { if (localStorage.getItem(DISMISSED) === "1") return null; } catch {} }
  const status = h("p", { class: "caption" }, isIOS() || isInAppBrowser() ? steps() : "");
  const el = h("div", { class: "notice stack" },
    h("strong", {}, "Instalá ReinventAR en el celular"),
    h("span", { class: "caption" }, "Queda como app en la pantalla de inicio, abre a pantalla completa y funciona sin señal."),
    status,
    h("div", { class: "actions" },
      isIOS() || isInAppBrowser() ? null : Button("Instalar app", { onclick: () => install(status) }),
      dismissible ? Button("Ahora no", { onclick: () => { try { localStorage.setItem(DISMISSED, "1"); } catch {} el.remove(); } }) : null));
  return el;
}
