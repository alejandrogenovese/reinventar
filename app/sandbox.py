"""Modo prueba por usuario: un admin lo prende desde Admin › Usuarios y ese usuario usa la app sin tocar sus datos reales.

Mientras está activo, cada pedido de ese usuario corre en un contexto de sandbox (contextvar):
- Postgres: search_path "<DB_SCHEMA>_prueba, <DB_SCHEMA>, public". En el schema de prueba solo existen las tablas de datos
  del usuario (grabaciones, itinerario), así que lo que escribe va ahí; usuarios, tokens y passkeys siguen saliendo del
  schema real. Los cachés que la app crea a demanda (briefings, temas) también quedan separados.
- Proveedores de STT y LLM elegidos por el admin ("fake" no gasta nada). Los embeddings no cambian: la búsqueda compara
  contra vectores ya calculados con el modelo real.
- Reloj simulado ("es martes 1/12 13:40 en Las Vegas", y avanza con el tiempo real) y ubicación simulada (una sede).
Las operaciones globales (cargar el catálogo, los embeddings) corren siempre en el contexto real: ver real().
"""
import datetime as dt
import functools
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from . import config

EVENT_TZ = ZoneInfo("America/Los_Angeles")
PROVEEDORES = ("fake", "real")


def schema_prueba() -> str:
    return f"{config.DB_SCHEMA}_prueba"


@dataclass(frozen=True)
class Sandbox:
    username: str
    stt: str = "fake"                       # "fake" | "real"
    llm: str = "fake"
    reloj: dt.datetime | None = None        # hora simulada en el momento en que se fijó (con zona)
    reloj_fijado: float | None = None       # time.time() de cuando se fijó: el reloj simulado avanza desde ahí
    id_sede: int | None = None              # ubicación simulada


_actual: ContextVar[Sandbox | None] = ContextVar("sandbox", default=None)


def actual() -> Sandbox | None:
    return _actual.get()


@contextmanager
def activar(sb: Sandbox | None):
    token = _actual.set(sb)
    try:
        yield sb
    finally:
        _actual.reset(token)


def real():
    """Contexto sin sandbox, para operaciones globales que no deben depender de quién las disparó."""
    return activar(None)


def en_real(fn):
    """Decorador para lo que arma estado global en memoria (catálogo, embeddings, temas): siempre en el contexto real,
    aunque lo dispare el pedido de un usuario en modo prueba."""
    @functools.wraps(fn)
    def envuelta(*args, **kwargs):
        with real():
            return fn(*args, **kwargs)
    return envuelta


# ---------- lo que consulta el resto de la app ----------

def proveedor_stt() -> str:
    sb = actual()
    return "fake" if sb and sb.stt == "fake" else config.STT_PROVIDER


def proveedor_llm() -> str:
    sb = actual()
    return "fake" if sb and sb.llm == "fake" else config.LLM_PROVIDER


def ahora(tz: dt.tzinfo = EVENT_TZ) -> dt.datetime:
    """La hora actual, o la simulada si el usuario está en modo prueba con reloj fijado."""
    sb = actual()
    if sb and sb.reloj is not None and sb.reloj_fijado is not None:
        return (sb.reloj + dt.timedelta(seconds=time.time() - sb.reloj_fijado)).astimezone(tz)
    return dt.datetime.now(tz)


def info(sb: Sandbox | None, sede: dict | None) -> dict | None:
    """Lo que ve la PWA (franja de modo prueba, ubicación simulada) y el admin."""
    if sb is None:
        return None
    with activar(sb):
        hora = ahora()
    return {"stt": sb.stt, "llm": sb.llm, "now": hora.isoformat(), "simulated_clock": sb.reloj is not None,
            "location": sede}


# ---------- persistencia (columna users.prueba, jsonb) ----------

def desde_usuario(user: dict | None) -> Sandbox | None:
    """El sandbox de un usuario según su fila en users; None si no está en modo prueba."""
    if not user or not user.get("modo_prueba"):
        return None
    cfg = user.get("prueba") or {}
    reloj = cfg.get("reloj")
    return Sandbox(
        username=user["username"],
        stt=cfg.get("stt") if cfg.get("stt") in PROVEEDORES else "fake",
        llm=cfg.get("llm") if cfg.get("llm") in PROVEEDORES else "fake",
        reloj=dt.datetime.fromisoformat(reloj) if reloj else None,
        reloj_fijado=cfg.get("reloj_fijado"),
        id_sede=cfg.get("id_sede"),
    )


def config_json(*, stt: str, llm: str, reloj: dt.datetime | None, id_sede: int | None) -> dict:
    """Lo que se guarda en users.prueba. El reloj queda anclado al momento en que se guarda."""
    return {"stt": stt, "llm": llm, "reloj": reloj.isoformat() if reloj else None,
            "reloj_fijado": time.time() if reloj else None, "id_sede": id_sede}
