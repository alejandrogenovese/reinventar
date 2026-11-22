// Admin › Eventos (#/admin/eventos): eventos automáticos: la última revisión de cada fuente (Luma, conferenceparties, links y el catálogo
// oficial de charlas), «Revisar ahora», «Agregar evento por link» (vista previa con el LLM, corregible, y guardar) y las
// «Charlas nuevas» que encontró la revisión (agrupadas por código, con buscador y filtro por track). Ver app/eventos_auto.py y app/charlas_auto.py.
import { Admin } from "./api.js";
import { estadoFuente } from "./adminAtencion.js";
import { agruparCharlas, filtrarCharlas, trackVigente, tracksDe, visibles } from "./adminCharlas.js";
import { NOMBRE_FUENTE } from "./adminTextos.js";
import { AdminShell, Cargable, Plegable, avisar, hace } from "./adminUi.js";
import { icon } from "./icons.js";
import { Button, Hint, Tag, h, mensajeError } from "./ui.js";

// Fechas que acepta «Agregar evento por link»: hasta el fin de la estadía (lun 7/12, ver app/estadia.py).
const FECHA_MIN = "2026-11-28";
const FECHA_MAX = "2026-12-07";
const ESPERA_MS = 5000;
const GRACIA_CICLOS = 2; // tras «Revisar ahora» se sigue sondeando aunque el servidor todavía diga ocupado=false
const TODOS = ""; // el chip «Todos» no filtra por track
const ESTADO_FUENTE = { ok: ["is-ok", "Al día"], atrasada: ["is-warn", "Atrasada"], error: ["is-err", "Con error"] };

const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

function RevisionRow(r, horas) {
  const unidad = { catalogo: "horarios futuros", ticketmaster: "funciones" }[r.fuente] || "eventos";
  const partes = [`${r.total} ${unidad}`, plural(r.nuevos, "nuevo", "nuevos"), plural(r.cambiados, "cambiado", "cambiados"),
    plural(r.cancelados, "cancelado", "cancelados"), r.pendientes ? `${r.pendientes} sin resumen todavía` : null].filter(Boolean);
  const [clase, texto] = ESTADO_FUENTE[estadoFuente(r, horas, Date.now())];
  return h("div", { class: "ra-adm-fila" },
    h("span", { class: "ra-adm-fila-cuerpo" },
      h("span", { class: "ra-adm-fila-nombre" }, NOMBRE_FUENTE[r.fuente] || r.fuente),
      h("span", { class: "ra-adm-fila-sub" }, `${hace(r.revisado)} · ${r.ok ? partes.join(" · ") : "falló la última revisión"}`),
      r.detalle ? h("span", { class: "ra-adm-fila-sub" }, r.detalle) : null),
    h("span", { class: "ra-adm-estado" }, h("span", { class: `ra-adm-dot ${clase}`, "aria-hidden": "true" }), texto));
}

const input = (id, label, value, attrs = {}) => {
  const el = h("input", { id, name: id, value: value ?? "", ...attrs });
  return { el, row: h("div", { class: "field" }, h("label", { class: "label", for: id }, label), el) };
};

/** La vista previa editable: lo que sacó el LLM, para corregir antes de guardar. */
function Preview(p, onSaved) {
  const nombre = input("ev-nombre", "Nombre", p.nombre, { required: true, maxlength: 200 });
  const fecha = input("ev-fecha", "Fecha", p.fecha, { type: "date", required: true, min: FECHA_MIN, max: FECHA_MAX });
  const inicio = input("ev-inicio", "Empieza", p.inicio, { type: "time", required: true });
  const fin = input("ev-fin", "Termina", p.fin, { type: "time" });
  const lugar = input("ev-lugar", "Lugar", p.lugar, { maxlength: 120 });
  const direccion = input("ev-direccion", "Dirección u hotel", p.direccion, { maxlength: 200 });
  const resumen = h("textarea", { id: "ev-resumen", rows: 4, maxlength: 1200 }, p.resumen_es || "");
  const guardar = h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Guardar evento");
  const form = h("form", { class: "ra-adm-form", onsubmit: async (e) => {
    e.preventDefault();
    guardar.disabled = true;
    const datos = {
      url: p.url, nombre: nombre.el.value.trim(), fecha: fecha.el.value, inicio: inicio.el.value, fin: fin.el.value || null,
      lugar: lugar.el.value.trim() || null, direccion: direccion.el.value.trim() || null, imagen: p.imagen,
      descripcion: p.descripcion, resumen_es: resumen.value.trim() || null, tipo: p.tipo, temas: p.temas, organizadores: p.organizadores,
    };
    try {
      await Admin.eventosGuardarLink(datos);
      avisar(`Guardado: ${datos.nombre}`);
      onSaved();
    } catch (err) { avisar(mensajeError(err), { error: true }); guardar.disabled = false; }
  } },
    p.ya_cargado ? Hint(`Ya está cargado: ${p.ya_cargado}`, { tone: "error" }) : null,
    nombre.row, fecha.row, h("div", { class: "ra-adm-form-2" }, inicio.row, fin.row), lugar.row, direccion.row,
    h("div", { class: "field" }, h("label", { class: "label", for: "ev-resumen" }, "Resumen"), resumen),
    h("p", { class: "ra-adm-cap" }, [p.tipo, ...(p.organizadores || [])].filter(Boolean).join(" · ")),
    guardar);
  return form;
}

function AddLink(onSaved) {
  const url = input("ev-link", "Link del evento", "", { type: "url", inputmode: "url", required: true, placeholder: "https://…", pattern: "https://.*" });
  const preview = h("div", { class: "ra-adm-sec" });
  const mirar = h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, "Ver cómo queda");
  const form = h("form", { class: "ra-adm-form", onsubmit: async (e) => {
    e.preventDefault();
    mirar.disabled = true;
    preview.replaceChildren(h("p", { class: "ra-adm-cap" }, "Leyendo la página…"));
    try {
      const p = await Admin.eventosVistaPrevia(url.el.value.trim());
      preview.replaceChildren(Preview(p, () => { form.reset(); preview.replaceChildren(); onSaved(); }));
    } catch (err) { preview.replaceChildren(); avisar(mensajeError(err), { error: true }); }
    mirar.disabled = false;
  } },
    h("p", { class: "ra-adm-cap" }, "Para los que no están en Luma ni en conferenceparties. Revisá la fecha y la hora antes de guardar."),
    url.row, mirar);
  return h("section", { class: "ra-num-card", "aria-labelledby": "ev-link-h" }, h("h2", { class: "label", id: "ev-link-h" }, "Agregar evento por link"), form, preview);
}

const diaHora = (iso) => (iso ? new Date(iso).toLocaleString("es-AR", { weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) : "sin horario");

const FilaCharla = (c) => h("a", { class: "ra-adm-fila", href: `#/charla/${encodeURIComponent(c.base)}` },
  h("span", { class: "ra-adm-fila-cuerpo" },
    h("span", { class: "ra-adm-fila-titulo" }, h("span", { class: "ra-adm-code" }, c.base), ` · ${c.titulo ?? ""}`),
    h("span", { class: "ra-g-marcas" }, Tag(c.track), c.horarios > 1 ? Tag(`${c.horarios} horarios`) : null),
    h("span", { class: "ra-adm-fila-sub" }, `${diaHora(c.primero)}${c.alta ? ` · encontrada ${hace(c.alta)}` : ""}`)),
  icon("seguir", 20));

/**
 * Las charlas que entraron solas desde el catálogo oficial (con el resumen en inglés): para revisarlas. Una fila por código, con
 * buscador y chips por track. Se arma una sola vez y `actualizar` solo cambia lo que cambió (título, chips, lista): el sondeo no le
 * quita el foco ni el cursor al buscador. `filtro` vive afuera para no perder lo que se estaba buscando.
 */
function CharlasNuevas(filtro) {
  let filas = [];
  const titulo = h("h2", { class: "label", id: "ev-charlas-h" });
  const nota = h("span", { class: "ra-adm-cap" });
  const lista = h("div", { class: "ra-adm-sec" });
  const chips = h("div", { class: "ra-pillrow", role: "group", "aria-label": "Filtrar por track" });
  const buscador = h("input", { type: "search", id: "ev-q", "aria-label": "Buscar entre las charlas nuevas", placeholder: "Buscar por código o título", value: filtro.texto });

  const pintarChips = () => chips.replaceChildren(...[["Todos", TODOS, filas.length], ...tracksDe(filas).map(([t, n]) => [t, t, n])].map(([etiqueta, track, n]) => {
    const activo = filtro.track === track;
    return h("button", { type: "button", class: `ra-chip${activo ? " ra-chip-on" : ""}`, "aria-pressed": String(activo),
      onclick: () => { filtro.track = track; filtro.todas = false; pintarChips(); pintarLista(); } },
    etiqueta, h("span", { class: "ra-adm-count" }, String(n)));
  }));
  const pintarLista = () => {
    const encontradas = filtrarCharlas(filas, filtro);
    const { filas: vistas, restantes } = visibles(encontradas, filtro.todas);
    const masBoton = Button(`Ver las ${restantes} restantes`, { onclick: () => { filtro.todas = true; pintarLista(); } });
    lista.replaceChildren(
      encontradas.length ? h("div", { class: "ra-adm-lista" }, vistas.map(FilaCharla)) : h("p", { class: "ra-adm-cap", role: "status" }, "Ninguna charla coincide con la búsqueda."),
      ...(restantes ? [masBoton] : []));
  };
  buscador.addEventListener("input", () => { filtro.texto = buscador.value; filtro.todas = false; pintarLista(); });

  const actualizar = (nuevas, ultima) => {
    filas = agruparCharlas(nuevas);
    filtro.track = trackVigente(filas, filtro.track); // si el track elegido ya no existe, vuelve a «Todos»
    titulo.textContent = plural(filas.length, "charla nueva", "charlas nuevas");
    nota.textContent = `${ultima ? `última revisión ${hace(ultima.revisado)}. ` : ""}Las agregó la revisión desde el catálogo oficial, con el resumen en inglés hasta la próxima carga manual.`;
    pintarChips();
    pintarLista();
  };
  const el = h("section", { "aria-labelledby": "ev-charlas-h" },
    h("div", { class: "ra-adm-nueva-head" }, titulo, nota),
    h("div", { class: "ra-searchfield" }, icon("buscar", 20), buscador),
    chips, lista);
  return { el, actualizar };
}

/** «Cargados por link»: el <details> se arma una vez (así el sondeo no lo cierra) y solo se actualiza su lista y su contador. */
function LinksCargados() {
  const lista = h("ul", { class: "ra-adm-lista" });
  const cuenta = h("span", { class: "ra-adm-count" });
  const el = Plegable("Cargados por link", lista, { extra: cuenta });
  const actualizar = (links) => {
    cuenta.textContent = String(links.length);
    lista.replaceChildren(...links.map((l) => h("li", {},
      h("a", { class: "ra-adm-fila", href: `#/evento/${encodeURIComponent(l.id)}` },
        h("span", { class: "ra-adm-fila-cuerpo" }, h("span", { class: "ra-adm-fila-nombre" }, l.nombre), l.cancelado ? h("span", { class: "ra-adm-fila-sub" }, "cancelado") : null),
        icon("seguir", 20)))));
  };
  return { el, actualizar };
}

/**
 * Pestaña Eventos. El formulario «Agregar evento por link» (y su vista previa) se arma una sola vez y queda afuera de lo que
 * se repinta: el sondeo de la revisión solo toca el estado de las fuentes. El timer se corta al salir de la pantalla.
 */
export function viewAdminEventos(view, { setCleanup = () => {} } = {}) {
  let timer = null;
  let activa = true;
  let ocupado = false; // lo último que dijo el servidor: mientras sea true se sigue sondeando, aunque un sondeo falle
  const parar = () => { activa = false; clearTimeout(timer); };
  setCleanup(parar);
  const formulario = h("div", { class: "ra-adm-sec" });
  const charlasHost = h("div", { class: "ra-adm-sec" }); // fuera de lo que repinta el sondeo: no se pierde el foco del buscador
  const linksHost = h("div", { class: "ra-adm-sec" });
  let formularioListo = false;
  let charlas = null;
  const links = LinksCargados();
  let gracia = 0;
  const filtro = { texto: "", track: TODOS, todas: false };

  const estado = Cargable({
    textoCargando: "Cargando las fuentes…",
    cargar: async () => {
      const d = await Admin.eventos();
      if (!formularioListo && d.activo && !d.migracion_pendiente) {
        formularioListo = true;
        formulario.replaceChildren(AddLink(() => void estado.recargar({ silencioso: true })));
      }
      ocupado = d.ocupado;
      if (ocupado) { gracia = 0; programar(); }
      actualizarSecundarias(d);
      return d;
    },
    pintar: (d) => {
      const revisando = d.ocupado || gracia > 0;
      const revisar = Button(revisando ? "Revisando…" : "Revisar ahora", { class: "ra-btn ra-btn-ghost ra-sec-action", onclick: async () => {
        revisar.disabled = true;
        revisar.setAttribute("aria-busy", "true");
        try {
          await Admin.eventosRevisar();
          // Queda deshabilitado en «Revisando…» hasta que el sondeo diga que terminó.
          revisar.textContent = "Revisando…";
          ocupado = true;
          gracia = GRACIA_CICLOS;
          avisar("Revisando las fuentes: tarda un par de minutos.");
          programar();
          void estado.recargar({ silencioso: true });
        } catch (err) {
          avisar(mensajeError(err), { error: true });
          revisar.disabled = false;
          revisar.removeAttribute("aria-busy");
        }
      } });
      revisar.disabled = revisando || !d.activo || d.migracion_pendiente;
      return [ // Cargable filtra los null: replaceChildren escribiría «null»
        !d.activo ? Hint("Apagado en este entorno: se prende con EVENTOS_AUTO=1 (solo en producción).") : null,
        d.migracion_pendiente ? Hint("Falta la migración 007 en la base.", { tone: "error" }) : null,
        h("section", { "aria-labelledby": "ev-fuentes-h" },
          h("div", { class: "ra-sec-head" }, h("h2", { class: "label", id: "ev-fuentes-h" }, "Fuentes"), revisar),
          d.activo ? h("p", { class: "ra-adm-cap" }, `Revisa Luma, conferenceparties${d.ticketmaster ? ", Ticketmaster" : ""} y los links cada ${d.horas} h; el catálogo oficial de charlas, cada 3 h (cada 30 min durante el evento).`) : null,
          !d.ticketmaster ? h("p", { class: "ra-adm-cap" }, "Ticketmaster apagado: falta TICKETMASTER_API_KEY (sin key no aparece la pestaña Shows).") : null,
          d.revisiones.length ? h("div", { class: "ra-adm-lista" }, d.revisiones.map((r) => RevisionRow(r, d.horas))) : null),
      ];
    },
  });

  function programar() {
    clearTimeout(timer);
    if (!activa) return;
    timer = setTimeout(async () => {
      if (!activa || !estado.isConnected) { parar(); return; } // se fue de la pantalla: no sigue pidiendo
      await estado.recargar({ silencioso: true });
      if (ocupado) programar(); // un sondeo que falla en silencio no deja «Revisando…» congelado
      else if (gracia > 0) { gracia -= 1; programar(); } // el servidor puede tardar en marcar ocupado: un ciclo más
    }, ESPERA_MS);
  }

  /** Charlas nuevas y «Cargados por link» viven fuera del Cargable: se arman al aparecer y después solo se actualizan. */
  function actualizarSecundarias(d) {
    const ultima = d.revisiones.find((r) => r.fuente === "catalogo");
    if (charlas && !d.charlas_nuevas?.length) { charlas = null; charlasHost.replaceChildren(); } // ya no quedan: se saca la sección
    if (!charlas && d.charlas_nuevas?.length) {
      charlas = CharlasNuevas(filtro);
      charlasHost.replaceChildren(charlas.el);
    }
    charlas?.actualizar(d.charlas_nuevas ?? [], ultima);
    links.actualizar(d.links ?? []);
    if (d.links?.length) { if (!links.el.isConnected) linksHost.replaceChildren(links.el); } else linksHost.replaceChildren();
  }

  estado.classList.add("ra-adm-resumen");
  AdminShell(view, "eventos", formulario, estado, charlasHost, linksHost);
}
