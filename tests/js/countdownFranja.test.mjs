// La franja del countdown (node --test): se repinta cada segundo, pero mientras muestre lo mismo solo cambia el texto.
// Rehacerla entera hacía que VoiceOver perdiera el foco, y cada clase reasignada despertaba al banner de estado.
import test from "node:test";
import assert from "node:assert/strict";
import { Nodo } from "./domMinimo.mjs";

const memoria = new Map();
globalThis.localStorage = {
  getItem: (k) => (memoria.has(k) ? memoria.get(k) : null), setItem: (k, v) => memoria.set(k, String(v)), removeItem: (k) => memoria.delete(k),
  key: (i) => [...memoria.keys()][i] ?? null, get length() { return memoria.size; },
};
const crearIntervalo = globalThis.setInterval;
globalThis.setInterval = (...args) => { const t = crearIntervalo(...args); t.unref?.(); return t; };

// La franja de index.html, contando cuántas veces se toca la clase y se rehacen los hijos.
const franja = new Nodo("div");
let clase = "countdown-banner", clasesAsignadas = 0, rehechos = 0;
Object.defineProperty(franja, "className", { get: () => clase, set: (v) => { clase = v; clasesAsignadas++; } });
franja.hidden = true;
const reemplazar = franja.replaceChildren.bind(franja);
franja.replaceChildren = (...hijos) => { rehechos++; reemplazar(...hijos); };
globalThis.document.getElementById = (id) => (id === "countdown-banner" ? franja : null);
globalThis.document.querySelectorAll = () => [];

const { setToken } = await import("../../web/js/api.js");
const { refreshCountdown } = await import("../../web/js/countdown.js");

// Un evento fijado que empieza en 45 min (hora de Las Vegas, -08:00): la franja muestra la cuenta regresiva.
const dateNow = Date.now;
const base = Math.floor(dateNow() / 60_000) * 60_000;
const inicio = new Date(base + 45 * 60_000 - 8 * 3_600_000).toISOString();
const ITEM = { code: "EV1", base: "EV1", kind: "event", title: "Cena", locked: true, day: inicio.slice(0, 10),
  start: inicio.slice(11, 16), end: null, venue: null };
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ days: [{ day: ITEM.day, sessions: [ITEM] }] }) });

const reposo = () => new Promise((r) => setTimeout(r, 20));
const enlace = () => franja.children.find((n) => n.className === "countdown-text");

test.after(() => { Date.now = dateNow; });

test("mientras es lo mismo, cada segundo cambia solo el texto: ni la clase ni los botones", async () => {
  setToken("tok-aaaaaaaaaaaa");
  Date.now = () => base;
  await refreshCountdown({ force: true });
  await reposo();
  assert.equal(franja.hidden, false);
  assert.equal(franja.className, "countdown-banner is-event");
  const primero = enlace();
  const textoAntes = primero.textContent;
  const [clases, hijos] = [clasesAsignadas, rehechos];

  Date.now = () => base + 1000;     // pasó un segundo
  await refreshCountdown();
  await reposo();

  assert.equal(enlace(), primero, "el mismo enlace: el lector de pantalla no pierde el foco");
  assert.notEqual(primero.textContent, textoAntes);
  assert.match(primero.textContent, /^Cena en 44:59/);
  assert.equal(clasesAsignadas, clases, "la clase no se reasigna si el tono es el mismo");
  assert.equal(rehechos, hijos);
});

test("cuando cambia el tono («Salí ya») sí cambian la clase y la franja", async () => {
  const [clases, hijos] = [clasesAsignadas, rehechos];
  memoria.set("ra.alerts.fired", JSON.stringify({ "EV1:leave": 1, "EV1:start": 1 }));   // sin toasts en node
  Date.now = () => base + 30 * 60_000;   // faltan 15 min: hay que salir (20 min de margen sin ubicación)
  await refreshCountdown();
  await reposo();
  assert.equal(franja.className, "countdown-banner is-urgent");
  assert.equal(clasesAsignadas, clases + 1);
  assert.equal(rehechos, hijos + 1);
  assert.match(enlace().textContent, /^Salí ya · Cena/);
});
