// Conversor (#/viaje/conversor): clima, comida, gym, distancia, talles, propina y dólares. Anda sin señal: las cuentas
// están en unidades.js (funciones puras) y la cotización tarjeta es la última que bajó Gastos (gastosCola.js, IndexedDB),
// que se refresca si hay red. Convierte mientras se escribe, ⇄ invierte y recuerda la última pestaña.
// Abajo, «Leer con la cámara» (conversorFoto.js), que sí necesita señal.
import { api } from "./api.js";
import { SeccionFoto } from "./conversorFoto.js";
import { edadCotizacion, guardarMeta, leerMeta, textoEdad } from "./gastosCola.js";
import { Button, Hint, IconText, Tag, h } from "./ui.js";
import {
  ATAJOS_COMIDA, IMPUESTO_CLARK, PARES, PROPINAS, TALLES, UNIDADES, buscarTalle, calcularPropina, discos, formatear,
  parsearNumero, resultadoDe, textoAtajo, tiraClima, usdAArs,
} from "./unidades.js";

const CLAVE_PESTANA = "reinventar.conversor.pestana";
export const PESTANAS = [
  ["clima", "Clima"], ["comida", "Comida"], ["gym", "Gym"], ["distancia", "Distancia"],
  ["talles", "Talles"], ["propina", "Propina"], ["dolar", "US$ → ARS"],
];
const AYUDA_NUMERO = "Escribí un número, por ejemplo 72 o 72,5.";

const usd = (n) => `US$ ${formatear(n, 2)}`;
const ars = (n) => `$ ${formatear(Math.round(n), 0)}`;
const nombre = (u) => UNIDADES[u]?.nombre ?? u;
let ultimoId = 0;
const nuevoId = (prefijo) => `${prefijo}-${++ultimoId}`;

/** La pestaña guardada si es una de las que existen; si no, Clima. */
export const pestanaValida = (guardada) => (PESTANAS.some(([v]) => v === guardada) ? guardada : PESTANAS[0][0]);

function leerPestana() { try { return pestanaValida(localStorage.getItem(CLAVE_PESTANA)); } catch { return PESTANAS[0][0]; } }
function guardarPestana(v) { try { localStorage.setItem(CLAVE_PESTANA, v); } catch {} }

/** Botones con aria-pressed (uno elegido). Devuelve el grupo y una función para repintarlo. */
function Chips(etiqueta, items, esActivo, elegir) {
  const botones = items.map(([valor, texto]) => h("button", { type: "button", class: "ra-chip", "aria-pressed": "false",
    onclick: () => { elegir(valor); pintar(); } }, texto));
  function pintar() {
    botones.forEach((b, i) => {
      const activo = esActivo(items[i][0]);
      b.setAttribute("aria-pressed", String(activo));
      b.classList.toggle("ra-chip-on", activo);
    });
  }
  pintar();
  return h("div", { class: "ra-chips", role: "group", "aria-label": etiqueta }, botones);
}

const Invertir = (onclick) => Button(IconText("invertir", "Invertir"), { "aria-label": "Invertir el sentido (⇄)", onclick });

/** Campo numérico con su resultado debajo. `calcular(texto)` devuelve { resultado, error }. */
function Campo(etiqueta, calcular, { placeholder = "" } = {}) {
  const id = nuevoId("conv");
  const label = h("label", { class: "label", for: id }, etiqueta);
  const input = h("input", { id, type: "text", inputmode: "decimal", autocomplete: "off", placeholder, oninput: () => pintar() });
  const salida = h("output", { for: id, class: "ra-g-grande", "aria-live": "polite" });
  const ayuda = h("p", { class: "caption", role: "status" });
  function pintar() {
    const r = calcular(input.value);
    salida.textContent = r.resultado;
    ayuda.textContent = r.error;
    ayuda.hidden = !r.error;
  }
  pintar();
  return { input, pintar, cambiarEtiqueta: (t) => { label.textContent = t; },
    el: h("div", { class: "stack" }, h("div", { class: "field" }, label, input), salida, ayuda) };
}

/** Conversión de unidades: chips para elegir el par (si hay más de uno), ⇄ y el resultado mientras se escribe. */
function Unidades(pares, extra = null) {
  const estado = { par: 0, invertido: false };
  const sentido = () => (estado.invertido ? [...pares[estado.par]].reverse() : pares[estado.par]);
  const campo = Campo("", (texto) => resultadoDe(texto, ...sentido()));
  function repintar() {
    const [de, a] = sentido();
    campo.cambiarEtiqueta(`${nombre(de)} → ${nombre(a)}`);
    campo.pintar();
  }
  repintar();
  const chips = pares.length > 1
    ? Chips("Unidades", pares.map(([de, a], i) => [i, `${nombre(de)} ↔ ${nombre(a)}`]), (i) => i === estado.par, (i) => { estado.par = i; repintar(); })
    : null;
  return h("div", { class: "stack" }, chips,
    campo.el,
    h("div", { class: "actions" }, Invertir(() => { estado.invertido = !estado.invertido; repintar(); campo.input.focus(); })),
    extra);
}

const Referencia = (titulo, items) => h("section", { class: "stack" },
  h("h2", { class: "label" }, titulo), h("div", { class: "ra-chips" }, items.map(Tag)));

const Clima = () => Unidades(PARES.clima, Referencia("Referencia", tiraClima().map((t) => `${t.f} °F = ${t.c} °C`)));
const Comida = () => Unidades(PARES.comida, Referencia("Atajos", ATAJOS_COMIDA.map(textoAtajo)));
const Gym = () => Unidades(PARES.gym, Referencia("Discos", discos().map((d) => `${d.lb} lb = ${formatear(d.kg, 1)} kg`)));
const Distancia = () => Unidades(PARES.distancia);

const talle = (v) => v.replaceAll(".", ",");  // 9.5 → 9,5, como se escribe acá

function Talles() {
  const estado = { genero: "hombre", tipo: "calzado", desdeUs: true };
  const tabla = () => TALLES[estado.genero][estado.tipo];
  const campo = Campo("", calcular, { placeholder: "Ej.: 9,5 o M" });
  const tipos = h("div");
  function calcular(texto) {
    if (!texto.trim()) return { resultado: "", error: "" };
    const fila = buscarTalle(tabla(), estado.desdeUs ? "us" : "ar", texto);
    if (!fila) {
      const validos = tabla().filas.map((f) => talle(estado.desdeUs ? f.us : f.ar)).join(" · ");
      return { resultado: "", error: `Ese talle no tiene equivalencia en la tabla. Probá con: ${validos}.` };
    }
    const [a, b] = estado.desdeUs ? [`AR ${fila.ar}`, `EU ${fila.eu}`] : [`US ${fila.us}`, `EU ${fila.eu}`];
    return { resultado: talle(`${a} · ${b}`), error: "" };
  }
  function repintar() {
    campo.cambiarEtiqueta(`${tabla().titulo}: ${estado.desdeUs ? "talle US → AR / EU" : "talle AR → US / EU"}`);
    tipos.replaceChildren(Chips("Tipo", Object.entries(TALLES[estado.genero]).map(([k, t]) => [k, t.titulo]),
      (k) => k === estado.tipo, (k) => { estado.tipo = k; repintar(); }));
    campo.pintar();
  }
  const genero = Chips("Para quién", [["hombre", "Hombre"], ["mujer", "Mujer"]], (g) => g === estado.genero,
    (g) => { estado.genero = g; if (!TALLES[g][estado.tipo]) estado.tipo = "calzado"; repintar(); });
  repintar();
  return h("div", { class: "stack" }, genero, tipos, campo.el,
    h("div", { class: "actions" }, Invertir(() => { estado.desdeUs = !estado.desdeUs; repintar(); })),
    Hint("Talles aproximados: cada marca corta distinto. Si podés, probátelo.", { tone: "warn" }));
}

function Propina(cotiz) {
  const estado = { porcentaje: PROPINAS[1] };
  const detalle = h("div", { class: "stack", "aria-live": "polite" });
  const campo = Campo("Subtotal de la cuenta (US$, sin impuesto)", (texto) => {
    detalle.replaceChildren();
    if (!texto.trim()) return { resultado: "", error: "" };
    const cuenta = calcularPropina(parsearNumero(texto), estado.porcentaje);
    if (!cuenta) return { resultado: "", error: AYUDA_NUMERO };
    const pesos = usdAArs(cuenta.total, cotiz.tarjeta());
    detalle.append(
      h("p", { class: "caption" }, `Impuesto (${formatear(IMPUESTO_CLARK, 3)} %): ${usd(cuenta.impuesto)}`),
      h("p", { class: "caption" }, `Propina (${estado.porcentaje} %): ${usd(cuenta.propina)}`),
      h("p", { class: "caption" }, pesos == null ? "En pesos: sin cotización todavía (se baja con señal)." : `En pesos (tarjeta): ${ars(pesos)}`));
    return { resultado: `Total ${usd(cuenta.total)}`, error: "" };
  });
  cotiz.alCambiar(campo.pintar);
  return h("div", { class: "stack" },
    Chips("Propina", PROPINAS.map((p) => [p, `${p} %`]), (p) => p === estado.porcentaje, (p) => { estado.porcentaje = p; campo.pintar(); }),
    campo.el, detalle,
    h("p", { class: "caption" }, "En Las Vegas la propina se calcula sobre el subtotal, antes del impuesto."));
}

function Dolar(cotiz) {
  const estado = { desdeUsd: true };
  const info = h("div", { class: "stack" });
  const campo = Campo("", (texto) => {
    if (!texto.trim()) return { resultado: "", error: "" };
    const n = parsearNumero(texto);
    if (n == null) return { resultado: "", error: AYUDA_NUMERO };
    const tarjeta = cotiz.tarjeta();
    if (!(tarjeta > 0)) return { resultado: "", error: "Sin cotización todavía: se baja cuando haya señal." };
    return { resultado: estado.desdeUsd ? ars(usdAArs(n, tarjeta)) : usd(n / tarjeta), error: "" };
  });
  function repintar() {
    campo.cambiarEtiqueta(estado.desdeUsd ? "Dólares (US$) → pesos" : "Pesos → dólares (US$)");
    const c = cotiz.actual();
    const edad = textoEdad(edadCotizacion(c));
    info.replaceChildren(...[
      h("p", { class: "caption" }, c?.tarjeta > 0 ? `Cotización tarjeta: ${ars(c.tarjeta)} por dólar${edad ? ` · ${edad}` : ""}` : "Sin cotización guardada."),
      c?.es_respaldo ? Hint("No pudimos traer la cotización del día: es un valor de respaldo, aproximado.", { tone: "warn" }) : null,
    ].filter(Boolean));
    campo.pintar();
  }
  cotiz.alCambiar(repintar);
  repintar();
  return h("div", { class: "stack" }, campo.el,
    h("div", { class: "actions" }, Invertir(() => { estado.desdeUsd = !estado.desdeUsd; repintar(); })), info);
}

const VISTAS = { clima: Clima, comida: Comida, gym: Gym, distancia: Distancia, talles: Talles, propina: Propina, dolar: Dolar };

/** La cotización tarjeta: la guardada en el celular al toque y, con señal, la del servidor. */
function Cotizacion() {
  let actual = null;
  const oyentes = new Set();
  const avisar = () => oyentes.forEach((f) => f());
  const cotiz = {
    actual: () => actual,
    tarjeta: () => actual?.tarjeta ?? null,
    alCambiar: (f) => oyentes.add(f),
    limpiar: () => oyentes.clear(),
    async cargar() {
      try { actual = await leerMeta("cotizacion"); avisar(); } catch (e) { console.warn("[conversor] no se pudo leer la cotización guardada", e); }
      if (navigator.onLine === false) return;
      try {
        const nueva = { ...(await api("/api/gastos/cotizacion")), leido_en: Date.now() };
        actual = nueva;
        avisar();
        await guardarMeta("cotizacion", nueva);
      } catch (e) { console.warn("[conversor] no se pudo actualizar la cotización", e); }
    },
  };
  return cotiz;
}

export function viewConversor(view) {
  let pestana = leerPestana();
  const cotiz = Cotizacion();
  const cuerpo = h("div", { class: "stack" });
  function mostrar() {
    cotiz.limpiar();
    cuerpo.replaceChildren(VISTAS[pestana](cotiz));
  }
  const pestanas = Chips("Qué convertir", PESTANAS, (v) => v === pestana, (v) => { pestana = v; guardarPestana(v); mostrar(); });
  mostrar();
  view.append(h("div", { class: "stack-lg" },
    h("div", { class: "stack" }, h("h1", { class: "title" }, "Conversor"),
      h("p", { class: "caption" }, "Anda sin señal. Escribí con coma o con punto.")),
    pestanas, h("section", { class: "ra-card", style: { cursor: "default" } }, cuerpo),
    SeccionFoto(cotiz)));
  void cotiz.cargar();
}

