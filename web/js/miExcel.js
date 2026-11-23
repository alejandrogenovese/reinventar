// Itinerario › «Mis códigos de Excel»: la persona sube un .xlsx o .csv con los códigos que quiere y la app los cruza con
// el catálogo y con lo que ya registró (/api/codigos). Cinco resultados: registrada, te falta, choque, de más
// (registrada y no está en el Excel) y código que no existe. Solo clases y componentes que ya existen.
import { api } from "./api.js";
import { Kpi, dayShort, int } from "./charts.js";
import { confirmDialog } from "./dialog.js";
import { Button, Hint, IconText, Tag, h, mensajeError, toast } from "./ui.js";

const ACCEPT = ".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const FILTROS = [["todos", "Todos"], ["falta", "Te faltan"], ["choque", "Choques"], ["registrado", "Registradas"],
  ["de_mas", "De más"], ["inexistente", "No existen"]];

const Codigos = {
  ver: () => api("/api/codigos"),
  subir: (file) => api(`/api/codigos?nombre=${encodeURIComponent(file.name)}`, { method: "POST", body: file,
    headers: { "Content-Type": file.type || "application/octet-stream" } }),
  borrar: () => api("/api/codigos", { method: "DELETE" }),
  alItinerario: () => api("/api/codigos/al-itinerario", { method: "POST" }),
  ejemplo: () => api("/api/codigos/ejemplo.xlsx", { raw: true }).then((r) => r.blob()),
};
const EJEMPLO = "reinventar-codigos-ejemplo.xlsx";
const MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** Baja el Excel de ejemplo (con el token: un <a href> no lo mandaría). Como en gastos.js: en la app instalada de
 *  iPhone un enlace de descarga deja la pantalla trabada en el archivo, así que si se puede se comparte. */
async function bajarEjemplo() {
  try {
    const blob = await Codigos.ejemplo();
    const archivo = typeof File === "function" ? new File([blob], EJEMPLO, { type: MIME_XLSX }) : null;
    if (archivo && navigator.canShare?.({ files: [archivo] })) {
      try { await navigator.share({ files: [archivo], title: "Excel de ejemplo" }); return; } catch (e) {
        if (e?.name === "AbortError") return; // cerró la hoja de compartir: no es un error
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

const Rail = (dia, inicio) => h("div", { class: "ra-rail" },
  h("span", { class: "ra-rail-time" }, inicio || "—"), h("span", { class: "ra-rail-day" }, dia ? dayShort(dia) : ""));

/** Una charla del cruce. e.estado: registrado | falta | inexistente; e.choca_con: otros que quiero y se pisan con ella. */
function CodigoItem(e) {
  const existe = e.estado !== "inexistente";
  const estado = { registrado: IconText("listo", "Registrada"), falta: Hint("Te falta registrarla.", { tone: "error" }),
    inexistente: Tag("Este código no está en el catálogo") }[e.estado];
  return h("article", { class: "ra-minicard" },
    Rail(e.dia, e.inicio),
    h("div", { class: "ra-minicard-body" },
      h("span", { class: "ra-kind" }, [e.tipo, e.codigo].filter(Boolean).join(" · ")),
      h("h3", { class: "ra-minicard-title" }, existe ? h("a", { class: "ra-link", href: `#/charla/${e.base}` }, e.titulo) : `Código ${e.codigo}`),
      e.sala ? h("div", { class: "ra-minicard-meta" }, e.sala) : null,
      e.en_itinerario ? h("span", { class: "caption" }, "En tu itinerario") : null,
      estado,
      e.choca_con?.length ? Hint(`Se pisa con ${e.choca_con.join(", ")}.`, { tone: "warn" }) : null,
      e.estado === "falta" ? h("a", { class: "ra-link", href: `#/charla/${e.base}` }, "Ver la ficha para registrarla") : null));
}

function DeMasItem(d) {
  return h("article", { class: "ra-minicard" },
    Rail(d.dia, d.inicio),
    h("div", { class: "ra-minicard-body" },
      h("span", { class: "ra-kind" }, d.codigo),
      h("h3", { class: "ra-minicard-title" }, h("a", { class: "ra-link", href: `#/charla/${d.base}` }, d.titulo || d.base)),
      d.sala ? h("div", { class: "ra-minicard-meta" }, d.sala) : null,
      Hint("La registraste y no está en tu Excel.", { tone: "info" })));
}

const visibles = (data, filtro) => ({
  codigos: data.codigos.filter((e) => ({ todos: true, falta: e.estado === "falta", registrado: e.estado === "registrado",
    inexistente: e.estado === "inexistente", choque: e.choca_con.length > 0, de_mas: false })[filtro]),
  de_mas: ["todos", "de_mas"].includes(filtro) ? data.de_mas : [],
});

const subidaEl = (ms) => new Date(ms).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" });
const plural = (n, uno, varios) => `${int(n)} ${n === 1 ? uno : varios}`;

export async function viewMiExcel(view) {
  const inicial = await Codigos.ver();
  if (!view.isConnected) return; // si ya navegó a otra pantalla, esta respuesta no la pisa
  let data = inicial;
  let filtro = "todos";
  let error = "";
  let descartados = []; // códigos del Excel que quedaron afuera (otras columnas u hojas): solo se saben al subir

  const elegirArchivo = () => {
    const input = h("input", { type: "file", accept: ACCEPT, hidden: true });
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      input.remove();
      if (!file) return;
      try {
        const nueva = await Codigos.subir(file);
        if (!view.isConnected) return;
        ({ codigos_descartados: descartados = [], ...data } = nueva);
        filtro = "todos"; error = "";
      } catch (err) {
        if (!view.isConnected) return;
        error = mensajeError(err); toast(error);
      }
      paint();
    });
    document.body.append(input);
    input.click();
  };
  const borrar = async () => {
    const ok = await confirmDialog("¿Borrar tu lista?", {
      text: "Se borra la lista que subiste. Tus charlas registradas no se tocan.", confirmLabel: "Borrar", danger: true });
    if (!ok) return;
    try {
      const nueva = await Codigos.borrar();
      if (!view.isConnected) return;
      data = nueva; error = ""; descartados = []; toast("Borré tu lista.");
    } catch (err) {
      if (!view.isConnected) return;
      toast(mensajeError(err));
    }
    paint();
  };

  let agregando = false;
  const agregar = async () => {
    agregando = true; paint();
    try {
      const { agregadas, ...nueva } = await Codigos.alItinerario();
      if (!view.isConnected) return;
      data = nueva; error = "";
      toast(agregadas ? `Agregué ${plural(agregadas, "charla", "charlas")} a tu itinerario.` : "Ya estaban todas en tu itinerario.");
    } catch (err) {
      if (!view.isConnected) return;
      toast(mensajeError(err));
    }
    agregando = false; paint();
  };

  /** «Agregar al itinerario» y, si no hay ninguna registrada, de dónde sale ese número. */
  function Acciones(r) {
    return [
      r.para_agregar ? h("div", { class: "actions" }, Button(`Agregar al itinerario (${int(r.para_agregar)})`,
        { variant: "primary", disabled: agregando, onclick: agregar })) : null,
      r.registrados ? null : Hint("«Registradas» cuenta las charlas de tu itinerario marcadas como reservadas. Si ya te anotaste en el portal de AWS, usá «Importar reservas de AWS» en Itinerario: las carga y las marca.", { tone: "info" })];
  }

  function Subida() {
    return h("div", { class: "stack" },
      error ? Hint(error, { tone: "error" }) : null,
      h("p", { class: "caption" }, "Un .xlsx o .csv de hasta 1 MB con los códigos que querés (AIM301, DAT402-R, KEY001). Busco sola la columna de códigos; lo demás se ignora."),
      h("div", { class: "actions" },
        Button(data.lista ? "Subir otra lista" : "Elegir archivo", { variant: data.lista ? "secondary" : "primary", onclick: elegirArchivo }),
        Button("Bajar un Excel de ejemplo", { variant: "ghost", onclick: bajarEjemplo })),
      h("p", { class: "caption" }, "¿No sabés cómo armarlo? Bajá el ejemplo, completá la columna Código con las charlas que querés y subilo acá."));
  }

  function Resultado() {
    const r = data.resumen;
    const lista = visibles(data, filtro);
    const cuenta = { todos: r.total, falta: r.faltan, choque: r.choques, registrado: r.registrados, de_mas: r.de_mas, inexistente: r.inexistentes };
    const chips = FILTROS.map(([id, texto]) => h("button", { type: "button", class: `ra-chip${filtro === id ? " ra-chip-on" : ""}`,
      "aria-pressed": String(filtro === id), onclick: () => { filtro = id; paint(); } }, `${texto} ${int(cuenta[id])}`));
    const items = [...lista.codigos.map(CodigoItem), ...lista.de_mas.map(DeMasItem)];
    return h("div", { class: "stack-lg" },
      h("div", { class: "ra-kpis" },
        Kpi("Registradas", int(r.registrados)),
        Kpi("Te faltan", int(r.faltan), { tone: r.faltan ? "err" : "" }),
        Kpi("Choques", int(r.choques), { tone: r.choques ? "err" : "" }),
        Kpi("De más", int(r.de_mas), { note: r.inexistentes ? plural(r.inexistentes, "código que no existe", "códigos que no existen") : "" })),
      descartados.length ? Hint(`No usé ${plural(descartados.length, "código", "códigos")} que ${descartados.length === 1 ? "estaba" : "estaban"} en otras columnas u hojas: ${descartados.slice(0, 10).join(", ")}${descartados.length > 10 ? "…" : ""}. Tomé la columna con más códigos.`, { tone: "warn" }) : null,
      ...Acciones(r),
      h("div", { class: "ra-chips", role: "group", "aria-label": "Filtrar el resultado" }, chips),
      items.length ? h("div", { class: "daylist" }, items) : h("p", { class: "caption" }, "No hay nada en esta categoría."),
      Subida(),
      Button("Borrar mi lista", { variant: "danger", onclick: borrar }));
  }

  function paint() {
    const sub = data.lista
      ? `${data.archivo || "Tu lista"} · ${plural(data.resumen.total, "código", "códigos")} · subida ${subidaEl(data.subido_en * 1000)}` : "";
    view.replaceChildren(h("div", { class: "stack-lg" },
      h("div", { class: "stack" }, h("h1", { class: "title" }, "Mis códigos de Excel"), sub ? h("p", { class: "caption" }, sub) : null),
      data.lista ? Resultado() : h("div", { class: "notice" }, Subida())));
  }
  paint();
}
