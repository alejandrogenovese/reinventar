// Demo «Sin señal, igual ves tu agenda»: escenas de demos/libretos/modo-sin-senal.yml (regenerar si cambia el libreto).
// Pre-roll con red en #/itinerario y #/ (quedan las copias de lastgood.js); se corta la red antes de la escena 1.
import { definirDemo, PAUSA_PREROLL_MS } from "./_comun";

definirDemo({
  feature: "modo-sin-senal",
  titulo: "Sin señal, igual ves tu agenda",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "La señal se cae justo\ncuando más la necesitás", duracion_s: 7 },
    { id: 2, accion: "hover text=Sin señal · datos de las", subtitulo: "Sin red, ves la última copia\ny de qué hora son los datos", duracion_s: 9 },
    { id: 3, accion: "scroll #hoy-title", subtitulo: "Tu día sigue ahí:\nla charla de ahora y lo que viene", duracion_s: 6 },
    { id: 4, accion: "goto #/itinerario", subtitulo: "El itinerario también, como estaba\nla última vez que hubo señal", duracion_s: 7 },
    { id: 5, accion: "hover text=Sin señal · datos de las", subtitulo: "Con red, al volver a entrar\nves todo al día", duracion_s: 7 },
  ],
  preparar: async ({ page, context, ejecutar }) => {
    await ejecutar("goto #/itinerario");
    await page.waitForTimeout(PAUSA_PREROLL_MS);
    await ejecutar("goto #/");
    await page.waitForTimeout(PAUSA_PREROLL_MS);
    await context.setOffline(true);
  },
});
