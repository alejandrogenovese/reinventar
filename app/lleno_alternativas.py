"""«Está llena»: otras charlas cerca para aprovechar el rato. Puro: recibe la charla llena (una card del catálogo), las
sesiones y la hora del evento; no consulta la base. Los avisos de lleno los cruza app/lleno_api.py.

Cerca en el tiempo: hoy, que empiecen dentro de VENTANA_MIN o que hayan empezado hace poco, siempre que caminando
llegues con no más de ATRASO_MAX_MIN de atraso y antes de que termine.
Cerca en el espacio: la misma sede o una a MAX_TRASLADO_MIN caminando como mucho (app/travel.py: medido o estimado).
Se supone que la persona está en la puerta de la charla llena, así que se camina desde esa sede.
"""
import datetime as dt
from collections.abc import Iterable

from . import catalog, itinerary, lleno, travel, venues

VENTANA_MIN = 60        # cuánto hacia adelante se buscan charlas que empiecen
ATRASO_MAX_MIN = 15     # se puede entrar a una charla que empezó hace un rato, no más
MAX_TRASLADO_MIN = 15   # minutos caminando entre sedes
MAX_SUGERENCIAS = 5


def _id_sede(card: dict) -> int | None:
    return venues.id_by_name((card.get("venue") or {}).get("hotel"))


def _sugerencia(session: dict, instance: dict, origen: int, minuto: int) -> dict | None:
    """La card resumida si la charla es alcanzable desde la sede de origen, o None."""
    if instance.get("cancelada") or not instance.get("st"):
        return None
    inicio = itinerary._minutes(instance["st"])
    if inicio > minuto + VENTANA_MIN:
        return None
    card = catalog.card(session, instance)
    destino = _id_sede(card)
    viaje = travel.viaje(origen, destino)
    if viaje is None or viaje.minutos > MAX_TRASLADO_MIN:
        return None
    llegada, fin = minuto + viaje.minutos, lleno._fin_min(session, instance)
    if llegada > inicio + ATRASO_MAX_MIN or llegada >= fin:
        return None
    venue = card["venue"] or {}
    return {"code": card["code"], "base": card["base"], "title": card["title"], "type": card["type"],
            "start": card["start"], "walk_in": card["walk_in"],
            "venue": {"hotel": venue.get("hotel"), "detail": venue.get("detail")},
            "minutos": viaje.minutos, "estimado": viaje.estimado, "misma_sede": origen == destino,
            "en_curso": inicio <= minuto}


def cercanas(origen: dict, sesiones: Iterable[dict], ahora: dt.datetime) -> list[dict]:
    """Charlas de hoy alcanzables desde la sede de `origen`, por hora de inicio y después por cercanía.
    Sin la sede de origen (Various Locations o fuera del maestro), []: no hay desde dónde medir."""
    id_origen = _id_sede(origen)
    if id_origen is None or venues.by_id(id_origen)["lat"] is None:
        return []
    hoy, minuto = ahora.strftime("%Y-%m-%d"), ahora.hour * 60 + ahora.minute
    candidatas = (_sugerencia(s, i, id_origen, minuto) for s in sesiones if s["base"] != origen["base"]
                  for i in s.get("instances", []) if i.get("d") == hoy)
    return sorted((c for c in candidatas if c), key=lambda c: (itinerary._minutes(c["start"]), c["minutos"]))
