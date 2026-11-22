// Demo «Vuelos y hoteles, con avisos»: escenas de demos/libretos/vuelos-y-hoteles.yml (regenerar si cambia el libreto).
// {id} de la escena 5: DEMO_VUELO_ID o, si no está, el del primer vuelo de la lista. Es de solo lectura: «Agregar un vuelo» solo abre el formulario.
import { definirDemo } from "./_comun";

definirDemo({
  feature: "vuelos-y-hoteles",
  titulo: "Vuelos y hoteles, con avisos",
  escenas: [
    { id: 1, accion: "goto #/viajes", subtitulo: "Cargás vuelos y hoteles una vez\ny la app te avisa", duracion_s: 7 },
    { id: 2, accion: "hover article[id^='vuelo-']", subtitulo: "La salida y desde cuándo\nhacés el check-in web", duracion_s: 7 },
    { id: 3, accion: "hover article[id^='hotel-']", subtitulo: "Check-in y check-out del hotel,\nen hora de Las Vegas", duracion_s: 7 },
    { id: 4, accion: "click text=Agregar un vuelo", subtitulo: "Sumar otro: número, fecha\ny de dónde sale", duracion_s: 5 },
    { id: 5, accion: "goto #/viajes/vuelo/{id}", subtitulo: "Te avisa cuando abre el check-in\ny si hay demora o cambio de puerta", duracion_s: 9 },
    { id: 6, accion: "hover role=link[name='Hacer check-in']", subtitulo: "El check-in, desde acá\ncon un toque", duracion_s: 5 },
  ],
  variables: {
    id: async ({ page }) => process.env.DEMO_VUELO_ID
      ?? (await page.locator("article[id^='vuelo-']").first().getAttribute("id"))?.replace(/^vuelo-/, "") ?? "",
  },
});
