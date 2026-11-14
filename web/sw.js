// Service worker de ReinventAR: la app abre sin red; la API nunca se cachea.
const VERSION = "reinventar-v0.21.0";
const SHELL = [
  "/", "/index.html", "/css/tokens.css", "/css/base.css", "/styles.css", "/manifest.webmanifest",
  "/js/app.js", "/js/api.js", "/js/store.js", "/js/recorder.js", "/js/ui.js", "/js/itinerary.js", "/js/map.js", "/js/account.js", "/js/adminLlm.js", "/js/adminEventos.js", "/js/install.js", "/js/passkey.js", "/js/knowledge.js", "/js/lleno.js", "/js/explore.js", "/js/ask.js", "/js/talkpicker.js", "/js/briefing.js", "/js/icons.js", "/js/today.js", "/js/dialog.js", "/js/search.js", "/js/interview.js", "/js/dayBuilder.js", "/js/myEvents.js", "/js/grabado.js", "/js/detail.js", "/js/menu.js", "/js/numeros.js", "/js/charts.js",
  "/js/changes.js", "/js/countdown.js", "/js/events.js", "/js/shows.js", "/js/location.js", "/js/missed.js", "/js/notifications.js", "/js/sandbox.js", "/js/anuncios.js", "/js/grabarCharla.js",
  "/icons/icon.svg", "/icons/icon-192.png", "/icons/badge-96.png", "/icons/icon-512.png", "/icons/apple-touch-icon.png",
];

const FONTS_CSS = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600&display=swap";

// Precarga la tipografía (CSS + woff2) para que la app abra sin señal con su fuente desde la primera visita.
// Si falla (sin red al instalar), no frena la instalación: se cachea sola en el próximo uso.
async function precacheFonts() {
  try {
    const cache = await caches.open("fonts");
    const css = await fetch(FONTS_CSS);
    if (!css.ok) return;
    await cache.put(FONTS_CSS, css.clone());
    // Solo el subset "latin" (cubre el español: á é ñ ¿ ¡); los demás alfabetos se bajan si alguna vez hacen falta.
    const latin = (await css.text()).split("/* ").filter((block) => block.startsWith("latin */"));
    const files = latin.flatMap((block) => [...block.matchAll(/url\((https:\/\/fonts\.gstatic\.com\/[^)]+)\)/g)].map((m) => m[1]));
    await Promise.all(files.map((u) => fetch(u).then((r) => (r.ok ? cache.put(u, r) : null))));
  } catch {}
}

self.addEventListener("install", (e) => {
  e.waitUntil(Promise.all([
    caches.open(VERSION).then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: "reload" })))),
    precacheFonts(),
  ]).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION && k !== "fonts").map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Guardar en caché es best effort: si falla (cuota llena, modo privado) la respuesta se sirve igual.
const cachePut = (name, req, res) =>
  caches.open(name).then((c) => c.put(req, res)).catch((err) => console.warn("[sw] no se pudo cachear", req.url, err));

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.origin === location.origin && (url.pathname.startsWith("/api/") || url.pathname === "/health")) return;

  // Google Fonts: stale-while-revalidate en su propia caché.
  if (url.hostname.endsWith("fonts.googleapis.com") || url.hostname.endsWith("fonts.gstatic.com")) {
    e.respondWith((async () => {
      const hit = await caches.match(e.request, { cacheName: "fonts" });
      const net = fetch(e.request)
        .then((r) => {
          if (r.ok || r.type === "opaque") void cachePut("fonts", e.request, r.clone());
          return r;
        })
        .catch(() => hit);
      return hit || net;
    })());
    return;
  }

  // Las imágenes de los eventos (Luma) y de los shows (Ticketmaster, s1.ticketm.net) no pasan por acá: las manda su
  // CDN con caché larga, así que el navegador las guarda y las muestra sin señal solo. Interceptarlas las rompía en
  // algunos navegadores.

  if (url.origin !== location.origin) return;
  // App shell: red primero (para tomar cambios), pero con tope: si la red no contesta en 3 s se sirve la caché y la red
  // sigue y la actualiza igual. Sin esto, un Wi-Fi que conecta pero no responde dejaba la app en blanco.
  e.respondWith(shellRedPrimero(e));
});

const SHELL_TIMEOUT_MS = 3000;

const shellDeCache = (req) => caches.match(req).then((hit) => hit || caches.match("/index.html"));

function shellRedPrimero(e) {
  const req = e.request;
  const red = fetch(req, { cache: "no-cache" }) // revalida con el servidor: nunca una copia vieja de la caché HTTP
    .then((r) => {
      if (r.ok) void cachePut(VERSION, req, r.clone());
      return r;
    });
  e.waitUntil(red.catch(() => {})); // que la caché se actualice aunque ya hayamos contestado con la copia
  const sinRed = red.catch(() => shellDeCache(req).then((hit) => hit || Response.error()));
  const lenta = new Promise((resolve) => setTimeout(() => shellDeCache(req).then((hit) => hit && resolve(hit)), SHELL_TIMEOUT_MS));
  return Promise.race([sinRed, lenta]);
}

// Web Push (app/push.py): avisos de lo fijado y de cambios, con la app cerrada. Tocar la notificación abre esa pantalla.
// El recordatorio "¿la grabás?" trae el botón "Grabar" (actions: Chrome lo muestra, Safari/iOS no) y en los dos casos
// lleva a #/grabar-charla/{code}. tag: uno por aviso (antes era el título, que pisaba avisos distintos con el mismo).
self.addEventListener("push", (e) => {
  let msg = {};
  try { msg = e.data?.json() || {}; } catch { msg = { title: "ReinventAR", body: e.data?.text() || "" }; }
  e.waitUntil(self.registration.showNotification(msg.title || "ReinventAR", {
    body: msg.body || "", icon: "/icons/icon-192.png", badge: "/icons/badge-96.png",
    data: { url: msg.url || "/#/", recordUrl: msg.recordUrl || null },
    actions: Array.isArray(msg.actions) ? msg.actions : [], tag: msg.tag || msg.title, renotify: true,
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const data = e.notification.data || {};
  const target = e.action === "grabar" ? data.recordUrl || data.url : data.url;
  const url = new URL(target || "/#/", self.location.origin).href;
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const open = wins.find((w) => w.url.startsWith(self.location.origin));
    if (open) { await open.focus(); return open.navigate(url); }
    return self.clients.openWindow(url);
  })());
});
