"""API de la sección Eventos (networking alrededor de re:Invent)."""
from fastapi import APIRouter, Depends, HTTPException

from . import events, itinerary
from .auth import auth

router = APIRouter(prefix="/api/events")


def _mine(username: str) -> dict[str, dict]:
    """Lo que el usuario tiene en el itinerario, por código (para marcar "en tu itinerario" y choques)."""
    return {c["code"]: c for d in itinerary.get_current(username)["days"] for c in d["sessions"]}


@router.get("")
def list_events(username: str = Depends(auth)):
    mine = _mine(username)
    return {"days": [{"day": d["day"], "events": [{**e, "in_itinerary": e["code"] in mine} for e in d["events"]]}
                     for d in events.by_day()]}


@router.get("/{code}")
def get_event(code: str, username: str = Depends(auth)):
    ev = events.get(code)
    if not ev:
        raise HTTPException(404, "Evento inexistente")
    mine = _mine(username)
    same_day = [c for c in mine.values() if c["day"] == ev["day"] and c["code"] != code and c.get("start")]
    start, end = itinerary._span(ev)
    clashes = [{"code": c["code"], "title": c["title"], "start": c["start"], "kind": c.get("kind")}
               for c in same_day if (s := itinerary._span(c)) and s[0] < end and start < s[1]]
    return {**ev, "in_itinerary": code in mine, "clashes": clashes}
