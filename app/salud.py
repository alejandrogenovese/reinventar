"""Los chequeos de /health que NO cambian el código de estado: solo booleanos para el monitoreo (UptimeRobot).

Postgres y disco siguen en app/main.py y son los únicos que dan 503: si una API externa (el gateway LiteLLM) se cae,
Railway no tiene que tumbar deploys ni reinicios. Acá no va nada sensible (ni URLs ni claves) y nada sale a la red por
pedido: el gateway y la cotización se prueban en un ejecutor aparte, con timeout, y quedan cacheados CACHE_S.
"""
import asyncio
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import catalog, config, cotizacion, healthcheck, pipeline, push

log = logging.getLogger("reinventar.salud")

# El hilo de avisos late al empezar y al terminar cada vuelta, y espera push.TICK_SECONDS (60 s) entre vueltas. Una
# vuelta larga (ofertas cada 6 h con red, muchos usuarios) puede tardar minutos: 20 min sin latido es que se trabó o
# se murió.
PUSH_SIN_VUELTA_MAX_S = 20 * 60
# Lo que se espera al gateway LiteLLM (/health/liveliness) y a la cotización (una consulta a la base).
LLM_GATEWAY_TIMEOUT_S = 2
COTIZACION_TIMEOUT_S = 2
# Cuánto vale un resultado del gateway o de la cotización: con UptimeRobot cada 5 min, se prueba como mucho una vez
# por minuto y el resto de los pedidos contesta del caché (rápido).
CACHE_S = 60

# Ejecutores propios: si el gateway se cuelga, no traba los de Postgres y disco de /health ni el threadpool de la app.
_EJECUTOR_GATEWAY = ThreadPoolExecutor(max_workers=1, thread_name_prefix="health-gateway")
_EJECUTOR_COTIZACION = ThreadPoolExecutor(max_workers=1, thread_name_prefix="health-cotizacion")


@dataclass(frozen=True)
class _Resultado:
    ok: bool
    at: float  # time.monotonic() de la prueba


_cache: dict[str, _Resultado] = {}


def limpiar_cache() -> None:
    _cache.clear()


def _hilo_vivo(nombre: str) -> bool:
    return any(t.name == nombre and t.is_alive() for t in threading.enumerate())


def push_al_dia(ahora: float | None = None) -> bool:
    """Sin claves VAPID el push está apagado por config: no es falla."""
    if not push.enabled():
        return True
    latido = push.latido()
    ahora = time.monotonic() if ahora is None else ahora
    return latido is not None and ahora - latido < PUSH_SIN_VUELTA_MAX_S


def revision_viva(nombre_hilo: str) -> bool:
    """Las revisiones de catálogo y eventos solo corren con EVENTOS_AUTO=1; apagadas por config no es falla."""
    return not config.EVENTOS_AUTO or _hilo_vivo(nombre_hilo)


def _probar_gateway() -> bool:
    healthcheck.litellm_vivo(LLM_GATEWAY_TIMEOUT_S)  # tira si no responde 200
    return True


def _probar_cotizacion() -> bool:
    return cotizacion.actual()["oficial"] > 0  # la guardada o, sin ninguna, la de respaldo


async def _cacheado(nombre: str, ejecutor: ThreadPoolExecutor, prueba: Callable[[], bool], timeout: float) -> bool:
    previo = _cache.get(nombre)
    if previo and time.monotonic() - previo.at < CACHE_S:
        return previo.ok
    try:
        ok = bool(await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(ejecutor, prueba), timeout))
    except Exception as e:  # noqa: BLE001 - cualquier falla (timeout incluido) es "no anda"; el detalle, solo al log
        log.warning("Health: falló %s (%s)", nombre, type(e).__name__)
        ok = False
    _cache[nombre] = _Resultado(ok, time.monotonic())
    return ok


async def llm_gateway() -> bool:
    """Si el LLM no va por LiteLLM, no hay gateway que mirar."""
    if config.LLM_PROVIDER != "litellm":
        return True
    return await _cacheado("llm_gateway", _EJECUTOR_GATEWAY, _probar_gateway, LLM_GATEWAY_TIMEOUT_S)


async def cotizacion_disponible() -> bool:
    return await _cacheado("cotizacion", _EJECUTOR_COTIZACION, _probar_cotizacion, COTIZACION_TIMEOUT_S)


async def chequeos_seguros() -> dict[str, bool]:
    """Los chequeos, o {} si algo explota: /health nunca da 500 por el monitoreo (todo_ok queda en false)."""
    try:
        return await chequeos()
    except Exception:  # noqa: BLE001 - el detalle va al log; el status sigue dependiendo de Postgres y disco
        log.exception("Health: fallaron los chequeos de monitoreo")
        return {}


async def chequeos() -> dict[str, bool]:
    gateway, cotiza = await asyncio.gather(llm_gateway(), cotizacion_disponible())
    return {
        "pipeline": pipeline.vivo(),
        "push": push_al_dia(),
        "catalogo": catalog.cargadas() > 0,
        "revision_catalogo": revision_viva("charlas-auto"),
        "revision_eventos": revision_viva("eventos-auto"),
        "cotizacion": cotiza,
        "llm_gateway": gateway,
    }
