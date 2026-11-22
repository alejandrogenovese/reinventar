// Demo «Viaje: lo que pasa fuera de las charlas»: escenas de demos/libretos/viaje-hub.yml (regenerar si cambia el libreto).
import { definirDemo } from "./_comun";

definirDemo({
  feature: "viaje-hub",
  titulo: "Viaje: lo que pasa fuera de las charlas",
  escenas: [
    { id: 1, accion: "goto #/viaje", subtitulo: "El viaje no es solo charlas:\nlo demás, todo junto", duracion_s: 7 },
    { id: 2, accion: "hover a.ra-card[href='#/comer']", subtitulo: "Dónde comer barato cerca,\ncon precio y reseñas", duracion_s: 6 },
    { id: 3, accion: "hover a.ra-card[href='#/gastos']", subtitulo: "Cuánto llevás gastado\ny qué se reintegra", duracion_s: 4 },
    { id: 4, accion: "hover a.ra-card[href='#/ofertas']", subtitulo: "Bajas de precio en shows y promos\nde comida y compras", duracion_s: 7 },
    { id: 5, accion: "hover a.ra-card[href='#/viajes']", subtitulo: "Vuelos y hoteles, con avisos de\ncheck-in, demoras y puerta", duracion_s: 6 },
    { id: 6, accion: "click a.ra-card[href='#/gastos']", subtitulo: "Un toque y entrás:\npor ejemplo, a tus gastos", duracion_s: 6 },
  ],
});
