// Demo «¿Te perdiste una charla?»: escenas de demos/libretos/me-la-perdi.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "me-la-perdi",
  titulo: "¿Te perdiste una charla?",
  escenas: [
    { id: 1, accion: "goto #/itinerario", subtitulo: "A veces te quedás afuera\nde una charla", duracion_s: 7 },
    { id: 2, accion: "hover role=button[name='Me la perdí']", subtitulo: "Cuando termina, aparece\n«Me la perdí»", duracion_s: 5 },
    { id: 3, accion: "click role=button[name='Me la perdí']", subtitulo: "Si se repite, primero los horarios\nque no chocan", duracion_s: 7 },
    { id: 4, accion: "scroll 400", subtitulo: "Y charlas parecidas que empiezan\nen las próximas horas", duracion_s: 5 },
    { id: 5, accion: "click role=button[name='Ir a esa']", subtitulo: "Elegís otro horario y queda\ncambiado en tu itinerario", duracion_s: 5 },
    { id: 6, accion: "wait 3", subtitulo: "Listo: la charla vuelve a tu agenda\nen el nuevo horario", duracion_s: 6 },
  ],
});
