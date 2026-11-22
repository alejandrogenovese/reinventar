// Demo «Ubicación y alertas a tu medida»: escenas de demos/libretos/ajustes-ubicacion-y-alertas.yml (regenerar si cambia el libreto).
// Geolocalización concedida y fijada en el Venetian; contexto nuevo, así «Usar mi ubicación» arranca apagada.
import { definirDemo, VENETIAN } from "./_comun";

definirDemo({
  feature: "ajustes-ubicacion-y-alertas",
  titulo: "Ubicación y alertas a tu medida",
  escenas: [
    { id: 1, accion: "goto #/ajustes", subtitulo: "En Ajustes decidís cuánto margen querés\npara moverte entre charlas.", duracion_s: 6 },
    { id: 2, accion: "fill #leave-margin \"10\"", subtitulo: "Fijás tu margen para salir:\ndiez minutos, por ejemplo.", duracion_s: 5 },
    { id: 3, accion: "fill #start-notice \"5\"", subtitulo: "Y cuántos minutos antes querés\nel aviso de que algo empieza.", duracion_s: 6 },
    { id: 4, accion: "click #use-location", subtitulo: "Con tu ubicación ves a cuánto queda\ncada charla y cuándo salir.", duracion_s: 7 },
    { id: 5, accion: "wait 3", subtitulo: "Tus coordenadas nunca\nsalen del celular.", duracion_s: 8 },
  ],
  contexto: { permissions: ["geolocation"], geolocation: VENETIAN },
});
