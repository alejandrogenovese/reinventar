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

export class Recorder extends EventTarget {
  constructor(sessionId) {
    super();
    this.id = sessionId;
    this.meta = store.recMeta(sessionId);
    this.state = "idle";
    this.elapsedMs = this.meta.elapsedMs || 0;
    this.level = 0;
    this.inflight = new Set();
  }

  async open(deviceId) {
    this.close();
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

    this.ctx = new AudioContext();
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
    // Cada MediaRecorder nuevo es una "parte" con su propio header webm.
    const part = Object.keys(this.meta.parts).length;
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
    this._startClock();
    this._setState("recording");
    void wakeLock.acquire();
  }

  pause() { if (this.mr?.state === "recording") { this.mr.pause(); this._stopClock(); this._setState("paused"); } }
  resume() { if (this.mr?.state === "paused") { this.mr.resume(); this._startClock(); this._setState("recording"); } }

  async stop() {
    if (!this.mr || this.mr.state === "inactive") return;
    const done = new Promise((res) => this.mr.addEventListener("stop", () => setTimeout(res, 50), { once: true }));
    this.mr.stop();
    await done;
    await Promise.allSettled([...this.inflight]);
    this._stopClock();
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
  // La sesión no existe o ya cerró, o el pedazo es demasiado grande: no se va a aceptar nunca.
  if (status === 404 || status === 409 || status === 413) return { accion: "descartar" };
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
