// Demo «Tus grabaciones, en Inicio»: escenas de demos/libretos/lista-de-grabaciones.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "lista-de-grabaciones",
  titulo: "Tus grabaciones, en Inicio",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "Grabaste varias charlas\ny las querés a mano.", duracion_s: 6 },
    { id: 2, accion: "scroll #grabaciones-title", subtitulo: "Lo que grabaste vos\ny el resto del equipo.", duracion_s: 7 },
    { id: 3, accion: "hover [aria-labelledby='grabaciones-title'] button.ra-reccard", subtitulo: "Título, sala, duración y estado:\ngrabando, procesando o lista.", duracion_s: 7 },
    { id: 4, accion: "hover [aria-label='Nueva grabación']", subtitulo: "Si arranca otra charla,\nsumás una nueva desde acá.", duracion_s: 6 },
    { id: 5, accion: "click [aria-labelledby='grabaciones-title'] button.ra-reccard", subtitulo: "Tocás una y abrís su resumen.\nSi se está grabando, volvés al grabador.", duracion_s: 7 },
    { id: 6, accion: "wait 2", subtitulo: "Resumen y transcripción,\nlistos para repasar.", duracion_s: 5 },
  ],
});
