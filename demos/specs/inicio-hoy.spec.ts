// Demo «Tu día de re:Invent, de un vistazo»: escenas de demos/libretos/inicio-hoy.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "inicio-hoy",
  titulo: "Tu día de re:Invent, de un vistazo",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "Inicio te muestra tu día\napenas abrís la app", duracion_s: 7 },
    { id: 2, accion: "scroll #hoy-title", subtitulo: "La charla de ahora,\ncon sala y horario", duracion_s: 7 },
    { id: 3, accion: "scroll 300", subtitulo: "Lo que sigue, con cuenta regresiva\ny a qué hora salir", duracion_s: 8 },
    { id: 4, accion: "wait 2", subtitulo: "Sin reserva: te dice desde qué hora\nhacer la cola", duracion_s: 6 },
    { id: 5, accion: "hover role=button[name='Grabar esta charla']", subtitulo: "Un toque y grabás la charla,\ncon los datos ya cargados", duracion_s: 8 },
    { id: 6, accion: "scroll #hoy-title", subtitulo: "Ahora, después y el resto del día,\nen una sola pantalla", duracion_s: 7 },
  ],
});
