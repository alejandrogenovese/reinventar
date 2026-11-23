"""Procesamiento de una sesión: ensamblar → transcribir → traducir → resumir.

Un solo worker en un thread: alcanza para un usuario y evita pisar límites de las APIs.
Al reiniciar el contenedor, las sesiones que quedaron a medio procesar se re-encolan.
"""
import logging
import queue
import re
import threading
import traceback

from . import (
    audio,
    config,
    db,
    fragmentos,
    huecos,
    langfuse_scores,
    llm,
    llm_router,
    prompts,
    sandbox,
    stt,
    talks,
    trazas,
)
from .llm_router import Tarea

log = logging.getLogger("reinventar.pipeline")
# Cada trabajo lleva el contexto de quien lo encoló: una grabación en modo prueba se procesa en el schema de prueba, y
# las llamadas al STT y al LLM quedan a nombre de quien grabó (gasto por persona en el gateway).
_q: "queue.Queue[tuple[str, sandbox.Sandbox | None, str | None]]" = queue.Queue()
_started = False
SIN_VOZ = ("No se escuchó voz en la grabación. Revisá que el medidor del micrófono se mueva mientras grabás "
           "(con auriculares, el micrófono no oye lo que suena en el mismo equipo) y volvé a grabar.")
SUMMARY_MAX_TOKENS = 16000  # incluye el thinking de modelos que no lo pueden apagar (Opus 5.5)


def enqueue(sid: str):
    db.update_session(sid, status="queued", error=None, progress=None)
    _q.put((sid, sandbox.actual(), llm_router.usuario_actual()))


def _dueno(sid: str) -> str:
    """Quién grabó la sesión (created_by); las de antes de ese campo, y las que ya no están, quedan del sistema."""
    creada_por = (db.get_session(sid) or {}).get("created_by")
    return creada_por or f"{llm_router.PREFIJO_SISTEMA}pipeline"


def reencolar_pendientes():
    """Al arrancar, retoma lo que quedó a medias, a nombre de quien lo grabó (sin eso las trazas y el gasto del
    reintento quedarían sin usuario)."""
    with sandbox.real():
        for sid in db.sessions_in(db.PROCESSING):
            _q.put((sid, None, _dueno(sid)))
    # Las de prueba que quedaron a medias se terminan con proveedores fake.
    prueba = sandbox.Sandbox(username="pipeline")
    with sandbox.activar(prueba):
        for sid in db.sessions_in(db.PROCESSING):
            _q.put((sid, prueba, _dueno(sid)))


def start_worker():
    global _started
    if _started:
        return
    _started = True
    reencolar_pendientes()
    threading.Thread(target=_loop, name="pipeline", daemon=True).start()


def vivo() -> bool:
    """Si el hilo que procesa las grabaciones está corriendo (lo mira el banner de estado)."""
    return any(t.name == "pipeline" and t.is_alive() for t in threading.enumerate())


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
            raise RuntimeError(SIN_VOZ)
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


def _textos(valor) -> list[str]:
    return [str(x) for x in valor if isinstance(x, str | int | float)] if isinstance(valor, list) else []


def _pares(valor, *claves) -> list[dict]:
    return [{k: str(x.get(k) or "") for k in claves} for x in valor if isinstance(x, dict)] if isinstance(valor, list) else []


def resumen_publico(s: dict) -> dict:
    """Lo que se puede compartir de una grabación fuera de la app (texto para WhatsApp y el link /c/<token>): título,
    charla y resumen. Lista blanca: sin vs_abstract ni takeaways (son para quien grabó), ni votos, transcripción,
    usuario o id. El resumen viene de un LLM: acá solo se normalizan los tipos; escapar es tarea de quien lo muestre."""
    sm = s.get("summary") if isinstance(s.get("summary"), dict) else {}
    return {
        "title": str(s.get("title") or ""), "kind": str(s.get("kind") or ""), "code": s.get("code") or None,
        "speaker": s.get("speaker") or None,
        "tldr": str(sm.get("tldr") or ""),
        "announcements": _pares(sm.get("announcements"), "service", "text"),
        "key_points": _textos(sm.get("key_points")),
        "services": _textos(sm.get("services")),
        "quotes": _pares(sm.get("quotes"), "time", "text"),
    }


def _md_resumen(sm: dict) -> list[str]:
    out = ["## TL;DR", "", sm.get("tldr", ""), ""]
    if sm.get("announcements"):
        out += ["## Anuncios", ""] + [f"- **{a['service']}** — {a['text']}" for a in sm["announcements"]] + [""]
    if sm.get("key_points"):
        out += ["## Puntos clave", ""] + [f"- {p}" for p in sm["key_points"]] + [""]
    if sm.get("services"):
        out += ["## Servicios mencionados", "", ", ".join(f"`{x}`" for x in sm["services"]), ""]
    if sm.get("quotes"):
        out += ["## Frases", ""] + [f"- `{q.get('time', '')}` “{q['text']}”" for q in sm["quotes"]] + [""]
    return out


def to_markdown_publico(s: dict) -> str:
    """El resumen para compartir (WhatsApp, copiar): solo lo de resumen_publico, sin transcripción."""
    p = resumen_publico(s)
    meta = " · ".join(x for x in [p["kind"], p["code"], p["speaker"]] if x)
    out = [f"# {p['title']}", "", f"_{meta}_", ""] if meta else [f"# {p['title']}", ""]
    if s.get("summary"):
        out += _md_resumen(p)
    return "\n".join(out).strip() + "\n"


def to_markdown(s: dict, blocks: list[dict]) -> str:
    sm = s.get("summary") or {}
    meta = " · ".join(x for x in [s["kind"], s.get("code"), s.get("venue"), s.get("speaker"),
                                  hms(s["duration_s"]) if s.get("duration_s") else None] if x)
    out = [f"# {s['title']}", "", f"_{meta}_", ""]
    if sm:
        out += _md_resumen(sm)
        if sm.get("vs_abstract"):
            out += ["## Versus lo prometido", "", sm["vs_abstract"], ""]
        if sm.get("takeaways"):
            out += ["## Para llevar a Galicia", ""] + [f"- {p}" for p in sm["takeaways"]] + [""]
    out += ["## Transcripción", ""]
    pendientes = sorted(s.get("huecos") or [], key=lambda h: h["desde"])
    for b in blocks:
        while pendientes and pendientes[0]["desde"] <= b["start_s"]:  # el hueco va antes del primer bloque que lo sigue
            out += [huecos.marca(pendientes.pop(0)), ""]
        out += [f"**{hms(b['start_s'])}** {b['es'] or ''}", "", f"> {b['en']}", ""]
    out += [x for h in pendientes for x in (huecos.marca(h), "")]
    return "\n".join(out)
