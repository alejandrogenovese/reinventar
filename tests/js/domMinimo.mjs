// DOM mínimo compartido por los tests de pantallas: alcanza para armar tarjetas, recorrerlas y tocar botones.
// Se importa antes que el módulo de web/js, porque deja cargados los globales que ese módulo usa al importarse.
export class Nodo {
  constructor(tag) { this.tag = tag; this.nodeType = 1; this.attrs = {}; this.children = []; this.className = ""; this.style = {}; this.on = {}; this.classList = { add: () => {}, toggle: () => {} }; this.dataset = {}; }
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
