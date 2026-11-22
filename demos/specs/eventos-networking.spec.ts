// Demo «Eventos de networking en Las Vegas»: escenas de demos/libretos/eventos-networking.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "eventos-networking",
  titulo: "Eventos de networking en Las Vegas",
  escenas: [
    { id: 1, accion: "goto #/eventos", subtitulo: "Re:Invent sigue fuera de las charlas:\ndesayunos, happy hours y fiestas", duracion_s: 7 },
    { id: 2, accion: "hover [aria-label='Día']", subtitulo: "Arranca en el día de hoy;\ncambiás de día con un toque", duracion_s: 7 },
    { id: 3, accion: "hover [aria-label='Tipo de evento']", subtitulo: "Filtrás por tipo de evento\no por hora de inicio", duracion_s: 5 },
    { id: 4, accion: "click role=button[name='↕ Más cerca']", subtitulo: "Los ordenás por cercanía\npara no cruzar todo el Strip", duracion_s: 6 },
    { id: 5, accion: "click a.ra-link[href^='#/evento/']", subtitulo: "De qué se trata, cuándo, dónde\ny quién lo organiza", duracion_s: 8 },
    { id: 6, accion: "hover role=button[name='+ Itinerario']", subtitulo: "Lo agregás y queda fijado,\no vas directo a anotarte", duracion_s: 6 },
  ],
});
