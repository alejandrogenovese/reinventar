// Demo «Tu itinerario en el calendario»: escenas de demos/libretos/exportar-calendario.yml (regenerar si cambia el libreto).
// Descarga el .ics: acceptDownloads, y navigator.canShare no acepta archivos (si no, abre la hoja del sistema).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "exportar-calendario",
  titulo: "Tu itinerario en el calendario",
  escenas: [
    { id: 1, accion: "goto #/itinerario", subtitulo: "Tu itinerario, en el calendario\nque usás todos los días.", duracion_s: 7 },
    { id: 2, accion: "scroll 300", subtitulo: "Tus charlas y eventos,\ndía por día.", duracion_s: 5 },
    { id: 3, accion: "wait 2", subtitulo: "Cada charla con hora, sede\ny alarma 15 minutos antes.", duracion_s: 7 },
    { id: 4, accion: "hover role=button[name='Pasar a mi calendario']", subtitulo: "¿Sin reserva? La alarma te avisa\na tiempo para la cola.", duracion_s: 7 },
    { id: 5, accion: "click role=button[name='Pasar a mi calendario']", subtitulo: "Con un toque, la app arma\nel archivo con tu agenda.", duracion_s: 6 },
    { id: 6, accion: "wait 3", subtitulo: "En la compu se descarga;\nen el celular, directo al Calendario.", duracion_s: 7 },
  ],
  contexto: { acceptDownloads: true },
  initScript: "Object.defineProperty(navigator, 'canShare', { value: () => false, configurable: true });",
});
