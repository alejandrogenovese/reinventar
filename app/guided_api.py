"""Endpoints del armado guiado: qué sigue, pendientes ("☆ para otro día"), salir antes y reservada."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import cuerpo, db, guided, itinerary, reservas_aws
from .auth import auth

router = APIRouter(dependencies=[Depends(auth)])

_DIA = r"^\d{4}-\d{2}-\d{2}$"
_HORA = r"^([01]\d|2[0-3]):[0-5]\d$"
SALIR_ANTES_TOPE = 240  # una roja elegida puede recortar la anterior más de 30 min; más de 4 h no tiene sentido


class Next(BaseModel):
    day: str = Field(pattern=_DIA)
    after: str | None = Field(None, max_length=40)   # código de lo último elegido; sin esto, la primera del día
    desde: str | None = Field(None, pattern=_HORA)   # "arrancar más tarde"


class Pending(BaseModel):
    base: str = Field(min_length=1, max_length=40)
    day: str = Field(pattern=_DIA)


class LeaveEarly(BaseModel):
    minutos: int = Field(ge=0, le=SALIR_ANTES_TOPE)


class Booked(BaseModel):
    reservada: bool


@router.post("/api/itinerary/guided/next")
def guided_next(body: Next, username: str = Depends(auth)):
    try:
        return guided.opciones(username, body.day, body.after, body.desde)
    except guided.SinFicha as e:
        raise HTTPException(409, str(e)) from e
    except guided.ItemInexistente as e:
        raise HTTPException(404, str(e)) from e


@router.get("/api/itinerary/pending")
def list_pending(username: str = Depends(auth)):
    return {"pendientes": guided.pendientes(username)}


@router.post("/api/itinerary/pending")
def add_pending(body: Pending, username: str = Depends(auth)):
    try:
        guided.marcar_pendiente(username, body.base, body.day)
    except guided.ItemInexistente as e:
        raise HTTPException(404, str(e)) from e
    return {"pendientes": guided.pendientes(username)}


@router.delete("/api/itinerary/pending/{base}")
def remove_pending(base: str, username: str = Depends(auth)):
    db.remove_pending(username, base)
    return {"pendientes": guided.pendientes(username)}


@router.put("/api/itinerary/items/{code}/salir-antes")
def leave_early(code: str, body: LeaveEarly, username: str = Depends(auth)):
    if not db.set_item_leave_early(username, code, body.minutos):
        raise HTTPException(404, "No está en tu itinerario")
    return itinerary.get_current(username)


@router.put("/api/itinerary/items/{code}/reservada")
def booked(code: str, body: Booked, username: str = Depends(auth)):
    if not db.set_item_booked(username, code, body.reservada):
        raise HTTPException(404, "No está en tu itinerario")
    return itinerary.get_current(username)


@router.post("/api/itinerary/import-ics")
async def import_reservations(request: Request, username: str = Depends(auth)):
    """El .ics que exporta el portal de AWS → esas charlas al itinerario, fijadas y marcadas como reservadas."""
    data = await cuerpo.leer_con_tope(request, reservas_aws.MAX_BYTES)
    try:
        return reservas_aws.importar(username, data.decode("utf-8", errors="replace"))
    except reservas_aws.CalendarioInvalido as e:
        raise HTTPException(422, str(e)) from e
