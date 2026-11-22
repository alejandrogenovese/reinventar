// Demo «Prepará una grabación»: escenas de demos/libretos/nueva-grabacion.yml (regenerar si cambia el libreto).
// Tip de no molestar ya visto y micrófono falso. Crea una sesión real: descartarla después.
import { definirDemo, CLAVE_TIP_NO_MOLESTAR } from "./_comun";

definirDemo({
  feature: "nueva-grabacion",
  titulo: "Prepará una grabación",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "Estás por entrar a una charla\ny la querés grabar.", duracion_s: 5 },
    { id: 2, accion: "click [aria-label='Nueva grabación']", subtitulo: "Desde Inicio arrancás una nueva.", duracion_s: 4 },
    { id: 3, accion: "hover #talkq", subtitulo: "Si está en el catálogo, la buscás\ny se completan sus datos.", duracion_s: 9 },
    { id: 4, accion: "click #k0", subtitulo: "Si no, elegís el tipo: keynote,\nchalk talk, workshop o breakout.", duracion_s: 6 },
    { id: 5, accion: "fill #title \"Keynote de apertura\"", subtitulo: "Le ponés un título.", duracion_s: 4 },
    { id: 6, accion: "fill #code \"ANT301\"", subtitulo: "Sumás el código de agenda.", duracion_s: 3 },
    { id: 7, accion: "fill #venue \"Venetian · Hall A\"", subtitulo: "Y la sala, si querés tenerla anotada.", duracion_s: 4 },
    { id: 8, accion: "click role=button[name='Preparar grabación']", subtitulo: "Preparás la grabación\ny se abre el grabador.", duracion_s: 5 },
    { id: 9, accion: "wait 3", subtitulo: "El grabador te espera,\ncon los datos de la charla arriba.", duracion_s: 8 },
  ],
  localStorage: { [CLAVE_TIP_NO_MOLESTAR]: "1" },
  contexto: { permissions: ["microphone"] },
});
