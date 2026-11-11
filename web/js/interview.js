// Itinerario guiado, paso 1: la entrevista ("Te conocemos"), una pregunta por pantalla, y la ficha que arma la IA.
import { Interview } from "./api.js";
import { icon } from "./icons.js";
import { Button, h, toast } from "./ui.js";

const MIN_DIA_A_DIA = 80;   // mismos mínimos que app/interview.py
const MIN_DESAFIO = 60;
const INDUSTRIAS = ["banca", "retail", "salud", "gobierno", "tech", "otra"];
const ANIOS = ["0-2", "3-5", "6-10", "+10"];
const ORIGENES = ["desarrollo", "infra/ops", "datos", "seguridad", "negocio", "otro"];
const NIVELES = [[200, "200 · intro"], [300, "300 · avanzado"], [400, "400 · experto"], [500, "500 · lo más profundo"]];
const FORMATOS = ["Breakout session", "Chalk talk", "Workshop", "Builders' session", "Code talk", "Lightning talk", "Keynote"];
const OBJETIVOS = ["aprender algo puntual", "ver el roadmap", "casos de clientes", "networking", "conocer proveedores"];
const CHARLAS_POR_DIA = [["3-4", "3 a 4"], ["5-6", "5 a 6"], ["todas", "Todas las que entren"]];

// --- piezas de formulario --------------------------------------------------------------------

/** Chips para elegir una (single) o varias opciones. get() devuelve el valor o la lista. */
function Choice(options, { multi = false, value } = {}) {
  const chosen = new Set(multi ? value || [] : value != null ? [value] : []);
  const wrap = h("div", { class: "ra-chips", role: multi ? "group" : "radiogroup" });
  const paint = () => wrap.replaceChildren(...options.map(([v, label]) => {
    const on = chosen.has(v);
    return h("button", { type: "button", class: `ra-chip${on ? " ra-chip-on" : ""}`, "aria-pressed": String(on), onclick: () => {
      if (multi) on ? chosen.delete(v) : chosen.add(v);
      else { chosen.clear(); chosen.add(v); }
      paint();
    } }, label);
  }));
  paint();
  wrap.get = () => (multi ? options.map(([v]) => v).filter((v) => chosen.has(v)) : [...chosen][0]);
  return wrap;
}
const pairs = (xs) => xs.map((x) => [x, x]);

// Grabar una respuesta con la voz: el servidor la pasa a texto (en castellano) y se suma al campo para revisarla.
// Mientras graba se ve una barra compacta (punto rojo, tiempo y nivel del micrófono), con el mismo lenguaje que la
// pantalla de grabar charlas: que no quede duda de que está escuchando.
const VOICE_MIME = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]
  .find((m) => window.MediaRecorder?.isTypeSupported?.(m));
const VOICE_BARS = 5;
const VOICE_GAIN = 4;  // la voz a un metro llega baja: se amplifica para que las barras se muevan

const mmss = (ms) => { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

/** Nivel del micrófono (0 a 1) leído del stream, cada cuadro; devuelve la función para cortarlo. */
function listenLevel(stream, onLevel) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return () => {};
  const ctx = new Ctx();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 256;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const data = new Uint8Array(analyser.fftSize);
  let raf = 0;
  const loop = () => {
    analyser.getByteTimeDomainData(data);
    const rms = Math.sqrt(data.reduce((acc, v) => acc + ((v - 128) / 128) ** 2, 0) / data.length);
    onLevel(Math.min(1, rms * VOICE_GAIN));
    raf = requestAnimationFrame(loop);
  };
  loop();
  return () => { cancelAnimationFrame(raf); void ctx.close(); };
}

function VoiceButton(textarea) {
  if (!VOICE_MIME || !navigator.mediaDevices?.getUserMedia) return null;
  let rec = null, cancelled = false, stopLevel = () => {}, clock = 0;
  const wrap = h("div", { class: "ra-voice" });

  const idle = () => wrap.replaceChildren(
    h("button", { type: "button", class: "ra-voice-start", onclick: start }, icon("grabar", 18), "Responder con la voz"));

  function recording() {
    const time = h("span", { class: "ra-voice-time", "aria-live": "off" }, "0:00");
    const bars = Array.from({ length: VOICE_BARS }, () => h("span"));
    const t0 = Date.now();
    clock = setInterval(() => { time.textContent = mmss(Date.now() - t0); }, 250);
    wrap.replaceChildren(h("div", { class: "ra-voicebar is-recording", role: "status", "aria-label": "Grabando tu respuesta" },
      h("span", { class: "ra-voice-dot", "aria-hidden": "true" }),
      h("span", { class: "ra-voice-word" }, "Grabando"), time,
      h("span", { class: "ra-voice-level", "aria-hidden": "true" }, bars),
      h("button", { type: "button", class: "ra-voice-cancel", onclick: () => { cancelled = true; rec?.stop(); } }, "Cancelar"),
      h("button", { type: "button", class: "ra-voice-stop", "aria-label": "Terminar y pasar a texto", onclick: () => rec?.stop() },
        h("span", { class: "ra-voice-stop-glyph", "aria-hidden": "true" }))));
    // Cada barra toma el nivel con un peso distinto: se ve como una onda y no como cinco barras iguales.
    return (level) => bars.forEach((b, i) => {
      const peso = 0.55 + 0.45 * Math.abs(Math.sin(Date.now() / 140 + i * 1.3));
      b.style.transform = `scaleY(${Math.max(0.18, level * peso)})`;
    });
  }

  const transcribing = () => wrap.replaceChildren(h("div", { class: "ra-voicebar is-busy", role: "status" },
    h("span", { class: "ra-voice-spinner", "aria-hidden": "true" }), h("span", { class: "ra-voice-word" }, "Pasando a texto…")));

  async function start() {
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { toast("No pude usar el micrófono: revisá el permiso."); return; }
    const parts = [];
    cancelled = false;
    rec = new MediaRecorder(stream, { mimeType: VOICE_MIME });
    rec.ondataavailable = (e) => e.data.size && parts.push(e.data);
    rec.onstop = async () => {
      clearInterval(clock);
      stopLevel();
      stream.getTracks().forEach((t) => t.stop());
      rec = null;
      if (cancelled) { idle(); return; }
      transcribing();
      try {
        const { texto } = await Interview.voice(new Blob(parts, { type: VOICE_MIME.split(";")[0] }));
        textarea.value = [textarea.value.trim(), texto].filter(Boolean).join(" ");
        textarea.dispatchEvent(new Event("input"));
      } catch (err) { toast(err.message); }
      idle();
    };
    stopLevel = listenLevel(stream, recording());
    rec.start();
  }

  idle();
  return wrap;
}

function LongText(value, { min = 0, placeholder = "" } = {}) {
  const ta = h("textarea", { rows: "5", maxlength: "2000", placeholder });
  ta.value = value || "";
  const count = h("p", { class: "caption", "aria-live": "polite" });
  const update = () => { count.textContent = min ? `${ta.value.trim().length} / ${min} caracteres como mínimo` : ""; };
  ta.addEventListener("input", update);
  update();
  const el = h("div", { class: "stack" }, ta, count, VoiceButton(ta));
  el.get = () => ta.value.trim();
  return el;
}

const field = (label, control) => h("div", { class: "field" }, h("span", { class: "label" }, label), control);

// --- las 10 preguntas (mismas claves que app/interview.py) -------------------------------------

const STEPS = [
  { key: "rol", title: "¿Cuál es tu rol y dónde trabajás?", hint: "Ej: Líder de Arquitectura de Datos en un banco.",
    build(v = {}) {
      const texto = h("input", { maxlength: "200", value: v.texto || "", placeholder: "Tu rol" });
      const industria = Choice(pairs(INDUSTRIAS), { value: v.industria });
      const el = h("div", { class: "stack" }, texto, field("Industria", industria));
      el.get = () => ({ texto: texto.value.trim(), industria: industria.get() });
      el.check = (x) => (x.texto.length < 2 ? "Contanos tu rol." : !x.industria ? "Elegí la industria." : null);
      return el;
    } },
  { key: "dia_a_dia", title: "¿Qué hacés en tu día a día?", hint: "Cuanto más concreto, mejores recomendaciones.",
    build(v) {
      const el = LongText(v, { min: MIN_DIA_A_DIA, placeholder: "Ej: lidero un equipo de arquitectos, definimos estándares y revisamos diseños de la migración al lakehouse." });
      el.check = (x) => (x.length < MIN_DIA_A_DIA ? `Contanos un poco más (al menos ${MIN_DIA_A_DIA} caracteres).` : null);
      return el;
    } },
  { key: "equipo", title: "¿Liderás un equipo?",
    build(v = {}) {
      const lidera = Choice([[false, "No"], [true, "Sí"]], { value: v.lidera });
      const personas = h("input", { type: "number", min: "1", max: "1000", inputmode: "numeric", value: v.personas || "", placeholder: "Cuántas personas" });
      const perfiles = h("input", { maxlength: "300", value: v.perfiles || "", placeholder: "Qué perfiles (ej: arquitectos de datos)" });
      const el = h("div", { class: "stack" }, lidera, personas, perfiles);
      el.get = () => ({ lidera: lidera.get(), personas: personas.value ? Number(personas.value) : null, perfiles: perfiles.value.trim() });
      el.check = (x) => (x.lidera == null ? "Elegí una opción." : x.lidera && !x.personas ? "¿Cuántas personas?" : null);
      return el;
    } },
  { key: "desafio", title: "¿Cuál es tu desafío principal hoy?", hint: "Lo que te gustaría resolver o destrabar en re:Invent.",
    build(v) {
      const el = LongText(v, { min: MIN_DESAFIO, placeholder: "Ej: \"migrar el DW a lakehouse sin frenar reportes\", \"llevar agentes a producción\"." });
      el.check = (x) => (x.length < MIN_DESAFIO ? `Contanos un poco más (al menos ${MIN_DESAFIO} caracteres).` : null);
      return el;
    } },
  { key: "trayectoria", title: "¿Cuál es tu trayectoria?", hint: "Años en la industria y de dónde venís.",
    build(v = {}) {
      const anios = Choice(ANIOS.map((a) => [a, `${a} años`]), { value: v.anios });
      const origen = Choice(pairs(ORIGENES), { multi: true, value: v.origen });
      const el = h("div", { class: "stack" }, field("Años", anios), field("Venís de", origen));
      el.get = () => ({ anios: anios.get(), origen: origen.get() });
      el.check = (x) => (!x.anios ? "Elegí los años." : !x.origen.length ? "Elegí de dónde venís." : null);
      return el;
    } },
  { key: "nivel", title: "¿Qué tan técnico querés que sea el contenido?",
    build(v = {}) {
      const niveles = Choice(NIVELES, { multi: true, value: v.niveles });
      const formatos = Choice(pairs(FORMATOS), { multi: true, value: v.formatos });
      const el = h("div", { class: "stack" }, field("Nivel", niveles), field("Formatos que preferís (opcional)", formatos));
      el.get = () => ({ niveles: niveles.get(), formatos: formatos.get() });
      el.check = (x) => (!x.niveles.length ? "Elegí al menos un nivel." : null);
      return el;
    } },
  { key: "tecnologias", title: "¿Qué usan hoy?", hint: "Servicios de AWS y otras tecnologías, separados por coma.",
    build(v = []) {
      const input = h("input", { maxlength: "1500", value: v.join(", "), placeholder: "Ej: Amazon Neptune, Lake Formation, dbt, Iceberg" });
      const el = h("div", { class: "stack" }, input);
      el.get = () => [...new Set(input.value.split(",").map((x) => x.trim().slice(0, 80)).filter(Boolean))].slice(0, 40);
      el.check = (x) => (!x.length ? "Nombrá al menos una." : null);
      return el;
    } },
  { key: "objetivos", title: "¿Qué te querés llevar de re:Invent?",
    build(v) {
      const el = Choice(pairs(OBJETIVOS), { multi: true, value: v });
      el.check = (x) => (!x.length ? "Elegí al menos uno." : null);
      return el;
    } },
  { key: "evitar", title: "¿Algo que quieras evitar?", hint: "Opcional. Ej: \"nada de intro a IA\", \"no me interesa marketing\".", optional: true,
    build(v) { const el = LongText(v); el.check = () => null; return el; } },
  { key: "ritmo", title: "¿Cómo te gusta el ritmo del día?", optional: true,
    build(v = {}) {
      const charlas = Choice(CHARLAS_POR_DIA, { value: v.charlas_por_dia || "5-6" });
      const almuerzo = h("input", { type: "checkbox", id: "almuerzo", checked: v.almuerzo ?? true });
      const noche = h("input", { type: "checkbox", id: "noche", checked: v.eventos_noche ?? true });
      const el = h("div", { class: "stack" }, field("Charlas por día", charlas),
        h("label", { class: "ra-check", for: "almuerzo" }, almuerzo, " Reservar un rato para almorzar"),
        h("label", { class: "ra-check", for: "noche" }, noche, " Sugerirme eventos de networking a la noche"));
      el.get = () => ({ charlas_por_dia: charlas.get(), almuerzo: almuerzo.checked, eventos_noche: noche.checked });
      el.check = () => null;
      return el;
    } },
];

// --- pantallas ---------------------------------------------------------------------------------

function Progress(i) {
  return h("div", { class: "ra-progress", role: "progressbar", "aria-valuemin": "1", "aria-valuemax": String(STEPS.length), "aria-valuenow": String(i + 1) },
    h("span", { class: "caption" }, `${i + 1} de ${STEPS.length}`),
    h("div", { class: "ra-progress-track" }, h("div", { class: "ra-progress-fill", style: { width: `${((i + 1) / STEPS.length) * 100}%` } })));
}

export async function viewEntrevista(view) {
  const estado = await Interview.get();
  const respuestas = { ...estado.respuestas };
  const firstMissing = STEPS.findIndex((s) => estado.faltan.includes(s.key));
  let i = estado.faltan.length && firstMissing >= 0 ? firstMissing : 0;

  function paint() {
    const step = STEPS[i];
    const control = step.build(respuestas[step.key]);
    const error = h("p", { class: "notice err", role: "alert", hidden: true });
    const next = Button(i === STEPS.length - 1 ? "Terminar" : "Siguiente →", { variant: "primary", onclick: async () => {
      const value = control.get();
      const problem = control.check(value);
      if (problem) { error.textContent = problem; error.hidden = false; return; }
      next.disabled = true;
      try {
        const empty = step.optional && (value === "" || value == null);
        const { faltan } = await Interview.save(empty ? {} : { [step.key]: value });
        if (!empty) respuestas[step.key] = value;
        if (i < STEPS.length - 1) { i += 1; paint(); return; }
        const pendiente = STEPS.findIndex((s) => faltan.includes(s.key));
        if (pendiente >= 0) { i = pendiente; paint(); toast("Te falta completar esta."); return; }
        await viewRepreguntas(view);
      } catch (err) { error.textContent = err.message; error.hidden = false; next.disabled = false; }
    } });
    view.replaceChildren(h("div", { class: "stack-lg ra-interview" },
      h("header", { class: "stack" }, h("p", { class: "label" }, "Te conocemos"), Progress(i)),
      h("h1", { class: "title" }, step.title),
      step.hint ? h("p", { class: "caption" }, step.hint) : null,
      control, error,
      h("div", { class: "actions" },
        i > 0 ? Button("← Atrás", { onclick: () => { i -= 1; paint(); } }) : null,
        next)));
    view.querySelector("input, textarea")?.focus();
  }
  paint();
}

async function viewRepreguntas(view) {
  view.replaceChildren(h("p", { class: "caption" }, "Pensando si hace falta preguntarte algo más…"));
  let repreguntas = [];
  try { ({ repreguntas } = await Interview.followups()); } catch (err) { toast(err.message); }
  if (!repreguntas.length) { await armarFicha(view); return; }
  const campos = repreguntas.map((r) => ({ pregunta: r.pregunta, control: LongText(r.respuesta) }));
  view.replaceChildren(h("div", { class: "stack-lg ra-interview" },
    h("p", { class: "label" }, "Te conocemos"),
    h("h1", { class: "title" }, campos.length === 1 ? "Una pregunta más" : "Dos preguntas más"),
    h("p", { class: "caption" }, "Son opcionales, pero mejoran mucho las recomendaciones."),
    campos.map((c) => h("div", { class: "field" }, h("p", { class: "ra-followup" }, c.pregunta), c.control)),
    h("div", { class: "actions" }, Button("Armar mi ficha →", { variant: "primary", onclick: async (e) => {
      e.target.disabled = true;
      const respondidas = campos.map((c) => ({ pregunta: c.pregunta, respuesta: c.control.get() }));
      try { await Interview.save({ repreguntas: respondidas }); await armarFicha(view); }
      catch (err) { toast(err.message); e.target.disabled = false; }
    } }))));
}

async function armarFicha(view) {
  view.replaceChildren(h("p", { class: "caption", role: "status" }, "Armando tu ficha…"));
  try {
    const { ficha } = await Interview.createFicha();
    paintFicha(view, ficha);
  } catch (err) {
    view.replaceChildren(h("div", { class: "stack" }, h("p", { class: "notice err" }, err.message),
      Button("Probar de nuevo", { variant: "primary", onclick: () => armarFicha(view) })));
  }
}

const dots = (peso) => "●".repeat(peso) + "○".repeat(3 - peso);

/** La ficha para revisar: el resumen se edita, el peso de cada prioridad cambia al tocarlo y se pueden sacar. */
function paintFicha(view, ficha) {
  const draft = structuredClone(ficha);
  let dirty = false;
  const resumen = h("textarea", { rows: "5", maxlength: "1500", oninput: () => { dirty = true; } });
  resumen.value = draft.resumen;
  const prioridades = h("ul", { class: "ra-priorities" });
  const paintPrioridades = () => prioridades.replaceChildren(...draft.prioridades.map((p, idx) => h("li", {},
    h("button", { type: "button", class: "ra-dots", "aria-label": `Importancia ${p.peso} de 3: tocá para cambiarla`, onclick: () => {
      p.peso = (p.peso % 3) + 1; dirty = true; paintPrioridades();
    } }, dots(p.peso)),
    h("span", {}, h("strong", {}, p.tema), p.claves.length ? h("span", { class: "caption" }, ` (${p.claves.join(", ")})`) : null),
    draft.prioridades.length > 1 ? h("button", { type: "button", class: "ra-more", "aria-label": `Sacar ${p.tema}`, onclick: () => {
      draft.prioridades.splice(idx, 1); dirty = true; paintPrioridades();
    } }, "✕") : null)));
  paintPrioridades();

  view.replaceChildren(h("div", { class: "stack-lg ra-interview" },
    h("p", { class: "label" }, "Tu ficha"),
    h("h1", { class: "title" }, "¿Es así?"),
    field("Resumen", resumen),
    field("Prioridades (tocá ●●○ para cambiar la importancia)", prioridades),
    h("p", { class: "caption" }, `Nivel ${draft.nivel.join("-")}`, draft.formatos.length ? ` · prefiere ${draft.formatos.join(", ")}` : "",
      draft.evitar.length ? ` · evita: ${draft.evitar.join(", ")}` : ""),
    h("div", { class: "actions" },
      Button("✎ Cambiar respuestas", { onclick: () => (location.hash = "#/itinerario/entrevista") }),
      Button("Está bien, sigamos →", { variant: "primary", onclick: async (e) => {
        e.target.disabled = true;
        try {
          if (dirty) await Interview.editFicha({ ...draft, resumen: resumen.value.trim() || draft.resumen });
          location.hash = "#/itinerario/armar";
        } catch (err) { toast(err.message); e.target.disabled = false; }
      } }))));
}

export async function viewFicha(view) {
  const { ficha } = await Interview.get();
  if (!ficha) { location.hash = "#/itinerario/entrevista"; return; }
  paintFicha(view, ficha);
}
