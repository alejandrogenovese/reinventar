// Captura de audio + subida en segundo plano.
import { Sessions } from "./api.js";
import * as store from "./store.js";

const TIMESLICE_MS = 10_000;
const MIME = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find(
  (m) => window.MediaRecorder?.isTypeSupported?.(m)
);
const DEVICE_KEY = "reinventar.mic";

export async function listMics() {
  // Los labels solo aparecen después de un permiso concedido.
  const devs = await navigator.mediaDevices.enumerateDevices();
  return devs.filter((d) => d.kind === "audioinput");
}
export function preferredMic() { try { return localStorage.getItem(DEVICE_KEY) || ""; } catch { return ""; } }
export function rememberMic(id) { try { localStorage.setItem(DEVICE_KEY, id); } catch {} }

export function pickDjI(mics) {
  return mics.find((m) => /dji|mic mini|wireless mic/i.test(m.label)) || mics.find((m) => /usb/i.test(m.label));
}

// Lleva la cuenta de por qué el audio está cortado (el micrófono silenciado por el sistema, el AudioContext
// interrumpido). "begin" cuando aparece el primer motivo, "end" cuando se van todos.
export class InterruptionTracker {
  constructor() { this.reasons = new Set(); }
  get active() { return this.reasons.size > 0; }
  add(reason) { const was = this.active; this.reasons.add(reason); return !was ? "begin" : null; }
  remove(reason) { const was = this.active; this.reasons.delete(reason); return was && !this.active ? "end" : null; }
  reset() { this.reasons.clear(); }
}

const RECOVER_DEBOUNCE_MS = 500;  // junta mute/unmute que rebotan para no abrir una parte nueva por cada uno
const MAX_PARTS_SOFT = 190;       // el servidor acepta hasta 200 partes por grabación (MAX_PARTES_POR_GRABACION)

export class Recorder extends EventTarget {
  constructor(sessionId) {
    super();
    this.id = sessionId;
    this.meta = store.recMeta(sessionId);
    this.state = "idle";
    this.elapsedMs = this.meta.elapsedMs || 0;
    this.level = 0;
    this.inflight = new Set();
    this.interrupted = false;  // el sistema cortó el audio (llamada, Siri, bloqueo): no se está grabando nada
    this._tracker = new InterruptionTracker();
    this._tainted = false;     // hubo un corte mientras estaba en pausa: el MediaRecorder en pausa ya no sirve
  }

  async open(deviceId) {
    this.close();
    this.deviceId = deviceId;
    this._tracker.reset();
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        deviceId: deviceId ? { exact: deviceId } : undefined,
        // El DSP del navegador empeora el reconocimiento: la limpieza la hace el DJI.
        echoCancellation: false, noiseSuppression: false, autoGainControl: false,
        channelCount: 1,
      },
    });
    const track = this.stream.getAudioTracks()[0];
    this.deviceLabel = track?.label || "Micrófono";
    if (deviceId) rememberMic(deviceId);
    track.addEventListener("ended", () => this._emit("error", new Error("Se desconectó el micrófono")));
    // iOS silencia el track (mute) cuando entra una llamada, Siri o se bloquea la pantalla, y lo devuelve (unmute).
    track.addEventListener("mute", () => this._signal("mute", true));
    track.addEventListener("unmute", () => this._signal("mute", false));

    // Un AudioContext nuevo nace "suspended" sin gesto del usuario, pero eso no dispara statechange: solo
    // cuenta como corte un cambio posterior. _recover() lo reanuda con resume().
    const ctx = this.ctx = new AudioContext();
    // Safari pasa el AudioContext a "interrupted" en esos mismos casos; Chrome puede dejarlo "suspended".
    // Se ignora el de un contexto viejo (close() lo cierra y avisa "closed" tarde).
    ctx.addEventListener("statechange", () => { if (ctx === this.ctx) this._signal("audiocontext", ctx.state !== "running"); });
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    src.connect(this.analyser);
    const buf = new Float32Array(this.analyser.fftSize);
    const tick = () => {
      this.analyser.getFloatTimeDomainData(buf);
      let sum = 0; for (const v of buf) sum += v * v;
      const db = 20 * Math.log10(Math.sqrt(sum / buf.length) || 1e-8);
      const now = Math.max(0, Math.min(1, (db + 60) / 60)); // -60 dBFS → 0, 0 dBFS → 1
      this.level = Math.max(now, this.level * 0.8); // caída suave para que se lea
      this._emit("level", this.level);
    };
    this.meterTimer = setInterval(tick, 100);
    // Chrome crea el AudioContext suspendido si no hubo un toque del usuario: se reanuda en start().
    this.ctx.resume().catch(() => {});
  }

  start() {
    this.ctx?.resume().catch(() => {});
    if (!this.stream) throw new Error("Primero abrí el micrófono");
    if (!MIME) throw new Error("Este navegador no puede grabar audio comprimido");
    this._startPart();
    this._startClock();
    this._setState("recording");
    void wakeLock.acquire();
  }

  // Cada MediaRecorder nuevo es una "parte" con su propio header webm: así un corte nunca deja audio
  // corrupto ni mezclado con el anterior.
  _startPart() {
    const part = Object.keys(this.meta.parts).length;
    if (part >= MAX_PARTS_SOFT) throw new Error("La grabación se cortó demasiadas veces: terminala y empezá otra");
    this.part = part;
    this.meta.parts[part] = 0;
    store.saveRecMeta(this.id, this.meta);

    this.mr = new MediaRecorder(this.stream, { mimeType: MIME, audioBitsPerSecond: 32000 });
    this.mr.ondataavailable = async (e) => {
      if (!e.data || !e.data.size) return;
      const seq = this.meta.parts[part]++;
      store.saveRecMeta(this.id, this.meta);
      const saving = store.putChunk({ session: this.id, part, seq, blob: e.data });
      this.inflight.add(saving);
      try { await saving; } finally { this.inflight.delete(saving); }
      uploader.kick();
      this._emit("chunk", { part, seq });
    };
    this.mr.onerror = (e) => this._emit("error", e.error || new Error("Error del grabador"));
    this.mr.start(TIMESLICE_MS);
  }

  _stopPart() { try { if (this.mr && this.mr.state !== "inactive") this.mr.stop(); } catch { /* ya estaba cortado */ } }

  // Un motivo de corte apareció o se fue. Mientras graba: se cierra la parte actual y se avisa; al volver
  // el audio, se abre una parte nueva. En pausa: solo se marca para no reanudar un MediaRecorder muerto.
  _signal(reason, active) {
    const ev = active ? this._tracker.add(reason) : this._tracker.remove(reason);
    clearTimeout(this._recoverTimer);
    if (ev === "begin") {
      if (this.state === "paused") this._tainted = true;
      else if (this.state === "recording" && !this.interrupted) this._interrupt(reason);
    } else if (ev === "end" && this.interrupted) {
      this._recoverTimer = setTimeout(() => void this._recover(), RECOVER_DEBOUNCE_MS);
    }
  }

  _interrupt(reason) {
    this._stopPart();  // guarda lo último que hubiera: ya es una parte completa y válida
    this._stopClock();
    this.interrupted = true;
    this._emit("interrupted", { reason });
  }

  // Abre una parte nueva. Si la pista murió (iOS a veces la termina tras una llamada), reabre el micrófono.
  async _recover() {
    if (!this.interrupted) return;
    try {
      if (this.stream?.getAudioTracks()[0]?.readyState !== "live") {
        try { await this.open(this.deviceId); } catch { await this.open(undefined); }
      }
      await this.ctx?.resume();
      if (this.interrupted && this.state === "recording") {
        this._startPart(); this._startClock();
        this.interrupted = false;
        this._emit("resumed");
      }
    } catch (e) {
      // Sin gesto del usuario iOS puede negarse a reanudar: queda avisado y se reintenta tocando Grabar.
      this._emit("error", new Error(`No pude retomar la grabación: ${e.message}. Tocá el botón para seguir.`));
    }
  }

  pause() {
    if (this.state !== "recording") return;
    clearTimeout(this._recoverTimer);
    if (this.interrupted) { this.interrupted = false; this._tainted = true; }  // el reloj ya estaba parado
    else if (this.mr?.state === "recording") { this.mr.pause(); this._stopClock(); }
    else return;
    this._setState("paused");
  }

  // Si hubo un corte durante la pausa, el MediaRecorder pausado ya no sirve: se cierra y arranca una parte nueva.
  resume() {
    if (this.state !== "paused") return;
    if (this._tainted || this._tracker.active || this.mr?.state !== "paused") {
      this._tainted = false;
      this._stopPart();
      this.ctx?.resume().catch(() => {});
      this._startPart();
    } else this.mr.resume();
    this._startClock(); this._setState("recording");
    if (this._tracker.active) this._interrupt("mute");
  }

  async stop() {
    if (!this.mr || ["idle", "stopped"].includes(this.state)) return;
    clearTimeout(this._recoverTimer);
    if (this.mr.state !== "inactive") {
      const done = new Promise((res) => this.mr.addEventListener("stop", () => setTimeout(res, 50), { once: true }));
      this.mr.stop();
      await done;
    }
    await Promise.allSettled([...this.inflight]);
    this._stopClock();
    this.interrupted = false;
    this._setState("stopped");
    wakeLock.release();
  }

  close() {
    clearInterval(this.meterTimer);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.stream = this.ctx = null;
  }

  partsCount() { return { ...this.meta.parts }; }

  _startClock() { this._t0 = performance.now(); this._clock = setInterval(() => this._emit("tick", this.elapsed()), 500); }
  _stopClock() {
    if (this._t0) this.elapsedMs += performance.now() - this._t0;
    this._t0 = null; clearInterval(this._clock);
    this.meta.elapsedMs = this.elapsedMs; store.saveRecMeta(this.id, this.meta);
  }
  elapsed() { return this.elapsedMs + (this._t0 ? performance.now() - this._t0 : 0); }
  _setState(s) { this.state = s; this._emit("state", s); }
  _emit(type, detail) { this.dispatchEvent(new CustomEvent(type, { detail })); }
}

// Mantiene la pantalla encendida mientras graba; se re-pide al volver a la pestaña.
export const wakeLock = {
  lock: null, wanted: false,
  async acquire() {
    this.wanted = true;
    try { this.lock = await navigator.wakeLock?.request("screen"); } catch { /* sin soporte o sin foco */ }
  },
  release() { this.wanted = false; this.lock?.release().catch(() => {}); this.lock = null; },
};
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && wakeLock.wanted) void wakeLock.acquire();
});

// Qué hacer con un pedazo según la respuesta del servidor.
export const MSG_PEDAZO_GRANDE = "Pedazo demasiado grande, no se pudo subir";
export const MSG_PEDAZO_RECHAZADO = "El servidor rechazó un pedazo, no se pudo subir";
export function clasificarFalloDeSubida(status) {
  // La sesión no existe o ya cerró: ese pedazo no se va a aceptar nunca y no hay nada que mostrar.
  if (status === 404 || status === 409) return { accion: "descartar" };
  // El servidor lo rechaza por su contenido: reintentar es inútil y borrarlo perdería audio sin avisar.
  // Queda en la cola marcado con error (y no frena a los demás) hasta que el usuario decida.
  if (status === 413) return { accion: "fallido", mensaje: MSG_PEDAZO_GRANDE };
  if (status === 422) return { accion: "fallido", mensaje: MSG_PEDAZO_RECHAZADO };
  return { accion: "reintentar" };
}

// Sube la cola de IndexedDB: de a un pedazo por vuelta, el más viejo primero, con backoff.
// Un solo loop para toda la app.
export const uploader = new (class extends EventTarget {
  constructor() { super(); this.running = false; this.pending = 0; this.failed = 0; this.failedError = null; this.lastError = null; this.backoff = 1000; }
  kick() { if (!this.running) this._run().catch((e) => { this.lastError = e.message; this._emit(); }); }
  async refresh() { await this._count(); this._emit(); }
  async retryFailed() { await store.retryFailed(); await this.refresh(); this.kick(); }
  async _count() { ({ pending: this.pending, failed: this.failed, failedError: this.failedError } = await store.queueStatus()); }
  async _run() {
    this.running = true;
    try {
      for (;;) {
        const c = await store.nextChunk();
        await this._count(); this._emit();
        if (!c) break;
        if (!navigator.onLine) { this.lastError = "Sin conexión"; this._emit(); break; }
        try {
          await Sessions.putChunk(c.session, c.part, c.seq, c.blob, AbortSignal.timeout?.(60_000));
          await store.deleteChunk(c.session, c.part, c.seq);
          this.lastError = null; this.backoff = 1000;
        } catch (e) {
          const { accion, mensaje } = clasificarFalloDeSubida(e.status);
          if (accion === "descartar") { await store.deleteChunk(c.session, c.part, c.seq); continue; }
          if (accion === "fallido") { await store.markFailed(c.session, c.part, c.seq, mensaje); continue; }
          this.lastError = e.status === 401 ? "Token inválido" : "Reintentando subida";
          this._emit();
          await new Promise((r) => setTimeout(r, this.backoff));
          this.backoff = Math.min(this.backoff * 2, 30_000);
        }
      }
    } finally { this.running = false; this._emit(); }
  }
  // "error" es lo que se muestra: un problema de red pasajero, o si no, el de los pedazos que quedaron fallidos.
  _emit() { this.dispatchEvent(new CustomEvent("change", { detail: { pending: this.pending, failed: this.failed, error: this.lastError || (this.failed ? this.failedError : null) } })); }
})();
window.addEventListener("online", () => uploader.kick());
setInterval(() => uploader.kick(), 30_000);
