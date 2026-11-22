// Demo «Entrá con Face ID o huella»: escenas de demos/libretos/login-con-passkey.yml (regenerar si cambia el libreto).
// Autenticador WebAuthn virtual por CDP. Pre-roll: login, registrar la passkey en Ajustes y cerrar sesión. Post-roll: quitarla.
import { definirDemo } from "./_comun";

definirDemo({
  feature: "login-con-passkey",
  titulo: "Entrá con Face ID o huella",
  escenas: [
    { id: 1, accion: "goto #/login", subtitulo: "En el evento no querés andar\ntipeando contraseñas.", duracion_s: 7 },
    { id: 2, accion: "hover role=button[name^='Entrar con']", subtitulo: "Si tu celular tiene Face ID o huella,\ntenés este atajo.", duracion_s: 6 },
    { id: 3, accion: "click role=button[name^='Entrar con']", subtitulo: "Lo tocás, confirmás con tu cara\no tu dedo, y adentro.", duracion_s: 6 },
    { id: 4, accion: "wait 3", subtitulo: "Entrás directo a Inicio, sin escribir.\nNo se guarda ningún dato biométrico.", duracion_s: 7 },
    { id: 5, accion: "hover [aria-label='Ajustes']", subtitulo: "¿No lo activaste? Entrás con contraseña\ny lo prendés en Ajustes.", duracion_s: 7 },
  ],
  sinSesion: true,
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
  },
});
