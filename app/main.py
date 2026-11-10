"""API de ReinventAR + hosting de la PWA."""
import logging
import shutil
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (__version__, admin_api, audio, auth_api, catalog, config, db, events, events_api, itinerary_api,
               knowledge_api, passkey_api, pg, pipeline, push, push_api, sandbox, search, talks)
from .auth import auth, bearer, sandbox_for_token
from .canonical_host import WwwRedirectMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app):
    db.init()
    if not config.BOOTSTRAP_USERS:
        logging.warning("BOOTSTRAP_USERS vacío: nadie va a poder loguearse hasta que lo configures")
    try:
        catalog.load()
        events.load()
        search.warm_async()  # embeddings en segundo plano: mientras tanto se busca solo por palabras
    except catalog.CatalogUnavailable as e:
        # No tumbamos la grabación por esto: el itinerario queda sin catálogo hasta que se resuelva.
        logging.warning("No se pudo cargar el catálogo de re:Invent (%s): /api/catalog y /api/itinerary van a fallar", e)
    pipeline.start_worker()
    push.start_worker()
    yield
    pg.close()


class SandboxMiddleware:
    """Si el pedido es de un usuario en modo prueba, lo corre dentro de su sandbox (ver app/sandbox.py).
    ASGI puro, no BaseHTTPMiddleware: así la contextvar llega al endpoint y al threadpool de los endpoints sync."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        token = bearer(headers.get(b"authorization", b"").decode("latin-1"))
        sb = await run_in_threadpool(sandbox_for_token, token) if token else None
        with sandbox.activar(sb):
            return await self.app(scope, receive, send)


app = FastAPI(title="ReinventAR", version=__version__, lifespan=lifespan)
app.add_middleware(SandboxMiddleware)
app.add_middleware(WwwRedirectMiddleware)  # el último que se agrega corre primero: www. redirige antes que nada
app.include_router(auth_api.router)
app.include_router(admin_api.router)
app.include_router(passkey_api.router)
app.include_router(knowledge_api.router)
app.include_router(itinerary_api.router)
app.include_router(events_api.router)
app.include_router(push_api.router)


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
    return {"ok": True, "version": __version__, "stt": config.STT_PROVIDER, "llm": config.LLM_PROVIDER}


@app.post("/api/sessions", dependencies=[Depends(auth)])
def create_session(body: NewSession):
    if body.kind not in db.KINDS:
        raise HTTPException(422, f"kind debe ser uno de {db.KINDS}")
    return db.create_session(body.title.strip(), body.kind, talks.normalize_code(body.code), body.venue, body.speaker)


@app.get("/api/sessions", dependencies=[Depends(auth)])
def list_sessions():
    return db.list_sessions()


@app.get("/api/sessions/{sid}", dependencies=[Depends(auth)])
def get_session(sid: str):
    s = _session_or_404(sid)
    s["blocks"] = db.get_blocks(sid)
    s["talk"] = talks.link(s.get("code"))  # {base, title} si el código es de una charla del catálogo
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


class RevalidatedStaticFiles(StaticFiles):
    """La PWA (HTML/JS/CSS) se revalida en cada carga: con ETag el navegador recibe un 304 si no cambió,
    y después de un deploy toma la versión nueva en vez de reusar una copia vieja por caché heurística."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", RevalidatedStaticFiles(directory=config.WEB_DIR, html=True), name="web")
