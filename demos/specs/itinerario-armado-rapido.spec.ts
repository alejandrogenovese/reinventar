// Demo «Armado rápido con IA»: escenas de demos/libretos/itinerario-armado-rapido.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "itinerario-armado-rapido",
  titulo: "Armado rápido con IA",
  escenas: [
    { id: 1, accion: "goto #/itinerario/nuevo", subtitulo: "¿Poco tiempo? La IA te arma\nuna agenda completa en un minuto.", duracion_s: 8 },
    { id: 2, accion: "click role=button[name='Armado rápido']", subtitulo: "Contás quién sos\ny qué te interesa.", duracion_s: 6 },
    { id: 3, accion: "fill #role \"Architect Lead de Arquitectura de Datos\"", subtitulo: "Primero tu rol, para afinar\nqué charlas te sirven.", duracion_s: 5 },
    { id: 4, accion: "click #int0", subtitulo: "Marcás tus intereses\nentre los temas del catálogo.", duracion_s: 5 },
    { id: 5, accion: "fill #prompt \"gobierno de datos, lakehouse y agentic AI aplicado a banca\"", subtitulo: "Y si querés, contás más\ncon tus palabras.", duracion_s: 5 },
    { id: 6, accion: "click role=button[name='Generar itinerario']", subtitulo: "La IA elige las sesiones\ny te arma la agenda por día.", duracion_s: 6 },
    { id: 7, accion: "wait 12", subtitulo: "Unos segundos y listo.", duracion_s: 13 },
    { id: 8, accion: "hover .mapbox", subtitulo: "Tu itinerario, con el mapa\ny las charlas de cada día.", duracion_s: 7 },
  ],
});
