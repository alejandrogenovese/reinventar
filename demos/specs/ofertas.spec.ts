// Demo «Ofertas de la semana»: escenas de demos/libretos/ofertas.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "ofertas",
  titulo: "Ofertas de la semana",
  escenas: [
    { id: 1, accion: "goto #/ofertas", subtitulo: "Bajas de precio en shows\ny promos de comida y compras", duracion_s: 7 },
    { id: 2, accion: "hover [aria-label='Categoría']", subtitulo: "Las vigentes, filtradas\npor lo que te interesa", duracion_s: 7 },
    { id: 3, accion: "click button[data-valor='comida']", subtitulo: "Por ejemplo, solo las de comida", duracion_s: 5 },
    { id: 4, accion: "hover article[id^='oferta-']", subtitulo: "Dónde es, hasta cuándo vale\ny el link para aprovecharla", duracion_s: 7 },
    { id: 5, accion: "wait 3", subtitulo: "Con los avisos prendidos en Ajustes,\nte llegan solas", duracion_s: 7 },
  ],
});
