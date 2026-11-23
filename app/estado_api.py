"""GET /api/estado: lo que alimenta el banner de estado de la PWA (reglas en app/estado.py).

Junta señales baratas (dos consultas a sessions, el hilo del pipeline, la tabla de revisiones de las fuentes y el
contador de fallas del LLM) y nunca llama a un modelo. La respuesta se guarda 60 s por contexto: «real» y «prueba»
(quien está en modo prueba ve las grabaciones de su schema de prueba, nunca datos de otros usuarios). Si una señal no
se puede leer, se registra en el log y esa regla no avisa: el banner nunca rompe por esto ni expone errores crudos.
"""
import logging
import threading
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends

from . import __version__, db, estado, eventos_auto, pipeline, sandbox
from .auth import auth

log = logging.getLogger("reinventar.estado")
router = APIRouter(prefix="/api/estado", dependencies=[Depends(auth)])

CACHE_S = 60
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _contexto() -> str:
    return "prueba" if sandbox.actual() else "real"


def _leer(nombre: str, leer: Callable):
    """El valor de la señal, o None si falló (queda en el log con el detalle; al usuario no le llega)."""
    try:
        return leer()
    except Exception:
        log.exception("estado: no se pudo leer la señal %s", nombre)
        return None


def _senales(contexto: str, ahora: float) -> estado.Senales:
    procesando = _leer("procesando", db.updated_at_en_proceso)
    eventos = _leer("eventos", eventos_auto.estado)
    return estado.Senales(
        ahora=ahora,
        pipeline_vivo=_leer("pipeline", pipeline.vivo),
        procesando=tuple(procesando) if procesando is not None else None,
        errores_ultima_hora=_leer("errores", lambda: db.errores_desde(ahora - estado.VENTANA_ERRORES_S)),
        fallas_llm=estado.fallas_llm(contexto, ahora),
        # Solo lo que usan las reglas: nada de links, detalles ni mensajes de error de las fuentes.
        eventos={k: eventos.get(k) for k in ("activo", "horas", "revisiones")} if eventos else None,
    )


def calcular(contexto: str, ahora: float | None = None) -> dict:
    momento = time.time() if ahora is None else ahora
    return {"version": __version__, "servicio": estado.servicio(_senales(contexto, momento)),
            "generado": estado.iso(momento)}


def reiniciar_cache() -> None:
    with _lock:
        _cache.clear()


@router.get("")
def estado_servicio():
    contexto, ahora = _contexto(), time.time()
    with _lock:
        guardado = _cache.get(contexto)
    if guardado and ahora - guardado[0] < CACHE_S:
        return guardado[1]
    respuesta = calcular(contexto, ahora)
    with _lock:
        _cache[contexto] = (ahora, respuesta)
    return respuesta
