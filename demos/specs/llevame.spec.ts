// Demo «Llevame: cómo llegar caminando»: escenas de demos/libretos/llevame.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "llevame",
  titulo: "Llevame: cómo llegar caminando",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "No hace falta saber el camino\nentre sedes", duracion_s: 5 },
    { id: 2, accion: "hover [title='Llevame']", subtitulo: "Junto a cada charla, Llevame", duracion_s: 5 },
    { id: 3, accion: "click [title='Llevame']", subtitulo: "El recorrido a pie desde donde estás\nhasta la sede", duracion_s: 7 },
    { id: 4, accion: "wait 3", subtitulo: "Minutos caminando y distancia,\nen un mapa dentro de la app", duracion_s: 7 },
    { id: 5, accion: "hover role=link[name='Abrir en Google Maps']", subtitulo: "¿Paso a paso? Lo abrís\nen Google Maps", duracion_s: 6 },
    { id: 6, accion: "hover #llevame-titulo", subtitulo: "Sabés cuánto te lleva\ny llegás sin dar vueltas", duracion_s: 5 },
  ],
});
