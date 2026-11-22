// Demo «Gastos del viaje en segundos»: escenas de demos/libretos/gastos.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "gastos",
  titulo: "Gastos del viaje en segundos",
  escenas: [
    { id: 1, accion: "goto #/gastos", subtitulo: "Dólares, pesos…\nes fácil perder la cuenta", duracion_s: 7 },
    { id: 2, accion: "click role=button[name='Cargar gasto']", subtitulo: "Cargar un gasto lleva segundos,\ny anda sin señal", duracion_s: 6 },
    { id: 3, accion: "fill #g-monto \"14,10\"", subtitulo: "El monto, en dólares o en pesos", duracion_s: 5 },
    { id: 4, accion: "fill #g-nota \"Almuerzo\"", subtitulo: "Una nota para acordarte qué fue", duracion_s: 5 },
    { id: 5, accion: "click [aria-label='Reintegrable'] button", subtitulo: "Si te lo reintegran, lo marcás\ny después lo exportás", duracion_s: 6 },
    { id: 6, accion: "click role=button[name='Guardar gasto']", subtitulo: "Lo guardás y se sincroniza\nsolo cuando hay red", duracion_s: 5 },
    { id: 7, accion: "scroll 250", subtitulo: "Hoy, total del viaje, cotización\ny gasto por categoría", duracion_s: 7 },
    { id: 8, accion: "scroll text=Almuerzo", subtitulo: "Tu gasto ya está en la lista,\nmarcado como reintegrable", duracion_s: 7 },
  ],
});
