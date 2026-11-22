// Demo «Preguntar al catálogo»: escenas de demos/libretos/buscar-preguntar.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "buscar-preguntar",
  titulo: "Preguntar al catálogo",
  escenas: [
    { id: 1, accion: "goto #/buscar?modo=preguntar", subtitulo: "Preguntale al catálogo\ncomo le hablarías a un colega.", duracion_s: 7 },
    { id: 2, accion: "fill [aria-label='Tu pregunta'] \"Bancos latinoamericanos usando IA generativa\"", subtitulo: "Escribí la pregunta\ncon tus palabras.", duracion_s: 7 },
    { id: 3, accion: "click [aria-label='Enviar pregunta']", subtitulo: "Busca en todo el catálogo\ny en lo que grabaste.", duracion_s: 7 },
    { id: 4, accion: "wait 8", subtitulo: "Te responde citando\nlas charlas que sirven.", duracion_s: 9 },
    { id: 5, accion: "scroll 600", subtitulo: "Debajo, las charlas citadas\ny los momentos de tus grabaciones.", duracion_s: 9 },
    { id: 6, accion: "click [aria-label='Agregar al itinerario']", subtitulo: "La agregás al itinerario\nsin salir de la conversación.", duracion_s: 7 },
    { id: 7, accion: "wait 2", subtitulo: "La conversación queda:\nvolvés y seguís preguntando.", duracion_s: 6 },
  ],
});
