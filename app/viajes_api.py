"""API de Viajes: vuelos y hoteles cargados a mano y las preferencias de sus avisos (app/vuelos.py, app/viajes_avisos.py)."""
import datetime as dt
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from . import vuelos
from .auth import auth

router = APIRouter(prefix="/api/viajes", dependencies=[Depends(auth)])

_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class VueloIn(BaseModel):
    numero: str = Field(max_length=12)
    aerolinea: str = Field(default="", max_length=60)
    fecha: dt.date
    hora: str | None = None
    zona: str = vuelos.ZONA_VUELO_DEFECTO

    @field_validator("numero")
    @classmethod
    def _numero(cls, v: str) -> str:
        return vuelos.normalizar_numero(v)

    @field_validator("hora")
    @classmethod
    def _hora(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not _HORA.match(v):
            raise ValueError("La hora tiene que ser HH:MM")
        return v

    @field_validator("zona")
    @classmethod
    def _zona(cls, v: str) -> str:
        if v not in vuelos.ZONAS:
            raise ValueError("Zona horaria no disponible")
        return v


class HotelIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    direccion: str = Field(default="", max_length=200)
    checkin: dt.datetime
    checkout: dt.datetime
    zona: str = vuelos.ZONA_HOTEL_DEFECTO

    @field_validator("zona")
    @classmethod
    def _zona(cls, v: str) -> str:
        if v not in vuelos.ZONAS:
            raise ValueError("Zona horaria no disponible")
        return v

    @model_validator(mode="after")
    def _orden(self):
        if self.checkin.tzinfo or self.checkout.tzinfo:
            raise ValueError("Las horas son locales del hotel, sin zona")
        if self.checkout <= self.checkin:
            raise ValueError("El check-out tiene que ser después del check-in")
        return self


class PreferenciasViajes(BaseModel):
    viajes_checkin: bool
    viajes_hoteles: bool
    viajes_estado: bool


def _vuelo_publico(v: dict) -> dict:
    sale = vuelos.salida(v)
    abre = vuelos.abre_checkin(v)
    return {"id": v["id"], "numero": v["numero"], "aerolinea": v["aerolinea"], "fecha": v["fecha"], "hora": v["hora"],
            "zona": v["zona"], "zona_nombre": vuelos.ZONAS.get(v["zona"], v["zona"]),
            "salida": sale.astimezone(vuelos.zona(v["zona"])).strftime("%Y-%m-%dT%H:%M") if sale else None,
            "checkin_abre": abre.astimezone(vuelos.zona(v["zona"])).strftime("%Y-%m-%dT%H:%M") if abre else None,
            "checkin_horas": vuelos.horas_checkin(v["numero"]), "checkin_url": vuelos.url_checkin(v["numero"]),
            "demora_min": v["demora_min"], "puerta": v["puerta"], "terminal": v["terminal"], "estado": v["estado"]}


def _hotel_publico(h: dict) -> dict:
    return {k: h[k] for k in ("id", "nombre", "direccion", "checkin", "checkout", "zona")} | {
        "zona_nombre": vuelos.ZONAS.get(h["zona"], h["zona"])}


@router.get("")
def listar(username: str = Depends(auth)):
    return {"vuelos": [_vuelo_publico(v) for v in vuelos.listar_vuelos(username)],
            "hoteles": [_hotel_publico(h) for h in vuelos.listar_hoteles(username)],
            "estado_disponible": vuelos.estado_disponible(),
            "zonas": [{"id": k, "nombre": n} for k, n in vuelos.ZONAS.items()],
            "preferencias": vuelos.get_prefs(username)}


@router.post("/vuelos", status_code=201)
def agregar_vuelo(body: VueloIn, username: str = Depends(auth)):
    v = vuelos.agregar_vuelo(username, body.numero, body.aerolinea.strip(), body.fecha.isoformat(), body.hora, body.zona)
    if not v:
        raise HTTPException(409, "Ya cargaste demasiados vuelos: quitá alguno")
    return _vuelo_publico(v)


@router.delete("/vuelos/{id_}")
def quitar_vuelo(id_: str, username: str = Depends(auth)):
    if not vuelos.quitar_vuelo(username, id_):
        raise HTTPException(404, "No encontramos ese vuelo")
    return {"ok": True}


@router.post("/hoteles", status_code=201)
def agregar_hotel(body: HotelIn, username: str = Depends(auth)):
    h = vuelos.agregar_hotel(username, body.nombre.strip(), body.direccion.strip(),
                             body.checkin.strftime("%Y-%m-%dT%H:%M"), body.checkout.strftime("%Y-%m-%dT%H:%M"), body.zona)
    if not h:
        raise HTTPException(409, "Ya cargaste demasiados hoteles: quitá alguno")
    return _hotel_publico(h)


@router.delete("/hoteles/{id_}")
def quitar_hotel(id_: str, username: str = Depends(auth)):
    if not vuelos.quitar_hotel(username, id_):
        raise HTTPException(404, "No encontramos ese hotel")
    return {"ok": True}


@router.get("/preferencias")
def get_preferencias(username: str = Depends(auth)):
    return vuelos.get_prefs(username)


@router.put("/preferencias")
def put_preferencias(body: PreferenciasViajes, username: str = Depends(auth)):
    return vuelos.set_prefs(username, body.model_dump())
