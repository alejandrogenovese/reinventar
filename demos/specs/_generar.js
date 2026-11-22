// Genera demos/specs/<feature>.spec.ts a partir de los libretos de demos/libretos/*.yml.
// Uso (desde la raíz del repo; ruby trae YAML y JSON sin instalar nada):
//   ruby -ryaml -rjson -e 'puts JSON.dump(Dir["demos/libretos/*.yml"].sort.to_h { |f| d = YAML.load_file(f); [d["feature"], d] })' > /tmp/libretos.json
//   node demos/specs/_generar.js /tmp/libretos.json demos/specs
// OPCIONES agrega a cada demo lo que piden las notas del libreto (permisos, red, passkey, variables {x}).
const fs = require("fs");
const path = require("path");
const [, , json, outDir] = process.argv;
const libretos = JSON.parse(fs.readFileSync(json, "utf8"));

const TIP = `localStorage: { [CLAVE_TIP_NO_MOLESTAR]: "1" },`;
const MIC = `contexto: { permissions: ["microphone"] },`;
const OPCIONES = {
  "ajustes-ubicacion-y-alertas": {
    nota: "Geolocalización concedida y fijada en el Venetian; contexto nuevo, así «Usar mi ubicación» arranca apagada.",
    imports: ["VENETIAN"],
    cuerpo: `contexto: { permissions: ["geolocation"], geolocation: VENETIAN },`,
  },
  "cambio-de-contrasena": {
    nota: "BLOQUEANTE en el libreto: nunca con tester. Cuenta descartable desde DEMO_USUARIO / DEMO_PASSWORD_ACTUAL.",
    cuerpo: `cuenta: { envUsuario: "DEMO_USUARIO", envPassword: "DEMO_PASSWORD_ACTUAL", prohibido: "tester" },`,
  },
  "cambio-de-tema": { nota: "Contexto nuevo en tema claro (colorScheme light, sin reinventar.theme)." },
  "detalle-de-grabacion": {
    nota: "Exportar .md descarga un archivo: acceptDownloads.",
    cuerpo: `contexto: { acceptDownloads: true },`,
  },
  "exportar-calendario": {
    nota: "Descarga el .ics: acceptDownloads, y navigator.canShare no acepta archivos (si no, abre la hoja del sistema).",
    cuerpo: `contexto: { acceptDownloads: true },\n  initScript: "Object.defineProperty(navigator, 'canShare', { value: () => false, configurable: true });",`,
  },
  "grabar-charla": { nota: "Tip de no molestar ya visto y micrófono falso (flags en playwright.config.ts). Crea una grabación real: borrarla después.", cuerpo: `${TIP}\n  ${MIC}` },
  "grabar-desde-charla": { nota: "Tip de no molestar ya visto y micrófono falso. Crea una grabación real: borrarla después.", cuerpo: `${TIP}\n  ${MIC}` },
  "nueva-grabacion": { nota: "Tip de no molestar ya visto y micrófono falso. Crea una sesión real: descartarla después.", cuerpo: `${TIP}\n  ${MIC}` },
  "grabar-sin-senal": {
    nota: "Pre-roll con red en #/, se corta la red antes de la escena 1 y vuelve al empezar la 8. Crea una grabación real.",
    imports: ["PAUSA_PREROLL_MS"],
    cuerpo: `${TIP}
  ${MIC}
  preparar: async ({ page, context, ejecutar }) => {
    await ejecutar("goto #/");
    await page.waitForTimeout(PAUSA_PREROLL_MS);
    await context.setOffline(true);
  },
  antesDeEscena: {
    8: async ({ context }) => context.setOffline(false),
  },`,
  },
  "modo-sin-senal": {
    nota: "Pre-roll con red en #/itinerario y #/ (quedan las copias de lastgood.js); se corta la red antes de la escena 1.",
    imports: ["PAUSA_PREROLL_MS"],
    cuerpo: `preparar: async ({ page, context, ejecutar }) => {
    await ejecutar("goto #/itinerario");
    await page.waitForTimeout(PAUSA_PREROLL_MS);
    await ejecutar("goto #/");
    await page.waitForTimeout(PAUSA_PREROLL_MS);
    await context.setOffline(true);
  },`,
  },
  "itinerario-armar-dia": {
    nota: "Las opciones las arma el LLM (~15 s): antes de la escena 4 se espera el primer «Elegir».",
    imports: ["ESPERA_LLM_MS", "localizar"],
    cuerpo: `antesDeEscena: {
    4: async ({ page }) => localizar(page, "role=button[name='Elegir']").waitFor({ timeout: ESPERA_LLM_MS }),
  },`,
  },
  "login-con-contrasena": { nota: "Arranca sin sesión; la contraseña sale de TESTER_PASSWORD.", cuerpo: `sinSesion: true,` },
  "login-con-passkey": {
    nota: "Autenticador WebAuthn virtual por CDP. Pre-roll: login, registrar la passkey en Ajustes y cerrar sesión. Post-roll: quitarla.",
    cuerpo: `sinSesion: true,
  passkey: true,
  preparar: async ({ page, ejecutar, loginCuenta }) => {
    await loginCuenta();
    await ejecutar("goto #/ajustes");
    await ejecutar("click role=button[name='Activar en este dispositivo']");
    await page.getByRole("button", { name: "Quitar", exact: true }).first().waitFor();
    await ejecutar("click role=button[name='Cerrar sesión']");
    await page.waitForURL((u) => u.hash.startsWith("#/login"));
  },
  despues: async ({ ejecutar }) => {
    await ejecutar("goto #/ajustes");
    await ejecutar("click role=button[name='Quitar']");
  },`,
  },
  "passkey-ajustes": {
    nota: "Autenticador WebAuthn virtual por CDP antes de cargar la app. Post-roll: quitar la passkey registrada.",
    cuerpo: `passkey: true,
  despues: async ({ ejecutar }) => ejecutar("click role=button[name='Quitar']"),`,
  },
  "notificaciones-push": {
    nota: "Permiso de notificaciones concedido. La suscripción Web Push puede fallar en headless.",
    cuerpo: `contexto: { permissions: ["notifications"] },`,
  },
  "shows": {
    nota: "{id} de la escena 4 sale de DEMO_SHOW_ID (un show con varias funciones en la semana).",
    cuerpo: `variables: { id: "DEMO_SHOW_ID" },`,
  },
  "vuelos-y-hoteles": {
    nota: "{id} de la escena 5: DEMO_VUELO_ID o, si no está, el del primer vuelo de la lista. Es de solo lectura: «Agregar un vuelo» solo abre el formulario.",
    cuerpo: `variables: {
    id: async ({ page }) => process.env.DEMO_VUELO_ID
      ?? (await page.locator("article[id^='vuelo-']").first().getAttribute("id"))?.replace(/^vuelo-/, "") ?? "",
  },`,
  },
};

const conocidas = new Set(Object.keys(libretos));
for (const k of Object.keys(OPCIONES)) if (!conocidas.has(k)) throw new Error(`Opción para feature inexistente: ${k}`);

for (const [feature, { titulo, escenas }] of Object.entries(libretos)) {
  const op = OPCIONES[feature] ?? {};
  const usaTip = (op.cuerpo ?? "").includes("CLAVE_TIP_NO_MOLESTAR");
  const imports = ["definirDemo", ...(usaTip ? ["CLAVE_TIP_NO_MOLESTAR"] : []), ...(op.imports ?? [])];
  const lineas = escenas.map((e) => `    { id: ${e.id}, accion: ${JSON.stringify(e.accion)}, subtitulo: ${JSON.stringify(e.subtitulo)}, duracion_s: ${e.duracion_s} },`);
  const src = `// Demo «${titulo}»: escenas de demos/libretos/${feature}.yml (regenerar si cambia el libreto).
${op.nota ? `// ${op.nota}\n` : ""}import { ${imports.join(", ")} } from "./_comun";

definirDemo({
  feature: ${JSON.stringify(feature)},
  titulo: ${JSON.stringify(titulo)},
  escenas: [
${lineas.join("\n")}
  ],${op.cuerpo ? `\n  ${op.cuerpo}` : ""}
});
`;
  fs.writeFileSync(path.join(outDir, `${feature}.spec.ts`), src);
}
console.log(`specs: ${Object.keys(libretos).length}`);
