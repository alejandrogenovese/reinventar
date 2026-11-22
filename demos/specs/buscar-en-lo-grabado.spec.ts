// Demo «Buscá en lo que grabaste»: escenas de demos/libretos/buscar-en-lo-grabado.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "buscar-en-lo-grabado",
  titulo: "Buscá en lo que grabaste",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "¿En qué charla hablaron de agentes?\nNo hace falta acordarse.", duracion_s: 5 },
    { id: 2, accion: "fill [aria-label='Buscar en lo que grabaste'] \"agentes\"", subtitulo: "Escribís el tema y busca\nen las transcripciones del equipo.", duracion_s: 7 },
    { id: 3, accion: "wait 2", subtitulo: "La charla, el minuto\ny lo que se dijo.", duracion_s: 7 },
    { id: 4, accion: "click a.ra-hit", subtitulo: "Tocás uno y caés justo en ese punto.", duracion_s: 6 },
    { id: 5, accion: "wait 3", subtitulo: "El momento queda marcado,\ncon la búsqueda arriba.", duracion_s: 7 },
    { id: 6, accion: "hover [aria-label='Quitar la marca de la búsqueda']", subtitulo: "Después sacás la marca y seguís leyendo.", duracion_s: 5 },
  ],
});
