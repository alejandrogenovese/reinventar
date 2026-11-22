// Demo «Revisá tu ficha»: escenas de demos/libretos/itinerario-ficha.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "itinerario-ficha",
  titulo: "Revisá tu ficha",
  escenas: [
    { id: 1, accion: "goto #/itinerario/ficha", subtitulo: "Después de la entrevista,\nla IA arma tu ficha.", duracion_s: 6 },
    { id: 2, accion: "wait 3", subtitulo: "Un resumen de quién sos,\nque podés editar.", duracion_s: 5 },
    { id: 3, accion: "hover button.ra-dots", subtitulo: "Tus prioridades, cada una\ncon su importancia de 1 a 3.", duracion_s: 6 },
    { id: 4, accion: "click [aria-label^='Sacar ']", subtitulo: "Lo que no va,\nlo sacás de la lista.", duracion_s: 5 },
    { id: 5, accion: "click button.ra-dots", subtitulo: "¿Te importa más o menos?\nLo tocás y cambia el peso.", duracion_s: 7 },
    { id: 6, accion: "click role=button[name='Está bien, sigamos →']", subtitulo: "¿Te cierra? Seguís y pasás\na armar tu día.", duracion_s: 7 },
    { id: 7, accion: "wait 3", subtitulo: "Te propone charlas según tu ficha,\nla distancia y la cola.", duracion_s: 6 },
  ],
});
