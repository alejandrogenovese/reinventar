"""Metadata de Langfuse para cada llamada al LLM o al STT por el gateway LiteLLM (app/llm.py y app/stt.py).

Las llamadas de un mismo flujo quedan en una sola traza: el flujo abre un contexto (abrir()) y todo lo que se llama
adentro lleva el mismo trace_id. Una grabación es UNA traza (de_grabacion: los pedazos de STT, cada lote de
traducción y el resumen); el chat, el briefing y el resto abren una por pedido. Sin contexto, cada llamada es su
propia traza, con un trace_id nuevo.

Además, cada llamada lleva:
- trace_release: la versión de la app, para ver qué cambió después de cada deploy.
- version: un hash corto del prompt de sistema (en el STT, del vocabulario): cambia solo si cambia el prompt.
- tags: la tarea, el entorno (prod/dev) y "prueba" si quien llama está en modo prueba.
- mask_input en la entrevista: las respuestas sobre el trabajo de la persona no hacen falta para depurar.
Nada de datos personales en trace_metadata: solo códigos de charla, tipos y cantidades.
"""
import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from . import __version__, config, llm_router, sandbox

LARGO_HASH_PROMPT = 8
LARGO_TRACE_ID = 32  # hex, como los que genera Langfuse
FLUJO_ENTREVISTA = "entrevista"
_ENMASCARADOS = frozenset({"entrevista", "stt-voz"})  # tareas cuya entrada no se guarda en Langfuse


@dataclass(frozen=True)
class Traza:
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    nombre: str | None = None        # trace_name; sin nombre, el de la tarea
    session_id: str | None = None    # sin sesión, "<flujo>-<usuario>-<día>"
    metadata: dict = field(default_factory=dict)  # trace_metadata, sin datos personales


_actual: ContextVar[Traza | None] = ContextVar("traza", default=None)


@contextmanager
def abrir(traza: Traza | None = None) -> Iterator[Traza]:
    """Las llamadas dentro del bloque van a la misma traza. Sin argumento, una traza nueva (una por pedido)."""
    traza = traza or Traza()
    token = _actual.set(traza)
    try:
        yield traza
    finally:
        _actual.reset(token)


def actual() -> Traza | None:
    return _actual.get()


def id_grabacion(sid: str) -> str:
    """Determinístico: si la grabación se reprocesa (reintento, reinicio), sigue en la misma traza."""
    return hashlib.sha256(f"grabacion-{sid}".encode()).hexdigest()[:LARGO_TRACE_ID]


def de_grabacion(sid: str, codigo: str | None, tipo: str | None) -> Traza:
    meta = {k: v for k, v in {"codigo": codigo, "tipo": tipo}.items() if v}
    return Traza(trace_id=id_grabacion(sid), nombre="grabacion", session_id=f"grabacion-{sid}", metadata=meta)


def hash_prompt(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()[:LARGO_HASH_PROMPT]


def entorno() -> str:
    return "prod" if config.RAILWAY_ENVIRONMENT_NAME == "production" else "dev"


def _sesion(flujo: str, usuario: str | None) -> str:
    dia = sandbox.ahora().date().isoformat()
    return "-".join(x for x in (flujo, usuario, dia) if x)


def metadata(tarea: str, prompt: str, flujo: str | None = None) -> dict:
    """La metadata de Langfuse para una llamada. tarea: la de llm_router (o el alias del STT); prompt: el de sistema
    (o el vocabulario del STT); flujo: el prefijo de la sesión cuando no hay contexto (por defecto, la tarea)."""
    traza = actual() or Traza()
    usuario = llm_router.usuario_actual()
    tags = [tarea, entorno()] + (["prueba"] if sandbox.actual() else [])
    meta = {
        "trace_id": traza.trace_id,
        "trace_name": traza.nombre or tarea,
        "session_id": traza.session_id or _sesion(flujo or tarea, usuario),
        "generation_name": tarea,
        "trace_release": __version__,
        "version": hash_prompt(prompt),
        "tags": tags,
    }
    if traza.metadata:
        meta["trace_metadata"] = dict(traza.metadata)
    if usuario:
        meta["trace_user_id"] = usuario
    if tarea in _ENMASCARADOS:
        meta["mask_input"] = True
    return meta
