// Demo «Ficha de empresa»: escenas de demos/libretos/ficha-de-empresa.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "ficha-de-empresa",
  titulo: "Ficha de empresa",
  escenas: [
    { id: 1, accion: "goto #/buscar", subtitulo: "¿Qué trae una empresa\na re:Invent?", duracion_s: 6 },
    { id: 2, accion: "fill [aria-label='Buscar charlas'] \"bancos el martes\"", subtitulo: "Por ejemplo,\nbancos el martes.", duracion_s: 4 },
    { id: 3, accion: "click button.ra-suggest", subtitulo: "Cada charla muestra quién la da\ny de qué empresa es.", duracion_s: 6 },
    { id: 4, accion: "click a.ra-link[href^='#/empresa/']", subtitulo: "Tocás la empresa:\nsector e industria de un vistazo.", duracion_s: 6 },
    { id: 5, accion: "click role=button[name='Preparar conversación']", subtitulo: "Una ficha para charlar con su gente,\ncruzada con tu perfil.", duracion_s: 7 },
    { id: 6, accion: "wait 8", subtitulo: "Qué hace con AWS,\ntemas y preguntas para abrir.", duracion_s: 9 },
    { id: 7, accion: "scroll 700", subtitulo: "Quiénes vienen y sus charlas,\nlistas para agregar.", duracion_s: 7 },
  ],
});
