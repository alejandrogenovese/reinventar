// Demo «Grabá la charla de tu itinerario»: escenas de demos/libretos/grabar-desde-charla.yml (regenerar si cambia el libreto).
// Tip de no molestar ya visto y micrófono falso. Crea una grabación real: borrarla después.
import { definirDemo, CLAVE_TIP_NO_MOLESTAR } from "./_comun";

definirDemo({
  feature: "grabar-desde-charla",
  titulo: "Grabá la charla de tu itinerario",
  escenas: [
    { id: 1, accion: "goto #/grabar-charla/IND302-R", subtitulo: "Empieza una charla y nadie la graba:\nte llega «¿La grabás?».", duracion_s: 8 },
    { id: 2, accion: "wait 2", subtitulo: "Caés acá, con la charla,\nla sala y el horario.", duracion_s: 6 },
    { id: 3, accion: "hover role=button[name='Empezar a grabar']", subtitulo: "No arranca sola: así no quedan\ngrabaciones vacías por error.", duracion_s: 5 },
    { id: 4, accion: "click role=button[name='Empezar a grabar']", subtitulo: "Se crea la grabación con título,\ncódigo, sala y speakers.", duracion_s: 7 },
    { id: 5, accion: "wait 3", subtitulo: "El grabador, con la charla cargada.\nTambién desde Hoy y desde la ficha.", duracion_s: 11 },
    { id: 6, accion: "click button.ra-rec[aria-label='Empezar a grabar']", subtitulo: "Un toque más y estás grabando.", duracion_s: 4 },
  ],
  localStorage: { [CLAVE_TIP_NO_MOLESTAR]: "1" },
  contexto: { permissions: ["microphone"] },
});
