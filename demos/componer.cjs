// Compone el video final de cada demo: placa de título (3 s) + el video del celular con su marco + el texto de cada
// escena, sincronizado con el timeline. Tres formatos (FORMATO):
//   16x9  1920×1080 (por defecto): teléfono a la izquierda y el texto grande a la derecha, sin caja.
//   9x16  1080×1920: el teléfono ocupa casi todo el cuadro y el subtítulo va debajo.
//   1x1   1080×1080: teléfono centrado y subtítulo debajo.
// Necesita Playwright (el mismo de las specs, por NODE_PATH), ffmpeg y ruby (para leer los YAML).
// Uso, desde la raíz del repo:
//   [FORMATO=9x16] NODE_PATH=<playwright>/node_modules node demos/componer.cjs [feature ...]
// Lee demos/out/<feature>.webm y .timeline.json, y deja demos/out/final-<formato>/<feature>.mp4.
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const RAIZ = path.resolve(__dirname, "..");
const OUT = path.join(__dirname, "out");
// Las fuentes van embebidas: la página se arma con setContent y no puede leer file://.
const fuente = (archivo) =>
  `data:font/woff2;base64,${fs.readFileSync(path.join(RAIZ, "web", "fonts", archivo)).toString("base64")}`;

const FPS = 30;
const PLACA_S = 3;
const FUNDIDO_ENTRADA_S = 0.4;
const FUNDIDO_SALIDA_S = 0.3;
const BISEL = 12;
const RELACION_TELEFONO = 430 / 932; // ancho / alto del video grabado
const FONDO = "#1a1a1a"; // el de la placa: igual en todo el video

const telefono = (alto, x, y) => ({ ancho: Math.round(alto * RELACION_TELEFONO), alto, x, y });

// Geometría de cada formato. `texto` dice dónde va el texto de la escena: debajo del teléfono (con caja) o al costado.
const FORMATOS = {
  "9x16": { ancho: 1080, alto: 1920, pantalla: telefono(1480, 199, 80),
    texto: { modo: "debajo", y: 1612, ancho: 960, alto: 240, fuente: 52 }, placa: { titulo: 120, beneficio: 52, margen: 96 } },
  "1x1": { ancho: 1080, alto: 1080, pantalla: telefono(780, 360, 40),
    texto: { modo: "debajo", y: 862, ancho: 960, alto: 180, fuente: 40 }, placa: { titulo: 96, beneficio: 44, margen: 88 } },
  "16x9": { ancho: 1920, alto: 1080, pantalla: telefono(960, 220, 60),
    texto: { modo: "costado", x: 820, ancho: 960, fuente: 64 }, placa: { titulo: 112, beneficio: 44, margen: 96 } },
};

const FORMATO = process.env.FORMATO ?? "16x9"; // el elegido para la galería
const F = FORMATOS[FORMATO];
if (!F) throw new Error(`FORMATO tiene que ser uno de: ${Object.keys(FORMATOS).join(", ")}`);
const FINAL = path.join(OUT, `final-${FORMATO}`);
const TMP = path.join(OUT, `.componer-${FORMATO}`);

const CSS_BASE = `
  @font-face { font-family: "Inter"; font-weight: 400; src: url("${fuente("inter-latin-400-normal.woff2")}"); }
  @font-face { font-family: "Inter"; font-weight: 600; src: url("${fuente("inter-latin-600-normal.woff2")}"); }
  @font-face { font-family: "Inter"; font-weight: 700; src: url("${fuente("inter-latin-700-normal.woff2")}"); }
  @font-face { font-family: "Inter"; font-weight: 800; src: url("${fuente("inter-latin-800-normal.woff2")}"); }
  @font-face { font-family: "JetBrains Mono"; font-weight: 500; src: url("${fuente("jetbrains-mono-latin-500-normal.woff2")}"); }
  * { box-sizing: border-box; margin: 0; }
  html, body { width: ${F.ancho}px; height: ${F.alto}px; background: transparent; font-family: Inter, sans-serif;
    -webkit-font-smoothing: antialiased; }`;

const LOGO = `<svg viewBox="0 0 512 512" width="64" height="64"><rect width="512" height="512" rx="112" fill="#2b2b2b"/><rect x="100" y="206" width="40" height="100" rx="20" fill="#fa6400"/><rect x="168" y="156" width="40" height="200" rx="20" fill="#fa6400"/><rect x="236" y="116" width="40" height="280" rx="20" fill="#f4f4f4"/><rect x="304" y="166" width="40" height="180" rx="20" fill="#fa6400"/><rect x="372" y="221" width="40" height="70" rx="20" fill="#fa6400"/></svg>`;

const escapar = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
// En una sola línea: el corte lo decide el ancho de la caja, así todas las escenas se ven parejas.
const enLinea = (s) => escapar(String(s).split(/\s+/).join(" "));

function htmlPlaca(titulo, beneficio) {
  const { titulo: t, beneficio: b, margen: m } = F.placa;
  return `<!doctype html><meta charset="utf-8"><style>${CSS_BASE}
    body { background: ${FONDO}; color: #f4f4f4; position: relative; }
    .logo { position: absolute; top: ${m * 0.75}px; left: ${m}px; display: flex; align-items: center; gap: 20px; font: 600 32px/1 Inter; }
    .centro { position: absolute; left: ${m}px; right: ${m}px; top: 50%; transform: translateY(-50%); }
    .acento { width: 96px; height: 10px; border-radius: 5px; background: #fa6400; margin-bottom: 48px; }
    .titulo { font: 800 ${t}px/1.05 Inter; letter-spacing: -0.03em; }
    .beneficio { font: 400 ${b}px/1.3 Inter; color: #bdbdbd; margin-top: 36px; max-width: 30ch; }
    .pie { position: absolute; bottom: ${m * 0.75}px; left: ${m}px; font: 500 26px/1 "JetBrains Mono"; color: #bdbdbd; }
  </style><div class="logo">${LOGO}<span>reinventar</span></div>
  <div class="centro"><div class="acento"></div><div class="titulo">${escapar(titulo)}</div>
  <div class="beneficio">${escapar(beneficio ?? "")}</div></div><div class="pie">reinventar.app</div>`;
}

/** Capa de una escena: el bisel del teléfono (tapa las esquinas del video) y el texto de esa escena. */
function htmlCapa(titulo, subtitulo) {
  const p = F.pantalla;
  const tx = F.texto;
  const texto = !subtitulo ? "" : tx.modo === "debajo"
    ? `<div class="caja"><span>${enLinea(subtitulo)}</span></div>`
    : `<div class="costado"><div class="tit">${escapar(titulo)}</div><div class="sub">${enLinea(subtitulo)}</div></div>`;
  return `<!doctype html><meta charset="utf-8"><style>${CSS_BASE}
    .bisel { position: absolute; left: ${p.x - BISEL}px; top: ${p.y - BISEL}px; width: ${p.ancho + 2 * BISEL}px;
      height: ${p.alto + 2 * BISEL}px; border: ${BISEL}px solid #0d0d0d; border-radius: 48px; }
    .caja { position: absolute; left: ${(F.ancho - (tx.ancho ?? 0)) / 2}px; top: ${tx.y}px; width: ${tx.ancho}px;
      height: ${tx.alto}px; display: flex; align-items: center; justify-content: center; padding: 20px 36px;
      border-radius: 16px; background: rgb(255 255 255 / .06); }
    .caja span { color: #fff; font: 600 ${tx.fuente}px/1.3 Inter; text-align: center; text-wrap: balance; }
    .costado { position: absolute; left: ${tx.x}px; width: ${tx.ancho}px; top: 50%; transform: translateY(-50%); }
    .costado .tit { color: #fa6400; font: 600 28px/1.2 Inter; letter-spacing: 0.02em; margin-bottom: 28px; }
    .costado .sub { color: #fff; font: 700 ${tx.fuente}px/1.2 Inter; letter-spacing: -0.02em; text-wrap: balance; }
  </style><div class="bisel"></div>${texto}`;
}

async function capturar(page, html, archivo) {
  await page.setContent(html, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: archivo, omitBackground: true });
}

function leerLibretos() {
  const ruby = 'puts JSON.dump(Dir["demos/libretos/*.yml"].to_h { |f| d = YAML.load_file(f); [d["feature"], d] })';
  return JSON.parse(execFileSync("ruby", ["-ryaml", "-rjson", "-e", ruby], { cwd: RAIZ, encoding: "utf8" }));
}

const ffmpeg = (args) => execFileSync("ffmpeg", ["-v", "error", "-y", ...args], { stdio: "inherit" });

function videoPrincipal(feature, timeline, capas, salida) {
  const recorte = (timeline.recorte_inicial_ms ?? 0) / 1000;
  const duracion = timeline.duracion_real_ms / 1000 - recorte;
  const entradas = ["-ss", String(recorte), "-i", path.join(OUT, `${feature}.webm`)];
  capas.forEach((c) => entradas.push("-loop", "1", "-i", c.png));
  const p = F.pantalla;
  const filtros = [
    `color=c=${FONDO}:s=${F.ancho}x${F.alto}:r=${FPS}[fondo]`,
    `[0:v]scale=${p.ancho}:${p.alto},setsar=1,fps=${FPS}[tel]`,
    `[fondo][tel]overlay=${p.x}:${p.y}:shortest=1[c0]`,
  ];
  capas.forEach((c, i) => {
    filtros.push(`[c${i}][${i + 1}:v]overlay=0:0:enable='between(t,${c.desde.toFixed(3)},${c.hasta.toFixed(3)})'[c${i + 1}]`);
  });
  ffmpeg([...entradas, "-filter_complex", filtros.join(";"), "-map", `[c${capas.length}]`, "-t", duracion.toFixed(3),
    "-r", String(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", salida]);
}

function videoPlaca(png, salida) {
  ffmpeg(["-loop", "1", "-t", String(PLACA_S), "-i", png, "-vf",
    `fade=in:st=0:d=${FUNDIDO_ENTRADA_S},fade=out:st=${PLACA_S - FUNDIDO_SALIDA_S}:d=${FUNDIDO_SALIDA_S},format=yuv420p`,
    "-r", String(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", salida]);
}

/** Una capa por escena, que cubre de su inicio al inicio de la siguiente (sin huecos en que el bisel desaparezca). */
function tramos(timeline) {
  const recorte = timeline.recorte_inicial_ms ?? 0;
  const fin = timeline.duracion_real_ms - recorte;
  return timeline.escenas.map((e, i, todas) => ({
    escena: e,
    desde: (e.inicio_ms - recorte) / 1000,
    hasta: ((i + 1 < todas.length ? todas[i + 1].inicio_ms - recorte : fin)) / 1000,
  }));
}

async function componer(page, feature, libreto) {
  const timeline = JSON.parse(fs.readFileSync(path.join(OUT, `${feature}.timeline.json`), "utf8"));
  if (!timeline.completo) { console.log(`${feature}: timeline incompleto, se saltea`); return false; }
  const dir = path.join(TMP, feature);
  fs.mkdirSync(dir, { recursive: true });
  const placa = path.join(dir, "placa.png");
  await capturar(page, htmlPlaca(libreto.titulo, libreto.beneficio), placa);
  const capas = [];
  for (const t of tramos(timeline)) {
    const png = path.join(dir, `capa-${t.escena.id}.png`);
    await capturar(page, htmlCapa(libreto.titulo, t.escena.subtitulo), png);
    capas.push({ png, desde: t.desde, hasta: t.hasta });
  }
  const partePlaca = path.join(dir, "placa.mp4");
  const parteDemo = path.join(dir, "demo.mp4");
  videoPlaca(placa, partePlaca);
  videoPrincipal(feature, timeline, capas, parteDemo);
  const lista = path.join(dir, "lista.txt");
  fs.writeFileSync(lista, `file '${partePlaca}'\nfile '${parteDemo}'\n`);
  ffmpeg(["-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", "-movflags", "+faststart", path.join(FINAL, `${feature}.mp4`)]);
  return true;
}

async function main() {
  const libretos = leerLibretos();
  const pedidas = process.argv.slice(2);
  const features = Object.keys(libretos).sort()
    .filter((f) => (!pedidas.length || pedidas.includes(f)) && fs.existsSync(path.join(OUT, `${f}.timeline.json`)));
  fs.mkdirSync(FINAL, { recursive: true });
  fs.mkdirSync(TMP, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: F.ancho, height: F.alto } });
  let hechas = 0;
  for (const feature of features) {
    if (await componer(page, feature, libretos[feature])) { hechas += 1; console.log(`${feature}: listo`); }
  }
  await browser.close();
  fs.rmSync(TMP, { recursive: true, force: true });
  console.log(`videos (${FORMATO}): ${hechas}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
