// Demo «Armá tu día, charla por charla»: escenas de demos/libretos/itinerario-armar-dia.yml (regenerar si cambia el libreto).
// Las opciones las arma el LLM (~15 s): antes de la escena 4 se espera el primer «Elegir».
import { definirDemo, ESPERA_LLM_MS, localizar } from "./_comun";

definirDemo({
  feature: "itinerario-armar-dia",
  titulo: "Armá tu día, charla por charla",
  escenas: [
    { id: 1, accion: "goto #/itinerario/armar", subtitulo: "Armás cada día charla por charla,\nsin correr entre sedes.", duracion_s: 7 },
    { id: 2, accion: "click .tabs [role=tab]:nth-child(6)", subtitulo: "Elegís el día:\n¿con qué arrancás?", duracion_s: 6 },
    { id: 3, accion: "wait 3", subtitulo: "Cada opción: por qué te sirve\ny desde qué hora hacer la cola.", duracion_s: 7 },
    { id: 4, accion: "click role=button[name='Elegir']", subtitulo: "Elegís una y te propone\nlo que sigue.", duracion_s: 6 },
    { id: 5, accion: "wait 3", subtitulo: "A tiempo, justo, salí antes\no se superpone: el semáforo avisa.", duracion_s: 9 },
    { id: 6, accion: "click role=button[name='Completá el resto del día por mí ✨']", subtitulo: "¿Sin tiempo? Que complete\nel resto del día por vos.", duracion_s: 6 },
    { id: 7, accion: "wait 10", subtitulo: "Elige charlas a las que llegás,\nhasta el ritmo que pediste.", duracion_s: 11 },
    { id: 8, accion: "click role=button[name='Terminar el día']", subtitulo: "Terminás el día y ves\ncómo te quedó.", duracion_s: 5 },
    { id: 9, accion: "wait 3", subtitulo: "Personas para conocer\ny eventos para la noche.", duracion_s: 7 },
  ],
  antesDeEscena: {
    4: async ({ page }) => localizar(page, "role=button[name='Elegir']").waitFor({ timeout: ESPERA_LLM_MS }),
  },
});
