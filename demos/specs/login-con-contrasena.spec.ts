// Demo «Entrá con tu usuario»: escenas de demos/libretos/login-con-contrasena.yml (regenerar si cambia el libreto).
// Arranca sin sesión; la contraseña sale de TESTER_PASSWORD.
import { definirDemo } from "./_comun";

definirDemo({
  feature: "login-con-contrasena",
  titulo: "Entrá con tu usuario",
  escenas: [
    { id: 1, accion: "goto #/login", subtitulo: "Sin sesión, arrancás en el ingreso.", duracion_s: 6 },
    { id: 2, accion: "fill #username \"tester\"", subtitulo: "Escribís el usuario que te pasaron.", duracion_s: 4 },
    { id: 3, accion: "fill #password \"{{TESTER_PASSWORD}}\"", subtitulo: "Después, tu contraseña:\nqueda oculta mientras la escribís.", duracion_s: 5 },
    { id: 4, accion: "hover .ra-pass-eye", subtitulo: "Si querés, la mostrás con el ojo.\nAl entrar se vuelve a ocultar.", duracion_s: 9 },
    { id: 5, accion: "click role=button[name='Entrar']", subtitulo: "Tocás Entrar. Si algo no coincide,\nte lo avisa ahí mismo.", duracion_s: 6 },
    { id: 6, accion: "wait 3", subtitulo: "Aparecés en Inicio, con tu día a mano.\nLa primera vez elegís tu contraseña.", duracion_s: 10 },
  ],
  sinSesion: true,
});
