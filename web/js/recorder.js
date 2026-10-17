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
    wakeLock.acquire();
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
  if (document.visibilityState === "visible" && wakeLock.wanted) wakeLock.acquire();
});

// Sube la cola de IndexedDB en orden, con backoff. Un solo loop para toda la app.
export const uploader = new (class extends EventTarget {
  constructor() { super(); this.running = false; this.pending = 0; this.lastError = null; this.backoff = 1000; }
  kick() { if (!this.running) this._run(); }
  async refresh() { this.pending = (await store.allChunks()).length; this._emit(); }
  async _run() {
    this.running = true;
    try {
      for (;;) {
        const all = (await store.allChunks()).sort((a, b) => a.at - b.at);
        this.pending = all.length; this._emit();
        if (!all.length) break;
        if (!navigator.onLine) { this.lastError = "Sin conexión"; this._emit(); break; }
        const c = all[0];
        try {
          await Sessions.putChunk(c.session, c.part, c.seq, c.blob, AbortSignal.timeout?.(60_000));
          await store.deleteChunk(c.session, c.part, c.seq);
          this.lastError = null; this.backoff = 1000;
        } catch (e) {
          if (e.status === 404 || e.status === 409 || e.status === 413) {
            // La sesión no existe o ya cerró: ese pedazo no se va a aceptar nunca.
            await store.deleteChunk(c.session, c.part, c.seq);
            continue;
          }
          this.lastError = e.status === 401 ? "Token inválido" : "Reintentando subida";
          this._emit();
          await new Promise((r) => setTimeout(r, this.backoff));
          this.backoff = Math.min(this.backoff * 2, 30_000);
        }
      }
    } finally { this.running = false; this._emit(); }
  }
  _emit() { this.dispatchEvent(new CustomEvent("change", { detail: { pending: this.pending, error: this.lastError } })); }
})();
window.addEventListener("online", () => uploader.kick());
setInterval(() => uploader.kick(), 30_000);
