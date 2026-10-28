"""API de ReinventAR + hosting de la PWA."""
import logging
import shutil
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import audio, auth_api, catalog, config, db, itinerary_api, pipeline
from .auth import auth

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app):
    db.init()
    if not config.BOOTSTRAP_USERS:
        logging.warning("BOOTSTRAP_USERS vacío: nadie va a poder loguearse hasta que lo configures")
    try:
        catalog.load()
    except catalog.CatalogUnavailable as e:
        # No tumbamos la grabación por esto: el itinerario queda sin catálogo hasta que se resuelva.
        logging.warning("No se pudo cargar el catálogo de re:Invent (%s): /api/catalog y /api/itinerary van a fallar", e)
    pipeline.start_worker()
    yield


app = FastAPI(title="ReinventAR", lifespan=lifespan)
app.include_router(auth_api.router)
app.include_router(itinerary_api.router)


@app.exception_handler(catalog.CatalogUnavailable)
async def _catalog_unavailable(_request, exc: catalog.CatalogUnavailable):
    logging.error("Catálogo de re:Invent no disponible: %s", exc)
    return JSONResponse({"detail": "El catálogo de sesiones no está disponible en el servidor todavía."}, status_code=503)


def _session_or_404(sid: str):
    s = db.get_session(sid)
    if not s:
        raise HTTPException(404, "Sesión inexistente")
    return s


class NewSession(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: str
    code: Optional[str] = Field(None, max_length=40)
    venue: Optional[str] = Field(None, max_length=120)
    speaker: Optional[str] = Field(None, max_length=200)


class Finish(BaseModel):
    # {"0": 132, "1": 7}: cantidad de pedazos que la PWA generó en cada parte.
    parts: dict[str, int]


@app.get("/health")
def health():
    return {"ok": True, "stt": config.STT_PROVIDER, "llm": config.LLM_PROVIDER}


@app.get("/api/me")
def me(username: str = Depends(auth)):
    return {"ok": True, "username": username}


@app.post("/api/sessions", dependencies=[Depends(auth)])
def create_session(body: NewSession):
    if body.kind not in db.KINDS:
        raise HTTPException(422, f"kind debe ser uno de {db.KINDS}")
    return db.create_session(body.title.strip(), body.kind, body.code, body.venue, body.speaker)


@app.get("/api/sessions", dependencies=[Depends(auth)])
def list_sessions():
    return db.list_sessions()


@app.get("/api/sessions/{sid}", dependencies=[Depends(auth)])
def get_session(sid: str):
    s = _session_or_404(sid)
    s["blocks"] = db.get_blocks(sid)
    return s


@app.put("/api/sessions/{sid}/chunks/{part}/{seq}", dependencies=[Depends(auth)])
async def put_chunk(sid: str, part: int, seq: int, request: Request):
    s = _session_or_404(sid)
    if s["status"] not in ("recording", "uploading", "error"):
        # Ya se está procesando: un pedazo tardío solo se acepta si ya lo teníamos (reintento idempotente).
        if seq in db.chunk_index(sid).get(part, set()):
            return {"ok": True, "duplicate": True}
        raise HTTPException(409, "La sesión ya se cerró")
    if not (0 <= part < 1000 and 0 <= seq < 1_000_000):
        raise HTTPException(422, "part/seq fuera de rango")
    data = await request.body()
    if not data:
        raise HTTPException(422, "Pedazo vacío")
    if len(data) > config.MAX_CHUNK_BYTES:
        raise HTTPException(413, "Pedazo demasiado grande")
    path = audio.chunk_path(sid, part, seq)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)  # escritura atómica: un reintento nunca deja un archivo a medias
    db.record_chunk(sid, part, seq, len(data))
    return {"ok": True}


@app.post("/api/sessions/{sid}/finish", dependencies=[Depends(auth)])
def finish(sid: str, body: Finish):
    s = _session_or_404(sid)
    if s["status"] in db.PROCESSING or s["status"] == "ready":
        return s
    have = db.chunk_index(sid)
    missing = {p: [q for q in range(n) if q not in have.get(int(p), set())] for p, n in body.parts.items()}
    missing = {p: m for p, m in missing.items() if m}
    db.update_session(sid, expected_parts=body.parts)
    if missing:
        db.update_session(sid, status="uploading")
        raise HTTPException(409, {"message": "Faltan pedazos", "missing": missing})
    pipeline.enqueue(sid)
    return db.get_session(sid)


@app.post("/api/sessions/{sid}/retry", dependencies=[Depends(auth)])
def retry(sid: str, from_scratch: bool = False):
    _session_or_404(sid)
    if from_scratch:
        db.replace_blocks(sid, [])
    pipeline.enqueue(sid)
    return db.get_session(sid)


@app.get("/api/sessions/{sid}/export.md", dependencies=[Depends(auth)])
def export_md(sid: str):
    s = _session_or_404(sid)
    md = pipeline.to_markdown(s, db.get_blocks(sid))
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8")


@app.delete("/api/sessions/{sid}", dependencies=[Depends(auth)])
def delete(sid: str):
    _session_or_404(sid)
    db.delete_session(sid)
    shutil.rmtree(audio.session_dir(sid), ignore_errors=True)
    return {"ok": True}


# --- PWA ---------------------------------------------------------------------------
@app.get("/sw.js")
def sw():
    # El service worker se sirve desde la raíz para controlar todo el sitio, sin caché HTTP.
    return FileResponse(config.WEB_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
