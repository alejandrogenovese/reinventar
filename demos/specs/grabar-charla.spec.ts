// Demo «Grabá una charla entera»: escenas de demos/libretos/grabar-charla.yml (regenerar si cambia el libreto).
// Tip de no molestar ya visto y micrófono falso (flags en playwright.config.ts). Crea una grabación real: borrarla después.
import { definirDemo, CLAVE_TIP_NO_MOLESTAR } from "./_comun";

definirDemo({
  feature: "grabar-charla",
  titulo: "Grabá una charla entera",
  escenas: [
    { id: 1, accion: "goto #/nueva", subtitulo: "Arranca el keynote y querés\nllevarte todo lo que se dice.", duracion_s: 6 },
    { id: 2, accion: "fill #title \"Keynote de apertura\"", subtitulo: "Le ponés título a la grabación.", duracion_s: 4 },
    { id: 3, accion: "click role=button[name='Preparar grabación']", subtitulo: "Se abre el grabador con el micrófono.", duracion_s: 5 },
    { id: 4, accion: "hover [aria-label='Entrada de audio']", subtitulo: "El medidor te muestra si llega el sonido.\nSi no llega nada, te avisa.", duracion_s: 7 },
    { id: 5, accion: "click button.ra-rec[aria-label='Empezar a grabar']", subtitulo: "Empezás a grabar y corre el contador.", duracion_s: 4 },
    { id: 6, accion: "wait 5", subtitulo: "Celular cerca del parlante\ny con la pantalla prendida.", duracion_s: 6 },
    { id: 7, accion: "click button.ra-rec[aria-label='Pausar grabación']", subtitulo: "Si hay un corte, pausás\ny el contador se frena.", duracion_s: 5 },
    { id: 8, accion: "click button.ra-rec[aria-label='Seguir grabando']", subtitulo: "Seguís cuando vuelve la charla,\nen la misma grabación.", duracion_s: 6 },
    { id: 9, accion: "click role=button[name='Modo sala']", subtitulo: "Modo sala: pantalla negra con el contador.\nNo molestás a nadie.", duracion_s: 7 },
    { id: 10, accion: "click [aria-label='Modo sala. Tocá para salir.']", subtitulo: "La tocás y volvés al grabador.", duracion_s: 4 },
    { id: 11, accion: "click role=button[name='Terminar y procesar']", subtitulo: "Al terminar, sube lo que falte\ny arranca el procesamiento.", duracion_s: 5 },
    { id: 12, accion: "wait 5", subtitulo: "Te lleva a la grabación: ahí aparecen\ntranscripción y resumen.", duracion_s: 8 },
  ],
  localStorage: { [CLAVE_TIP_NO_MOLESTAR]: "1" },
  contexto: { permissions: ["microphone"] },
});
