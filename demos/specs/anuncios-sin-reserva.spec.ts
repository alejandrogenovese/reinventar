// Demo «Keynotes y lanzamientos sin reserva»: escenas de demos/libretos/anuncios-sin-reserva.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "anuncios-sin-reserva",
  titulo: "Keynotes y lanzamientos sin reserva",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "Keynotes y lanzamientos no se reservan:\nse entra por la cola", duracion_s: 7 },
    { id: 2, accion: "scroll #anuncios-title", subtitulo: "Los que quedan hoy y no están\nen tu itinerario", duracion_s: 7 },
    { id: 3, accion: "click [aria-controls='anuncios-fila'][aria-label='Siguiente']", subtitulo: "Cuánto falta y desde qué hora\narranca la fila", duracion_s: 7 },
    { id: 4, accion: "click [aria-controls='anuncios-fila'][aria-label='Siguiente']", subtitulo: "La agregás al itinerario\nsin salir de Inicio", duracion_s: 6 },
    { id: 5, accion: "click a.ra-ann.is-more", subtitulo: "Ver todos te lleva a Buscar\ncon el filtro ya puesto", duracion_s: 7 },
    { id: 6, accion: "wait 3", subtitulo: "La lista completa del día,\npara elegir con calma", duracion_s: 6 },
  ],
});
