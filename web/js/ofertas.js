// Ofertas de la semana: la lista de vigentes con filtro por categoría (#/ofertas), la ficha de una (#/ofertas/<id>, a donde
// abre el push) y los interruptores de Ajustes para recibir alertas. Ver app/ofertas.py y app/ofertas_avisos.py.
import { api } from "./api.js";
import { Hint, h, mensajeError, toast } from "./ui.js";

const TZ = "America/Los_Angeles"; // las vigencias son en hora de Las Vegas
const TODAS = "todas";
const CATEGORIAS_FALLBACK = { shows: "Shows", comida: "Comida", compras: "Compras y outlets", otros: "Otros" };

export const Ofertas = {
  list: (categoria) => api(`/api/ofertas${categoria && categoria !== TODAS ? `?${new URLSearchParams({ categoria })}` : ""}`),
  get: (id) => api(`/api/ofertas/${encodeURIComponent(id)}`),
  prefs: () => api("/api/ofertas/preferencias"),
  savePrefs: (prefs) => api("/api/ofertas/preferencias", { method: "PUT", json: prefs }),
};

const cuando = (iso) => (iso ? new Date(iso).toLocaleString("es-AR", { timeZone: TZ, weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }).replaceAll(".", "") : "");
const usd = (n) => `US$ ${Number.isInteger(n) ? n : n.toFixed(2)}`;
// El link viene de un admin o de Ticketmaster: solo https.
const linkSeguro = (url) => (typeof url === "string" && url.startsWith("https://") ? url : null);

/** "(-30 %)" de una baja de precio, o "". */
export const porcentajeBaja = (o) => (o.precio_antes && o.precio_ahora != null && o.precio_antes > o.precio_ahora
  ? `-${Math.round((1 - o.precio_ahora / o.precio_antes) * 100)} %` : "");

/** Lo que pasa al tocar «Avisarme de ofertas»: "instalar" | "no_soportado" | "denegado" | "pedir" (se pide el permiso y se suscribe). */
export function decisionActivacion({ estado, permiso }) {
  if (estado === "ios_sin_instalar") return "instalar";
  if (estado !== "ok") return "no_soportado";
  return permiso === "denied" ? "denegado" : "pedir";
}

export const TEXTO_DENEGADO = "Las notificaciones están bloqueadas en este dispositivo. Habilitalas en los ajustes del navegador (iPhone: Ajustes → Notificaciones → ReinventAR; Android: ícono del candado → Permisos → Notificaciones) y volvé a activar. Mientras tanto podés ver las ofertas en la pantalla Ofertas.";

/**
 * Qué mostrar cuando no hay ofertas vigentes: el texto y los enlaces ({ texto, href, primario }). Con todas las categorías
 * se explica de dónde salen las ofertas (así la pantalla no parece rota) y, si es admin, se ofrece cargar una.
 */
export function estadoVacio({ categoria = TODAS, esAdmin = false } = {}) {
  if (categoria !== TODAS) return { texto: "No hay ofertas vigentes en esta categoría.", enlaces: [] };
  return {
    texto: "Todavía no hay ofertas. Las bajas de precio de shows aparecen cuando Ticketmaster publica precios, y el equipo carga ofertas de comida y outlets durante la semana.",
    enlaces: [
      { texto: "Ver los shows", href: "#/eventos/shows", primario: false },
      ...(esAdmin ? [{ texto: "Cargar una oferta", href: "#/admin/ofertas", primario: true }] : []),
    ],
  };
}

function Vacio(estado) {
  return h("div", { class: "stack" }, h("p", { class: "caption" }, estado.texto),
    estado.enlaces.length ? h("div", { class: "actions" }, estado.enlaces.map((e) => h("a", { class: e.primario ? "ra-btn ra-btn-primary" : "ra-btn", href: e.href }, e.texto))) : null);
}

// --- tarjetas --------------------------------------------------------------------
function Precio(o) {
  if (o.precio_ahora == null) return null;
  const baja = porcentajeBaja(o);
  return h("p", { class: "caption" }, o.precio_antes ? h("s", {}, usd(o.precio_antes)) : null, o.precio_antes ? " " : "", h("strong", {}, usd(o.precio_ahora)), baja ? ` (${baja})` : "");
}

function Tarjeta(o, nombres) {
  const link = linkSeguro(o.link);
  return h("article", { class: "ra-event", id: `oferta-${o.id}` },
    h("div", { class: "ra-event-body" },
      h("span", { class: "ra-kind" }, (nombres[o.categoria] || o.categoria).toUpperCase()),
      h("h3", { class: "ra-card-title" }, h("a", { class: "ra-link", href: `#/ofertas/${encodeURIComponent(o.id)}` }, o.titulo)),
      Precio(o),
      h("div", { class: "ra-card-meta" }, o.lugar ? h("span", {}, o.lugar) : null,
        h("span", {}, o.hasta ? `Hasta ${cuando(o.hasta)}` : `Desde ${cuando(o.desde)}`)),
      o.nota ? h("p", { class: "caption" }, o.nota) : null,
      link ? h("div", { class: "actions" }, h("a", { class: "ra-link", href: link, target: "_blank", rel: "noopener noreferrer" }, "Ver la oferta")) : null));
}

function Filtros(nombres, actual, onPick) {
  return h("div", { class: "ra-segtabs", role: "group", "aria-label": "Categoría" },
    [[TODAS, "Todas"], ...Object.entries(nombres)].map(([valor, nombre]) => h("button", { type: "button", class: "ra-segtab",
      "aria-pressed": String(valor === actual), "data-valor": valor, onclick: () => onPick(valor) }, nombre)));
}

// --- pantallas -------------------------------------------------------------------
/** #/ofertas (lista con filtro) o #/ofertas/<id> (una sola). */
export async function viewOfertas(view, id = null) {
  if (id) return viewOferta(view, decodeURIComponent(id));
  let categoria = TODAS;
  const lista = h("div", { class: "stack" });
  const filtros = h("div");
  const admin = h("div", { class: "actions" });
  let pedido = 0;
  // Los botones se repintan en el lugar (sin rehacerlos), así el foco no se pierde al elegir un filtro.
  const marcar = () => { for (const b of filtros.querySelectorAll("button[data-valor]")) b.setAttribute("aria-pressed", String(b.dataset.valor === categoria)); };
  async function pintar() {
    const mio = ++pedido;
    let d;
    try { d = await Ofertas.list(categoria); } catch (err) {
      if (mio === pedido) lista.replaceChildren(Hint(mensajeError(err), { tone: "error" }));
      return;
    }
    if (mio !== pedido) return; // llegó una respuesta más nueva: esta ya no vale
    const nombres = d.categorias || CATEGORIAS_FALLBACK;
    if (!filtros.firstChild) filtros.replaceChildren(Filtros(nombres, categoria, (c) => { categoria = c; marcar(); void pintar(); }));
    marcar();
    const vacio = !d.ofertas.length;
    const vacioConAdmin = vacio && categoria === TODAS; // el estado vacío ya trae «Cargar una oferta»: no se repite abajo
    admin.replaceChildren(...(d.es_admin && !vacioConAdmin ? [h("a", { class: "ra-btn", href: "#/admin/ofertas" }, "Cargar ofertas")] : []));
    lista.replaceChildren(...(vacio ? [Vacio(estadoVacio({ categoria, esAdmin: d.es_admin }))] : d.ofertas.map((o) => Tarjeta(o, nombres))));
  }
  view.append(h("div", { class: "stack-lg" }, h("h1", { class: "title" }, "Ofertas"),
    h("p", { class: "caption" }, "Bajas de precio de shows y ofertas de comida y compras en Las Vegas. Podés recibir avisos desde Ajustes."),
    filtros, lista, admin));
  await pintar();
}

async function viewOferta(view, id) {
  const raiz = h("div"); // si ya navegó a otra pantalla, la respuesta tardía no la pisa
  view.append(raiz);
  let o;
  try { o = await Ofertas.get(id); } catch (err) {
    if (!raiz.isConnected) return;
    raiz.append(h("div", { class: "stack-lg" }, h("h1", { class: "title" }, "Oferta"), Hint(err.status === 404 ? "Esta oferta ya no está disponible." : mensajeError(err), { tone: "error" }),
      h("a", { class: "ra-link", href: "#/ofertas" }, "← Ver todas las ofertas")));
    return;
  }
  if (!raiz.isConnected) return;
  raiz.append(h("div", { class: "stack-lg" }, h("a", { class: "ra-link", href: "#/ofertas" }, "← Ofertas"), Tarjeta(o, o.categoria_nombre ? { [o.categoria]: o.categoria_nombre } : CATEGORIAS_FALLBACK),
    o.id_show ? h("a", { class: "ra-btn", href: `#/show/${encodeURIComponent(o.id_show)}` }, "Ver el show") : null));
}

// --- Ajustes ---------------------------------------------------------------------
/**
 * «Avisarme de ofertas» y las categorías. `deps`: estado() ("ok" | "ios_sin_instalar" | "no_soportado"), permiso() y
 * activarDispositivo() (pide el permiso y suscribe este dispositivo: lo pone notifications.js). El permiso se pide
 * directo del toque, sin ningún await antes: iOS no lo muestra si no.
 */
export function OfertasSettings(deps) {
  const aviso = h("div", { class: "stack" });
  const activas = h("input", { type: "checkbox", id: "ofertas-on", disabled: true });
  const categorias = Object.entries(CATEGORIAS_FALLBACK).map(([clave, nombre]) => {
    const input = h("input", { type: "checkbox", id: `ofertas-cat-${clave}`, value: clave, disabled: true });
    return { clave, input, row: h("label", { class: "actions is-center", for: input.id }, input, nombre) };
  });
  const elegidas = () => categorias.filter((c) => c.input.checked).map((c) => c.clave);
  const guardar = () => Ofertas.savePrefs({ activas: activas.checked, categorias: elegidas() });
  const mostrar = (nodo) => aviso.replaceChildren(...[nodo].filter(Boolean));

  activas.onchange = async () => {
    mostrar(null);
    if (!activas.checked) {
      try { await guardar(); toast("Alertas de ofertas apagadas."); } catch (err) { activas.checked = true; toast(mensajeError(err)); }
      return;
    }
    const plan = decisionActivacion({ estado: deps.estado(), permiso: deps.permiso() });
    if (plan !== "pedir") {
      activas.checked = false;
      // install.js engancha eventos de window al cargarse: solo se trae cuando hace falta mostrar los pasos.
      if (plan === "instalar") mostrar((await import("./install.js")).InstallPrompt() ?? Hint("Abrí la app desde el ícono de la pantalla de inicio y activá las ofertas de nuevo."));
      else mostrar(Hint(plan === "denegado" ? TEXTO_DENEGADO : "Este navegador no soporta notificaciones. En iPhone, instalá la app en la pantalla de inicio y abrila desde ahí.", { tone: plan === "denegado" ? "error" : "warn" }));
      return;
    }
    activas.disabled = true;
    try {
      await deps.activarDispositivo(); // pide el permiso en este mismo toque
      await guardar();
      toast("Listo: te avisamos de las ofertas.");
    } catch (err) {
      activas.checked = false;
      if (deps.permiso() === "denied") mostrar(Hint(TEXTO_DENEGADO, { tone: "error" })); else toast(mensajeError(err));
    }
    activas.disabled = false;
  };
  for (const c of categorias) {
    c.input.onchange = async () => {
      c.input.disabled = true;
      try { await guardar(); } catch (err) { c.input.checked = !c.input.checked; toast(mensajeError(err)); }
      c.input.disabled = false;
    };
  }
  void Ofertas.prefs().then((p) => {
    activas.checked = p.activas;
    for (const c of categorias) { c.input.checked = p.categorias.includes(c.clave); c.input.disabled = false; }
    activas.disabled = false;
  }).catch(() => {});
  return h("div", { class: "stack" },
    h("h2", { class: "label" }, "Ofertas"),
    h("label", { class: "actions is-center", for: "ofertas-on" }, activas, "Avisarme de ofertas"),
    h("p", { class: "caption" }, "Bajas de precio de shows y ofertas de comida y compras. Pocos avisos por día y nunca de noche."),
    aviso,
    h("span", { class: "label" }, "Qué ofertas"),
    ...categorias.map((c) => c.row),
    h("div", { class: "actions" }, h("a", { class: "ra-btn", href: "#/ofertas" }, "Ver ofertas vigentes")));
}
