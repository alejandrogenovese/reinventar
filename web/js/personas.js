// «Personas que conocí» (#/viaje/personas): la libreta privada de networking (app/personas.py). La lista tiene copia sin
// señal (lastgood.js) y lo que se carga, edita o borra sin señal queda en la cola (personasCola.js) y se sube solo al
// volver la red. Cada persona tiene su id generado en el teléfono: reenviar no duplica.
import { Itinerary, api, apiConUltimaCopia, duenoDeCopias, sinServicio } from "./api.js";
import { icon } from "./icons.js";
import { horaCorta, staleAt } from "./lastgood.js";
import { LARGOS, aDatos, aVCard, aplicarCola, encolar, filtrar, guardarCola, leerCola, linkedinValido, vaciarCola, validarPersona } from "./personasCola.js";
import { Button, Hint, h, mensajeError, toast, withUndo } from "./ui.js";

const RUTA = "/api/personas";
export const Personas = {
  list: () => apiConUltimaCopia(RUTA),
  save: (id, datos) => api(`${RUTA}/${encodeURIComponent(id)}`, { method: "PUT", json: datos }),
  remove: (id) => api(`${RUTA}/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

const enviar = (op) => (op.op === "put" ? Personas.save(op.id, op.datos) : Personas.remove(op.id));

/** Sube lo que haya en la cola. Devuelve cuántas quedaron sin subir. Avisa (toast) de las que el servidor rechazó. */
export async function subirCola() {
  const dueno = await duenoDeCopias();
  const cola = leerCola(dueno);
  if (!cola.length) return 0;
  const r = await vaciarCola(cola, enviar);
  // Lo que se encoló mientras tanto (otra pestaña) se respeta: se sacan solo las operaciones que ya se resolvieron.
  const resueltas = new Set(cola.slice(0, cola.length - r.cola.length));
  guardarCola(dueno, leerCola(dueno).filter((op) => ![...resueltas].some((x) => x.id === op.id && x.at === op.at)));
  for (const { op, error } of r.rechazados) toast(`No se pudo guardar «${op.datos?.nombre ?? "una persona"}»: ${mensajeError(error)}`);
  return r.cola.length;
}

const conCharla = (p) => [p.donde, p.charla_titulo].filter(Boolean).join(" · ");

function Tarjeta(p, { onEditar, onBorrar }) {
  const sub = [p.cargo, p.empresa].filter(Boolean).join(" · ");
  const donde = conCharla(p);
  return h("li", { class: "ra-card stack", id: `persona-${p.id}` },
    h("div", { class: "ra-card-top" },
      h("h2", { class: "ra-card-title" }, p.nombre),
      p.pendiente ? h("span", { class: "ra-tag" }, "Sin subir") : null),
    sub ? h("p", {}, sub) : null,
    donde ? h("p", { class: "caption" }, `Nos conocimos: ${donde}`) : null,
    p.nota ? h("p", { class: "caption", style: { whiteSpace: "pre-line" } }, p.nota) : null,
    h("div", { class: "actions" },
      linkedinValido(p.linkedin)
        ? h("a", { class: "ra-btn ra-btn-secondary ra-icotext", href: p.linkedin, target: "_blank", rel: "noopener noreferrer",
          "aria-label": `Abrir el LinkedIn de ${p.nombre}` }, icon("externo", 16), h("span", {}, "Abrir LinkedIn"))
        : null,
      Button("Editar", { variant: "ghost", "aria-label": `Editar a ${p.nombre}`, onclick: onEditar }),
      h("button", { type: "button", class: "iconbtn", "aria-label": `Borrar a ${p.nombre}`, title: "Borrar", onclick: onBorrar }, icon("borrar", 20))));
}

const campo = (id, etiqueta, input) => h("div", { class: "field" }, h("label", { class: "label", for: id }, etiqueta), input);

/** Las charlas del itinerario para elegir dónde se conocieron (sin señal, la última copia; si no hay, ninguna). */
async function charlasDelItinerario() {
  try {
    const { days = [] } = await Itinerary.get();
    return days.flatMap((d) => d.sessions ?? []).filter((s) => s.code && s.title && (s.kind ?? "talk") === "talk");
  } catch { return []; }
}

/** El mismo formulario para agregar (sin `p`) y editar (con `p`). */
function FormPersona({ p = null, charlas, onGuardar, onCancelar = null }) {
  const suf = p ? p.id : "nueva";
  const input = (k, attrs = {}) => h("input", { id: `per-${k}-${suf}`, maxlength: LARGOS[k], value: p?.[k] ?? "", autocomplete: "off", ...attrs });
  const nombre = input("nombre", { required: true });
  const empresa = input("empresa");
  const cargo = input("cargo");
  const linkedin = input("linkedin", { type: "url", inputmode: "url", placeholder: "https://www.linkedin.com/in/…" });
  const donde = input("donde", { placeholder: "Ej.: en la fila del keynote del martes" });
  const nota = h("textarea", { id: `per-nota-${suf}`, rows: 3, maxlength: LARGOS.nota }, p?.nota ?? "");
  const charla = h("select", { id: `per-charla-${suf}` },
    h("option", { value: "" }, "Ninguna"),
    charlas.map((s) => h("option", { value: s.code, selected: p?.charla_code === s.code }, s.title)));
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    const elegida = charlas.find((s) => s.code === charla.value);
    const datos = { nombre: nombre.value.trim(), empresa: empresa.value.trim(), cargo: cargo.value.trim(), linkedin: linkedin.value.trim(),
      donde: donde.value.trim(), nota: nota.value.trim(),
      // Si la charla ya no está en el itinerario se conserva la que tenía.
      charla_code: elegida?.code ?? (charla.value ? p?.charla_code ?? null : null),
      charla_titulo: elegida?.title.slice(0, LARGOS.charla_titulo) ?? (charla.value ? p?.charla_titulo ?? "" : "") };
    const error = validarPersona(datos);
    if (error) { toast(error); return; }
    await onGuardar(datos);
  } },
  campo(nombre.id, "Nombre", nombre),
  campo(empresa.id, "Empresa (opcional)", empresa),
  campo(cargo.id, "Cargo (opcional)", cargo),
  campo(linkedin.id, "LinkedIn (opcional)", linkedin),
  campo(donde.id, "Dónde o cuándo se conocieron (opcional)", donde),
  charlas.length ? campo(charla.id, "En qué charla (opcional)", charla) : null,
  campo(nota.id, "Nota (opcional)", nota),
  h("div", { class: "actions" },
    h("button", { type: "submit", class: "ra-btn ra-btn-primary" }, p ? "Guardar" : "Agregar"),
    onCancelar ? Button("Cancelar", { onclick: onCancelar }) : null));
  return form;
}

function descargarVCard(personas) {
  const blob = new Blob([aVCard(personas)], { type: "text/vcard" });
  const url = URL.createObjectURL(blob);
  const enlace = h("a", { href: url, download: "personas-reinvent.vcf" });
  document.body.append(enlace);
  enlace.click();
  enlace.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

// Al volver la red se sube lo pendiente aunque la pantalla ya no esté abierta (una sola vez por carga de la app).
let escuchandoRed = false;
function subirAlVolverLaRed() {
  if (escuchandoRed) return;
  escuchandoRed = true;
  window.addEventListener("online", () => { void subirCola().catch(() => {}); });
}

export async function viewPersonas(view) {
  subirAlVolverLaRed();
  const raiz = h("div");
  view.append(raiz);
  const dueno = await duenoDeCopias();
  await subirCola().catch(() => {});
  let data;
  try { data = await Personas.list(); } catch (err) {
    if (!raiz.isConnected) return;
    const texto = sinServicio(err) ? "Sin señal y sin una copia de tus contactos en este teléfono." : mensajeError(err);
    raiz.replaceChildren(h("div", { class: "stack-lg" }, h("h1", { class: "title" }, "Personas que conocí"), Hint(texto, { tone: "warn" })));
    return;
  }
  const charlas = await charlasDelItinerario();
  if (!raiz.isConnected) return;
  let servidor = data.personas ?? [];
  let copiaDe = staleAt(data);
  let q = "";
  let ocultas = new Set();
  const visibles = () => aplicarCola(servidor, leerCola(dueno)).filter((p) => !ocultas.has(p.id));

  const recargar = async () => {
    const quedan = await subirCola().catch(() => 1);
    try { const d = await Personas.list(); servidor = d.personas ?? []; copiaDe = staleAt(d); } catch { /* sigue con lo que había */ }
    return quedan;
  };

  /** Encola, intenta subir y repinta. Sin señal queda guardado en el teléfono. */
  const cambiar = async (op, ok) => {
    if (!guardarCola(dueno, encolar(leerCola(dueno), op))) { toast("No se pudo guardar en este teléfono."); return false; }
    const quedan = await recargar();
    if (quedan) toast("Guardado en el teléfono: se sube cuando vuelva la señal.");
    else if (ok) toast(ok);
    paint();
    return true;
  };

  const ahora = () => new Date().toISOString();
  const agregar = async (datos) => {
    if (await cambiar({ op: "put", id: crypto.randomUUID(), datos: aDatos(datos), at: ahora() }, "Persona agregada.")) formNuevo.reset();
  };
  const editar = (p) => () => {
    const form = FormPersona({ p, charlas, onCancelar: () => paint(),
      onGuardar: (datos) => cambiar({ op: "put", id: p.id, datos: aDatos(datos), at: ahora() }, "Cambios guardados.") });
    document.getElementById(`persona-${p.id}`)?.replaceChildren(form);
    form.querySelector("input")?.focus();
  };
  // Mientras corre el «Deshacer» la persona solo se oculta; el borrado se encola cuando vence el aviso.
  const borrar = (p) => () => withUndo(`Borraste a ${p.nombre}.`, {
    apply: () => { ocultas = new Set([...ocultas, p.id]); paint(); },
    commit: () => void cambiar({ op: "del", id: p.id, at: ahora() }, null)
      .finally(() => { ocultas = new Set([...ocultas].filter((id) => id !== p.id)); }),
    undo: () => { ocultas = new Set([...ocultas].filter((id) => id !== p.id)); paint(); },
  });

  const formNuevo = FormPersona({ charlas, onGuardar: agregar });
  const buscador = h("input", { type: "search", id: "per-buscar", placeholder: "Nombre, empresa, charla…", autocomplete: "off",
    oninput: (e) => { q = e.target.value; pintarLista(); } });
  const lista = h("div");

  function pintarLista() {
    const todas = visibles();
    const encontradas = filtrar(todas, q);
    lista.replaceChildren(!todas.length
      ? h("p", { class: "caption" }, "Todavía no cargaste a nadie. Agregá la primera persona acá abajo.")
      : encontradas.length
        ? h("ul", { class: "stack", "aria-label": "Personas que conocí", style: { listStyle: "none", padding: 0 } },
          encontradas.map((p) => Tarjeta(p, { onEditar: editar(p), onBorrar: borrar(p) })))
        : h("p", { class: "caption", role: "status" }, "Nadie coincide con esa búsqueda."));
  }

  function paint() {
    if (!raiz.isConnected) return;
    const todas = visibles();
    raiz.replaceChildren(h("div", { class: "stack-lg" },
      h("a", { class: "ra-btn ra-btn-ghost ra-back", href: "#/viaje" }, icon("volver", 16), h("span", {}, "Viaje")),
      h("h1", { class: "title" }, "Personas que conocí"),
      h("p", { class: "caption" }, "Tu libreta de contactos de re:Invent. Es privada: nadie más del grupo la ve."),
      copiaDe !== null ? Hint(`Sin señal: ves la copia de las ${horaCorta(copiaDe)}. Lo que cargues se sube cuando vuelva la señal.`, { tone: "warn" }) : null,
      todas.length ? campo(buscador.id, "Buscar", buscador) : null,
      lista,
      todas.length ? h("div", { class: "actions" }, Button("Exportar a contactos (vCard)", { onclick: () => descargarVCard(todas) })) : null,
      h("section", { class: "stack" }, h("h2", { class: "label" }, "Agregar una persona"), formNuevo)));
    pintarLista();
  }
  paint();
}
