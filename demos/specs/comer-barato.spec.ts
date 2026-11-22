// Demo «Dónde comer barato, cerca»: escenas de demos/libretos/comer-barato.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "comer-barato",
  titulo: "Dónde comer barato, cerca",
  escenas: [
    { id: 1, accion: "goto #/comer", subtitulo: "Poco tiempo entre charlas\ny comer en Las Vegas sale caro", duracion_s: 6 },
    { id: 2, accion: "wait 2", subtitulo: "Lugares cerca de donde estás\no de tu próxima sesión", duracion_s: 7 },
    { id: 3, accion: "click [aria-label='Precio'] button", subtitulo: "Elegís cuánto gastar:\nbarato o moderado", duracion_s: 4 },
    { id: 4, accion: "hover [aria-label='Hasta 10 minutos caminando']", subtitulo: "Y cuánto querés caminar:\n5, 10 o 15 minutos", duracion_s: 5 },
    { id: 5, accion: "scroll 400", subtitulo: "Puntaje, reseñas, minutos a pie\ny si está abierto ahora", duracion_s: 6 },
    { id: 6, accion: "click [title='Llevame']", subtitulo: "Tocás Llevame y ves\ncómo llegar caminando", duracion_s: 6 },
  ],
});
