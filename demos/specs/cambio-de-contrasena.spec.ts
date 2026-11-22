// Demo «Cambiá tu contraseña»: escenas de demos/libretos/cambio-de-contrasena.yml (regenerar si cambia el libreto).
// BLOQUEANTE en el libreto: nunca con tester. Cuenta descartable desde DEMO_USUARIO / DEMO_PASSWORD_ACTUAL.
import { definirDemo } from "./_comun";

definirDemo({
  feature: "cambio-de-contrasena",
  titulo: "Cambiá tu contraseña",
  escenas: [
    { id: 1, accion: "goto #/ajustes", subtitulo: "En Ajustes manejás tu cuenta.", duracion_s: 5 },
    { id: 2, accion: "click role=button[name='Cambiar contraseña']", subtitulo: "La cambiás cuando quieras, desde acá.", duracion_s: 4 },
    { id: 3, accion: "fill #current \"{{DEMO_PASSWORD_ACTUAL}}\"", subtitulo: "Primero confirmás la que usás hoy.", duracion_s: 4 },
    { id: 4, accion: "fill #next \"{{DEMO_PASSWORD_NUEVA}}\"", subtitulo: "Elegís la nueva:\nmínimo ocho caracteres.", duracion_s: 4 },
    { id: 5, accion: "fill #repeat \"{{DEMO_PASSWORD_NUEVA}}\"", subtitulo: "La repetís, así no te equivocás de tecla.", duracion_s: 5 },
    { id: 6, accion: "click role=button[name='Guardar']", subtitulo: "Guardás, y se cierra la sesión\nen tus otros dispositivos.", duracion_s: 5 },
    { id: 7, accion: "wait 3", subtitulo: "Contraseña actualizada.\nEn tu primer ingreso, te la pide sola.", duracion_s: 10 },
  ],
  cuenta: { envUsuario: "DEMO_USUARIO", envPassword: "DEMO_PASSWORD_ACTUAL", prohibido: "tester" },
});
