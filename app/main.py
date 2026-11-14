"""API de ReinventAR + hosting de la PWA."""
import asyncio
import itertools
import logging
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import (
    __version__,
    admin_api,
    audio,
    auth_api,
    cabeceras,
    catalog,
    charlas_auto,
    config,
    cuerpo,
    db,
    eventos_auto,
    events,
    events_api,
    fragmentos,
    guided_api,
    interview_api,
    itinerary_api,
    knowledge_api,
    lleno_api,
    my_events_api,
    numeros_api,
    passkey_api,
    pg,
    pipeline,
    push,
    push_api,
    sandbox,
    search,
    shows,
    shows_api,
    talks,
    ubicacion_api,
    voto_resumen_api,
)
from .auth import auth, bearer, context_for_token
from .canonical_host import WwwRedirectMiddleware
from .esquema_proxy import EsquemaProxyMiddleware
from .llm_router import como_usuario

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app):
    db.init()
    if not config.BOOTSTRAP_USERS:
        logging.warning("BOOTSTRAP_USERS vacío: nadie va a poder loguearse hasta que lo configures")
    try:
        catalog.load()
        events.load()
        shows.load()
        search.warm_async()  # embeddings en segundo plano: mientras tanto se busca solo por palabras
    except catalog.CatalogUnavailable as e:
        # No tumbamos la grabación por esto: el itinerario queda sin catálogo hasta que se resuelva.
        logging.warning("No se pudo cargar el catálogo de re:Invent (%s): /api/catalog y /api/itinerary van a fallar", e)
    fragmentos.indexar_pendientes_async()  # grabaciones viejas o sin indexar: en segundo plano
    pipeline.start_worker()
    push.start_worker()
    eventos_auto.start_worker()
    charlas_auto.start_worker()
    yield
    pg.close()


class SandboxMiddleware:
    """Si el pedido es de un usuario en modo prueba, lo corre dentro de su sandbox (ver app/sandbox.py), y deja el
    usuario a mano para las trazas del LLM (app/llm_router.py: gasto y trazas por persona).
    ASGI puro, no BaseHTTPMiddleware: así las contextvars llegan al endpoint y al threadpool de los endpoints sync."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        token = bearer(headers.get(b"authorization", b"").decode("latin-1"))
        username, sb = await run_in_threadpool(context_for_token, token, scope) if token else (None, None)
        with sandbox.activar(sb), como_usuario(username):
            return await self.app(scope, receive, send)


GZIP_TAMANO_MINIMO = 1000  # bytes: por debajo, comprimir cuesta más CPU de lo que ahorra
# Ya vienen comprimidos (imágenes, audio, tipografías, zip): gzip no les saca nada y gasta CPU.
EXTENSIONES_COMPRIMIDAS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".ico", ".woff", ".woff2",
    ".mp3", ".m4a", ".ogg", ".opus", ".webm", ".mp4", ".zip", ".gz",
})


class GzipSelectivo:
    """GZipMiddleware de Starlette, salvo en lo que no se comprime: archivos ya comprimidos (por extensión) y pedidos
    con Range (un 206 gzipeado no sirve para reanudar). Respuestas con Content-Encoding propio las deja pasar la
    propia GZipMiddleware. ASGI puro, como los otros middlewares."""

    def __init__(self, app, minimum_size: int = GZIP_TAMANO_MINIMO):
        self.app = app
        self._gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self._no_comprimir(scope):
            return await self.app(scope, receive, send)
        return await self._gzip(scope, receive, send)

    @staticmethod
    def _no_comprimir(scope) -> bool:
        if any(nombre == b"range" for nombre, _ in scope.get("headers") or []):
            return True
        return PurePosixPath(scope["path"]).suffix.lower() in EXTENSIONES_COMPRIMIDAS


app = FastAPI(title="ReinventAR", version=__version__, lifespan=lifespan)
app.add_middleware(SandboxMiddleware)
app.add_middleware(cabeceras.CabecerasMiddleware)
app.add_middleware(GzipSelectivo)  # por fuera de las cabeceras (que no tocan el cuerpo) y por dentro del redirect
app.add_middleware(WwwRedirectMiddleware)  # el último que se agrega corre primero: www. redirige antes que nada
app.add_middleware(EsquemaProxyMiddleware)  # el más externo: fija https antes de los redirects de rutas y StaticFiles
app.include_router(auth_api.router)
app.include_router(admin_api.router)
app.include_router(passkey_api.router)
app.include_router(knowledge_api.router)
app.include_router(itinerary_api.router)
app.include_router(interview_api.router)
app.include_router(guided_api.router)
app.include_router(my_events_api.router)
app.include_router(events_api.router)
app.include_router(shows_api.router)
app.include_router(push_api.router)
app.include_router(ubicacion_api.router)
app.include_router(numeros_api.router)
app.include_router(lleno_api.router)
app.include_router(voto_resumen_api.router)


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
    code: str | None = Field(None, max_length=40)
    venue: str | None = Field(None, max_length=120)
    speaker: str | None = Field(None, max_length=200)


# Topes de una grabación: parte = tramo entre pausas o cambios de micrófono; pedazo = 10 s de audio
# (TIMESLICE_MS en web/js/recorder.js), así que 100.000 pedazos son más de 270 horas.
MAX_PARTES = 1000
MAX_PEDAZOS = 100_000
MAX_PARTES_POR_GRABACION = 200
MAX_FALTANTES_INFORMADOS = 1000  # por parte: la PWA solo muestra la cantidad y vuelve a subir lo que tenga


class Finish(BaseModel):
    # {"0": 132, "1": 7}: cantidad de pedazos que la PWA generó en cada parte.
    parts: dict[Annotated[int, Field(ge=0, lt=MAX_PARTES)], Annotated[int, Field(ge=0, le=MAX_PEDAZOS)]] = Field(
        max_length=MAX_PARTES_POR_GRABACION)


HEALTH_TIMEOUT_SEGUNDOS = 2
# Un ejecutor por chequeo: si el disco se cuelga, el hilo queda ocupado pero Postgres se sigue informando bien.
_EJECUTOR_POSTGRES = ThreadPoolExecutor(max_workers=2, thread_name_prefix="health-pg")
_EJECUTOR_DISCO = ThreadPoolExecutor(max_workers=2, thread_name_prefix="health-disco")


def _probar_postgres() -> None:
    timeout_ms = HEALTH_TIMEOUT_SEGUNDOS * 1000
    with pg.pool().connection(timeout=HEALTH_TIMEOUT_SEGUNDOS) as c:
        c.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
        c.execute("SELECT 1")


def _probar_disco() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=config.DATA_DIR, prefix=".health-", delete=True) as f:
        f.write(b"ok")
        f.flush()
        os.fsync(f.fileno())


async def _chequear(nombre: str, ejecutor: ThreadPoolExecutor, prueba) -> str | None:
    """None si la prueba anduvo; si no, el nombre de lo que falló (el detalle va al log, no a la respuesta)."""
    try:
        await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(ejecutor, prueba), HEALTH_TIMEOUT_SEGUNDOS)
    except Exception as e:  # noqa: BLE001 - cualquier falla (timeout incluido) es "no anda"
        logging.error("Health: falló %s (%s: %s)", nombre, type(e).__name__, e)
        return nombre
    return None


@app.get("/health")
async def health():
    fallas = [f for f in await asyncio.gather(
        _chequear("postgres", _EJECUTOR_POSTGRES, _probar_postgres),
        _chequear("disco", _EJECUTOR_DISCO, _probar_disco),
    ) if f]
    cuerpo = {"ok": not fallas, "version": __version__, "stt": config.STT_PROVIDER, "llm": config.LLM_PROVIDER}
    if fallas:
        return JSONResponse({**cuerpo, "fallas": fallas}, status_code=503)
    return cuerpo


@app.post("/api/sessions")
def create_session(body: NewSession, username: str = Depends(auth)):
    if body.kind not in db.KINDS:
        raise HTTPException(422, f"kind debe ser uno de {db.KINDS}")
    return db.create_session(body.title.strip(), body.kind, talks.normalize_code(body.code), body.venue, body.speaker,
                             created_by=username)


@app.get("/api/sessions", dependencies=[Depends(auth)])
def list_sessions():
    return db.list_sessions()


@app.get("/api/grabaciones/buscar", dependencies=[Depends(auth)])
def buscar_en_grabaciones(q: str = Query(min_length=2, max_length=fragmentos.LARGO_MAXIMO_CONSULTA)):
    """Fragmentos de lo grabado que responden a la consulta, con el segundo donde arrancan."""
    return {"disponible": db.vector_disponible, "resultados": fragmentos.buscar(q)}


@app.get("/api/sessions/{sid}")
def get_session(sid: str, username: str = Depends(auth)):
    s = _session_or_404(sid)
    s["voto"] = db.votos_resumen(sid, username)  # 👍/👎 del resumen (app/voto_resumen_api.py)
    s["blocks"] = db.get_blocks(sid)
    s["talk"] = talks.link(s.get("code"))  # {base, title} si el código es de una charla del catálogo
    return s


@app.put("/api/sessions/{sid}/chunks/{part}/{seq}", dependencies=[Depends(auth)])
async def put_chunk(sid: str, part: int, seq: int, request: Request):
    if not (0 <= part < MAX_PARTES and 0 <= seq < MAX_PEDAZOS):
        raise HTTPException(422, "part/seq fuera de rango")
    data = await cuerpo.leer_con_tope(request, config.MAX_CHUNK_BYTES, "Pedazo demasiado grande")
    if not data:
        raise HTTPException(422, "Pedazo vacío")
    # Base y disco en el threadpool: en el event loop frenarían todos los demás pedidos (hay un solo worker).
    return await run_in_threadpool(_guardar_pedazo, sid, part, seq, data)


def _guardar_pedazo(sid: str, part: int, seq: int, data: bytes) -> dict:
    s = _session_or_404(sid)
    if s["status"] not in ("recording", "uploading", "error"):
        # Ya se está procesando: un pedazo tardío solo se acepta si ya lo teníamos (reintento idempotente).
        if seq in db.chunk_index(sid).get(part, set()):
            return {"ok": True, "duplicate": True}
        raise HTTPException(409, "La sesión ya se cerró")
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
    missing = {p: list(itertools.islice((q for q in range(n) if q not in have.get(p, set())), MAX_FALTANTES_INFORMADOS))
               for p, n in body.parts.items()}
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
