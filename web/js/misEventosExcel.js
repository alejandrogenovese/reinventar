// Eventos › Mis eventos › «Cargar desde Excel»: la persona sube un .xlsx o .csv con sus eventos, ve una vista previa
// (nueva, actualiza, sin cambios o error por fila) y confirma. Para confirmar se reenvía el mismo archivo con
// ?confirmar=1: el servidor no guarda nada entre los dos pasos (app/eventos_excel_api.py). Mismo patrón que miExcel.js.
import { api } from "./api.js";
import { shortDay } from "./itinerary.js";
import { Button, Hint, IconText, h, mensajeError, toast } from "./ui.js";

const ACCEPT = ".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const EJEMPLO = "reinventar-eventos-ejemplo.xlsx";
const MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const ESTADOS = { nueva: "Nueva", actualiza: "Actualiza", vuelve: "Se vuelve a agregar", sin_cambios: "Sin cambios", error: "Error" };

const EventosExcel = {
  subir: (file, confirmar) => api(`/api/my-events/excel?nombre=${encodeURIComponent(file.name)}${confirmar ? "&confirmar=1" : ""}`,
    { method: "POST", body: file, headers: { "Content-Type": file.type || "application/octet-stream" } }),
  ejemplo: () => api("/api/my-events/excel/ejemplo.xlsx", { raw: true }).then((r) => r.blob()),
};

/** Baja el Excel de ejemplo (con el token). Como en miExcel.js: si se puede, se comparte (la app instalada de iPhone
 *  se traba con un enlace de descarga). */
async function bajarEjemplo() {
  try {
    const blob = await EventosExcel.ejemplo();
    const archivo = typeof File === "function" ? new File([blob], EJEMPLO, { type: MIME_XLSX }) : null;
    if (archivo && navigator.canShare?.({ files: [archivo] })) {
      try { await navigator.share({ files: [archivo], title: "Excel de ejemplo" }); return; } catch (e) {
        if (e?.name === "AbortError") return;
      }
    }
    const url = URL.createObjectURL(blob);
    const enlace = h("a", { href: url, download: EJEMPLO });
    document.body.append(enlace);
    enlace.click();
    enlace.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  } catch (err) {
    toast(mensajeError(err));
  }
}

/** Texto del resumen de la vista previa: «3 nuevos · 1 actualiza · 2 con error». */
export function textoResumen(r) {
  const partes = [[r.nueva, "nuevo", "nuevos"], [r.actualiza, "actualiza", "actualizan"],
    [r.vuelve || 0, "vuelve al itinerario", "vuelven al itinerario"],
    [r.sin_cambios, "sin cambios", "sin cambios"], [r.error, "con error", "con error"]]
    .filter(([n]) => n > 0).map(([n, uno, varios]) => `${n} ${n === 1 ? uno : varios}`);
  return partes.join(" · ") || "Nada para cargar";
}

/** Cuántas filas se guardarían al confirmar. */
export const aGuardar = (r) => r.nueva + r.actualiza + (r.vuelve || 0);

/** Una fila de la vista previa, con las clases de las tarjetas de Mis eventos (ra-minicard). */
function FilaPrevia(f) {
  const estado = `Fila ${f.fila} · ${ESTADOS[f.estado] || f.estado}`;
  return h("article", { class: "ra-minicard" },
    h("div", { class: "ra-rail" },
      h("span", { class: "ra-rail-time" }, f.inicio || "—"),
      h("span", { class: "ra-rail-day" }, f.dia ? shortDay(f.dia) : "")),
    h("div", { class: "ra-minicard-body" },
      h("span", { class: "ra-kind" }, [estado, f.fin ? `hasta ${f.fin}` : null].filter(Boolean).join(" · ")),
      f.error ? Hint(f.error, { tone: "error" }) : [
        h("h3", { class: "ra-minicard-title" }, f.nombre),
        h("div", { class: "ra-minicard-meta" }, IconText("ubicacion", f.sede ? f.lugar : `${f.lugar} (sin ubicar en el mapa)`)),
        f.nota ? h("p", { class: "caption", style: "white-space:pre-line" }, f.nota) : null]));
}

/** El bloque «Cargar desde Excel». alGuardar: se llama después de confirmar, para refrescar la lista de Mis eventos. */
export function CargarDesdeExcel({ alGuardar } = {}) {
  const el = h("div", { class: "stack" });
  let archivo = null;
  let previa = null;
  let error = "";
  let ocupado = false;

  async function subir(confirmar) {
    ocupado = true; paint();
    try {
      const r = await EventosExcel.subir(archivo, confirmar);
      error = "";
      if (confirmar) {
        toast(`Listo: ${textoResumen(r.resumen)}.`);
        previa = null; archivo = null;
        await alGuardar?.();
      } else {
        previa = r;
      }
    } catch (err) {
      error = mensajeError(err); previa = null;
    }
    ocupado = false; paint();
  }

  const elegirArchivo = () => {
    const input = h("input", { type: "file", accept: ACCEPT, hidden: true });
    input.addEventListener("change", () => {
      const file = input.files?.[0];
      input.remove();
      if (!file) return;
      archivo = file;
      void subir(false); // subir() atrapa sus propios errores y los muestra en pantalla
    });
    document.body.append(input);
    input.click();
  };

  function paint() {
    const n = previa ? aGuardar(previa.resumen) : 0;
    el.replaceChildren(...[
      h("p", { class: "caption" }, "Un .xlsx o .csv de hasta 1 MB y 100 eventos, uno por fila: Nombre, Día, Inicio y Lugar son obligatorios. Antes de guardar ves qué entra. Si lo subís otra vez, no se duplica."),
      h("div", { class: "actions" },
        Button(previa ? "Elegir otro archivo" : "Elegir archivo", { variant: previa ? "secondary" : "primary", onclick: elegirArchivo, disabled: ocupado }),
        Button("Bajar ejemplo", { variant: "ghost", onclick: bajarEjemplo })),
      error ? Hint(error, { tone: "error" }) : null,
      previa ? h("div", { class: "stack" },
        h("p", { class: "label" }, `${archivo?.name || "Tu archivo"}: ${textoResumen(previa.resumen)}`),
        h("div", { class: "daylist" }, previa.filas.map(FilaPrevia)),
        previa.resumen.error ? Hint("Las filas con error no se guardan: corregilas en el Excel y subilo de nuevo.", { tone: "warn" }) : null,
        h("div", { class: "actions" },
          Button(n ? `Confirmar (${n})` : "No hay nada nuevo", { variant: "primary", disabled: ocupado || !n, onclick: () => subir(true) }),
          Button("Cancelar", { variant: "ghost", onclick: () => { previa = null; archivo = null; error = ""; paint(); } }))) : null].filter(Boolean));
  }
  paint();
  return el;
}
