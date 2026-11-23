// Dónde comer barato: lugares cerca de donde estás (o de la sede de tu próxima sesión) con puntaje, reseñas, precio y
// minutos caminando. Filtros de tipo de lugar, precio ($ / $$) y distancia; «Llevame» reusa el botón de location.js. El servidor
// cachea la búsqueda a Google, así que cambiar un filtro es barato. Si no hay clave de Places, la pantalla lo dice.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { GoThereParts, currentPosition } from "./location.js";
import { Hint, h, mensajeError } from "./ui.js";

const PRECIOS = [[1, "$", "Hasta $ (barato)"], [2, "$$", "Hasta $$ (moderado)"]];
const MINUTOS = [5, 10, 15];
// Las claves son las de places.TIPOS_POR_CATEGORIA (app/places.py); cada tipo es otra búsqueda a Google, cacheada aparte.
const TIPOS = [["todo", "Todo"], ["rapida", "Comida rápida"], ["dulces", "Dulces y postres"], ["cafe", "Café y panadería"],
  ["restaurantes", "Restaurantes"]];
const DEFAULT = { tipo: "todo", precio: 2, minutos: 10 };

const int = (n) => Number(n || 0).toLocaleString("es-AR");
const puntaje = (n) => Number(n).toLocaleString("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** Querystring del pedido: con ubicación del teléfono manda lat/lng; sin ella el servidor usa la próxima sesión. */
export function consulta({ precio, minutos, tipo = "todo" }, pos) {
  const params = new URLSearchParams({ precio, minutos });
  if (tipo !== "todo") params.set("tipo", tipo);
  if (pos) { params.set("lat", pos.lat); params.set("lng", pos.lng); }
  return `/api/comer?${params}`;
}

const etiquetaPrecio = (n) => (n ? "$".repeat(n) : "Sin dato de precio");

function Resena(r) {
  return h("blockquote", { class: "caption", style: { margin: "0", paddingLeft: "var(--space-3)", borderLeft: "2px solid var(--surface-3)" } },
    `“${r.texto}”`);
}

export function LugarCard(l) {
  const dest = { lat: l.lat, lng: l.lng, name: l.nombre, placeId: l.place_id };
  const ir = GoThereParts(dest, { iconOnly: true })?.link;
  const abierto = l.abierto == null ? null : h("span", { class: "ra-tag" }, l.abierto ? "Abierto ahora" : "Cerrado ahora");
  const puntajeTxt = l.rating ? `${puntaje(l.rating)} ★ (${int(l.resenas)} reseñas)` : "Sin reseñas todavía";
  return h("article", { class: "ra-card", style: { cursor: "default" } },
    h("div", { class: "ra-card-top" },
      h("h2", { class: "ra-card-title" }, l.nombre),
      ir),
    l.tipo ? h("span", { class: "ra-kind" }, l.tipo) : null,
    h("div", { class: "ra-card-meta" },
      h("span", {}, puntajeTxt), h("span", {}, etiquetaPrecio(l.precio)),
      h("span", { class: "ra-icotext" }, icon("caminar", 16), `${l.minutos} min caminando`), abierto),
    h("p", { class: "caption" }, l.direccion),
    (l.extracto || []).map(Resena));
}

export async function viewComer(view) {
  const filtros = { ...DEFAULT };
  const lista = h("div", { class: "stack", "aria-live": "polite" });
  const origenEl = h("p", { class: "caption" });
  const grupo = (titulo, opciones, clave) => h("div", { class: "ra-chips", role: "group", "aria-label": titulo },
    opciones.map(([valor, texto, aria]) => {
      const b = h("button", { type: "button", class: "ra-chip", "aria-pressed": "false", "aria-label": aria || null,
        onclick: () => { filtros[clave] = valor; pintarChips(); void cargar(); } }, texto);
      b.dataset.clave = clave; b.dataset.valor = valor;
      return b;
    }));
  const chips = [
    grupo("Tipo de lugar", TIPOS, "tipo"),
    grupo("Precio", PRECIOS, "precio"),
    grupo("Distancia caminando", MINUTOS.map((m) => [m, `${m} min`, `Hasta ${m} minutos caminando`]), "minutos")];
  function pintarChips() {
    for (const b of view.querySelectorAll("button.ra-chip[data-clave]")) {
      const on = String(filtros[b.dataset.clave]) === b.dataset.valor;
      b.classList.toggle("ra-chip-on", on);
      b.setAttribute("aria-pressed", String(on));
    }
  }

  view.append(h("div", { class: "stack-lg" },
    h("div", { class: "stack" },
      h("a", { class: "ra-btn ra-btn-ghost ra-back", href: "#/viaje" }, icon("volver", 16), h("span", {}, "Viaje")),
      h("h1", { class: "title" }, "Dónde comer barato"), origenEl, ...chips),
    lista));
  pintarChips();

  let pedido = 0;
  async function cargar() {
    const mio = ++pedido;
    lista.replaceChildren(h("p", { class: "caption", role: "status" }, "Buscando lugares…"));
    try {
      const pos = await currentPosition();
      const r = await api(consulta(filtros, pos));
      if (mio !== pedido) return; // llegó una respuesta más nueva
      origenEl.textContent = r.origen.fuente === "sesion" ? `Cerca de ${r.origen.nombre}, tu próxima sesión` : "Cerca de donde estás";
      lista.replaceChildren(...(r.lugares.length ? r.lugares.map(LugarCard)
        : [Hint("No encontramos lugares con esos filtros. Probá con más minutos, con $$ o con otro tipo de lugar.")]));
    } catch (e) {
      if (mio !== pedido) return;
      origenEl.textContent = "";
      lista.replaceChildren(Hint(mensajeError(e, "No pudimos buscar lugares para comer."), { tone: "error" }));
    }
  }
  await cargar();
}
