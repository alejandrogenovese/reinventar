// Demo «Shows en Las Vegas, sin chocar»: escenas de demos/libretos/shows.yml (regenerar si cambia el libreto).
// {id} de la escena 4 sale de DEMO_SHOW_ID (un show con varias funciones en la semana).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "shows",
  titulo: "Shows en Las Vegas, sin chocar",
  escenas: [
    { id: 1, accion: "goto #/eventos", subtitulo: "Una noche libre: shows,\nconciertos y deportes", duracion_s: 7 },
    { id: 2, accion: "click role=tab[name='Shows']", subtitulo: "Los shows del día, con precio\nmínimo y la sede", duracion_s: 7 },
    { id: 3, accion: "hover [aria-label='Tipo de show']", subtitulo: "Música, teatro, comedia,\ndeportes o actividades", duracion_s: 5 },
    { id: 4, accion: "goto #/show/{id}", subtitulo: "Elegís la función que te sirve", duracion_s: 5 },
    { id: 5, accion: "scroll 500", subtitulo: "Te dice cuándo conviene ir,\nsegún tu agenda de ese día", duracion_s: 9 },
    { id: 6, accion: "hover role=button[name='Ver esta función']", subtitulo: "Cada opción dice por qué:\nlibre, justa o choca", duracion_s: 6 },
    { id: 7, accion: "click role=button[name='Ver esta función']", subtitulo: "Horario, precio y el link\na Ticketmaster para comprar", duracion_s: 7 },
  ],
  variables: { id: "DEMO_SHOW_ID" },
});
