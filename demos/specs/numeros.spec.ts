// Demo «Tu re:Invent en números»: escenas de demos/libretos/numeros.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "numeros",
  titulo: "Tu re:Invent en números",
  escenas: [
    { id: 1, accion: "goto #/itinerario", subtitulo: "¿Cómo viene tu semana?\nMirala en números.", duracion_s: 6 },
    { id: 2, accion: "click a.ra-sec-action[href^='#/itinerario/numeros']", subtitulo: "Lo agendado, las horas ocupadas,\nla caminata y los choques.", duracion_s: 7 },
    { id: 3, accion: "scroll 400", subtitulo: "Tu semana de 8 a 22 h,\ncon lo que se pisa marcado.", duracion_s: 9 },
    { id: 4, accion: "scroll 500", subtitulo: "Cuánto caminás por día y cuánto\ncubre tu agenda lo que pediste.", duracion_s: 8 },
    { id: 5, accion: "click #num-catalogo", subtitulo: "Todo re:Invent: charlas,\nspeakers, sedes y lanzamientos.", duracion_s: 5 },
    { id: 6, accion: "scroll 500", subtitulo: "Qué días y horas vienen cargados\ny dónde ya tenés algo.", duracion_s: 7 },
    { id: 7, accion: "hover #numeros-panel a[href^='#/buscar']", subtitulo: "Tocás una barra y vas directo\na esas charlas en Buscar.", duracion_s: 6 },
  ],
});
