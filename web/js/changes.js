// Avisos de cambios sobre lo que tenés en el itinerario (AWS movió una charla, cambió el horario, la dio de baja,
// un evento se llenó). Se muestran en una franja arriba hasta que tocás "Entendido".
import { Itinerary, getToken } from "./api.js";
import { Button, h, toast } from "./ui.js";

const REFRESH_MS = 60_000;
let fetchedAt = 0;
let pending = [];

function paint() {
  const bar = document.getElementById("changes-banner");
  if (!bar) return;
  bar.hidden = !pending.length;
  if (!pending.length) return;
  const first = pending[0];
  const more = pending.length > 1 ? ` (y ${pending.length - 1} aviso${pending.length > 2 ? "s" : ""} más)` : "";
  bar.replaceChildren(
    h("p", {}, `⚠ ${first.messages.join(" ")}${more}`),
    Button("Entendido", { onclick: async () => {
      try { ({ changes: pending } = await Itinerary.ackChanges([first.code])); paint(); } catch (err) { toast(err.message); }
    } }));
}

export async function refreshChanges({ force = false } = {}) {
  if (!getToken()) { pending = []; paint(); return; }
  if (!force && Date.now() - fetchedAt < REFRESH_MS) { paint(); return; }
  try { ({ changes: pending } = await Itinerary.changes()); fetchedAt = Date.now(); } catch { return; }
  paint();
}
