// Demo «Avisos en el celular»: escenas de demos/libretos/notificaciones-push.yml (regenerar si cambia el libreto).
// Permiso de notificaciones concedido. La suscripción Web Push puede fallar en headless.
import { definirDemo } from "./_comun";

definirDemo({
  feature: "notificaciones-push",
  titulo: "Avisos en el celular",
  escenas: [
    { id: 1, accion: "goto #/ajustes", subtitulo: "Con el celular en el bolsillo,\nigual te enterás de lo importante.", duracion_s: 6 },
    { id: 2, accion: "scroll #push-on", subtitulo: "Notificaciones en el celular.", duracion_s: 4 },
    { id: 3, accion: "click #push-on", subtitulo: "Te avisamos cuándo salir, cuándo empieza\ny si AWS cambia algo de tu itinerario.", duracion_s: 9 },
    { id: 4, accion: "click role=button[name='Probar una notificación']", subtitulo: "Con una prueba confirmás que llegan.", duracion_s: 5 },
    { id: 5, accion: "hover #push-grabar", subtitulo: "Si empieza una charla y nadie la graba,\nte lo recordamos.", duracion_s: 7 },
    { id: 6, accion: "hover #push-eventos-nuevos", subtitulo: "También, eventos nuevos.\nNunca de noche.", duracion_s: 5 },
    { id: 7, accion: "click #ofertas-on", subtitulo: "Sumás ofertas de shows, comida y compras:\npocos avisos por día.", duracion_s: 7 },
    { id: 8, accion: "hover #ofertas-cat-shows", subtitulo: "Elegís qué ofertas te interesan, y listo:\nte avisa aunque la app esté cerrada.", duracion_s: 7 },
  ],
  contexto: { permissions: ["notifications"] },
});
