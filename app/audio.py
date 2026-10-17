"""Ensamblado y preparación del audio con ffmpeg.

La PWA graba con MediaRecorder en webm/opus y manda pedazos de ~10 s. Dentro de una
misma "parte" (una instancia de MediaRecorder) los pedazos se concatenan byte a byte y
forman un webm válido. Si la página se recarga y arranca otro MediaRecorder, empieza una
parte nueva con su propio header: por eso cada parte se decodifica por separado.
"""
import json
import subprocess
from pathlib import Path

from . import config


def session_dir(sid: str) -> Path:
    return config.SESSIONS_DIR / sid


def chunk_path(sid: str, part: int, seq: int) -> Path:
    return session_dir(sid) / "chunks" / f"{part:03d}" / f"{seq:06d}.webm"


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg falló: {' '.join(cmd[:3])}…\n{p.stderr[-1500:]}")
    return p


def duration(path: Path) -> float:
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(p.stdout)["format"].get("duration") or 0)


def assemble(sid: str, parts: dict) -> Path:
    """parts = {part: [seq,...]} → work/full.ogg (16 kHz mono opus)."""
    work = session_dir(sid) / "work"
    work.mkdir(parents=True, exist_ok=True)
    wavs = []
    for part in sorted(parts):
        raw = work / f"part-{part:03d}.webm"
        with raw.open("wb") as out:
            for seq in sorted(parts[part]):
                out.write(chunk_path(sid, part, seq).read_bytes())
        wav = work / f"part-{part:03d}.wav"
        # -fflags +genpts: el webm de MediaRecorder no trae duración ni cues.
        _run(["ffmpeg", "-y", "-v", "error", "-fflags", "+genpts", "-i", str(raw), "-ac", "1", "-ar", "16000", str(wav)])
        wavs.append(wav)
    full = work / "full.ogg"
    if len(wavs) == 1:
        src = ["-i", str(wavs[0])]
    else:
        lst = work / "concat.txt"
        lst.write_text("".join(f"file '{w.name}'\n" for w in wavs))
        src = ["-f", "concat", "-safe", "0", "-i", str(lst)]
    _run(["ffmpeg", "-y", "-v", "error", *src, "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k", str(full)])
    for w in wavs:
        w.unlink(missing_ok=True)
    return full


def split(full: Path, seconds: int) -> list[tuple[float, Path]]:
    """Corta en pedazos de `seconds` para respetar el límite de tamaño de las APIs de STT."""
    total = duration(full)
    out = []
    start = 0.0
    i = 0
    while start < total - 0.5:
        seg = full.parent / f"seg-{i:03d}.ogg"
        _run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(seconds), "-i", str(full), "-c:a", "libopus", "-b:a", "24k", str(seg)])
        out.append((start, seg))
        start += seconds
        i += 1
    return out
