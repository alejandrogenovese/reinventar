"""«Dónde comer barato»: lugares cerca de donde estás (o de tu próxima sesión) con puntaje, reseñas, precio y minutos
caminando. Cada búsqueda a Google Places cuesta: se cachea por cuadrado de ~200 m (varias horas) y se limita por usuario.
Los filtros de precio y distancia se aplican acá sobre lo cacheado, así cambiarlos no vuelve a pegarle a Google."""
import logging
import math
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from . import limites, places, today, travel
from .auth import auth

log = logging.getLogger("reinventar.comer")
router = APIRouter(prefix="/api/comer")

CELDA_GRADOS = 0.0018        # ~200 m de lado en latitud
RADIO_BUSQUEDA_M = 1000      # cubre 15 min caminando (~800 m en línea recta) más el desvío del centro de la celda
TTL_CACHE_S = 6 * 3600
TTL_ABIERTO_S = 30 * 60      # «abierto ahora» es lo único que cambia con la hora: pasado esto no se afirma
MAX_CACHE = 500              # cuadrados guardados; al pasarse se descartan los más viejos
BUSQUEDAS_POR_HORA = 20      # llamadas reales a Google por usuario
PRECIO_MAXIMO_DEFAULT = 2
MINUTOS_MAXIMOS = 15
MINUTOS_DEFAULT = 10
MAX_LUGARES = 20
# Orden: puntaje bayesiano (con pocas reseñas el puntaje se acerca al promedio general) menos un castigo por distancia.
RESENAS_PRIOR = 50
PUNTAJE_PRIOR = 4.0
CASTIGO_DISTANCIA = 0.5      # puntos que resta estar a la distancia máxima
METROS_MAXIMOS = MINUTOS_MAXIMOS * travel.METROS_POR_MIN

_limite = limites.Limite(BUSQUEDAS_POR_HORA, ventana=3600)
_cache: dict[tuple[int, int], tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def reiniciar() -> None:
    """Para los tests."""
    with _lock:
        _cache.clear()
    _limite.reiniciar()


def _celda(lat: float, lng: float) -> tuple[int, int]:
    paso_lng = CELDA_GRADOS / max(math.cos(math.radians(lat)), 0.01)
    return round(lat / CELDA_GRADOS), round(lng / paso_lng)


def _centro(celda: tuple[int, int]) -> tuple[float, float]:
    lat = celda[0] * CELDA_GRADOS
    return lat, celda[1] * CELDA_GRADOS / max(math.cos(math.radians(lat)), 0.01)


def _en_cache(celda: tuple[int, int]) -> list[dict] | None:
    with _lock:
        hit = _cache.get(celda)
        if not hit:
            return None
        edad = time.monotonic() - hit[0]
        if edad >= TTL_CACHE_S:
            return None
        if edad < TTL_ABIERTO_S:
            return hit[1]
        return [{**lugar, "abierto": None} for lugar in hit[1]]


def _guardar(celda: tuple[int, int], lugares: list[dict]) -> None:
    if not lugares:  # una respuesta vacía puede ser un hipo de Google: no se queda 6 h
        return
    with _lock:
        if len(_cache) >= MAX_CACHE:
            del _cache[min(_cache, key=lambda k: _cache[k][0])]
        _cache[celda] = (time.monotonic(), lugares)


def _cercanos(lat: float, lng: float, usuario: str) -> list[dict]:
    celda = _celda(lat, lng)
    if (hit := _en_cache(celda)) is not None:
        return hit
    limites.exigir_cupo(_limite, usuario, "lugares para comer")
    try:
        lugares = places.nearby(*_centro(celda), RADIO_BUSQUEDA_M)
    except places.PlacesNoDisponible as e:
        log.warning("Places no disponible al buscar dónde comer: %s", e)
        raise HTTPException(503, "Dónde comer no está disponible por ahora. Probá de nuevo en un rato.") from e
    _guardar(celda, lugares)
    return lugares


def _origen_de_la_sesion(usuario: str) -> dict | None:
    plan = today.for_user(usuario)
    sesion = plan.get("next") or plan.get("now") or (plan.get("upcoming") or {}).get("first")
    venue = (sesion or {}).get("venue") or {}
    if venue.get("lat") is None or venue.get("lng") is None:
        return None
    return {"lat": venue["lat"], "lng": venue["lng"], "nombre": venue.get("hotel") or "tu próxima sesión",
            "fuente": "sesion"}


def _puntaje(lugar: dict) -> float:
    if not lugar["rating"]:
        return 0.0
    n = lugar["resenas"]
    bayes = (n * lugar["rating"] + RESENAS_PRIOR * PUNTAJE_PRIOR) / (n + RESENAS_PRIOR)
    return bayes - CASTIGO_DISTANCIA * lugar["metros"] / METROS_MAXIMOS


def _armar(lugares: list[dict], origen: tuple[float, float], precio_max: int, minutos_max: int) -> list[dict]:
    out = []
    for lugar in lugares:
        destino = (lugar["lat"], lugar["lng"])
        minutos = travel.estimar_minutos(origen, destino)
        if minutos > minutos_max or (lugar["precio"] is not None and lugar["precio"] > precio_max):
            continue
        out.append({**lugar, "minutos": minutos, "metros": round(travel.metros(origen, destino) * travel.FACTOR_RODEO)})
    return sorted(out, key=_puntaje, reverse=True)[:MAX_LUGARES]


@router.get("")
def donde_comer(lat: float | None = Query(None, ge=-90, le=90), lng: float | None = Query(None, ge=-180, le=180),
                precio: int = Query(PRECIO_MAXIMO_DEFAULT, ge=1, le=2),
                minutos: int = Query(MINUTOS_DEFAULT, ge=1, le=MINUTOS_MAXIMOS), username: str = Depends(auth)):
    """Con lat y lng (el celular), desde ahí; sin ellos, desde la sede de la próxima sesión del itinerario. `precio` es el
    máximo ($ = 1, $$ = 2); los lugares sin dato de precio entran igual. `minutos` es el máximo caminando."""
    if (lat is None) != (lng is None):
        raise HTTPException(422, "Mandá lat y lng juntos.")
    if lat is not None:
        origen = {"lat": lat, "lng": lng, "nombre": None, "fuente": "telefono"}
    elif not (origen := _origen_de_la_sesion(username)):
        raise HTTPException(404, "No sé desde dónde buscar: prendé la ubicación o agendá una sesión en una sede.")
    lugares = _cercanos(origen["lat"], origen["lng"], username)
    return {"origen": origen, "lugares": _armar(lugares, (origen["lat"], origen["lng"]), precio, minutos)}
