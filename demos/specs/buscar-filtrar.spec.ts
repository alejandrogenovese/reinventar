// Demo «Buscar charlas con filtros»: escenas de demos/libretos/buscar-filtrar.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "buscar-filtrar",
  titulo: "Buscar charlas con filtros",
  escenas: [
    { id: 1, accion: "goto #/buscar", subtitulo: "Miles de charlas en re:Invent:\nencontrá las tuyas en segundos.", duracion_s: 7 },
    { id: 2, accion: "fill [aria-label='Buscar charlas'] \"bancos el martes\"", subtitulo: "Escribí lo que buscás,\ncomo lo dirías vos.", duracion_s: 6 },
    { id: 3, accion: "click button.ra-suggest", subtitulo: "La app entiende tu pedido\ny lo traduce en filtros.", duracion_s: 7 },
    { id: 4, accion: "wait 3", subtitulo: "¿No era eso? Lo deshacés\ncon un toque.", duracion_s: 6 },
    { id: 5, accion: "click button.ra-infield-btn", subtitulo: "Afinás por día, sector, tipo,\nnivel o servicio de AWS.", duracion_s: 8 },
    { id: 6, accion: "click [aria-label='Cerrar filtros']", subtitulo: "Cerrás y seguís con\nla lista ya acotada.", duracion_s: 5 },
    { id: 7, accion: "click [aria-label='Agregar al itinerario']", subtitulo: "La que te interesa,\nla sumás a tu itinerario.", duracion_s: 7 },
    { id: 8, accion: "wait 2", subtitulo: "Listo: ya está en tu agenda,\ny los filtros siguen ahí.", duracion_s: 7 },
  ],
});
