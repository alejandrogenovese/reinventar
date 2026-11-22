// Demo «La franja que te dice cuándo salir»: escenas de demos/libretos/franja-cuenta-regresiva.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "franja-cuenta-regresiva",
  titulo: "La franja que te dice cuándo salir",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "Las sedes quedan lejos\ny caminar lleva tiempo", duracion_s: 5 },
    { id: 2, accion: "hover #countdown-banner", subtitulo: "Falta menos de una hora:\narriba, la cuenta regresiva", duracion_s: 7 },
    { id: 3, accion: "hover #countdown-banner .countdown-text", subtitulo: "Te dice a qué hora salir,\nsegún lo que caminás y tu margen", duracion_s: 7 },
    { id: 4, accion: "goto #/itinerario", subtitulo: "Te sigue en cualquier pantalla", duracion_s: 6 },
    { id: 5, accion: "click #countdown-banner .countdown-text", subtitulo: "La tocás y vas directo a la charla", duracion_s: 5 },
    { id: 6, accion: "wait 3", subtitulo: "La ficha de la charla,\ny la franja sigue contando", duracion_s: 6 },
  ],
});
