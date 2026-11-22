// Galería pública de videos demo: pide /api/demos (links firmados al bucket), arma la grilla y abre cada video en un
// diálogo. El hash (#gastos) abre ese video directo, para poder compartir el link de uno solo.
const $ = (id) => document.getElementById(id);
const grilla = $("grilla");
const estado = $("estado");
const conteo = $("conteo");
const buscar = $("buscar");
const reproductor = $("reproductor");
const video = $("video");

let demos = [];

const normalizar = (s) => s.toLocaleLowerCase("es-AR").normalize("NFD").replace(/\p{Diacritic}/gu, "");
const duracion = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

function el(tag, props = {}, ...hijos) {
  const nodo = Object.assign(document.createElement(tag), props);
  nodo.append(...hijos.filter((h) => h !== null && h !== undefined));
  return nodo;
}

function tarjeta(d) {
  const portada = el("div", { className: "dm-portada" },
    el("img", { src: d.poster, alt: "", loading: "lazy", decoding: "async" }),
    el("span", { className: "dm-play", ariaHidden: "true", textContent: "▶" }),
    el("span", { className: "dm-duracion", textContent: duracion(d.duracion_s) }));
  const boton = el("button", { type: "button", className: "dm-tarjeta" }, portada,
    el("div", { className: "dm-texto" }, el("strong", { textContent: d.titulo }), el("span", { textContent: d.beneficio })));
  boton.setAttribute("aria-label", `Ver «${d.titulo}», ${duracion(d.duracion_s)}`);
  boton.addEventListener("click", () => abrir(d));
  return el("li", {}, boton);
}

function pintar() {
  const q = normalizar(buscar.value.trim());
  const visibles = q ? demos.filter((d) => normalizar(`${d.titulo} ${d.beneficio} ${d.feature}`).includes(q)) : demos;
  grilla.replaceChildren(...visibles.map(tarjeta));
  conteo.textContent = q ? `${visibles.length} de ${demos.length} videos` : `${demos.length} videos`;
  estado.textContent = visibles.length ? "" : "No hay videos que coincidan con la búsqueda.";
}

function abrir(d) {
  $("rep-titulo").textContent = d.titulo;
  $("rep-beneficio").textContent = d.beneficio;
  video.poster = d.poster;
  video.src = d.video;
  if (location.hash.slice(1) !== d.feature) history.replaceState(null, "", `#${d.feature}`);
  reproductor.showModal();
  video.play().catch(() => {}); // si el navegador no deja arrancar solo, queda con los controles
}

function cerrar() {
  video.pause();
  video.removeAttribute("src");
  video.load();
  history.replaceState(null, "", location.pathname);
}

async function cargar() {
  try {
    const r = await fetch("/api/demos", { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const datos = await r.json();
    if (!datos.disponible || !datos.demos.length) {
      estado.textContent = "Todavía no hay videos publicados. Volvé en unos días.";
      return;
    }
    demos = datos.demos;
    buscar.disabled = false;
    pintar();
    const pedida = demos.find((d) => d.feature === location.hash.slice(1));
    if (pedida) abrir(pedida);
  } catch (e) {
    console.error("[demos] no se pudo cargar la lista", e);
    estado.textContent = "No pudimos cargar los videos. Recargá la página en un rato.";
  }
}

buscar.disabled = true;
buscar.addEventListener("input", pintar);
$("cerrar").addEventListener("click", () => reproductor.close());
reproductor.addEventListener("close", cerrar);
reproductor.addEventListener("click", (e) => { if (e.target === reproductor) reproductor.close(); }); // click afuera
await cargar();
