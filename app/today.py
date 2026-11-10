"""Pantalla Hoy: a partir del itinerario, qué charla está pasando ahora, cuál sigue y el resto del día.

Los horarios del catálogo están en hora de Las Vegas, así que "ahora" se calcula en esa zona.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from . import itinerary, sandbox, talks

EVENT_TZ = ZoneInfo("America/Los_Angeles")


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _with_end(card: dict) -> dict:
    if card.get("end"):  # ya calculado por el itinerario (o el de la fuente, en eventos)
        return {**card, "recording_kind": talks.recording_kind(card.get("type"))}
    end = itinerary._minutes(card["start"]) + itinerary._duration(card.get("type") or "")
    return {**card, "end": _hhmm(end), "recording_kind": talks.recording_kind(card.get("type"))}


def plan(days: list[dict], now: datetime) -> dict:
    """`days` es el itinerario (`[{day, sessions}]`); `now`, la hora local del evento."""
    date, time = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    minute = now.hour * 60 + now.minute

    todays = [_with_end(s) for d in days if d["day"] == date for s in d["sessions"] if s.get("start")]
    current = [s for s in todays if itinerary._minutes(s["start"]) <= minute < itinerary._minutes(s["end"])]
    pending = [s for s in todays if itinerary._minutes(s["start"]) > minute]

    upcoming = None
    if not current and not pending:
        future = [d for d in days if d["day"] > date and d["sessions"]]
        if future:
            upcoming = {"day": future[0]["day"], "first": _with_end(future[0]["sessions"][0])}

    return {
        "date": date, "time": time,
        "now": current[-1] if current else None,
        "next": pending[0] if pending else None,
        "later": pending[1:],
        "upcoming": upcoming,
    }


def for_user(username: str) -> dict:
    return plan(itinerary.get_current(username)["days"], sandbox.ahora(EVENT_TZ))
