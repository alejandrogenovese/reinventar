// Demo «Ficha de speaker»: escenas de demos/libretos/ficha-de-speaker.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "ficha-de-speaker",
  titulo: "Ficha de speaker",
  escenas: [
    { id: 1, accion: "goto #/buscar", subtitulo: "Detrás de cada charla hay gente\nque vale la pena conocer.", duracion_s: 6 },
    { id: 2, accion: "fill [aria-label='Buscar charlas'] \"bancos el martes\"", subtitulo: "Por ejemplo, charlas\nde bancos el martes.", duracion_s: 4 },
    { id: 3, accion: "click button.ra-suggest", subtitulo: "Ves quién da cada charla.", duracion_s: 7 },
    { id: 4, accion: "click a.ra-link[href^='#/speaker/']", subtitulo: "Tocás un nombre\ny se abre su ficha.", duracion_s: 5 },
    { id: 5, accion: "wait 2", subtitulo: "Cargo, empresa y, si hay perfil,\ntrayectoria, educación y skills.", duracion_s: 8 },
    { id: 6, accion: "click role=button[name='Preparar conversación']", subtitulo: "La IA te arma una ficha\ncruzada con tu perfil.", duracion_s: 7 },
    { id: 7, accion: "wait 8", subtitulo: "Tarda unos segundos\nla primera vez.", duracion_s: 9 },
    { id: 8, accion: "scroll 300", subtitulo: "Quién es, su empresa y AWS,\ntemas y preguntas para charlar.", duracion_s: 8 },
  ],
});
