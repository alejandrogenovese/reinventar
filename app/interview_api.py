"""Endpoints de la entrevista del itinerario guiado: progreso, repreguntas, ficha y respuesta por voz."""
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from . import cuerpo, db, interview, stt
from .auth import auth
from .interview import Ficha, Respuestas
from .llm_router import UsoSTT

log = logging.getLogger("reinventar.interview")
router = APIRouter(dependencies=[Depends(auth)])

# Extensión del archivo temporal según lo que grabó el navegador (el STT detecta el formato por el nombre).
_EXTENSIONES = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/mpeg": ".mp3",
                "audio/wav": ".wav", "audio/x-m4a": ".m4a"}


def _respuestas(username: str) -> Respuestas:
    return Respuestas(**(db.get_interview(username)["respuestas"] or {}))


def _estado(username: str) -> dict:
    guardado = db.get_interview(username)
    r = Respuestas(**(guardado["respuestas"] or {}))
    return {"respuestas": r.model_dump(exclude_none=True), "faltan": interview.faltantes(r),
            "ficha": guardado["ficha"], "ficha_texto": guardado["ficha_texto"]}


@router.get("/api/itinerary/interview")
def get_interview(username: str = Depends(auth)):
    return _estado(username)


@router.put("/api/itinerary/interview")
def save_interview(body: Respuestas, username: str = Depends(auth)):
    """Guarda lo que llegó (una o varias respuestas) sin pisar el resto."""
    r = interview.combinar(db.get_interview(username)["respuestas"], body)
    db.save_answers(username, r.model_dump(exclude_none=True))
    return {"faltan": interview.faltantes(r)}


@router.post("/api/itinerary/interview/repreguntas")
def followups(username: str = Depends(auth)):
    """Hasta 2 repreguntas del LLM (opcionales). Reemplazan las anteriores."""
    r = _respuestas(username)
    try:
        nuevas = interview.repreguntas(r)
    except interview.EntrevistaIncompleta as e:
        raise HTTPException(422, str(e)) from e
    actualizadas = r.model_copy(update={"repreguntas": nuevas})
    db.save_answers(username, actualizadas.model_dump(exclude_none=True))
    return {"repreguntas": [q.model_dump() for q in nuevas]}


def _guardar_ficha(username: str, ficha: Ficha) -> dict:
    texto = interview.ficha_a_texto(ficha)
    db.save_ficha(username, ficha.model_dump(), texto)
    return {"ficha": ficha.model_dump(), "ficha_texto": texto}


@router.post("/api/itinerary/ficha")
def create_ficha(username: str = Depends(auth)):
    try:
        ficha = interview.generar_ficha(_respuestas(username))
    except interview.EntrevistaIncompleta as e:
        raise HTTPException(422, str(e)) from e
    except interview.FichaInvalida as e:
        raise HTTPException(502, str(e)) from e
    return _guardar_ficha(username, ficha)


@router.put("/api/itinerary/ficha")
def edit_ficha(body: Ficha, username: str = Depends(auth)):
    """La persona corrige la ficha a mano."""
    return _guardar_ficha(username, body)


def _transcribir(data: bytes, extension: str) -> str:
    with tempfile.TemporaryDirectory(prefix="voz-") as tmp:
        path = Path(tmp) / f"respuesta{extension}"
        path.write_bytes(data)
        return " ".join(s["text"] for s in stt.transcribe(path, 0, language=interview.IDIOMA_VOZ, uso=UsoSTT.VOZ)).strip()


@router.post("/api/itinerary/interview/voz")
async def voice_answer(request: Request):
    """Audio de una respuesta → texto en castellano, para que la persona lo revise antes de guardarlo."""
    data = await cuerpo.leer_con_tope(request, interview.MAX_VOZ_BYTES, "El audio es demasiado largo")
    if not data:
        raise HTTPException(422, "Audio vacío")
    tipo = request.headers.get("content-type", "").split(";")[0].strip().lower()
    try:
        texto = await run_in_threadpool(_transcribir, data, _EXTENSIONES.get(tipo, ".webm"))
    except Exception as e:  # noqa: BLE001 - falla del proveedor de STT: se informa sin cortar la entrevista
        log.warning("No se pudo transcribir la respuesta por voz: %s", e)
        raise HTTPException(502, "No pude pasar el audio a texto; probá de nuevo o escribilo.") from e
    if not texto:  # solo silencio (o lo que Whisper inventa sobre el silencio)
        raise HTTPException(422, "No se escuchó voz. Probá de nuevo más cerca del micrófono o escribilo.")
    return {"texto": texto}
