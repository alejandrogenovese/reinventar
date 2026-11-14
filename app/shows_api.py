"""API de los shows de Ticketmaster (pestaña Shows de Eventos). Sin la key, `enabled: false` y nada más."""
from fastapi import APIRouter, Depends, HTTPException

from . import itinerary, shows
from .auth import auth

router = APIRouter(prefix="/api/shows")


def _mine(username: str) -> dict[str, dict]:
    return {c["code"]: c for d in itinerary.get_current(username)["days"] for c in d["sessions"]}


def _marcar(show: dict, mine: dict[str, dict]) -> dict:
    funciones = [{**f, "in_itinerary": f["code"] in mine} for f in show["functions"]]
    return {**show, "functions": funciones, "in_itinerary": any(f["in_itinerary"] for f in funciones)}


@router.get("")
def list_shows(username: str = Depends(auth)):
    if not shows.habilitado():
        return {"enabled": False, "days": []}
    mine = _mine(username)
    return {"enabled": True, "days": [{"day": d["day"], "shows": [_marcar(s, mine) for s in d["shows"]]}
                                      for d in shows.by_day()]}


@router.get("/{id_show}")
def get_show(id_show: str, username: str = Depends(auth)):
    s = shows.show(id_show) if shows.habilitado() else None
    if not s:
        raise HTTPException(404, "Show inexistente")
    return _marcar(s, _mine(username))
