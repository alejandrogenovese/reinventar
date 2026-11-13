// Detalle de una grabación: barra de arriba (Volver, Compartir y el menú ⋯ con Exportar y Eliminar), encabezado con
// estado y datos, y las pestañas Resumen / Transcripción. Llegando desde un buscador, marca el momento encontrado.
import { Sessions } from "./api.js";
import { confirmDialog } from "./dialog.js";
import { scrollToMoment } from "./grabado.js";
import { icon } from "./icons.js";
import { MenuButton } from "./menu.js";
import * as store from "./store.js";
import { Button, StatusPill, SummaryPanel, TranscriptBlock, clock, h, toast, toastOnError } from "./ui.js";

const PROCESSING = ["queued", "transcribing", "translating", "summarizing"];
const LIVE = ["recording", "uploading"];
const RELOAD_MS = 4000;
const MD_TYPE = "text/markdown";

// --- 👍/👎 del resumen (app/voto_resumen_api.py) ------------------------------------------------------
const OPCIONES_VOTO = [[true, "👍 Sí", "Me sirvió"], [false, "👎 No", "No me sirvió"]];
const personas = (n) => `${n} persona${n === 1 ? "" : "s"}`;

/** «¿Te sirvió este resumen?» con 👍 y 👎. Tocar el voto propio lo retira; otro toque lo cambia. */
function VotoResumen(id, voto) {
  const box = h("div", { class: "ra-voto" });
  const pintar = (v) => {
    const botones = OPCIONES_VOTO.map(([util, label, nombre]) => {
      const mio = v.mio === util;
      const btn = h("button", { type: "button", class: mio ? "ra-chip ra-chip-on" : "ra-chip", "aria-pressed": String(mio), "aria-label": nombre,
        onclick: async () => {
          btn.disabled = true;
          try {
            pintar(mio ? await Sessions.retirarVoto(id) : await Sessions.votar(id, util));
            if (!mio) toast(util ? "¡Gracias!" : "Gracias: nos ayuda a mejorar los resúmenes.");
          } catch (e) { toast(e.message); btn.disabled = false; }
        } }, label);
      return btn;
    });
    const total = v.si + v.no;
    box.replaceChildren(h("span", { class: "caption", id: `voto-${id}` }, "¿Te sirvió este resumen?"),
      h("div", { class: "ra-voto-botones", role: "group", "aria-labelledby": `voto-${id}` }, botones),
      total ? h("span", { class: "caption" }, `Le sirvió a ${v.si} de ${personas(total)}`) : null);
  };
  pintar(voto || { si: 0, no: 0, mio: null });
  return box;
}

// --- barra de la pantalla (reemplaza al logo y a tema/ajustes mientras se ve un detalle) ----------------
const pagebar = document.getElementById("pagebar");

/** Vacía la barra de la pantalla; el router la limpia en cada navegación. */
export function clearPageBar() {
  if (!pagebar) return;
  pagebar.replaceChildren();
  pagebar.hidden = true;
  document.body.classList.remove("has-pagebar");
}

function setPageBar(start, end) {
  if (!pagebar) return;
  pagebar.replaceChildren(start, h("div", { class: "toolbar" }, end));
  pagebar.hidden = false;
  document.body.classList.add("has-pagebar");
}

// --- exportar y compartir el .md -------------------------------------------------------------------
const fileName = (s) => `${(s.code ? `${s.code}-` : "") + s.title}`
  .replace(/[^\w\-áéíóúñÁÉÍÓÚÑ ]+/g, "").trim().replace(/\s+/g, "-") + ".md";

/** El navegador puede compartir archivos (hoja de compartir del celular): solo así se muestra Compartir. */
export function canShareFiles() {
  try { return Boolean(navigator.canShare?.({ files: [new File([""], "resumen.md", { type: MD_TYPE })] })); } catch { return false; }
}

async function mdFile(id, s) {
  return new File([await Sessions.exportMd(id)], fileName(s), { type: MD_TYPE });
}

function download(file) {
  const url = URL.createObjectURL(file);
  const a = h("a", { href: url, download: file.name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url));
}

async function share(id, s) {
  const file = await mdFile(id, s);
  try { await navigator.share({ files: [file], title: s.title }); } catch (e) {
    if (e?.name !== "AbortError") download(file); // si el celular no lo deja compartir, se descarga
  }
}

// --- piezas del encabezado -------------------------------------------------------------------------
const KindLine = (s) => h("span", { class: "ra-kind" }, s.code ? [h("b", {}, s.code), " · "] : null, s.kind);

function MetaRow(s) {
  const who = [s.speaker, s.venue].filter(Boolean).join(" · ");
  return h("div", { class: "ra-detail-meta" },
    StatusPill(s.status, s.progress || undefined),
    who ? h("span", {}, who) : null,
    s.duration_s ? h("span", { class: "ra-mono" }, clock(s.duration_s)) : null);
}

const TalkLink = (talk) => h("a", { class: "ra-btn ra-btn-ghost ra-talklink", href: `#/charla/${talk.base}`,
  "aria-label": `Ver la ficha de la charla: ${talk.title}` }, h("span", {}, "Ver la ficha de la charla"), icon("seguir", 16));

/** Pastilla "Desde la búsqueda" sobre la transcripción, con ✕ para sacar la marca. */
const FromSearch = (q, onClose) => h("div", { class: "ra-from" }, icon("buscar", 16),
  h("span", { class: "ra-from-text" }, q ? `Desde la búsqueda «${q}»` : "Desde la búsqueda"),
  h("button", { type: "button", class: "ra-from-close", "aria-label": "Quitar la marca de la búsqueda", onclick: onClose }, icon("cerrar", 16)));

// --- pantalla --------------------------------------------------------------------------------------
/**
 * #/s/<id> y #/s/<id>/t/<segundo>?q=<búsqueda> (desde Buscar en lo grabado o el chat): abre la transcripción en ese
 * momento. `setCleanup` recibe lo que hay que cortar al salir; `onError` muestra un error de las recargas.
 */
export async function viewDetail(view, id, { at = null, q = "", canGoBack = false, setCleanup, onError }) {
  let tab = at != null ? "transcripcion" : "resumen";
  let hit = at != null ? Number(at) : null; // el momento marcado; null cuando se cierra la pastilla
  let scrolled = false;
  let barStatus = null;
  let timer;
  const head = h("div", { class: "ra-detail-head" });
  const body = h("div", { class: "stack" });
  const actions = h("div", { class: "actions" });
  view.append(h("div", { class: "ra-detail" }, head, actions, body));
  setCleanup(() => clearTimeout(timer));

  const goBack = () => { if (canGoBack) history.back(); else location.hash = "#/"; };

  async function remove() {
    if (!await confirmDialog("¿Eliminar la sesión?", { text: "Se borran el audio, la transcripción y el resumen. No se puede deshacer.", confirmLabel: "Eliminar", danger: true })) return;
    await Sessions.remove(id); store.dropRecMeta(id); location.hash = "#/";
  }

  function paintBar(s) {
    if (barStatus === s.status) return; // no rearmar mientras procesa: cerraría el menú abierto
    barStatus = s.status;
    const ready = s.status === "ready";
    const items = [
      ready ? { label: "Exportar .md", iconName: "bajar", onSelect: () => toastOnError(mdFile(id, s).then(download)) } : null,
      { label: "Eliminar", iconName: "borrar", danger: true, onSelect: () => toastOnError(remove()) },
    ].filter(Boolean);
    setPageBar(
      h("button", { type: "button", class: "iconbtn", "aria-label": "Volver", title: "Volver", onclick: goBack }, icon("volver", 24)),
      [ready && canShareFiles()
        ? h("button", { type: "button", class: "iconbtn", "aria-label": "Compartir el resumen (.md)", title: "Compartir",
          onclick: () => toastOnError(share(id, s)) }, icon("compartir", 24))
        : null,
      MenuButton({ label: "Más acciones", items })]);
  }

  function paintTranscript(s) {
    if (!s.blocks?.length) return h("div", { class: "empty" }, "Sin transcripción todavía.");
    const content = h("div", { class: "ra-transcript" }, s.blocks.map(TranscriptBlock));
    if (hit == null) return content;
    const unmark = () => { hit = null; from.remove(); content.querySelector(".ra-tb.is-hit")?.classList.remove("is-hit"); };
    const from = FromSearch(q, unmark);
    const scroll = !scrolled;
    scrolled = true; // una sola vez: las recargas mientras procesa no vuelven a mover la vista
    setTimeout(() => scrollToMoment(content, hit, { scroll })); // después del scrollTo(0, 0) del router
    return h("div", {}, from, content);
  }

  async function load() {
    const s = await Sessions.get(id);
    paintBar(s);
    head.replaceChildren(KindLine(s), h("h1", { class: "title ra-detail-title" }, s.title), MetaRow(s),
      s.talk ? TalkLink(s.talk) : "",
      s.error ? h("div", { class: "notice err" }, s.error) : "");
    actions.replaceChildren(
      s.status === "error" ? Button("Reintentar", { variant: "primary", onclick: () => toastOnError(Sessions.retry(id).then(load)) }) : "",
      LIVE.includes(s.status) ? Button("Seguir grabando", { variant: "primary", onclick: () => (location.hash = `#/grabar/${id}`) }) : "");
    actions.hidden = !actions.childElementCount;

    const tabs = h("div", { class: "tabs", role: "tablist" },
      [["resumen", "Resumen"], ["transcripcion", "Transcripción"]].map(([k, label]) =>
        h("button", { class: "ra-tab", role: "tab", "aria-selected": String(tab === k), onclick: () => { tab = k; toastOnError(load()); } }, label)));
    const content = tab === "resumen"
      ? (s.summary ? h("div", {}, SummaryPanel(s.summary), VotoResumen(id, s.voto)) : h("div", { class: "empty" }, PROCESSING.includes(s.status) ? "El resumen aparece cuando termina el procesamiento." : "Sin resumen todavía."))
      : paintTranscript(s);
    body.replaceChildren(tabs, content);

    clearTimeout(timer);
    if (PROCESSING.includes(s.status)) timer = setTimeout(() => load().catch(onError), RELOAD_MS);
  }

  await load();
}
