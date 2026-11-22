// Runner común de las demos: cada spec declara sus escenas (copiadas de demos/libretos/<feature>.yml) y lo que
// el libreto pide preparar en sus `notas:`; acá se graba el video, se ejecutan las acciones y se escribe el timeline.
import { test, type Browser, type BrowserContext, type BrowserContextOptions, type CDPSession, type Locator, type Page } from "@playwright/test";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

export interface Escena {
  readonly id: number;
  readonly accion: string;
  readonly subtitulo: string;
  readonly duracion_s: number;
}

/** Lo que tiene a mano un hook de preparación: la página que se graba y cómo ejecutar acciones del libreto. */
export interface Director {
  readonly page: Page;
  readonly context: BrowserContext;
  readonly baseURL: string;
  ejecutar(accion: string): Promise<void>;
  /** Login por formulario, en la página que se graba, con la cuenta de la demo. */
  loginCuenta(): Promise<void>;
}

type Hook = (d: Director) => Promise<void>;

export interface Demo {
  readonly feature: string;
  readonly titulo: string;
  readonly escenas: readonly Escena[];
  /** No loguear antes de grabar (las demos de login arrancan sin sesión). */
  readonly sinSesion?: boolean;
  /** Variables de entorno con el usuario y la contraseña de la cuenta que se graba (por defecto, tester). */
  readonly cuenta?: { readonly envUsuario: string; readonly envPassword: string; readonly prohibido?: string };
  /** Claves de localStorage para dejar cargadas antes de grabar (ej. el tip de no molestar ya visto). */
  readonly localStorage?: Readonly<Record<string, string>>;
  /** Opciones extra del contexto de grabación (permisos, geolocalización, descargas, tema). */
  readonly contexto?: BrowserContextOptions;
  /** Script que corre en cada carga de página, antes que la app. */
  readonly initScript?: string;
  /** Agregar un autenticador WebAuthn virtual por CDP antes de cargar la app. */
  readonly passkey?: boolean;
  /** Resolución de las variables `{x}` de las acciones: nombre de variable de entorno o función. */
  readonly variables?: Readonly<Record<string, string | ((d: Director) => Promise<string>)>>;
  /** Pre-roll: corre ya grabando, antes de la escena 1 (se recorta con `recorte_inicial_ms` del timeline). */
  readonly preparar?: Hook;
  /** Hooks que corren justo antes de que empiece la escena con ese id (no cuentan en su duración). */
  readonly antesDeEscena?: Readonly<Record<number, Hook>>;
  /** Post-roll: limpieza fuera de cámara, después de la última escena. */
  readonly despues?: Hook;
  /** Si está, el test se saltea con este motivo. */
  readonly skip?: string;
}

const BASE_URL = (process.env.BASE_URL || "https://staging.reinventar.app").replace(/\/+$/, "");
const OUT = path.resolve(__dirname, "..", "out");
// El screencast de Chromium entrega cuadros en píxeles CSS del viewport aunque deviceScaleFactor sea 2: pedir
// 860x1864 deja la captura de 430x932 en una esquina con relleno gris. Se graba al tamaño nativo; la composición
// 16:9 pone el teléfono a ~1000 px de alto, así que no se pierde detalle.
const VIDEO_SIZE = { width: 430, height: 932 } as const;
// Ruido de milisegundos entre acciones: una escena recién se marca excedida si se pasa de esto.
const TOLERANCIA_EXCESO_MS = 150;
const ANDROID_UA =
  "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36";
const MARGEN_TIMEOUT_MS = 180_000;
const TIPEO_MS = 45;
const PASOS_CURSOR = 18;
const PASOS_SCROLL = 12;
const PAUSA_SCROLL_MS = 35;

export const CLAVE_TIP_NO_MOLESTAR = "reinventar.tip-no-molestar";
/** Venetian: la sede de la ubicación simulada de tester en staging (demos/README.md). */
export const VENETIAN = { latitude: 36.1212, longitude: -115.1697 } as const;
/** Pausa del pre-roll para que la app termine de pedir sus datos (y deje las copias para sin señal). */
export const PAUSA_PREROLL_MS = 4000;
/** Lo que tardan en aparecer las opciones que arma el LLM (itinerario-armar-dia). */
export const ESPERA_LLM_MS = 60_000;

/** Teléfono al centro del cuadro: viewport de celular, video del mismo aspecto (diseno/placa-y-subtitulos.html). */
export const DISPOSITIVO: BrowserContextOptions = {
  viewport: { width: 430, height: 932 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
  userAgent: ANDROID_UA,
  locale: "es-AR",
  timezoneId: "America/Los_Angeles",
  colorScheme: "light",
};

/** La franja «MODO PRUEBA · …» (web/js/sandbox.js) no va en los videos: tester graba en modo prueba. */
const OCULTAR_FRANJA_PRUEBA = `(() => {
  const css = '#sandbox-banner { display: none !important; }';
  const poner = () => { const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s); };
  if (document.head) poner(); else document.addEventListener('DOMContentLoaded', poner, { once: true });
})();`;

/** Cursor/toque visible: un círculo que sigue al mouse de Playwright y late en cada click. */
const CURSOR_OVERLAY = `(() => {
  const montar = () => {
    if (document.getElementById("demo-cursor")) return;
    const estilo = document.createElement("style");
    estilo.textContent = "#demo-cursor{position:fixed;left:0;top:0;width:34px;height:34px;margin:-17px 0 0 -17px;" +
      "border-radius:50%;background:rgba(255,255,255,.35);border:2px solid rgba(20,20,20,.75);" +
      "box-shadow:0 2px 8px rgba(0,0,0,.35);pointer-events:none;z-index:2147483647;opacity:0;" +
      "transition:opacity .2s,transform .12s}" +
      "#demo-cursor.toque{transform:scale(.7);background:rgba(255,153,0,.6)}";
    const punto = document.createElement("div");
    punto.id = "demo-cursor";
    document.documentElement.append(estilo, punto);
    const mover = (x, y) => { punto.style.left = x + "px"; punto.style.top = y + "px"; punto.style.opacity = "1"; };
    const opciones = { capture: true, passive: true };
    addEventListener("mousemove", (e) => mover(e.clientX, e.clientY), opciones);
    addEventListener("pointermove", (e) => mover(e.clientX, e.clientY), opciones);
    addEventListener("pointerdown", (e) => { mover(e.clientX, e.clientY); punto.classList.add("toque"); }, opciones);
    addEventListener("pointerup", () => punto.classList.remove("toque"), opciones);
    addEventListener("touchstart", (e) => { const t = e.touches[0]; if (t) { mover(t.clientX, t.clientY); punto.classList.add("toque"); } }, opciones);
    addEventListener("touchend", () => punto.classList.remove("toque"), opciones);
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", montar); else montar();
})();`;

const escaparRegex = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Traduce un selector del libreto a un Locator: `role=x[name='...']` es exacto, `role=x[name^='...']` es
 * "empieza con", y el resto (CSS, `text=`) va directo a Playwright. Siempre el primero: varios libretos
 * dicen "tomar el primero" y en el resto el selector ya es único.
 */
export function localizar(page: Page, selector: string): Locator {
  const rol = /^role=([a-z]+)\[name(\^?)='(.*)'\]$/.exec(selector);
  if (!rol) return page.locator(selector).first();
  const [, nombreRol, empieza, nombre] = rol;
  const name = empieza ? new RegExp(`^${escaparRegex(nombre)}`) : nombre;
  return page.getByRole(nombreRol as Parameters<Page["getByRole"]>[0], { name, exact: !empieza }).first();
}

/** Lleva el cursor hasta el elemento con un movimiento visible (si no, Playwright lo teletransporta). */
/** Los radios y checkboxes con estilo propio están ocultos: el toque va a su label, que es lo que se ve. */
async function objetivoVisible(page: Page, loc: Locator): Promise<Locator> {
  const esCasilla = await loc.evaluate((el) => el instanceof HTMLInputElement && ["radio", "checkbox"].includes(el.type))
    .catch(() => false);
  if (!esCasilla) return loc;
  const id = await loc.getAttribute("id");
  const porFor = id ? page.locator(`label[for="${id}"]`) : null;
  if (porFor && (await porFor.count())) return porFor.first();
  const envolvente = loc.locator("xpath=ancestor::label[1]");
  return (await envolvente.count()) ? envolvente : loc;
}

async function acercarCursor(page: Page, loc: Locator): Promise<void> {
  await loc.scrollIntoViewIfNeeded();
  const caja = await loc.boundingBox();
  if (!caja) return;
  await page.mouse.move(caja.x + caja.width / 2, caja.y + caja.height / 2, { steps: PASOS_CURSOR });
}

/** `scroll <px>`: rueda relativa a la posición actual, en pasos para que se vea suave. */
async function scrollPx(page: Page, px: number): Promise<void> {
  const vp = page.viewportSize();
  if (vp) await page.mouse.move(vp.width / 2, vp.height / 2, { steps: PASOS_CURSOR });
  for (let i = 0; i < PASOS_SCROLL; i += 1) {
    await page.mouse.wheel(0, px / PASOS_SCROLL);
    await page.waitForTimeout(PAUSA_SCROLL_MS);
  }
}

/** Reemplaza `{{ENV}}` por la variable de entorno y `{x}` con los resolvedores de la demo. */
async function resolver(accion: string, demo: Demo, d: Director): Promise<string> {
  let out = accion.replace(/\{\{([A-Z0-9_]+)\}\}/g, (_, v: string) => {
    const valor = process.env[v];
    if (!valor) throw new Error(`Falta la variable de entorno ${v}`);
    return valor;
  });
  for (const [, nombre] of out.matchAll(/\{([a-z_]+)\}/g)) {
    const fuente = demo.variables?.[nombre];
    if (!fuente) throw new Error(`No hay cómo resolver {${nombre}} en «${accion}»`);
    const valor = typeof fuente === "string" ? process.env[fuente] : await fuente(d);
    if (!valor) throw new Error(`No se pudo resolver {${nombre}}`);
    out = out.split(`{${nombre}}`).join(valor);
  }
  return out;
}

/** Ejecuta una acción del libreto: goto, click, hover, fill, scroll o wait. */
export async function ejecutarAccion(page: Page, accion: string): Promise<void> {
  const [, verbo, resto] = /^(\w+)\s+(.+)$/s.exec(accion.trim()) ?? [];
  switch (verbo) {
    case "goto":
      await page.goto(new URL(resto, `${BASE_URL}/`).href, { waitUntil: "domcontentloaded" });
      return;
    case "wait":
      await page.waitForTimeout(Number(resto) * 1000);
      return;
    case "scroll":
      if (/^-?\d+$/.test(resto)) await scrollPx(page, Number(resto));
      else await localizar(page, resto).scrollIntoViewIfNeeded();
      return;
    case "click":
    case "hover": {
      const loc = await objetivoVisible(page, localizar(page, resto));
      await acercarCursor(page, loc);
      await (verbo === "click" ? loc.click() : loc.hover());
      return;
    }
    case "fill": {
      const [, selector, valor] = /^(.+?)\s+"(.*)"$/s.exec(resto) ?? [];
      if (selector === undefined) throw new Error(`fill sin valor entre comillas: «${accion}»`);
      const loc = localizar(page, selector);
      await acercarCursor(page, loc);
      await loc.click();
      await loc.fill("");
      await loc.pressSequentially(valor, { delay: TIPEO_MS });
      return;
    }
    default:
      throw new Error(`Acción desconocida: «${accion}»`);
  }
}

/** Login por el formulario de la app (#username, #password, «Entrar») hasta que el hash sea #/. */
export async function login(page: Page, usuario: string, password: string): Promise<void> {
  await page.goto(`${BASE_URL}/#/login`, { waitUntil: "domcontentloaded" });
  await page.locator("#username").fill(usuario);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL((u) => u.hash === "#/", { timeout: 30_000 });
}

/** Loguea en un contexto sin video y devuelve el storageState (token + claves extra) para el contexto que graba. */
async function sesionPrevia(browser: Browser, demo: Demo, usuario: string, password: string) {
  const ctx = await browser.newContext(DISPOSITIVO);
  try {
    const page = await ctx.newPage();
    await login(page, usuario, password);
    const extra = demo.localStorage ?? {};
    await page.evaluate((kv) => Object.entries(kv).forEach(([k, v]) => localStorage.setItem(k, v)), extra);
    return await ctx.storageState();
  } finally {
    await ctx.close();
  }
}

async function agregarAutenticador(context: BrowserContext, page: Page): Promise<CDPSession> {
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true },
  });
  return cdp;
}

/** Variables de entorno que hacen falta: placeholders {{X}}, la cuenta y las variables {x} que salen de env. */
function envFaltantes(demo: Demo): string[] {
  const deAcciones = demo.escenas.flatMap((e) => [...e.accion.matchAll(/\{\{([A-Z0-9_]+)\}\}/g)].map((m) => m[1]));
  const cuenta = demo.cuenta ? [demo.cuenta.envUsuario, demo.cuenta.envPassword] : ["TESTER_PASSWORD"];
  const deVariables = Object.values(demo.variables ?? {}).filter((v): v is string => typeof v === "string");
  return [...new Set([...deAcciones, ...cuenta, ...deVariables])].filter((v) => !process.env[v]);
}

interface Marca {
  readonly id: number;
  readonly accion: string;
  readonly subtitulo: string;
  readonly duracion_s: number;
  readonly inicio_ms: number;
  readonly fin_ms: number;
  readonly excedida_ms: number;
}

function escribirTimeline(demo: Demo, marcas: readonly Marca[], completo: boolean, video: string | null): string {
  const archivo = path.join(OUT, `${demo.feature}.timeline.json`);
  const timeline = {
    feature: demo.feature,
    titulo: demo.titulo,
    base_url: BASE_URL,
    completo,
    video,
    viewport: DISPOSITIVO.viewport,
    video_size: VIDEO_SIZE,
    generado: new Date().toISOString(),
    recorte_inicial_ms: marcas[0]?.inicio_ms ?? 0,
    suma_duracion_ms: demo.escenas.reduce((t, e) => t + e.duracion_s * 1000, 0),
    duracion_real_ms: marcas.length ? marcas[marcas.length - 1].fin_ms - marcas[0].inicio_ms : 0,
    escenas: marcas,
  };
  writeFileSync(archivo, `${JSON.stringify(timeline, null, 2)}\n`);
  return archivo;
}

function excesoMs(realMs: number, duracionS: number): number {
  const exceso = realMs - duracionS * 1000;
  return exceso > TOLERANCIA_EXCESO_MS ? exceso : 0;
}

/** Cada escena: hook previo, acción y relleno con espera hasta duracion_s desde que empezó la escena. */
async function grabarEscenas(demo: Demo, d: Director, t0: number, marcas: Marca[]): Promise<void> {
  for (const escena of demo.escenas) {
    await demo.antesDeEscena?.[escena.id]?.(d);
    const inicio = Date.now();
    await test.step(`escena ${escena.id}: ${escena.accion}`, async () => {
      await d.ejecutar(await resolver(escena.accion, demo, d));
      const restante = escena.duracion_s * 1000 - (Date.now() - inicio);
      if (restante > 0) await d.page.waitForTimeout(restante);
    });
    const fin = Date.now();
    marcas.push({
      id: escena.id, accion: escena.accion, subtitulo: escena.subtitulo, duracion_s: escena.duracion_s,
      inicio_ms: inicio - t0, fin_ms: fin - t0, excedida_ms: excesoMs(fin - inicio, escena.duracion_s),
    });
  }
}

/** Saltea con motivo si la demo está marcada o faltan variables de entorno; devuelve la cuenta a usar. */
function credenciales(demo: Demo): { usuario: string; password: string } {
  test.skip(Boolean(demo.skip), demo.skip ?? "");
  const faltan = envFaltantes(demo);
  test.skip(faltan.length > 0, `Faltan variables de entorno: ${faltan.join(", ")}`);
  const usuario = demo.cuenta ? process.env[demo.cuenta.envUsuario] ?? "" : "tester";
  const prohibido = demo.cuenta?.prohibido;
  test.skip(Boolean(prohibido) && usuario === prohibido, `No se graba con la cuenta ${prohibido}: usá una descartable`);
  return { usuario, password: process.env[demo.cuenta?.envPassword ?? "TESTER_PASSWORD"] ?? "" };
}

/** Declara el test de la demo: sesión previa sin video, contexto que graba, pre-roll, escenas y timeline. */
export function definirDemo(demo: Demo): void {
  test(`demo ${demo.feature}`, async ({ browser }) => {
    const { usuario, password } = credenciales(demo);
    test.setTimeout(demo.escenas.reduce((t, e) => t + e.duracion_s * 1000, 0) + MARGEN_TIMEOUT_MS);
    mkdirSync(OUT, { recursive: true });
    const storageState = demo.sinSesion ? undefined : await sesionPrevia(browser, demo, usuario, password);
    const dirVideo = path.join(OUT, `.video-${demo.feature}`);
    const context = await browser.newContext({
      ...DISPOSITIVO, ...demo.contexto, storageState, recordVideo: { dir: dirVideo, size: VIDEO_SIZE },
    });
    await context.addInitScript(CURSOR_OVERLAY);
    await context.addInitScript(OCULTAR_FRANJA_PRUEBA);
    if (demo.initScript) await context.addInitScript(demo.initScript);
    const page = await context.newPage();
    const t0 = Date.now();
    if (demo.passkey) await agregarAutenticador(context, page);
    const d: Director = {
      page, context, baseURL: BASE_URL,
      ejecutar: (accion) => ejecutarAccion(page, accion),
      loginCuenta: () => login(page, usuario, password),
    };
    const marcas: Marca[] = [];
    let completo = false;
    try {
      await demo.preparar?.(d);
      await grabarEscenas(demo, d, t0, marcas);
      completo = true;
      await demo.despues?.(d);
    } finally {
      const video = page.video();
      await context.close();
      const destino = path.join(OUT, `${demo.feature}.webm`);
      if (video) await video.saveAs(destino);
      rmSync(dirVideo, { recursive: true, force: true });
      const timeline = escribirTimeline(demo, marcas, completo, video ? path.basename(destino) : null);
      test.info().annotations.push({ type: "timeline", description: timeline });
    }
  });
}
