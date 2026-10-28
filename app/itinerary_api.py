"""Endpoints de catálogo e itinerario: recomendación de sesiones de re:Invent y armado de agenda."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import catalog, config, db, itinerary
from .auth import auth

router = APIRouter(dependencies=[Depends(auth)])


class Profile(BaseModel):
    role: str = Field("", max_length=200)
    experience: str = Field("", max_length=200)
    interests: list[str] = Field(default_factory=list)


class Generate(BaseModel):
    profile: Profile
    prompt: str = Field("", max_length=2000)


class AddItem(BaseModel):
    code: str = Field(min_length=1, max_length=40)


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


@router.get("/api/itinerary")
def get_itinerary(username: str = Depends(auth)):
    return itinerary.get_current(username)


@router.post("/api/itinerary/items")
def add_item(body: AddItem, username: str = Depends(auth)):
    try:
        return itinerary.add_manual(username, body.code.strip())
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/api/itinerary/items/{code}/lock")
def lock_item(code: str, locked: bool = True, username: str = Depends(auth)):
    return itinerary.set_lock(username, code, locked)


@router.delete("/api/itinerary/items/{code}")
def remove_item(code: str, username: str = Depends(auth)):
    return itinerary.remove(username, code)
