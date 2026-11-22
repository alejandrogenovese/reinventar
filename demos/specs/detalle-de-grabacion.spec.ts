// Demo «Resumen y transcripción de tu charla»: escenas de demos/libretos/detalle-de-grabacion.yml (regenerar si cambia el libreto).
// Exportar .md descarga un archivo: acceptDownloads.
import { definirDemo } from "./_comun";

definirDemo({
  feature: "detalle-de-grabacion",
  titulo: "Resumen y transcripción de tu charla",
  escenas: [
    { id: 1, accion: "goto #/", subtitulo: "Saliste de una charla de una hora\ny querés lo importante, ya.", duracion_s: 6 },
    { id: 2, accion: "click [aria-labelledby='grabaciones-title'] button.ra-reccard:has-text('CEO Keynote')", subtitulo: "Abrís la grabación\ny arrancás por el resumen.", duracion_s: 5 },
    { id: 3, accion: "scroll 400", subtitulo: "TL;DR y puntos clave en castellano;\nlas frases del speaker, textuales.", duracion_s: 7 },
    { id: 4, accion: "hover role=button[name='Me sirvió']", subtitulo: "Votás si te sirvió el resumen:\nnos ayuda a mejorarlos.", duracion_s: 6 },
    { id: 5, accion: "click role=tab[name='Transcripción']", subtitulo: "Cada bloque en castellano,\ncon el original en inglés abajo.", duracion_s: 7 },
    { id: 6, accion: "scroll 600", subtitulo: "Los tramos sin audio quedan marcados:\nsabés dónde hubo un corte.", duracion_s: 8 },
    { id: 7, accion: "click [aria-label='Más acciones']", subtitulo: "Desde el menú exportás en Markdown\no borrás la grabación.", duracion_s: 7 },
    { id: 8, accion: "click role=menuitem[name='Exportar .md']", subtitulo: "Te queda el archivo para tus notas\no para el equipo.", duracion_s: 7 },
    { id: 9, accion: "click a.ra-talklink", subtitulo: "Si está vinculada a una charla,\nsaltás a su ficha con un toque.", duracion_s: 8 },
  ],
  contexto: { acceptDownloads: true },
});
