// Actividades (node --test): textos de duración, precio y distancia de las tarjetas, y la consulta de Cerca.
import test from "node:test";
import assert from "node:assert/strict";

// DOM mínimo: alcanza para armar las tarjetas, recorrerlas y tocar botones.
class Nodo {
  constructor(tag) { this.tag = tag; this.nodeType = 1; this.attrs = {}; this.children = []; this.className = ""; this.style = {}; this.on = {}; this.classList = { add: () => {}, toggle: () => {} }; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(tipo, fn) { this.on[tipo] = fn; }
  append(...hijos) { this.children.push(...hijos); }
  replaceChildren(...hijos) { this.children = hijos; }
  get textContent() { return this.children.map((c) => (typeof c === "string" ? c : c.textContent)).join(""); }
  set textContent(v) { this.children = [String(v)]; }
}
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.window = { dispatchEvent() {}, addEventListener() {} };
globalThis.location = { hash: "" };
globalThis.document = { createElement: (t) => new Nodo(t), createElementNS: (_n, t) => new Nodo(t), getElementById: () => null };

const { minutosTexto, duracionTexto, precioTexto, distanciaTexto, consultaCerca, pintarExcursiones, panelExcursiones, pestanaInicial } =
  await import("../../web/js/actividades.js");

const todos = (n) => (typeof n === "string" ? [] : [n, ...n.children.flatMap(todos)]);
const buscar = (raiz, tag, texto) => todos(raiz).filter((n) => n.tag === tag && (!texto || n.textContent.includes(texto)));
const producto = (codigo, extra = {}) => ({ codigo, titulo: `Excursión ${codigo}`, foto: null, precio_desde: 50, moneda: "USD", rating: 4.5,
  resenas: 10, minutos_desde: 60, minutos_hasta: 60, url: `https://www.viator.com/tours/${codigo}?pid=P1&mcid=1&medium=api`, tags: [], ...extra });
const esperar = () => new Promise((r) => setTimeout(r, 0));

test("minutos en horas y minutos", () => {
  assert.equal(minutosTexto(45), "45 min");
  assert.equal(minutosTexto(120), "2 h");
  assert.equal(minutosTexto(90), "1 h 30 min");
});

test("duración fija, variable o sin dato", () => {
  assert.equal(duracionTexto(720, 720), "12 h");
  assert.equal(duracionTexto(30, 60), "30 min a 1 h");
  assert.equal(duracionTexto(null, 90), "1 h 30 min");
  assert.equal(duracionTexto(null, null), null);
});

test("precio desde, con decimales solo si hacen falta", () => {
  assert.equal(precioTexto(189.99), "desde US$ 189,99");
  assert.equal(precioTexto(25, "USD"), "desde US$ 25");
  assert.equal(precioTexto(30, "EUR"), "desde EUR 30");
  assert.equal(precioTexto(null), null);
});

test("distancia en metros redondeados o en km", () => {
  assert.equal(distanciaTexto(648), "a 650 m");
  assert.equal(distanciaTexto(2300), "a 2,3 km");
});

test("Cerca manda lat/lng solo si hay ubicación", () => {
  assert.equal(consultaCerca(null), "/api/actividades/cerca");
  assert.equal(consultaCerca({ lat: 36.1, lng: -115.2 }), "/api/actividades/cerca?lat=36.1&lng=-115.2");
});

test("pintarExcursiones agrupa con títulos de categoría y el botón abre el link de afiliado tal cual", () => {
  const r = { productos: [producto("A"), producto("B")], grupos: [
    { clave: "excursiones", titulo: "Excursiones de un día", productos: [producto("A")] },
    { clave: "atracciones", titulo: "Atracciones", productos: [producto("B")] }] };
  const { productos, nodos } = pintarExcursiones(r);
  assert.equal(productos.length, 2);
  assert.deepEqual(nodos.filter((n) => n.tag === "h2").map((n) => n.textContent), ["Excursiones de un día · 1", "Atracciones · 1"]);
  const [link] = nodos.flatMap((n) => buscar(n, "a", "Reservar en Viator"));
  assert.equal(link.attrs.href, producto("A").url);
  assert.equal(link.attrs.target, "_blank");
});

test("pintarExcursiones sin grupos va en lista simple, y sin productos muestra un aviso", () => {
  assert.deepEqual(pintarExcursiones({ productos: [producto("A")], grupos: null }).nodos.map((n) => n.tag), ["article"]);
  const vacio = pintarExcursiones({ productos: [], grupos: null });
  assert.match(vacio.nodos[0].textContent, /No encontramos excursiones/);
});

test("pintarExcursiones no toca la lista acumulada y las páginas siguientes van sin agrupar", () => {
  const previos = Object.freeze([producto("A")]);
  const r = { productos: [producto("B")], grupos: [{ clave: "tours", titulo: "Tours", productos: [producto("B")] }] };
  const { productos, nodos } = pintarExcursiones(r, previos);
  assert.deepEqual(productos.map((p) => p.codigo), ["A", "B"]);
  assert.deepEqual(nodos.map((n) => n.tag), ["article"]);
});

test("«Ver más» pide la página siguiente y suma las tarjetas", async () => {
  const pedidas = [];
  const pedir = async (pagina) => {
    pedidas.push(pagina);
    return pagina === 1 ? { productos: [producto("A")], grupos: null, hay_mas: true } : { productos: [producto("B")], grupos: null, hay_mas: false };
  };
  const cont = new Nodo("div");
  await panelExcursiones(cont, pedir);
  assert.equal(buscar(cont, "article").length, 1);
  const [verMas] = buscar(cont, "button", "Ver más");
  await verMas.on.click();
  assert.deepEqual(pedidas, [1, 2]);
  assert.equal(buscar(cont, "article").length, 2);
  assert.equal(buscar(cont, "button", "Ver más").length, 0);
});

test("si «Ver más» falla queda el error con «Reintentar», que vuelve a pedir la misma página", async () => {
  let falla = true;
  const pedidas = [];
  const pedir = async (pagina) => {
    pedidas.push(pagina);
    if (pagina === 2 && falla) throw new Error("sin señal");
    return { productos: [producto(`P${pagina}`)], grupos: null, hay_mas: pagina === 1 };
  };
  const cont = new Nodo("div");
  await panelExcursiones(cont, pedir);
  await buscar(cont, "button", "Ver más")[0].on.click();
  assert.equal(buscar(cont, "p").some((n) => n.className.includes("is-error")), true);
  assert.equal(buscar(cont, "article").length, 1, "las tarjetas de la primera página quedan");
  falla = false;
  await buscar(cont, "button", "Reintentar")[0].on.click();
  await esperar();
  assert.deepEqual(pedidas, [1, 2, 2]);
  assert.equal(buscar(cont, "article").length, 2);
  assert.equal(buscar(cont, "button", "Reintentar").length, 0);
});

test("sin Viator la pestaña por defecto es Cerca; con Viator, la de la ruta", () => {
  assert.equal(pestanaInicial("excursiones", false), "cerca");
  assert.equal(pestanaInicial("excursiones", true), "excursiones");
  assert.equal(pestanaInicial("cerca", true), "cerca");
});
