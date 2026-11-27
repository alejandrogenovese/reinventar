"""«Dónde comer barato»: lugares cerca de donde estás (o de tu próxima sesión) con puntaje, reseñas, precio y minutos
caminando. Cada búsqueda a Google Places cuesta: se cachea por cuadrado de ~200 m (varias horas) y se limita por usuario.
Precio, distancia, abierto ahora, puntaje mínimo y orden se aplican acá sobre lo cacheado: cambiarlos no vuelve a
pegarle a Google. Lo único que suma una búsqueda es pasar de 15 minutos (otro radio) o pedir «abierto ahora» con
datos de más de media hora."""
import logging
import math
import threading
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from . import limites, places, sandbox, today, travel, venues, vuelos
from .auth import auth

log = logging.getLogger("reinventar.comer")
router = APIRouter(prefix="/api/comer")

CELDA_GRADOS = 0.0018        # ~200 m de lado en latitud
RADIO_BUSQUEDA_M = 1000      # cubre 15 min caminando (~800 m en línea recta) más el desvío del centro de la celda
RADIO_LEJOS_M = 1800         # cubre 30 min (~1,6 km en línea recta); Google trae 20 por pedido, así que se suma al cercano
MINUTOS_RADIO_CERCANO = 15
TTL_CACHE_S = 6 * 3600
TTL_ABIERTO_S = 30 * 60      # «abierto ahora» es lo único que cambia con la hora: pasado esto no se afirma
MAX_CACHE = 500              # cuadrados guardados; al pasarse se descartan los más viejos
BUSQUEDAS_POR_HORA = 20      # llamadas reales a Google por usuario
PRECIO_MAXIMO_DEFAULT = 2
PRECIO_MAXIMO = 4            # $$$$
MINUTOS_MAXIMOS = 30
MINUTOS_DEFAULT = 10
MAX_LUGARES = 20
# Orden: puntaje bayesiano (con pocas reseñas el puntaje se acerca al promedio general) menos un castigo por distancia.
RESENAS_PRIOR = 50
PUNTAJE_PRIOR = 4.0
CASTIGO_DISTANCIA = 0.5      # puntos que resta estar a la distancia máxima
METROS_MAXIMOS = MINUTOS_RADIO_CERCANO * travel.METROS_POR_MIN

SIN_ORIGEN = "Prendé la ubicación para ver dónde comer cerca."

Orden = Literal["recomendado", "cerca", "puntaje"]

_limite = limites.Limite(BUSQUEDAS_POR_HORA, ventana=3600)
Tipo = Literal["todo", "rapida", "dulces", "cafe", "restaurantes"]  # las claves de places.TIPOS_POR_CATEGORIA
_cache: dict[tuple[tuple[int, int], str, int], tuple[float, list[dict]]] = {}  # (cuadrado, tipo, radio)
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


def _en_cache(celda: tuple, fresco: bool = False) -> list[dict] | None:
    """fresco: hace falta saber si está abierto ahora, así que una entrada de más de media hora no sirve."""
    with _lock:
        hit = _cache.get(celda)
        if not hit:
            return None
        edad = time.monotonic() - hit[0]
        if edad >= TTL_CACHE_S or (fresco and edad >= TTL_ABIERTO_S):
            return None
        if edad < TTL_ABIERTO_S:
            return hit[1]
        return [{**lugar, "abierto": None} for lugar in hit[1]]


def _guardar(celda: tuple, lugares: list[dict]) -> None:
    if not lugares:  # una respuesta vacía puede ser un hipo de Google: no se queda 6 h
        return
    with _lock:
        if len(_cache) >= MAX_CACHE:
            del _cache[min(_cache, key=lambda k: _cache[k][0])]
        _cache[celda] = (time.monotonic(), lugares)


def _cercanos(lat: float, lng: float, usuario: str, tipo: str = "todo", minutos: int = MINUTOS_DEFAULT,
              fresco: bool = False) -> list[dict]:
    """Lo de Google para el cuadrado. Pasando los 15 min se suma una búsqueda de radio grande: Google trae como mucho
    20 por pedido, así que sola dejaría afuera lugares cerca."""
    cuadrado = _celda(lat, lng)
    lugares = _buscar(cuadrado, usuario, tipo, RADIO_BUSQUEDA_M, fresco)
    if minutos <= MINUTOS_RADIO_CERCANO:
        return lugares
    vistos = {lugar["place_id"] for lugar in lugares}
    return lugares + [lugar for lugar in _buscar(cuadrado, usuario, tipo, RADIO_LEJOS_M, fresco)
                      if lugar["place_id"] not in vistos]


def _buscar(cuadrado: tuple[int, int], usuario: str, tipo: str, radio: int, fresco: bool) -> list[dict]:
    clave = (cuadrado, tipo, radio)
    if (hit := _en_cache(clave, fresco)) is not None:
        return hit
    limites.exigir_cupo(_limite, usuario, "lugares para comer")
    incluir, excluir = places.TIPOS_POR_CATEGORIA.get(tipo, (None, None))
    try:
        lugares = places.nearby(*_centro(cuadrado), radio, tipos=incluir, excluir=excluir)
    except places.PlacesNoDisponible as e:
        log.warning("Places no disponible al buscar dónde comer: %s", e)
        raise HTTPException(503, "Dónde comer no está disponible por ahora. Probá de nuevo en un rato.") from e
    _guardar(clave, lugares)
    return lugares


def _origen_de_la_sesion(usuario: str) -> dict | None:
    plan = today.for_user(usuario)
    sesion = plan.get("next") or plan.get("now") or (plan.get("upcoming") or {}).get("first")
    venue = (sesion or {}).get("venue") or {}
    if venue.get("lat") is None or venue.get("lng") is None:
        return None
    return {"lat": venue["lat"], "lng": venue["lng"], "nombre": venue.get("hotel") or "tu próxima sesión",
            "fuente": "sesion"}


def _hotel_vigente(hoteles: list[dict], ahora: str) -> dict | None:
    """El hotel donde estás parando (check-in ≤ ahora < check-out, en hora local «YYYY-MM-DDTHH:MM»); si ninguno, el
    primero cargado."""
    return next((h for h in hoteles if h["checkin"] <= ahora < h["checkout"]), hoteles[0] if hoteles else None)


def _sede_del_hotel(nombre: str) -> dict | None:
    """Coordenadas del hotel si su nombre contiene el de una sede del maestro («The Venetian Resort» → Venetian). Los
    hoteles cargados en Viajes no tienen coordenadas propias: sin coincidencia, None."""
    texto = nombre.casefold()
    candidatas = [v for v in venues.all_venues() if v.get("lat") is not None and v.get("lng") is not None
                  and v.get("name") and v["name"].casefold() in texto]
    return max(candidatas, key=lambda v: len(v["name"]), default=None)  # la más específica: «MGM Grand» antes que «MGM»


def _origen_del_hotel(usuario: str) -> dict | None:
    """En días sin sesiones (o sin itinerario): desde el hotel cargado en Viajes, si se reconoce la sede."""
    try:
        hoteles = vuelos.listar_hoteles(usuario)
    except Exception:  # la base caída no tiene que tapar el mensaje útil de «prendé la ubicación»
        log.warning("no se pudieron leer los hoteles de %s para dónde comer", usuario, exc_info=True)
        return None
    ahora = sandbox.ahora(vuelos.zona(vuelos.ZONA_HOTEL_DEFECTO)).strftime("%Y-%m-%dT%H:%M")
    hotel = _hotel_vigente(hoteles, ahora)
    sede = _sede_del_hotel(hotel["nombre"]) if hotel else None
    if not sede:
        return None
    return {"lat": sede["lat"], "lng": sede["lng"], "nombre": hotel["nombre"], "fuente": "hotel"}


def _puntaje(lugar: dict) -> float:
    if not lugar["rating"]:
        return 0.0
    n = lugar["resenas"]
    bayes = (n * lugar["rating"] + RESENAS_PRIOR * PUNTAJE_PRIOR) / (n + RESENAS_PRIOR)
    return bayes - CASTIGO_DISTANCIA * lugar["metros"] / METROS_MAXIMOS


_ORDENES = {
    "recomendado": lambda lugar: -_puntaje(lugar),
    "cerca": lambda lugar: lugar["metros"],
    "puntaje": lambda lugar: (-(lugar["rating"] or 0), -lugar["resenas"]),
}


def _pasa(lugar: dict, precio_max: int, solo_abiertos: bool, puntaje_min: float) -> bool:
    if lugar["precio"] is not None and lugar["precio"] > precio_max:
        return False
    if solo_abiertos and lugar["abierto"] is not True:
        return False
    return not puntaje_min or (lugar["rating"] or 0) >= puntaje_min


def _armar(lugares: list[dict], origen: tuple[float, float], precio_max: int, minutos_max: int,
           solo_abiertos: bool = False, puntaje_min: float = 0, orden: str = "recomendado") -> list[dict]:
    out = []
    for lugar in lugares:
        destino = (lugar["lat"], lugar["lng"])
        minutos = travel.estimar_minutos(origen, destino)
        if minutos > minutos_max or not _pasa(lugar, precio_max, solo_abiertos, puntaje_min):
            continue
        out.append({**lugar, "minutos": minutos, "metros": round(travel.metros(origen, destino) * travel.FACTOR_RODEO)})
    return sorted(out, key=_ORDENES[orden])[:MAX_LUGARES]


@router.get("")
def donde_comer(lat: float | None = Query(None, ge=-90, le=90), lng: float | None = Query(None, ge=-180, le=180),
                precio: int = Query(PRECIO_MAXIMO_DEFAULT, ge=1, le=PRECIO_MAXIMO),
                minutos: int = Query(MINUTOS_DEFAULT, ge=1, le=MINUTOS_MAXIMOS), tipo: Tipo = "todo",
                abierto: bool = False, puntaje: float = Query(0, ge=0, le=5), orden: Orden = "recomendado",
                username: str = Depends(auth)):
    """Con lat y lng (el celular), desde ahí; sin ellos, desde la sede de la próxima sesión del itinerario y, si no hay
    (un día libre), desde el hotel cargado en Viajes.
    `precio`: máximo ($ = 1 … $$$$ = 4); los lugares sin dato de precio entran igual. `minutos`: máximo caminando.
    `tipo`: comida rápida, dulces, café o restaurantes (cada uno es otra búsqueda). `abierto`: solo los abiertos ahora.
    `puntaje`: mínimo de estrellas. `orden`: recomendado (puntaje y distancia), más cerca o mejor puntaje."""
    if (lat is None) != (lng is None):
        raise HTTPException(422, "Mandá lat y lng juntos.")
    if lat is not None:
        origen = {"lat": lat, "lng": lng, "nombre": None, "fuente": "telefono"}
    elif not (origen := _origen_de_la_sesion(username) or _origen_del_hotel(username)):
        raise HTTPException(404, SIN_ORIGEN)
    lugares = _cercanos(origen["lat"], origen["lng"], username, tipo, minutos, fresco=abierto)
    return {"origen": origen, "lugares": _armar(lugares, (origen["lat"], origen["lng"]), precio, minutos, abierto,
                                                puntaje, orden)}
