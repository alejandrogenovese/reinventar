// Pruebas del cliente de la API (node --test): qué ve el usuario cuando no hay red.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { api, ApiError, MSG_SIN_CONEXION } = await import("../../web/js/api.js");

test("sin red, el error dice «Sin conexión» en castellano y no «Failed to fetch»", async () => {
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(api("/api/me"), (e) => e instanceof ApiError && e.status === 0 && e.message === MSG_SIN_CONEXION);
});

test("una cancelación (AbortError) sigue saliendo tal cual: quien llama la ignora", async () => {
  globalThis.fetch = async () => { throw new DOMException("cancelado", "AbortError"); };
  await assert.rejects(api("/api/me"), (e) => e.name === "AbortError");
});

test("los errores del servidor no cambian", async () => {
  globalThis.fetch = async () => ({ ok: false, status: 500, statusText: "Internal", json: async () => ({ detail: "se rompió" }) });
  await assert.rejects(api("/api/me"), (e) => e instanceof ApiError && e.status === 500 && e.message === "se rompió");
});
