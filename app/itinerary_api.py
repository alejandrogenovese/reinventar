"""Endpoints de catálogo e itinerario: recomendación de sesiones de re:Invent y armado de agenda."""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import anuncios, catalog, changes, config, db, ics, itinerary, missed, sandbox, today
from .auth import auth

router = APIRouter(dependencies=[Depends(auth)])

# Los intereses van al prompt del LLM: con tope, para que nadie infle la base ni el gasto de tokens.
MAX_INTERESES = 30
MAX_LARGO_INTERES = 80


class Profile(BaseModel):
    role: str = Field("", max_length=200)
    experience: str = Field("", max_length=200)
    interests: list[Annotated[str, Field(max_length=MAX_LARGO_INTERES)]] = Field(default_factory=list,
                                                                                  max_length=MAX_INTERESES)


class Generate(BaseModel):
    profile: Profile
    prompt: str = Field("", max_length=2000)


class AddItem(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    reason: Optional[str] = Field(None, max_length=400)  # la razón del armado guiado, si viene de ahí


class Swap(BaseModel):
    to: str = Field(min_length=1, max_length=40)


class Acknowledge(BaseModel):
    codes: list[str] = Field(max_length=200)


@router.get("/api/itinerary/missed/{code}")
def missed_options(code: str, username: str = Depends(auth)):
    """"Me la perdí": otros horarios de la charla y parecidas que empiezan pronto."""
    result = missed.options(username, code)
    if result is None:
        raise HTTPException(404, "Código de sesión inexistente")
    return result


@router.post("/api/itinerary/items/{code}/swap")
def swap_item(code: str, body: Swap, username: str = Depends(auth)):
    """"Cambiar a este": otro horario de la misma charla, conservando si estaba fijada."""
    try:
        return missed.swap(username, code, body.to.strip())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/itinerary/changes")
def get_changes(username: str = Depends(auth)):
    """Lo que cambió (sala, horario, baja, lleno) en lo que el usuario tiene en el itinerario."""
    return {"changes": changes.pending(username)}


@router.post("/api/itinerary/changes/ack")
def ack_changes(body: Acknowledge, username: str = Depends(auth)):
    return {"changes": changes.acknowledge(username, body.codes)}


@router.get("/api/today")
def get_today(username: str = Depends(auth)):
    return today.for_user(username)


@router.get("/api/anuncios")
def get_anuncios(username: str = Depends(auth)):
    """Anuncios sin reserva para Inicio (los que quedan hoy, sin los que ya están en el itinerario)."""
    days = itinerary.get_current(username)["days"]
    en_itinerario = {code for d in days for s in d["sessions"] for code in (s.get("code"), s.get("base")) if code}
    return anuncios.del_dia(sandbox.ahora(today.EVENT_TZ), en_itinerario)


@router.get("/api/maps-key")
def maps_key():
    return {"key": config.GOOGLE_MAPS_API_KEY}


@router.get("/api/catalog/meta")
def catalog_meta():
    return catalog.facets()


@router.get("/api/catalog/sessions")
def catalog_search(q: Optional[str] = None, day: Optional[str] = None, venue: Optional[str] = None,
                    topic: Optional[str] = None, aoi: Optional[str] = None, level: Optional[str] = None,
                    kind: Optional[str] = None, limit: int = 60):
    return catalog.search(q, day, venue, topic, aoi, level, kind, min(limit, 200))


@router.get("/api/catalog/sessions/{base}")
def catalog_detail(base: str):
    s = catalog.get_session(base)
    if not s:
        raise HTTPException(404, "Sesión inexistente")
    return s


@router.get("/api/itinerary/profile")
def get_profile(username: str = Depends(auth)):
    return db.get_profile(username) or {"role": "", "experience": "", "interests": [], "prompt": ""}


@router.post("/api/itinerary/generate")
def generate_itinerary(body: Generate, username: str = Depends(auth)):
    try:
        return itinerary.generate(username, body.profile.model_dump(), body.prompt.strip())
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/api/itinerary/calendar.ics")
def itinerary_calendar(username: str = Depends(auth)):
    """El itinerario para importar en el calendario del teléfono (con alarma de cola si no está reservada)."""
    cards = [c for d in itinerary.get_current(username)["days"] for c in d["sessions"]]
    return Response(ics.calendario(cards), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="reinvent-itinerario.ics"'})


@router.get("/api/itinerary")
def get_itinerary(username: str = Depends(auth)):
    return itinerary.get_current(username)


@router.post("/api/itinerary/items")
def add_item(body: AddItem, username: str = Depends(auth)):
    try:
        return itinerary.add_manual(username, body.code.strip(), body.reason)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/api/itinerary/items/{code}/lock")
def lock_item(code: str, locked: bool = True, username: str = Depends(auth)):
    return itinerary.set_lock(username, code, locked)


@router.delete("/api/itinerary/items/{code}")
def remove_item(code: str, username: str = Depends(auth)):
    return itinerary.remove(username, code)
