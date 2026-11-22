// Demo «Tu itinerario»: escenas de demos/libretos/itinerario-ver.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "itinerario-ver",
  titulo: "Tu itinerario",
  escenas: [
    { id: 1, accion: "goto #/itinerario", subtitulo: "Todo lo que elegiste,\nordenado por día.", duracion_s: 7 },
    { id: 2, accion: "hover .mapbox", subtitulo: "El mapa te muestra\nel recorrido del día.", duracion_s: 5 },
    { id: 3, accion: "scroll 400", subtitulo: "Cada charla con su hora,\nsu sede y quién la da.", duracion_s: 6 },
    { id: 4, accion: "click role=button[name='Marcar reservada']", subtitulo: "¿La reservaste en AWS? Marcala\ny no te suma la cola.", duracion_s: 11 },
    { id: 5, accion: "click role=button[name='Fijar']", subtitulo: "Lo que fijás queda aunque\nregeneres el itinerario.", duracion_s: 5 },
    { id: 6, accion: "scroll .tabs [role=tab]", subtitulo: "Volvés arriba para ver\nel resto de la semana.", duracion_s: 5 },
    { id: 7, accion: "click .tabs [role=tab]:nth-child(2)", subtitulo: "Pasás al día siguiente\ny el mapa se redibuja.", duracion_s: 6 },
  ],
});
