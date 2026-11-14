"""Shows de Ticketmaster (reinvent.show_funcion, los mantiene app/ticketmaster.py), en memoria como los eventos.

Cada función es una tarjeta con el mismo formato que las de charlas y eventos (day, start, end, venue con lat/lng),
así el itinerario, Hoy, los avisos y el mapa la tratan igual; kind = "show" la distingue y su código es "tm-<id>".
La lista agrupa las funciones por show (artista o nombre + sala).
"""
import datetime as dt
import logging
from zoneinfo import ZoneInfo

import psycopg

from . import config, pg, sandbox, ticketmaster
from .travel import metros

log = logging.getLogger("reinventar.shows")
EVENT_TZ = ZoneInfo("America/Los_Angeles")
PREFIJO = "tm-"
TIPOS = {"musica": "Música", "teatro": "Teatro y shows", "comedia": "Comedia", "deportes": "Deportes",
         "actividades": "Actividades"}
# Ticketmaster no publica cuánto dura: se estima por tipo (para superposiciones y la cuenta regresiva).
_DURACION_MIN = {"musica": 120, "deportes": 150}
_DURACION_DEFAULT_MIN = 90

_LOAD_SQL = """
SELECT id_funcion, id_show, nombre, artista, tipo, sala, direccion, lat, lng, inicio, estado, precio_desde,
       imagen_url, url
FROM reinvent.show_funcion
ORDER BY inicio, nombre
"""
_SEDES_SQL = "SELECT nombre, lat, lng FROM reinvent.sede WHERE lat IS NOT NULL"

_funciones: dict[str, dict] = {}


def habilitado() -> bool:
    """Sin la key de Ticketmaster la pestaña Shows no aparece (lo que haya en la base sigue en los itinerarios)."""
    return bool(config.TICKETMASTER_API_KEY)


def _cercana(lat: float | None, lng: float | None, sedes: list[tuple[str, float, float]]) -> dict | None:
    if lat is None or lng is None or not sedes:
        return None
    nombre, dist = min(((n, metros((lat, lng), (la, ln))) for n, la, ln in sedes), key=lambda t: t[1])
    return {"name": nombre, "meters": round(dist)}


def _card(r: dict, sedes: list[tuple[str, float, float]]) -> dict:
    inicio = r["inicio"].astimezone(EVENT_TZ)
    fin = inicio + dt.timedelta(minutes=_DURACION_MIN.get(r["tipo"], _DURACION_DEFAULT_MIN))
    lat = float(r["lat"]) if r["lat"] is not None else None
    lng = float(r["lng"]) if r["lng"] is not None else None
    code = f"{PREFIJO}{r['id_funcion']}"
    return {
        "kind": "show", "code": code, "base": code, "show": r["id_show"], "title": r["nombre"],
        "artist": r["artista"], "tipo": r["tipo"], "type": TIPOS.get(r["tipo"], "Actividades"),
        "day": inicio.strftime("%Y-%m-%d"), "start": inicio.strftime("%H:%M"),
        "end": fin.strftime("%H:%M") if fin.date() == inicio.date() else "23:59",
        "venue": {"hotel": r["sala"], "detail": "", "lat": lat, "lng": lng, "address": r["direccion"], "exact": True,
                  "place_id": None},
        "status": r["estado"], "cancelled": r["estado"] == "canceled", "postponed": r["estado"] == "postponed",
        "price_from": float(r["precio_desde"]) if r["precio_desde"] is not None else None,
        "image": r["imagen_url"], "url": r["url"], "near": _cercana(lat, lng, sedes),
    }


def _leer() -> tuple[list[dict], list[tuple[str, float, float]]]:
    with pg.pool().connection() as c:
        filas = c.execute(_LOAD_SQL).fetchall()
        sedes = [(r["nombre"], float(r["lat"]), float(r["lng"])) for r in c.execute(_SEDES_SQL).fetchall()]
    return filas, sedes


@sandbox.en_real
def load() -> int:
    """(Re)carga las funciones. Sin la tabla (falta la migración 009) la app sigue sin shows."""
    global _funciones
    try:
        filas, sedes = _leer()
    except psycopg.errors.UndefinedTable:
        log.warning("reinvent.show_funcion no existe todavía (falta la migración 009): sin shows")
        filas, sedes = [], []
    _funciones = {f"{PREFIJO}{r['id_funcion']}": _card(r, sedes) for r in filas}
    log.info("Funciones de shows cargadas: %d", len(_funciones))
    return len(_funciones)


def get(code: str) -> dict | None:
    return _funciones.get(code)


def _de_la_semana(c: dict) -> bool:
    desde, hasta = (m.astimezone(EVENT_TZ).strftime("%Y-%m-%d") for m in (ticketmaster.DESDE, ticketmaster.HASTA))
    return desde <= c["day"] <= hasta


def _resumen(funciones: list[dict]) -> dict:
    """La tarjeta de un show: lo de su primera función, el precio más bajo y sus funciones."""
    primera = funciones[0]
    precios = [f["price_from"] for f in funciones if f["price_from"] is not None]
    return {"id": primera["show"], "title": primera["title"], "artist": primera["artist"], "tipo": primera["tipo"],
            "type": primera["type"], "venue": primera["venue"], "near": primera["near"], "image": primera["image"],
            "url": primera["url"], "price_from": min(precios) if precios else None,
            "cancelled": all(f["cancelled"] for f in funciones), "functions": funciones}


def by_day() -> list[dict]:
    """[{day, shows}]: por día, los shows con sus funciones de ese día (las canceladas al final)."""
    dias: dict[str, dict[str, list[dict]]] = {}
    for f in sorted(_funciones.values(), key=lambda f: (f["day"], f["start"], f["title"])):
        if _de_la_semana(f):
            dias.setdefault(f["day"], {}).setdefault(f["show"], []).append(f)
    return [{"day": d, "shows": sorted((_resumen(fs) for fs in dias[d].values()), key=lambda s: s["cancelled"])}
            for d in sorted(dias)]


def show(id_show: str) -> dict | None:
    """Un show con todas sus funciones de la semana."""
    funciones = sorted((f for f in _funciones.values() if f["show"] == id_show and _de_la_semana(f)),
                       key=lambda f: (f["day"], f["start"]))
    return _resumen(funciones) if funciones else None
