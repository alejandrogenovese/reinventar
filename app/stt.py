"""Speech-to-text intercambiable. Devuelve segmentos [{start, end, text}] en segundos."""
from pathlib import Path

import httpx

from . import config


def transcribe(path: Path, offset: float) -> list[dict]:
    provider = config.STT_PROVIDER
    if provider == "openai":
        segs = _openai_compatible(path)
    elif provider == "local":
        segs = _faster_whisper(path)
    elif provider == "fake":
        segs = _fake(path)
    else:
        raise ValueError(f"STT_PROVIDER desconocido: {provider}")
    return [{"start": s["start"] + offset, "end": s["end"] + offset, "text": s["text"].strip()} for s in segs if s["text"].strip()]


def _openai_compatible(path: Path) -> list[dict]:
    if not config.STT_API_KEY:
        raise RuntimeError("Falta STT_API_KEY")
    with path.open("rb") as f:
        r = httpx.post(
            f"{config.STT_BASE_URL.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.STT_API_KEY}"},
            data={"model": config.STT_MODEL, "language": config.STT_LANGUAGE, "response_format": "verbose_json", "temperature": "0"},
            files={"file": (path.name, f, "audio/ogg")},
            timeout=httpx.Timeout(600, connect=20),
        )
    if r.status_code >= 400:
        raise RuntimeError(f"STT {r.status_code}: {r.text[:500]}")
    body = r.json()
    segs = body.get("segments")
    if not segs:  # algunos modelos no devuelven segmentos: un solo bloque
        return [{"start": 0.0, "end": float(body.get("duration") or 0), "text": body.get("text", "")}]
    return [{"start": float(s["start"]), "end": float(s["end"]), "text": s["text"]} for s in segs]


_model = None


def _faster_whisper(path: Path) -> list[dict]:
    global _model
    from faster_whisper import WhisperModel  # opcional: pip install faster-whisper

    if _model is None:
        _model = WhisperModel(config.STT_MODEL if "/" in config.STT_MODEL or config.STT_MODEL.startswith("large") else "large-v3-turbo",
                              device="cpu", compute_type="int8")
    segments, _ = _model.transcribe(str(path), language=config.STT_LANGUAGE, vad_filter=True)
    return [{"start": s.start, "end": s.end, "text": s.text} for s in segments]


def _fake(path: Path) -> list[dict]:
    from .audio import duration

    d = duration(path)
    out, t, i = [], 0.0, 0
    while t < d:
        out.append({"start": t, "end": min(d, t + 5), "text": f"Today we are launching Amazon S3 feature number {i}."})
        t += 5
        i += 1
    return out
