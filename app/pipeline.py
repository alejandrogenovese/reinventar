"""Procesamiento de una sesión: ensamblar → transcribir → traducir → resumir.

Un solo worker en un thread: alcanza para un usuario y evita pisar límites de las APIs.
Al reiniciar el contenedor, las sesiones que quedaron a medio procesar se re-encolan.
"""
import logging
import queue
import re
import threading
import traceback

from . import audio, config, db, fragmentos, langfuse_scores, llm, llm_router, prompts, sandbox, stt, talks, trazas
from .llm_router import Tarea

log = logging.getLogger("reinventar.pipeline")
# Cada trabajo lleva el contexto de quien lo encoló: una grabación en modo prueba se procesa en el schema de prueba, y
# las llamadas al STT y al LLM quedan a nombre de quien grabó (gasto por persona en el gateway).
_q: "queue.Queue[tuple[str, sandbox.Sandbox | None, str | None]]" = queue.Queue()
_started = False
SUMMARY_MAX_TOKENS = 16000  # incluye el thinking de modelos que no lo pueden apagar (Opus 5.5)


def enqueue(sid: str):
    db.update_session(sid, status="queued", error=None, progress=None)
    _q.put((sid, sandbox.actual(), llm_router.usuario_actual()))


def start_worker():
    global _started
    if _started:
        return
    _started = True
    with sandbox.real():
        for sid in db.sessions_in(db.PROCESSING):
            _q.put((sid, None, None))
    # Las de prueba que quedaron a medias se terminan con proveedores fake (no se sabe quién las encoló).
    prueba = sandbox.Sandbox(username="pipeline")
    with sandbox.activar(prueba):
        for sid in db.sessions_in(db.PROCESSING):
            _q.put((sid, prueba, None))
    threading.Thread(target=_loop, name="pipeline", daemon=True).start()


def _loop():
    while True:
        trabajo = _q.get()
        try:
            _procesar(*trabajo)
        finally:
            _q.task_done()


def _procesar(sid: str, contexto: "sandbox.Sandbox | None", usuario: str | None):
    with sandbox.activar(contexto), llm_router.como_usuario(usuario):
        try:
            process(sid)
        except Exception as e:  # noqa: BLE001
            log.error("sesión %s falló: %s", sid, traceback.format_exc())
            db.update_session(sid, status="error", error=str(e)[:1000], progress=None)


def hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


BLOCK_MAX_FACTOR = 2  # sin fin de oración a la vista (música, habla de corrido), se corta igual al doble del objetivo


def group_blocks(segs: list[dict], target: float) -> list[dict]:
    """Agrupa segmentos de Whisper en bloques de lectura de ~`target` segundos, cortando en fin de oración."""
    blocks, cur = [], None
    for s in segs:
        if cur is None:
            cur = {"start": s["start"], "end": s["end"], "en": s["text"]}
            continue
        cur["en"] += " " + s["text"]
        cur["end"] = s["end"]
        length = cur["end"] - cur["start"]
        if (length >= target and re.search(r"[.!?]\"?$", s["text"])) or length >= target * BLOCK_MAX_FACTOR:
            blocks.append(cur)
            cur = None
    if cur:
        blocks.append(cur)
    return blocks


def process(sid: str):
    s = db.get_session(sid)
    if not s:
        return
    # Una grabación es una traza en Langfuse: los pedazos de STT, los lotes de traducción y el resumen quedan juntos.
    with trazas.abrir(trazas.de_grabacion(sid, s.get("code"), s.get("kind"))):
        _etapas(sid, s)


def _etapas(sid: str, s: dict):
    title, kind = s["title"], s["kind"]
    names, context = talks.proper_names(s.get("code")), talks.context(s.get("code"))

    # 1 + 2. Ensamblar y transcribir (si ya hay bloques de una corrida anterior, se reusan).
    blocks = db.get_blocks(sid)
    if not blocks:
        db.update_session(sid, status="transcribing", progress="Uniendo audio")
        parts = db.chunk_index(sid)
        if not parts:
            raise RuntimeError("La sesión no tiene audio")
        full = audio.assemble(sid, parts)
        db.update_session(sid, duration_s=audio.duration(full))
        pieces = audio.split(full, config.STT_SEGMENT_SECONDS)
        segs = []
        for n, (offset, path) in enumerate(pieces, 1):
            db.update_session(sid, progress=f"Transcribiendo {n}/{len(pieces)}")
            segs += stt.transcribe(path, offset)
            path.unlink(missing_ok=True)
        if not segs:
            raise RuntimeError("La transcripción vino vacía: ¿se grabó audio?")
        db.replace_blocks(sid, group_blocks(segs, config.BLOCK_SECONDS))
        blocks = db.get_blocks(sid)

    # 3. Traducir lo que falte, por lotes.
    db.update_session(sid, status="translating", progress=None)
    pending = [(b["idx"], b["en"]) for b in blocks if not b["es"]]
    batches = [pending[i:i + config.TRANSLATE_BATCH] for i in range(0, len(pending), config.TRANSLATE_BATCH)]
    faltantes = 0
    for n, batch in enumerate(batches, 1):
        db.update_session(sid, progress=f"Traduciendo {n}/{len(batches)}")
        out = llm.complete(Tarea.TRADUCCION, prompts.TRANSLATE_SYSTEM, prompts.translate_user(batch, names))
        got = {int(i): t.strip() for i, t in re.findall(r"\[\[(\d+)\]\]\s*(.*?)(?=\n?\[\[\d+\]\]|\Z)", out, re.S)}
        missing = [(i, t) for i, t in batch if not got.get(i)]
        faltantes += len(missing)
        for i, t in missing:  # reintento uno por uno si el modelo se comió alguna línea
            one = llm.complete(Tarea.TRADUCCION, prompts.TRANSLATE_SYSTEM, prompts.translate_user([(i, t)], names), 2000)
            got[i] = re.sub(r"^\s*\[\[\d+\]\]\s*", "", one).strip()
        db.set_translations(sid, [(i, got[i]) for i, _ in batch])
    if batches:  # cuántas líneas se comió el modelo y hubo que reintentar una por una
        langfuse_scores.puntuar("lineas_faltantes", faltantes)

    # 4. Resumir sobre el original en inglés (más fiel) con timestamps.
    db.update_session(sid, status="summarizing", progress=None)
    transcript = "\n".join(f"[{hms(b['start_s'])}] {b['en']}" for b in db.get_blocks(sid))
    raw = llm.complete(Tarea.RESUMEN, prompts.SUMMARY_SYSTEM, prompts.summary_user(kind, title, transcript, context), SUMMARY_MAX_TOKENS)
    summary = llm.parse_json_puntuado(raw)
    # 5. Fragmentos para buscar en lo grabado, antes de marcarla lista (si falla, la grabación igual queda lista).
    fragmentos.indexar_sin_fallar(sid)
    db.update_session(sid, status="ready", summary=summary, progress=None, error=None)


def to_markdown(s: dict, blocks: list[dict]) -> str:
    sm = s.get("summary") or {}
    meta = " · ".join(x for x in [s["kind"], s.get("code"), s.get("venue"), s.get("speaker"),
                                  hms(s["duration_s"]) if s.get("duration_s") else None] if x)
    out = [f"# {s['title']}", "", f"_{meta}_", ""]
    if sm:
        out += ["## TL;DR", "", sm.get("tldr", ""), ""]
        if sm.get("announcements"):
            out += ["## Anuncios", ""] + [f"- **{a['service']}** — {a['text']}" for a in sm["announcements"]] + [""]
        if sm.get("key_points"):
            out += ["## Puntos clave", ""] + [f"- {p}" for p in sm["key_points"]] + [""]
        if sm.get("services"):
            out += ["## Servicios mencionados", "", ", ".join(f"`{x}`" for x in sm["services"]), ""]
        if sm.get("quotes"):
            out += ["## Frases", ""] + [f"- `{q.get('time', '')}` “{q['text']}”" for q in sm["quotes"]] + [""]
        if sm.get("vs_abstract"):
            out += ["## Versus lo prometido", "", sm["vs_abstract"], ""]
        if sm.get("takeaways"):
            out += ["## Para llevar a Galicia", ""] + [f"- {p}" for p in sm["takeaways"]] + [""]
    out += ["## Transcripción", ""]
    for b in blocks:
        out += [f"**{hms(b['start_s'])}** {b['es'] or ''}", "", f"> {b['en']}", ""]
    return "\n".join(out)
