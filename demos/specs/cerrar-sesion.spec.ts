// Demo «Cerrá sesión»: escenas de demos/libretos/cerrar-sesion.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "cerrar-sesion",
  titulo: "Cerrá sesión",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "¿Prestás el celular o terminó el evento?\nCerrás sesión en dos toques.", duracion_s: 7 },
    { id: 2, accion: "click [aria-label='Ajustes']", subtitulo: "En Ajustes ves con qué cuenta\nestás conectado.", duracion_s: 5 },
    { id: 3, accion: "hover role=button[name='Cerrar sesión']", subtitulo: "Te saca de la cuenta y da de baja\nlas notificaciones de este celular.", duracion_s: 9 },
    { id: 4, accion: "wait 2", subtitulo: "Y borra los gastos guardados acá:\nno le quedan a la próxima persona.", duracion_s: 8 },
    { id: 5, accion: "click role=button[name='Cerrar sesión']", subtitulo: "Lo tocás y salís al instante.", duracion_s: 4 },
    { id: 6, accion: "wait 2", subtitulo: "Volvés al ingreso,\nlisto para la próxima persona.", duracion_s: 6 },
  ],
});
