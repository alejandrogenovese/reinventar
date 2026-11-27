// Dónde comer barato: lugares cerca de donde estás (o de la sede de tu próxima sesión) con puntaje, reseñas, precio y
// minutos caminando. Filtros: tipo de lugar, precio ($ a $$$$), minutos (deslizador que actualiza al moverlo), abierto
// ahora, puntaje mínimo y orden. «Llevame» reusa el botón de location.js. El servidor cachea la búsqueda a Google, así
// que cambiar un filtro es barato. Si no hay clave de Places, la pantalla lo dice.
import { api } from "./api.js";
import { AppsPedidos } from "./appsPedidos.js";
import { icon } from "./icons.js";
import { GoThereParts, currentPosition } from "./location.js";
import { Hint, h, mensajeError } from "./ui.js";

const PRECIOS = [[1, "$ barato", "Hasta $ (barato)"], [2, "$$ moderado", "Hasta $$ (moderado)"],
  [3, "$$$ caro", "Hasta $$$ (caro)"], [4, "$$$$ muy caro", "Hasta $$$$ (muy caro)"]];

/** De dónde se buscó: la próxima sesión, el hotel cargado en Viajes (en un día libre) o la ubicación del celular. */
export function textoOrigen(origen) {
  if (origen?.fuente === "sesion") return `Cerca de ${origen.nombre}, tu próxima sesión`;
  if (origen?.fuente === "hotel") return `Cerca de tu hotel, ${origen.nombre}`;
  return "Cerca de donde estás";
}

export const MINUTOS = { min: 5, max: 30, paso: 5 };
const PUNTAJES = [[0, "Cualquier puntaje"], [4, "4 ★ o más"], [4.5, "4,5 ★ o más"]];
const ORDENES = [["recomendado", "Recomendados"], ["cerca", "Más cerca"], ["puntaje", "Mejor puntaje"]];
const ESPERA_DESLIZADOR_MS = 300; // mientras se arrastra no se pide nada: se pide al quedarse quieto
export const APPS = "apps"; // no busca en Google: muestra las apps de delivery (appsPedidos.js)
// Las claves son las de places.TIPOS_POR_CATEGORIA (app/places.py); cada tipo es otra búsqueda a Google, cacheada aparte.
const TIPOS = [["todo", "Todo"], ["rapida", "Comida rápida"], ["dulces", "Dulces y postres"], ["cafe", "Café y panadería"],
  ["restaurantes", "Restaurantes"], [APPS, "Apps de pedidos"]];
const DEFAULT = { tipo: "todo", precios: [1, 2], minutos: 10, abierto: false, puntaje: 0, orden: "recomendado" };

const int = (n) => Number(n || 0).toLocaleString("es-AR");
const puntaje = (n) => Number(n).toLocaleString("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** Querystring del pedido: con ubicación del teléfono manda lat/lng; sin ella el servidor usa la próxima sesión. Lo que
 * está en su valor por defecto no viaja. `precios`: los niveles elegidos (pueden ser salteados: $ y $$$). */
export function consulta({ precios = DEFAULT.precios, minutos, tipo = "todo", abierto = false, puntaje = 0, orden = "recomendado" }, pos) {
  const params = new URLSearchParams();
  for (const p of [...precios].sort((a, b) => a - b)) params.append("precios", p);
  params.set("minutos", minutos);
  if (tipo !== "todo") params.set("tipo", tipo);
  if (abierto) params.set("abierto", "true");
  if (puntaje) params.set("puntaje", puntaje);
  if (orden !== "recomendado") params.set("orden", orden);
  if (pos) { params.set("lat", pos.lat); params.set("lng", pos.lng); }
  return `/api/comer?${params}`;
}

const NIVELES_PRECIO = ["", "Barato", "Moderado", "Caro", "Muy caro"];
export const minutosTexto = (m) => `Hasta ${m} min caminando`;

/** Ancho de la capa dorada: 4,3 → 86 %. Redondeado a la décima de estrella, como Google. */
export const llenoPct = (rating) => Math.round(Math.min(5, Math.max(0, Number(rating) || 0)) * 10) * 2;

/** Prende o apaga un nivel de precio; siempre queda al menos uno elegido. */
export function alternarPrecio(precios, nivel) {
  const nuevos = precios.includes(nivel) ? precios.filter((p) => p !== nivel) : [...precios, nivel].sort((a, b) => a - b);
  return nuevos.length ? nuevos : precios;
}

/** «4,5 ★★★★⯪ (1.234)»: el número, cinco estrellas (la última parcial) y las reseñas. chica: sin número ni reseñas. */
export function Estrellas(rating, { resenas = null, chica = false } = {}) {
  const fila = h("span", { class: "ra-estrellas-fila", "aria-hidden": "true" }, "★★★★★",
    h("span", { class: "ra-estrellas-llenas", style: { width: `${llenoPct(rating)}%` } }, "★★★★★"));
  const aria = `${puntaje(rating)} de 5 estrellas${resenas == null ? "" : `, ${int(resenas)} reseñas`}`;
  return h("span", { class: `ra-estrellas${chica ? " ra-estrellas-chica" : ""}`, role: "img", "aria-label": aria },
    chica ? null : h("span", { class: "ra-estrellas-num" }, puntaje(rating)),
    fila,
    resenas == null ? null : h("span", { class: "ra-estrellas-cant" }, `(${int(resenas)})`));
}

/** «$$·· Moderado»: los $ del nivel resaltados, los que faltan hasta $$$$ apagados, y la palabra. */
export function Precio(n) {
  if (!n) return h("span", { class: "ra-precio" }, "Sin dato de precio");
  return h("span", { class: "ra-precio", "aria-label": `Precio: ${NIVELES_PRECIO[n].toLowerCase()} (${"$".repeat(n)})` },
    h("span", { class: "ra-precio-on", "aria-hidden": "true" }, "$".repeat(n)),
    h("span", { class: "ra-precio-off", "aria-hidden": "true" }, "$".repeat(4 - n)),
    ` · ${NIVELES_PRECIO[n]}`);
}

function Resena(r) {
  return h("blockquote", { class: "ra-resena caption" },
    r.puntaje ? Estrellas(r.puntaje, { chica: true }) : null,
    h("p", {}, `“${r.texto}”`));
}

export function LugarCard(l) {
  const dest = { lat: l.lat, lng: l.lng, name: l.nombre, placeId: l.place_id };
  const ir = GoThereParts(dest, { iconOnly: true })?.link;
  const abierto = l.abierto == null ? null : h("span", { class: "ra-tag" }, l.abierto ? "Abierto ahora" : "Cerrado ahora");
  const puntajeEl = l.rating ? Estrellas(l.rating, { resenas: l.resenas }) : h("span", {}, "Sin reseñas todavía");
  return h("article", { class: "ra-card", style: { cursor: "default" } },
    h("div", { class: "ra-card-top" },
      h("h2", { class: "ra-card-title" }, l.nombre),
      ir),
    l.tipo ? h("span", { class: "ra-kind" }, l.tipo) : null,
    h("div", { class: "ra-card-meta" },
      puntajeEl, Precio(l.precio),
      h("span", { class: "ra-icotext" }, icon("caminar", 16), `${l.minutos} min caminando`), abierto),
    h("p", { class: "caption" }, l.direccion),
    (l.extracto || []).map(Resena));
}

export async function viewComer(view) {
  const filtros = { ...DEFAULT };
  const lista = h("div", { class: "stack", "aria-live": "polite" });
  const origenEl = h("p", { class: "caption" });
  const abiertoBtn = h("button", { type: "button", class: "ra-chip", "aria-pressed": "false",
    onclick: () => { filtros.abierto = !filtros.abierto; pintarChips(); void cargar(); } }, "Abierto ahora");
  const elegir = (clave, valor) => {
    filtros[clave] = clave === "precios" ? alternarPrecio(filtros.precios, valor) : valor;
    pintarChips(); void cargar();
  };
  const chipsDe = (titulo, opciones, clave) => h("div", { class: "ra-chips", role: "group", "aria-label": titulo },
    opciones.map(([valor, texto, aria]) => {
      const b = h("button", { type: "button", class: "ra-chip", "aria-pressed": "false", "aria-label": aria || null,
        onclick: () => elegir(clave, valor) }, texto);
      b.dataset.clave = clave; b.dataset.valor = valor;
      return b;
    }));
  const seccion = (titulo, ayuda, ...contenido) => h("div", { class: "ra-filtro" },
    h("div", { class: "ra-filtro-titulo" }, h("span", { class: "label" }, titulo), ayuda ? h("span", { class: "caption" }, ayuda) : null),
    ...contenido);
  // Con «Apps de pedidos» el resto de los filtros no aplica: se ocultan.
  const deLugares = [
    seccion("Precio", "Podés elegir varios", chipsDe("Precio", PRECIOS, "precios")),
    seccion("Distancia", null, Deslizador()),
    seccion("Puntaje mínimo", null, chipsDe("Puntaje", PUNTAJES, "puntaje")),
    seccion("Ordenar por", null, chipsDe("Ordenar", ORDENES, "orden")),
    seccion("Horario", null, h("div", { class: "ra-chips" }, abiertoBtn))];
  const panel = h("details", { class: "ra-filtros" },
    h("summary", {}, icon("filtrar", 16), h("span", {}, "Filtros")),
    seccion("Tipo de lugar", null, chipsDe("Tipo de lugar", TIPOS, "tipo")),
    ...deLugares);
  panel.open = true; // h() toma «open» como evento (empieza con «on»)

  function Deslizador() {
    const etiqueta = h("span", { class: "label" }, minutosTexto(filtros.minutos));
    let espera;
    const input = h("input", { type: "range", min: MINUTOS.min, max: MINUTOS.max, step: MINUTOS.paso,
      value: filtros.minutos, "aria-label": "Minutos caminando como máximo",
      oninput: () => {
        filtros.minutos = Number(input.value);
        etiqueta.textContent = minutosTexto(filtros.minutos);
        clearTimeout(espera);
        espera = setTimeout(() => void cargar(), ESPERA_DESLIZADOR_MS);
      } });
    return h("div", { class: "ra-range" }, etiqueta, input,
      h("div", { class: "ra-range-marcas", "aria-hidden": "true" }, h("span", {}, `${MINUTOS.min} min`), h("span", {}, `${MINUTOS.max} min`)));
  }

  function pintarChips() {
    abiertoBtn.classList.toggle("ra-chip-on", filtros.abierto);
    abiertoBtn.setAttribute("aria-pressed", String(filtros.abierto));
    for (const b of view.querySelectorAll("button.ra-chip[data-clave]")) {
      const actual = filtros[b.dataset.clave];
      const on = Array.isArray(actual) ? actual.map(String).includes(b.dataset.valor) : String(actual) === b.dataset.valor;
      b.classList.toggle("ra-chip-on", on);
      b.setAttribute("aria-pressed", String(on));
    }
  }

  view.append(h("div", { class: "stack-lg" },
    h("div", { class: "stack" },
      h("a", { class: "ra-btn ra-btn-ghost ra-back", href: "#/viaje" }, icon("volver", 16), h("span", {}, "Viaje")),
      h("h1", { class: "title" }, "Dónde comer barato"), origenEl, panel),
    lista));
  pintarChips();

  let pedido = 0;
  async function cargar() {
    const mio = ++pedido;
    const apps = filtros.tipo === APPS;
    for (const s of deLugares) s.hidden = apps;
    if (apps) {
      origenEl.textContent = "Delivery al hotel o adonde estés";
      lista.replaceChildren(...AppsPedidos());
      return;
    }
    lista.replaceChildren(h("p", { class: "caption", role: "status" }, "Buscando lugares…"));
    try {
      const pos = await currentPosition();
      const r = await api(consulta(filtros, pos));
      if (mio !== pedido) return; // llegó una respuesta más nueva
      origenEl.textContent = textoOrigen(r.origen);
      lista.replaceChildren(...(r.lugares.length ? r.lugares.map(LugarCard)
        : [Hint("No encontramos lugares con esos filtros. Probá con más minutos, más $, otro tipo de lugar o sacando «Abierto ahora».")]));
    } catch (e) {
      if (mio !== pedido) return;
      origenEl.textContent = "";
      lista.replaceChildren(Hint(mensajeError(e, "No pudimos buscar lugares para comer."), { tone: "error" }));
    }
  }
  await cargar();
}
