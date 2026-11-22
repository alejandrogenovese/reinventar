// Demo «Grabá aunque no haya señal»: escenas de demos/libretos/grabar-sin-senal.yml (regenerar si cambia el libreto).
// Pre-roll con red en #/, se corta la red antes de la escena 1 y vuelve al empezar la 8. Crea una grabación real.
import { definirDemo, CLAVE_TIP_NO_MOLESTAR, PAUSA_PREROLL_MS } from "./_comun";

definirDemo({
  feature: "grabar-sin-senal",
  titulo: "Grabá aunque no haya señal",
  escenas: [
    { id: 1, accion: "goto #/nueva", subtitulo: "En un salón lleno,\nla señal va y viene.", duracion_s: 5 },
    { id: 2, accion: "fill #title \"Keynote de apertura\"", subtitulo: "Preparás la grabación como siempre,\nsin señal.", duracion_s: 5 },
    { id: 3, accion: "click role=button[name='Preparar grabación']", subtitulo: "No te frena: arranca\nuna grabación en el celular.", duracion_s: 5 },
    { id: 4, accion: "click button.ra-rec[aria-label='Empezar a grabar']", subtitulo: "Grabás normal: todo queda en el teléfono\nhasta que vuelva la red.", duracion_s: 8 },
    { id: 5, accion: "wait 5", subtitulo: "El audio se va guardando de a pedazos.", duracion_s: 6 },
    { id: 6, accion: "click role=button[name='Terminar y procesar']", subtitulo: "Queda guardada y se procesa sola\ncuando vuelva la señal.", duracion_s: 8 },
    { id: 7, accion: "click role=button[name='Volver al inicio']", subtitulo: "En Inicio la ves aparte,\nesperando señal.", duracion_s: 6 },
    { id: 8, accion: "wait 10", subtitulo: "Cuando vuelve la red, se sube sola,\nsin que hagas nada.", duracion_s: 11 },
    { id: 9, accion: "goto /?r=1#/", subtitulo: "Y aparece en Tus grabaciones,\ncomo cualquier otra.", duracion_s: 5 },
  ],
  localStorage: { [CLAVE_TIP_NO_MOLESTAR]: "1" },
  contexto: { permissions: ["microphone"] },
  preparar: async ({ page, context, ejecutar }) => {
    await ejecutar("goto #/");
    await page.waitForTimeout(PAUSA_PREROLL_MS);
    await context.setOffline(true);
  },
  antesDeEscena: {
    8: async ({ context }) => context.setOffline(false),
  },
});
