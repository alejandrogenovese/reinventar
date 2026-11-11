"""Endpoints de Mis eventos y del autocompletar de lugares (Google Places)."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from . import my_events, places
from .auth import auth
from .my_events import MiEvento

log = logging.getLogger("reinventar.my_events")
router = APIRouter(dependencies=[Depends(auth)])


def _guardar(accion, *args) -> dict:
    try:
        return accion(*args)
    except my_events.EventoInexistente as e:
        raise HTTPException(404, str(e)) from e
    except places.PlacesNoDisponible as e:
        log.warning("Places no disponible al ubicar un evento: %s", e)
        raise HTTPException(503, "No pude ubicar el lugar con Google; probá con una sede o escribí la dirección.") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/api/my-events")
def list_my_events(username: str = Depends(auth)):
    return {"eventos": my_events.listar(username)}


@router.post("/api/my-events")
def create_my_event(body: MiEvento, username: str = Depends(auth)):
    return _guardar(my_events.crear, username, body)


@router.put("/api/my-events/{id_}")
def edit_my_event(id_: str, body: MiEvento, username: str = Depends(auth)):
    return _guardar(my_events.editar, username, id_, body)


@router.delete("/api/my-events/{id_}")
def delete_my_event(id_: str, username: str = Depends(auth)):
    try:
        my_events.borrar(username, id_)
    except my_events.EventoInexistente as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True}


@router.get("/api/places/autocomplete")
def autocomplete(q: str = Query(min_length=3, max_length=100), sesion: Optional[str] = Query(None, max_length=64)):
    try:
        return {"lugares": places.autocomplete(q.strip(), sesion)}
    except places.PlacesNoDisponible as e:
        log.warning("Autocompletar de Places no disponible: %s", e)
        raise HTTPException(503, "El autocompletar de lugares no está disponible; elegí una sede o escribí la dirección.") from e
