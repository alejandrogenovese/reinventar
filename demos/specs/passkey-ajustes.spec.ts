// Demo «Activá Face ID o huella»: escenas de demos/libretos/passkey-ajustes.yml (regenerar si cambia el libreto).
// Autenticador WebAuthn virtual por CDP antes de cargar la app. Post-roll: quitar la passkey registrada.
import { definirDemo } from "./_comun";

definirDemo({
  feature: "passkey-ajustes",
  titulo: "Activá Face ID o huella",
  escenas: [
    { id: 1, accion: "goto #/ajustes", subtitulo: "Tipear la contraseña en un pasillo\ndel evento es incómodo.", duracion_s: 6 },
    { id: 2, accion: "scroll role=button[name='Activar en este dispositivo']", subtitulo: "En Ajustes tenés el ingreso\ncon Face ID o huella.", duracion_s: 7 },
    { id: 3, accion: "click role=button[name='Activar en este dispositivo']", subtitulo: "Lo activás y confirmás con tu cara o dedo.\nNo se guarda ningún dato biométrico.", duracion_s: 8 },
    { id: 4, accion: "wait 2", subtitulo: "Queda en la lista con tu dispositivo.\nLa próxima, sin contraseña.", duracion_s: 7 },
    { id: 5, accion: "hover role=button[name='Quitar']", subtitulo: "¿Cambiaste de celular?\nLo quitás desde acá.", duracion_s: 5 },
  ],
  passkey: true,
  despues: async ({ ejecutar }) => ejecutar("click role=button[name='Quitar']"),
});
