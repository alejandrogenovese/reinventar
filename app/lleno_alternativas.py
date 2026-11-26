"""«Está llena»: otras charlas cerca para aprovechar el rato. Puro: recibe la charla llena (una card del catálogo), las
sesiones y la hora del evento; no consulta la base. Los avisos de lleno los cruza app/lleno_api.py.

Cerca en el tiempo: hoy, que empiecen dentro de VENTANA_MIN o que hayan empezado hace poco, siempre que caminando
llegues con no más de ATRASO_MAX_MIN de atraso y antes de que termine.
Cerca en el espacio: la misma sede o una a MAX_TRASLADO_MIN caminando como mucho (app/travel.py: medido o estimado).
Se supone que la persona está en la puerta de la charla llena, así que se camina desde esa sede.
Cómo ir (con_rutas): a las pocas que se muestran se les agrega el tiempo real de Google y la recomendación corta
(shuttle, monorail, puente) de app/rutas.py.
"""
import datetime as dt
from collections.abc import Iterable

from . import catalog, itinerary, lleno, rutas, travel, venues

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
            "day": card["day"], "start": card["start"], "walk_in": card["walk_in"],
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


def con_rutas(origen: dict, alternativas: list[dict]) -> list[dict]:
    """Las alternativas con `ruta` (la recomendación corta o None) y, si Google respondió, los minutos caminando reales.
    Una sola consulta para todas; sin Routes API quedan los minutos de app/travel.py. El shuttle se ofrece solo si corre
    a la hora de inicio de cada charla sugerida, el día de esa charla (hoy, la hora del evento de app/sandbox.py)."""
    id_origen, nombre_origen = _id_sede(origen), (origen.get("venue") or {}).get("hotel")
    destinos = {a["code"]: venues.id_by_name(a["venue"]["hotel"]) for a in alternativas if not a["misma_sede"]}
    cuandos = {a["code"]: rutas.momento(a.get("day"), a["start"]) for a in alternativas}
    primera = min((c for c in cuandos.values() if c), default=None)
    medido = rutas.medir(id_origen, destinos.values(), primera) if destinos else {}
    out = []
    for a in alternativas:
        m = medido.get(destinos.get(a["code"]))
        real = {"minutos": m.caminando_min, "estimado": False} if m and m.caminando_min else {}
        caminando = real.get("minutos", a["minutos"])
        ruta = None if a["misma_sede"] else rutas.recomendar(nombre_origen, a["venue"]["hotel"], caminando,
                                                                m.transporte_min if m else None, cuandos[a["code"]])
        out.append({**a, **real, "ruta": ruta})
    return out
