"""Eventos de networking (reinvent.evento, los carga scripts/cargar_eventos.py), en memoria como el catálogo.

Las tarjetas tienen el mismo formato que las de charlas (day, start, end, venue con lat/lng) para que el itinerario,
"Hoy" y el mapa las traten igual; kind = "event" las distingue.
"""
import logging
from zoneinfo import ZoneInfo

import psycopg

from . import pg, sandbox

log = logging.getLogger("reinventar.events")
EVENT_TZ = ZoneInfo("America/Los_Angeles")

_LOAD_SQL = """
SELECT e.id_evento, e.plataforma, e.url, e.nombre, e.inicio, e.fin, e.imagen_url, e.lat, e.lng, e.lugar, e.direccion,
       e.direccion_exacta, e.google_place_id, e.descripcion, e.resumen_es, e.tipo, e.temas, e.organizadores,
       e.anotados, e.lleno, e.precio, e.requiere_aprobacion, s.nombre AS sede_cercana, e.metros_a_sede{extra}
FROM reinvent.evento e
LEFT JOIN reinvent.sede s ON s.id_sede = e.id_sede_cercana
ORDER BY e.inicio, e.nombre
"""

# Columnas de la revisión automática (migración 007): sin ellas (base sin migrar) la app sigue con lo de antes.
_EXTRA = ", e.cancelado_desde, e.alta"

_events: dict[str, dict] = {}


def _card(r: dict) -> dict:
    inicio, fin = r["inicio"].astimezone(EVENT_TZ), r["fin"].astimezone(EVENT_TZ) if r["fin"] else None
    lat = float(r["lat"]) if r["lat"] is not None else None
    return {
        "kind": "event", "code": r["id_evento"], "base": r["id_evento"], "title": r["nombre"],
        "type": r["tipo"], "day": inicio.strftime("%Y-%m-%d"), "start": inicio.strftime("%H:%M"),
        "end": fin.strftime("%H:%M") if fin else None,
        "venue": {"hotel": r["lugar"] or "Las Vegas", "detail": r["direccion"] or "", "lat": lat,
                  "lng": float(r["lng"]) if r["lng"] is not None else None, "address": r["direccion"],
                  "exact": r["direccion_exacta"], "place_id": r["google_place_id"]},
        "image": r["imagen_url"], "summary": r["resumen_es"], "description": r["descripcion"],
        "topics": list(r["temas"] or []), "organizers": list(r["organizadores"] or []),
        "guests": r["anotados"] or None, "full": r["lleno"], "price": r["precio"], "approval": r["requiere_aprobacion"],
        "url": r["url"], "platform": r["plataforma"],
        "near": {"name": r["sede_cercana"], "meters": r["metros_a_sede"]} if r["sede_cercana"] else None,
        "cancelled": r.get("cancelado_desde") is not None,
        "added": r["alta"].timestamp() if r.get("alta") else None,
    }


def _leer() -> list[dict]:
    with pg.pool().connection() as c:
        try:
            return c.execute(_LOAD_SQL.format(extra=_EXTRA)).fetchall()
        except psycopg.errors.UndefinedColumn:
            c.rollback()
            log.warning("reinvent.evento sin las columnas de la revisión automática (falta la migración 007)")
            return c.execute(_LOAD_SQL.format(extra="")).fetchall()


@sandbox.en_real
def load() -> int:
    """(Re)carga los eventos. Si la tabla todavía no existe (base sin sincronizar), la app sigue sin eventos."""
    global _events
    try:
        rows = _leer()
    except psycopg.errors.UndefinedTable:
        log.warning("reinvent.evento no existe todavía: la sección Eventos queda vacía hasta el próximo sync")
        rows = []
    _events = {r["id_evento"]: _card(r) for r in rows}
    log.info("Eventos cargados: %d", len(_events))
    return len(_events)


def get(code: str) -> dict | None:
    return _events.get(code)


def nuevos_desde(desde: float) -> list[dict]:
    """Los eventos que encontró la revisión automática después de `desde` (time.time()), sin los cancelados."""
    return sorted((e for e in _events.values() if (e.get("added") or 0) > desde and not e.get("cancelled")),
                  key=lambda e: e["added"])


def by_day() -> list[dict]:
    """[{day, events}] en orden, para la pestaña Eventos."""
    days: dict[str, list[dict]] = {}
    for e in _events.values():
        days.setdefault(e["day"], []).append(e)
    return [{"day": d, "events": days[d]} for d in sorted(days)]
