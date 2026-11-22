// Demo «Tema claro u oscuro»: escenas de demos/libretos/cambio-de-tema.yml (regenerar si cambia el libreto).
// Contexto nuevo en tema claro (colorScheme light, sin reinventar.theme).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "cambio-de-tema",
  titulo: "Tema claro u oscuro",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "En un keynote a oscuras,\nuna pantalla blanca encandila.", duracion_s: 6 },
    { id: 2, accion: "click #themeBtn", subtitulo: "Con un toque arriba, pasás a oscuro.", duracion_s: 5 },
    { id: 3, accion: "goto #/ajustes", subtitulo: "Se mantiene en toda la app.", duracion_s: 5 },
    { id: 4, accion: "click #themeBtn", subtitulo: "Afuera, con sol, volvés al claro\ncon el mismo botón.", duracion_s: 7 },
    { id: 5, accion: "wait 3", subtitulo: "Se acuerda de tu elección. Si no elegiste,\nsigue el tema de tu celular.", duracion_s: 10 },
  ],
});
