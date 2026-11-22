// Compone el video final de cada demo según demos/diseno/placa-y-subtitulos.html:
// placa de título (3 s) + el video del celular al centro de un cuadro 1920×1080 + subtítulos por escena.
// Necesita Playwright (el mismo de las specs, por NODE_PATH), ffmpeg y ruby (para leer los YAML).
// Uso, desde la raíz del repo:
//   NODE_PATH=<playwright>/node_modules node demos/componer.cjs [feature ...]
// Lee demos/out/<feature>.webm y .timeline.json, y deja demos/out/final/<feature>.mp4.
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const RAIZ = path.resolve(__dirname, "..");
const OUT = path.join(__dirname, "out");
const FINAL = path.join(OUT, "final");
const TMP = path.join(OUT, ".componer");
// Las fuentes van embebidas: la página se arma con setContent y no puede leer file://.
const fuente = (archivo) =>
  `data:font/woff2;base64,${fs.readFileSync(path.join(RAIZ, "web", "fonts", archivo)).toString("base64")}`;

const ANCHO = 1920;
const ALTO = 1080;
const FPS = 30;
const PLACA_S = 3;
const FUNDIDO_ENTRADA_S = 0.4;
const FUNDIDO_SALIDA_S = 0.3;
// Teléfono: el video (430×932) escalado a 800 de alto y centrado, con un bisel de 12 px; termina antes del subtítulo.
const PANTALLA = { ancho: 369, alto: 800, x: 776, y: 40 };
const BISEL = 12;
const SUBTITULO_BASE_Y = Math.round(ALTO * 0.92); // margen inferior del 8 %

const CSS_FUENTES = `
  @font-face { font-family: "Inter"; font-weight: 400; src: url("${fuente("inter-latin-400-normal.woff2")}"); }
  @font-face { font-family: "Inter"; font-weight: 600; src: url("${fuente("inter-latin-600-normal.woff2")}"); }
  @font-face { font-family: "Inter"; font-weight: 800; src: url("${fuente("inter-latin-800-normal.woff2")}"); }
  @font-face { font-family: "JetBrains Mono"; font-weight: 500; src: url("${fuente("jetbrains-mono-latin-500-normal.woff2")}"); }
  * { box-sizing: border-box; margin: 0; }
  html, body { width: ${ANCHO}px; height: ${ALTO}px; background: transparent; }`;

const LOGO = `<svg viewBox="0 0 512 512" width="64" height="64"><rect width="512" height="512" rx="112" fill="#2b2b2b"/><rect x="100" y="206" width="40" height="100" rx="20" fill="#fa6400"/><rect x="168" y="156" width="40" height="200" rx="20" fill="#fa6400"/><rect x="236" y="116" width="40" height="280" rx="20" fill="#f4f4f4"/><rect x="304" y="166" width="40" height="180" rx="20" fill="#fa6400"/><rect x="372" y="221" width="40" height="70" rx="20" fill="#fa6400"/></svg>`;

const escapar = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function htmlPlaca(titulo, beneficio) {
  return `<!doctype html><meta charset="utf-8"><style>${CSS_FUENTES}
    body { background: #1a1a1a; color: #f4f4f4; font-family: Inter, sans-serif; position: relative; }
    .logo { position: absolute; top: 72px; left: 96px; display: flex; align-items: center; gap: 20px; font: 600 32px/1 Inter; }
    .centro { position: absolute; left: 96px; right: 96px; top: 50%; transform: translateY(-50%); }
    .acento { width: 96px; height: 10px; border-radius: 5px; background: #fa6400; margin-bottom: 48px; }
    .titulo { font: 800 112px/1.05 Inter; letter-spacing: -0.03em; max-width: 16ch; }
    .beneficio { font: 400 44px/1.3 Inter; color: #bdbdbd; margin-top: 36px; max-width: 34ch; }
    .pie { position: absolute; bottom: 72px; left: 96px; font: 500 26px/1 "JetBrains Mono"; color: #bdbdbd; }
  </style><div class="logo">${LOGO}<span>reinventar</span></div>
  <div class="centro"><div class="acento"></div><div class="titulo">${escapar(titulo)}</div>
  <div class="beneficio">${escapar(beneficio ?? "")}</div></div><div class="pie">reinventar.app</div>`;
}

function htmlMarco() {
  const { ancho, alto, x, y } = PANTALLA;
  return `<!doctype html><style>${CSS_FUENTES}
    .bisel { position: absolute; left: ${x - BISEL}px; top: ${y - BISEL}px; width: ${ancho + 2 * BISEL}px;
      height: ${alto + 2 * BISEL}px; border: ${BISEL}px solid #0d0d0d; border-radius: 48px; }
  </style><div class="bisel"></div>`;
}

function htmlSubtitulo(texto) {
  return `<!doctype html><meta charset="utf-8"><style>${CSS_FUENTES}
    body { display: flex; justify-content: center; align-items: flex-start; padding-top: 8px; }
    .sub { max-width: ${Math.round(ANCHO * 0.7)}px; padding: 16px 28px; border-radius: 12px; background: rgb(17 17 17 / .82);
      color: #fff; font: 600 40px/1.3 Inter, sans-serif; text-align: center; white-space: pre-line; }
  </style><div class="sub">${escapar(texto)}</div>`;
}

async function capturar(page, html, archivo, { soloElemento } = {}) {
  await page.setContent(html, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  if (soloElemento) await page.locator(soloElemento).screenshot({ path: archivo, omitBackground: true });
  else await page.screenshot({ path: archivo, omitBackground: true });
}

function leerLibretos() {
  const ruby = 'puts JSON.dump(Dir["demos/libretos/*.yml"].to_h { |f| d = YAML.load_file(f); [d["feature"], d] })';
  return JSON.parse(execFileSync("ruby", ["-ryaml", "-rjson", "-e", ruby], { cwd: RAIZ, encoding: "utf8" }));
}

const ffmpeg = (args) => execFileSync("ffmpeg", ["-v", "error", "-y", ...args], { stdio: "inherit" });

function videoPrincipal(feature, timeline, subs, salida) {
  const recorte = (timeline.recorte_inicial_ms ?? 0) / 1000;
  const duracion = timeline.duracion_real_ms / 1000 - recorte;
  const entradas = ["-ss", String(recorte), "-i", path.join(OUT, `${feature}.webm`), "-loop", "1", "-i", subs.marco];
  subs.escenas.forEach((s) => entradas.push("-loop", "1", "-i", s.png));
  const { ancho, alto, x, y } = PANTALLA;
  const filtros = [
    `color=c=#2a2a2a:s=${ANCHO}x${ALTO}:r=${FPS}[fondo]`,
    `[0:v]scale=${ancho}:${alto},setsar=1,fps=${FPS}[tel]`,
    `[fondo][tel]overlay=${x}:${y}:shortest=1[c0]`,
    `[c0][1:v]overlay=0:0[c1]`,
  ];
  subs.escenas.forEach((s, i) => {
    filtros.push(`[c${i + 1}][${i + 2}:v]overlay=x=(W-w)/2:y=${SUBTITULO_BASE_Y}-h:enable='between(t,${s.desde.toFixed(3)},${s.hasta.toFixed(3)})'[c${i + 2}]`);
  });
  const ultimo = `[c${subs.escenas.length + 1}]`;
  ffmpeg([...entradas, "-filter_complex", filtros.join(";"), "-map", ultimo, "-t", duracion.toFixed(3),
    "-r", String(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", salida]);
}

function videoPlaca(png, salida) {
  ffmpeg(["-loop", "1", "-t", String(PLACA_S), "-i", png, "-vf",
    `fade=in:st=0:d=${FUNDIDO_ENTRADA_S},fade=out:st=${PLACA_S - FUNDIDO_SALIDA_S}:d=${FUNDIDO_SALIDA_S},format=yuv420p`,
    "-r", String(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", salida]);
}

async function main() {
  const libretos = leerLibretos();
  const pedidas = process.argv.slice(2);
  const features = Object.keys(libretos).sort()
    .filter((f) => (!pedidas.length || pedidas.includes(f)) && fs.existsSync(path.join(OUT, `${f}.timeline.json`)));
  fs.mkdirSync(FINAL, { recursive: true });
  fs.mkdirSync(TMP, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: ANCHO, height: ALTO } });
  const marco = path.join(TMP, "marco.png");
  await capturar(page, htmlMarco(), marco);
  const hechas = [];
  for (const feature of features) {
    const timeline = JSON.parse(fs.readFileSync(path.join(OUT, `${feature}.timeline.json`), "utf8"));
    if (!timeline.completo) { console.log(`${feature}: timeline incompleto, se saltea`); continue; }
    const libreto = libretos[feature];
    const dir = path.join(TMP, feature);
    fs.mkdirSync(dir, { recursive: true });
    const placa = path.join(dir, "placa.png");
    await capturar(page, htmlPlaca(libreto.titulo, libreto.beneficio), placa);
    const recorte = timeline.recorte_inicial_ms ?? 0;
    const escenas = [];
    for (const e of timeline.escenas) {
      if (!e.subtitulo) continue;
      const png = path.join(dir, `sub-${e.id}.png`);
      await capturar(page, htmlSubtitulo(e.subtitulo), png, { soloElemento: ".sub" });
      escenas.push({ png, desde: (e.inicio_ms - recorte) / 1000, hasta: (e.fin_ms - recorte) / 1000 });
    }
    const partePlaca = path.join(dir, "placa.mp4");
    const parteDemo = path.join(dir, "demo.mp4");
    videoPlaca(placa, partePlaca);
    videoPrincipal(feature, timeline, { marco, escenas }, parteDemo);
    const lista = path.join(dir, "lista.txt");
    fs.writeFileSync(lista, `file '${partePlaca}'\nfile '${parteDemo}'\n`);
    ffmpeg(["-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", "-movflags", "+faststart", path.join(FINAL, `${feature}.mp4`)]);
    hechas.push(feature);
    console.log(`${feature}: listo`);
  }
  await browser.close();
  fs.rmSync(TMP, { recursive: true, force: true });
  console.log(`videos: ${hechas.length}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
