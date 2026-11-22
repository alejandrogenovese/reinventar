// Config de Playwright solo para grabar las demos (separado de los tests de la app, que son pytest).
// El video, el contexto del celular y el timeline los arma demos/specs/_comun.ts en cada spec.
import { defineConfig } from "@playwright/test";

const MINUTO_MS = 60_000;

// Micrófono falso para las demos de grabación; con DEMO_AUDIO_WAV se usa un wav en vez del tono de prueba.
const MICROFONO_FALSO = [
  "--use-fake-ui-for-media-stream",
  "--use-fake-device-for-media-stream",
  ...(process.env.DEMO_AUDIO_WAV ? [`--use-file-for-fake-audio-capture=${process.env.DEMO_AUDIO_WAV}`] : []),
];

export default defineConfig({
  testDir: "./specs",
  testMatch: "*.spec.ts",
  outputDir: "./out/test-results",
  // Todas usan el mismo usuario tester en staging: de a una, sin reintentos (un reintento duplica datos).
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 5 * MINUTO_MS,
  reporter: [["list"]],
  use: {
    browserName: "chromium",
    headless: true,
    actionTimeout: 30_000,
    navigationTimeout: 45_000,
    launchOptions: { args: MICROFONO_FALSO },
  },
});
