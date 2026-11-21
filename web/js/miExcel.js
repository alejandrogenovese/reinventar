// Itinerario › «Mis códigos de Excel»: la persona sube un .xlsx o .csv con los códigos que quiere y la app los cruza con
// el catálogo y con lo que ya registró (/api/codigos). Cinco resultados: registrada, te falta, choque, de más
// (registrada y no está en el Excel) y código que no existe. Solo clases y componentes que ya existen.
import { api } from "./api.js";
import { Kpi, dayShort, int } from "./charts.js";
import { Button, Hint, IconText, Tag, h, mensajeError, toast } from "./ui.js";

const ACCEPT = ".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const FILTROS = [["todos", "Todos"], ["falta", "Te faltan"], ["choque", "Choques"], ["registrado", "Registradas"],
  ["de_mas", "De más"], ["inexistente", "No existen"]];

const Codigos = {
  ver: () => api("/api/codigos"),
  subir: (file) => api(`/api/codigos?nombre=${encodeURIComponent(file.name)}`, { method: "POST", body: file,
    headers: { "Content-Type": file.type || "application/octet-stream" } }),
  borrar: () => api("/api/codigos", { method: "DELETE" }),
};

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
  let data = await Codigos.ver();
  let filtro = "todos";
  let error = "";

  const elegirArchivo = () => {
    const input = h("input", { type: "file", accept: ACCEPT, hidden: true });
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      input.remove();
      if (!file) return;
      try { data = await Codigos.subir(file); filtro = "todos"; error = ""; } catch (err) { error = mensajeError(err); toast(error); }
      paint();
    });
    document.body.append(input);
    input.click();
  };
  const borrar = async () => {
    try { data = await Codigos.borrar(); error = ""; toast("Borré tu lista."); } catch (err) { toast(mensajeError(err)); }
    paint();
  };

  function Subida() {
    return h("div", { class: "stack" },
      error ? Hint(error, { tone: "error" }) : null,
      h("p", { class: "caption" }, "Un .xlsx o .csv de hasta 1 MB con los códigos que querés (AIM301, DAT402-R, KEY001). Busco sola la columna de códigos; lo demás se ignora."),
      Button(data.lista ? "Subir otra lista" : "Elegir archivo", { variant: data.lista ? "secondary" : "primary", onclick: elegirArchivo }));
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
