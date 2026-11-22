// Galería pública de videos demo: pide /api/demos (links firmados al bucket), arma las secciones y abre cada video en
// un diálogo. El hash (#gastos) abre ese video directo, y Atrás lo cierra (en Android es lo primero que se toca).
const $ = (id) => document.getElementById(id);
const contenedor = $("secciones");
const estado = $("estado");
const conteo = $("conteo");
const buscar = $("buscar");
const saltos = $("saltos");
const reproductor = $("reproductor");
const video = $("video");

// Orden: lo más útil en el evento primero; lo que no esté acá va a «Más». Las secciones vacías no se muestran.
const SECCIONES = [
  ["grabar", "Grabar charlas", ["grabar-charla", "grabar-desde-charla", "nueva-grabacion", "grabar-sin-senal",
    "lista-de-grabaciones", "detalle-de-grabacion", "buscar-en-lo-grabado"]],
  ["evento", "En el evento", ["inicio-hoy", "llevame", "anuncios-sin-reserva", "avisos-lleno-cola", "me-la-perdi",
    "franja-cuenta-regresiva", "franja-cambios-itinerario", "eventos-networking", "shows"]],
  ["agenda", "Buscar y armar tu agenda", ["buscar-filtrar", "buscar-preguntar", "ficha-de-charla", "ficha-de-speaker",
    "ficha-de-empresa", "itinerario-ver", "itinerario-armado-rapido", "itinerario-entrevista", "itinerario-ficha",
    "itinerario-armar-dia", "mi-evento", "exportar-calendario", "importar-reservas-aws", "cruzar-con-excel", "numeros"]],
  ["viaje", "Viaje", ["viaje-hub", "vuelos-y-hoteles", "gastos", "comer-barato", "ofertas"]],
  ["cuenta", "Cuenta y app", ["login-con-contrasena", "login-con-passkey", "passkey-ajustes", "cambio-de-contrasena",
    "cerrar-sesion", "instalar-pwa", "notificaciones-push", "ajustes-ubicacion-y-alertas", "cambio-de-tema", "modo-sin-senal"]],
];
const ESQUELETOS = 6;

let demos = [];
const tarjetas = new Map(); // feature → <li>, para no rehacer las portadas en cada tecla

const normalizar = (s) => s.toLocaleLowerCase("es-AR").normalize("NFD").replace(/\p{Diacritic}/gu, "");
const duracion = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const duracionHablada = (s) => (s < 60 ? `${s} segundos` : `${Math.floor(s / 60)} min ${s % 60} s`);
const sinMovimiento = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function el(tag, props = {}, ...hijos) {
  const nodo = Object.assign(document.createElement(tag), props);
  nodo.append(...hijos.filter((h) => h !== null && h !== undefined));
  return nodo;
}

function seccionDe(feature) {
  const s = SECCIONES.find(([, , ids]) => ids.includes(feature));
  return s ? s[0] : "mas";
}

function tarjeta(d) {
  const portada = el("span", { className: "dm-portada" },
    el("img", { src: d.poster, alt: "", loading: "lazy", decoding: "async" }),
    el("span", { className: "dm-duracion", textContent: `▶ ${duracion(d.duracion_s)}` }));
  const boton = el("button", { type: "button", className: "dm-tarjeta" }, portada,
    el("span", { className: "dm-texto" }, el("strong", { textContent: d.titulo }), el("span", { textContent: d.beneficio })));
  boton.setAttribute("aria-label", `Ver «${d.titulo}», ${duracionHablada(d.duracion_s)}`);
  boton.addEventListener("click", () => abrir(d));
  return el("li", {}, boton);
}

function armarSecciones() {
  const grupos = [...SECCIONES.map(([id, nombre]) => [id, nombre]), ["mas", "Más"]]
    .map(([id, nombre]) => ({ id, nombre, demos: demos.filter((d) => seccionDe(d.feature) === id) }))
    .filter((g) => g.demos.length);
  for (const d of demos) tarjetas.set(d.feature, tarjeta(d));
  contenedor.replaceChildren(...grupos.map((g) => el("section", { className: "dm-seccion", id: `sec-${g.id}` },
    el("h2", { id: `titulo-${g.id}`, textContent: g.nombre }),
    el("ul", { className: "dm-grilla" }, ...g.demos.map((d) => tarjetas.get(d.feature))))));
  contenedor.querySelectorAll("section").forEach((s) => s.setAttribute("aria-labelledby", s.id.replace("sec-", "titulo-")));
  saltos.replaceChildren(...grupos.map((g) => el("a", { href: `#sec-${g.id}` }, g.nombre, " ",
    el("span", { textContent: String(g.demos.length) }))));
  saltos.hidden = grupos.length < 2;
}

function pintar() {
  const q = normalizar(buscar.value.trim());
  let visibles = 0;
  for (const seccion of contenedor.querySelectorAll("section")) {
    const nombre = normalizar(seccion.querySelector("h2").textContent);
    let enSeccion = 0;
    for (const li of seccion.querySelectorAll(".dm-grilla > li")) {
      const d = demos.find((x) => tarjetas.get(x.feature) === li);
      const ve = !q || nombre.includes(q) || normalizar(`${d.titulo} ${d.beneficio} ${d.feature}`).includes(q);
      li.hidden = !ve;
      enSeccion += ve ? 1 : 0;
    }
    seccion.hidden = enSeccion === 0;
    visibles += enSeccion;
  }
  conteo.textContent = q ? `${visibles} de ${demos.length} videos` : `${demos.length} videos`;
  if (visibles) { estado.replaceChildren(); return; }
  estado.replaceChildren(`Ningún video coincide con «${buscar.value.trim()}».`,
    el("button", { type: "button", className: "ra-btn ra-btn-ghost", textContent: "Borrar búsqueda",
      onclick: () => { buscar.value = ""; pintar(); buscar.focus(); } }));
}

function abrir(d, { desdeLink = false } = {}) {
  $("rep-titulo").textContent = d.titulo;
  $("rep-beneficio").textContent = d.beneficio;
  $("rep-pasos").replaceChildren(...(d.pasos ?? []).map((p) => el("li", { textContent: p })));
  $("rep-detalle").hidden = !d.pasos?.length;
  video.setAttribute("aria-label", `Video sin sonido: ${d.titulo}`);
  video.poster = d.poster;
  video.src = d.video;
  if (!desdeLink) history.pushState({ demo: d.feature }, "", `#${d.feature}`);
  reproductor.showModal();
  if (!sinMovimiento()) video.play().catch(() => {}); // sin autoplay permitido, quedan los controles
}

function cerrar() {
  video.pause();
  video.removeAttribute("src");
  video.load();
  if (history.state?.demo) history.back();
  else history.replaceState(null, "", location.pathname + location.search);
}

function abrirDelHash() {
  const id = location.hash.slice(1);
  if (!id || id.startsWith("sec-")) return;
  const d = demos.find((x) => x.feature === id);
  if (d) abrir(d, { desdeLink: true });
  else estado.replaceChildren("Ese video ya no está. Mirá los demás abajo.");
}

async function cargar() {
  contenedor.setAttribute("aria-busy", "true");
  contenedor.replaceChildren(el("ul", { className: "dm-grilla", ariaHidden: "true" },
    ...Array.from({ length: ESQUELETOS }, () => el("li", { className: "ra-skel dm-skel" }))));
  estado.replaceChildren();
  try {
    const r = await fetch("/api/demos", { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const datos = await r.json();
    if (!datos.disponible || !datos.demos.length) {
      contenedor.replaceChildren();
      estado.replaceChildren("Todavía no hay videos publicados. Volvé en unos días.");
      return;
    }
    demos = datos.demos;
    armarSecciones();
    buscar.disabled = false;
    pintar();
    abrirDelHash();
  } catch (e) {
    console.error("[demos] no se pudo cargar la lista", e);
    contenedor.replaceChildren();
    estado.replaceChildren("No pudimos cargar los videos.",
      el("button", { type: "button", className: "ra-btn ra-btn-secondary", textContent: "Reintentar", onclick: cargar }));
  } finally {
    contenedor.removeAttribute("aria-busy");
  }
}

buscar.addEventListener("input", pintar);
$("cerrar").addEventListener("click", () => reproductor.close());
reproductor.addEventListener("close", cerrar);
reproductor.addEventListener("click", (e) => { if (e.target === reproductor) reproductor.close(); }); // click afuera
video.addEventListener("error", () => {
  if (!video.getAttribute("src")) return; // el error de vaciar el video al cerrar no cuenta
  $("rep-beneficio").textContent = "No se pudo reproducir el video. Recargá la página para pedir uno nuevo.";
});
addEventListener("popstate", () => {
  const d = demos.find((x) => x.feature === location.hash.slice(1));
  if (d && !reproductor.open) abrir(d, { desdeLink: true });
  else if (!d && reproductor.open) reproductor.close();
});
await cargar();
