// Demo «Instalá ReinventAR en el celular»: escenas de demos/libretos/instalar-pwa.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "instalar-pwa",
  titulo: "Instalá ReinventAR en el celular",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "En el evento, la querés a un toque.", duracion_s: 7 },
    { id: 2, accion: "hover text=Instalá ReinventAR en el celular", subtitulo: "Queda como app en tu pantalla de inicio.", duracion_s: 7 },
    { id: 3, accion: "hover role=button[name='Instalar app']", subtitulo: "Abre a pantalla completa\ny anda aunque no haya señal.", duracion_s: 5 },
    { id: 4, accion: "click role=button[name='Instalar app']", subtitulo: "En Android sale el diálogo del sistema;\nsi no, te explica los pasos.", duracion_s: 7 },
    { id: 5, accion: "wait 3", subtitulo: "Chrome: menú → Instalar app.\niPhone: Compartir → Agregar a inicio.", duracion_s: 7 },
  ],
});
