// Demo «¿Está llena? Avisá desde la puerta»: escenas de demos/libretos/avisos-lleno-cola.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "avisos-lleno-cola",
  titulo: "¿Está llena? Avisá desde la puerta",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "AWS no publica cuántos lugares quedan:\nlo cuenta la gente en la puerta", duracion_s: 7 },
    { id: 2, accion: "scroll #hoy-title", subtitulo: "Desde un rato antes, te pregunta\nsi estás en la puerta", duracion_s: 8 },
    { id: 3, accion: "click role=button[name='Hay mucha cola']", subtitulo: "¿Mucha cola? Lo avisás\ncon un toque", duracion_s: 5 },
    { id: 4, accion: "hover .ra-lleno-dato", subtitulo: "El resto ve cuántos avisaron\ny hace cuánto. Nunca quién", duracion_s: 6 },
    { id: 5, accion: "wait 3", subtitulo: "Decidís si ir o buscar otra,\nantes de caminar hasta la sala", duracion_s: 7 },
  ],
});
