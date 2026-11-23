// Detalle de una grabación: barra de arriba (Volver, Compartir resumen y el menú ⋯ con Exportar, Link público y
// Eliminar), encabezado con estado y datos, y las pestañas Resumen / Transcripción. Llegando desde un buscador, marca el
// momento encontrado. Ver y exportar, cualquiera; reintentar, borrar y el link público, quien grabó o un admin
// (puede_borrar, app/grabaciones_api.py).
import { Sessions } from "./api.js";
import { confirmDialog } from "./dialog.js";
import { scrollToMoment } from "./grabado.js";
import { icon } from "./icons.js";
import { MenuButton } from "./menu.js";
import * as store from "./store.js";
import { Button, StatusPill, SummaryPanel, TranscriptBlock, clock, h, mensajeError, toast, toastOnError } from "./ui.js";
import { intercalarHuecos, textoHueco } from "./huecos.js";

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
          } catch (e) { toast(mensajeError(e)); btn.disabled = false; }
        } }, label);
      return btn;
    });
    const total = v.si + v.no;
    box.replaceChildren(h("span", { class: "caption", id: `voto-${id}` }, "¿Te sirvió este resumen?"),
      h("div", { class: "ra-voto-botones", role: "group", "aria-labelledby": `voto-${id}` }, botones),
      total ? h("span", { class: "caption" }, `Le sirvió a ${v.si} de ${personas(total)}`) : ""); // "" y no null: replaceChildren escribe «null»
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

// --- exportar el .md y compartir el resumen -------------------------------------------------------------
const fileName = (s) => `${(s.code ? `${s.code}-` : "") + s.title}`
  .replace(/[^\w\-áéíóúñÁÉÍÓÚÑ ]+/g, "").trim().replace(/\s+/g, "-") + ".md";

async function mdFile(id, s) {
  return new File([await Sessions.exportMd(id)], fileName(s), { type: MD_TYPE });
}

function download(file) {
  const url = URL.createObjectURL(file);
  const a = h("a", { href: url, download: file.name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url));
}

/** Comparte un texto con la hoja del celular (WhatsApp, mail…); si no se puede, lo copia y avisa con `copiado`. */
export async function compartirTexto({ title, text, url }, copiado) {
  if (navigator.share) {
    try { await navigator.share(url ? { title, text, url } : { title, text }); return; } catch (e) {
      if (e?.name === "AbortError") return; // canceló la hoja de compartir: no se copia nada
    }
  }
  await navigator.clipboard.writeText(url ? `${text}\n${url}` : text);
  toast(copiado);
}

/** «Compartir resumen»: el markdown público (sin «Versus lo prometido» ni «Para llevar», que son personales). */
async function compartirResumen(id, s) {
  await compartirTexto({ title: s.title, text: await Sessions.resumenMd(id) }, "Resumen copiado: pegalo donde quieras.");
}

const venceEl = (iso) => new Date(iso).toLocaleDateString("es-AR", { day: "numeric", month: "short" });

/** Link público de solo lectura que vence (/c/<token>): lo abre cualquiera que lo tenga, sin cuenta. */
async function compartirLink(id, s) {
  const { url, vence } = await Sessions.compartir(id);
  await compartirTexto({ title: s.title, text: `Resumen de «${s.title}» (vence el ${venceEl(vence)}):`, url },
    `Link copiado. Vence el ${venceEl(vence)}.`);
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
    const ready = s.status === "ready" && Boolean(s.summary);
    const items = [
      ready ? { label: "Exportar .md", iconName: "bajar", onSelect: () => toastOnError(mdFile(id, s).then(download)) } : null,
      ready && s.puede_borrar ? { label: "Link público (vence)", iconName: "compartir", onSelect: () => toastOnError(compartirLink(id, s)) } : null,
      s.puede_borrar ? { label: "Eliminar", iconName: "borrar", danger: true, onSelect: () => toastOnError(remove()) } : null,
    ].filter(Boolean);
    setPageBar(
      h("button", { type: "button", class: "iconbtn", "aria-label": "Volver", title: "Volver", onclick: goBack }, icon("volver", 24)),
      [ready
        ? h("button", { type: "button", class: "iconbtn", "aria-label": "Compartir resumen", title: "Compartir resumen",
          onclick: () => toastOnError(compartirResumen(id, s)) }, icon("compartir", 24))
        : null,
      items.length ? MenuButton({ label: "Más acciones", items }) : null]);
  }

  function paintTranscript(s) {
    if (!s.blocks?.length) return h("div", { class: "empty" }, "Sin transcripción todavía.");
    // Los tramos sin audio van entre los bloques, en el lugar que les toca por tiempo.
    const items = intercalarHuecos(s.blocks, s.huecos).map((i) => i.tipo === "hueco"
      ? h("div", { class: "ra-hueco", role: "separator" }, textoHueco(i)) : TranscriptBlock(i.bloque));
    const content = h("div", { class: "ra-transcript" }, items);
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
      s.status === "error" && s.puede_borrar ? Button("Reintentar", { variant: "primary", onclick: () => toastOnError(Sessions.retry(id).then(load)) }) : "",
      LIVE.includes(s.status) && s.es_mia ? Button("Seguir grabando", { variant: "primary", onclick: () => (location.hash = `#/grabar/${id}`) }) : "");
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
