"""Actividades: dos pestañas para lo que no es re:Invent.

- Excursiones: productos de Viator (app/viator.py) para los días de la estadía. Sin VIATOR_API_KEY la pestaña no se
  muestra (`habilitado: false`) y no se pide nada; en el log queda un solo aviso informativo.
- Cerca: atracciones de Google Places (museos, parques, atracciones turísticas) ordenadas por distancia a donde estás o
  a la sede de tu próxima sesión, como «Dónde comer». La field mask pide solo campos del SKU Pro (sin puntajes ni
  reseñas) y la búsqueda se cachea por cuadrado y se limita por usuario.
"""
import logging
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from . import comer_api, limites, places, travel, viator
from .auth import auth

log = logging.getLogger("reinventar.actividades")
router = APIRouter(prefix="/api/actividades")

TIPOS_ATRACCIONES = ["tourist_attraction", "museum", "art_gallery", "amusement_center", "amusement_park", "aquarium",
                     "zoo", "park", "historical_landmark"]
CAMPOS_ATRACCIONES = ",".join(f"places.{c}" for c in (
    "id", "displayName", "location", "formattedAddress", "googleMapsUri", "primaryTypeDisplayName"))
RADIO_BUSQUEDA_M = 5000      # en Las Vegas lo interesante está a unos minutos en auto o en monorriel
TTL_CACHE_S = 24 * 3600      # una atracción no se muda: sin horarios ni puntajes, la lista dura un día
MAX_CACHE = 300
BUSQUEDAS_POR_HORA = 20
MAX_LUGARES = 20

_limite = limites.Limite(BUSQUEDAS_POR_HORA, ventana=3600)
_cache: dict[tuple[int, int], tuple[float, list[dict]]] = {}
_lock = threading.Lock()
_avisado_sin_clave = threading.Event()


def reiniciar() -> None:
    """Para los tests."""
    with _lock:
        _cache.clear()
    _limite.reiniciar()
    _avisado_sin_clave.clear()
    viator.reiniciar()


# ---- Excursiones (Viator) -----------------------------------------------------------------------------------------
def _viator_habilitado() -> bool:
    if viator.habilitado():
        return True
    if not _avisado_sin_clave.is_set():
        _avisado_sin_clave.set()
        log.info("Sin VIATOR_API_KEY: la pestaña Excursiones no se muestra")
    return False


@router.get("/estado")
def estado(username: str = Depends(auth)):
    """Barato (no le pega a nadie): la pantalla lo usa para decidir si muestra la pestaña Excursiones."""
    return {"excursiones": _viator_habilitado()}


@router.get("/excursiones")
def excursiones(pagina: int = Query(1, ge=1, le=viator.MAX_PAGINAS), username: str = Depends(auth)):
    """Una página de excursiones de Viator. Sin clave, `habilitado: false`; si Viator falla, 503 con un mensaje."""
    if not _viator_habilitado():
        return {"habilitado": False}
    try:
        return {"habilitado": True, **viator.excursiones(pagina)}
    except viator.ViatorNoDisponible as e:
        log.warning("Viator no disponible: %s", e)
        raise HTTPException(503, "Las excursiones no están disponibles por ahora. Probá de nuevo en un rato.") from e


# ---- Cerca (Google Places) ----------------------------------------------------------------------------------------
def _en_cache(celda: tuple[int, int]) -> list[dict] | None:
    with _lock:
        hit = _cache.get(celda)
    if not hit or time.monotonic() - hit[0] >= TTL_CACHE_S:
        return None
    return hit[1]


def _guardar(celda: tuple[int, int], lugares: list[dict]) -> None:
    if not lugares:
        return
    with _lock:
        if len(_cache) >= MAX_CACHE:
            del _cache[min(_cache, key=lambda k: _cache[k][0])]
        _cache[celda] = (time.monotonic(), lugares)


def _cercanas(lat: float, lng: float, usuario: str) -> list[dict]:
    celda = comer_api._celda(lat, lng)
    if (hit := _en_cache(celda)) is not None:
        return hit
    limites.exigir_cupo(_limite, usuario, "atracciones cercanas")
    try:
        lugares = places.nearby(*comer_api._centro(celda), RADIO_BUSQUEDA_M, tipos=TIPOS_ATRACCIONES,
                                campos=CAMPOS_ATRACCIONES)
    except places.PlacesNoDisponible as e:
        log.warning("Places no disponible al buscar atracciones: %s", e)
        raise HTTPException(503, "Las atracciones cercanas no están disponibles por ahora. Probá de nuevo en un rato.") from e
    _guardar(celda, lugares)
    return lugares


def _armar(lugares: list[dict], origen: tuple[float, float]) -> list[dict]:
    out = []
    for lugar in lugares:
        destino = (lugar["lat"], lugar["lng"])
        out.append({"place_id": lugar["place_id"], "nombre": lugar["nombre"], "direccion": lugar["direccion"],
                    "lat": lugar["lat"], "lng": lugar["lng"], "url": lugar["url"], "tipo": lugar.get("tipo"),
                    "minutos": travel.estimar_minutos(origen, destino),
                    "metros": round(travel.metros(origen, destino) * travel.FACTOR_RODEO)})
    return sorted(out, key=lambda x: x["metros"])[:MAX_LUGARES]


@router.get("/cerca")
def cerca(lat: float | None = Query(None, ge=-90, le=90), lng: float | None = Query(None, ge=-180, le=180),
          username: str = Depends(auth)):
    """Con lat y lng (el celular), desde ahí; sin ellos, desde la sede de la próxima sesión del itinerario."""
    if (lat is None) != (lng is None):
        raise HTTPException(422, "Mandá lat y lng juntos.")
    if lat is not None:
        origen = {"lat": lat, "lng": lng, "nombre": None, "fuente": "telefono"}
    elif not (origen := comer_api._origen_de_la_sesion(username)):
        raise HTTPException(404, "No sé desde dónde buscar: prendé la ubicación o agendá una sesión en una sede.")
    lugares = _cercanas(origen["lat"], origen["lng"], username)
    return {"origen": origen, "lugares": _armar(lugares, (origen["lat"], origen["lng"]))}
