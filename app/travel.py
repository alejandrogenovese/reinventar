"""Minutos caminando entre sedes de re:Invent, para los avisos del armado del día ("si salís 30 min antes llegás").

El dato medido sale de reinvent.sede_tiempo (Routes API, una sola vez: scripts/calcular_tiempos_sedes.py) y lo carga
catalog.load. Si un par no está medido, se estima por línea recta con un factor de rodeo, igual que la PWA sin Routes.
"""
import math
from dataclasses import dataclass

from . import venues

MISMA_SEDE_MIN = 5       # cambiar de sala dentro del mismo edificio
FACTOR_RODEO = 1.4       # caminando se recorre más que la línea recta
METROS_POR_MIN = 75      # paso tranquilo (el mismo de web/js/location.js)
RADIO_TIERRA_M = 6_371_000

EXISTE_SQL = "SELECT to_regclass('reinvent.sede_tiempo') IS NOT NULL AS existe"
LOAD_SQL = "SELECT id_origen, id_destino, minutos FROM reinvent.sede_tiempo"

_minutos: dict[tuple[int, int], int] = {}


@dataclass(frozen=True)
class Viaje:
    minutos: int
    estimado: bool  # True: el par no está medido y se calculó por línea recta


def load(rows) -> None:
    """Reemplaza los tiempos medidos en memoria. rows: dicts con id_origen, id_destino y minutos."""
    global _minutos
    _minutos = {(r["id_origen"], r["id_destino"]): int(r["minutos"]) for r in rows}


def metros(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distancia en línea recta (haversine) entre (lat, lng)."""
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    x = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(math.sqrt(x))


def estimar_minutos(a: tuple[float, float], b: tuple[float, float]) -> int:
    """Minutos caminando estimados por línea recta con rodeo; como mínimo 1."""
    return max(1, math.ceil(metros(a, b) * FACTOR_RODEO / METROS_POR_MIN))


def _coordenadas(id_sede: int) -> tuple[float, float] | None:
    sede = venues.by_id(id_sede)
    if not sede or sede["lat"] is None:
        return None
    return sede["lat"], sede["lng"]


def viaje(origen: int | None, destino: int | None) -> Viaje | None:
    """Minutos de una sede a otra. None si falta alguna sede o no tiene coordenadas (Various Locations)."""
    if origen is None or destino is None:
        return None
    if origen == destino:
        return Viaje(MISMA_SEDE_MIN, estimado=False)
    medido = _minutos.get((origen, destino))
    if medido is not None:
        return Viaje(medido, estimado=False)
    a, b = _coordenadas(origen), _coordenadas(destino)
    if a is None or b is None:
        return None
    return Viaje(estimar_minutos(a, b), estimado=True)
