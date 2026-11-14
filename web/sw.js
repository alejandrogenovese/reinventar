// Service worker de ReinventAR: la app abre sin red; la API nunca se cachea.
const VERSION = "reinventar-v0.21.0";
// Datos chicos para el SW (el token de sesión, que la página guarda al activar las notificaciones): el SW no ve localStorage.
const DATOS = "sw-datos";
const SHELL = [
  "/", "/index.html", "/css/tokens.css", "/css/base.css", "/styles.css", "/manifest.webmanifest",
  "/js/app.js", "/js/api.js", "/js/store.js", "/js/recorder.js", "/js/ui.js", "/js/itinerary.js", "/js/map.js", "/js/account.js", "/js/adminLlm.js", "/js/adminEventos.js", "/js/install.js", "/js/passkey.js", "/js/knowledge.js", "/js/lleno.js", "/js/explore.js", "/js/ask.js", "/js/talkpicker.js", "/js/briefing.js", "/js/icons.js", "/js/today.js", "/js/dialog.js", "/js/search.js", "/js/interview.js", "/js/dayBuilder.js", "/js/myEvents.js", "/js/grabado.js", "/js/detail.js", "/js/menu.js", "/js/numeros.js", "/js/charts.js",
  "/js/changes.js", "/js/countdown.js", "/js/events.js", "/js/shows.js", "/js/location.js", "/js/missed.js", "/js/notifications.js", "/js/sandbox.js", "/js/anuncios.js", "/js/grabarCharla.js",
  "/fonts/inter-latin-400-normal.woff2", "/fonts/inter-latin-500-normal.woff2", "/fonts/inter-latin-600-normal.woff2", "/fonts/inter-latin-700-normal.woff2", "/fonts/inter-latin-800-normal.woff2", "/fonts/jetbrains-mono-latin-500-normal.woff2", "/fonts/jetbrains-mono-latin-600-normal.woff2",
  "/icons/icon.svg", "/icons/icon-192.png", "/icons/badge-96.png", "/icons/icon-512.png", "/icons/apple-touch-icon.png",
  // Los que piden index.html y el manifest llevan ?v=2: la caché compara la URL entera, así que sin estos offline no aparecen.
  "/icons/icon.svg?v=2", "/icons/icon-192.png?v=2", "/icons/icon-512.png?v=2", "/icons/icon-maskable-512.png?v=2", "/icons/apple-touch-icon.png?v=2",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: "reload" })))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION && k !== DATOS).map((k) => caches.delete(k))))
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
  let timer;
  const lenta = new Promise((resolve) => { timer = setTimeout(() => shellDeCache(req).then((hit) => hit && resolve(hit)), SHELL_TIMEOUT_MS); });
  red.then(() => clearTimeout(timer), () => clearTimeout(timer)); // si la red contesta, no hace falta mirar la caché
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
    // Solo ventanas que este SW controla: WindowClient.navigate() falla (o no hace nada) sobre las que no controla.
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: false });
    const open = wins.find((w) => w.url.startsWith(self.location.origin));
    if (open) {
      try { await open.focus(); if (await open.navigate(url)) return; } catch (err) { console.warn("[sw] no se pudo navegar", err); }
    }
    return self.clients.openWindow(url);
  })());
});

// El navegador puede vencer o rotar la suscripción push (iOS y Chrome lo hacen): sin esto los avisos se cortan en silencio.
// Se re-suscribe con la clave VAPID del servidor y se manda la suscripción nueva al mismo endpoint que usa notifications.js.
const keyBytes = (b64) => Uint8Array.from(atob(b64.replaceAll("-", "+").replaceAll("_", "/").padEnd(Math.ceil(b64.length / 4) * 4, "=")), (c) => c.codePointAt(0));

const PUSH_TIMEOUT_MS = 10000;

async function leerToken() {
  const hit = await (await caches.open(DATOS)).match("/__token");
  return hit ? hit.text() : "";
}

async function resuscribir(e) {
  const token = await leerToken();
  if (!token) return; // sin sesión guardada: la página resincroniza sola la próxima vez que se abra
  const auth = { Authorization: `Bearer ${token}` };
  const signal = () => AbortSignal.timeout(PUSH_TIMEOUT_MS); // un servidor que no contesta no debe colgar al SW
  const post = (path, json) => fetch(path, { method: "POST", headers: { ...auth, "Content-Type": "application/json" }, body: JSON.stringify(json), signal: signal() });
  let sub = e.newSubscription;
  if (!sub) {
    const { key } = await (await fetch("/api/push/key", { headers: auth, signal: signal() })).json();
    if (!key) return;
    sub = await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
  }
  const r = await post("/api/push/subscribe", sub.toJSON());
  if (!r.ok) throw new Error(`push/subscribe respondió ${r.status}`);
  const viejo = e.oldSubscription?.endpoint;
  if (viejo && viejo !== sub.endpoint) await post("/api/push/unsubscribe", { endpoint: viejo }).catch(() => {});
}

self.addEventListener("pushsubscriptionchange", (e) => {
  e.waitUntil(resuscribir(e).catch((err) => console.warn("[sw] no se pudo re-suscribir", err)));
});
