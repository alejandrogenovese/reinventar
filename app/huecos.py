"""Huecos sin audio de una grabación: tramos en que Android le sacó el micrófono a la app (una llamada, otra app que
graba) y quedaron en silencio. El cliente los detecta y los manda; la pantalla de la grabación y el export markdown
los muestran en su lugar.

POST /api/sessions/{sid}/huecos  {"huecos": [{"desde": 126.0, "hasta": 160.5}]}  (segundos desde el inicio)
Reemplaza la lista entera, así que repetirlo es inocuo. Solo la persona que grabó. Se guardan en sessions.huecos
(JSON, como expected_parts); el GET de la sesión los devuelve ordenados, o [] si no hay.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from . import db
from .auth import auth

router = APIRouter(prefix="/api/sessions/{sid}/huecos")

MAX_HUECOS = 200
MAX_SEGUNDOS = 6 * 3600  # ninguna grabación dura más


class Hueco(BaseModel):
    desde: float = Field(ge=0, allow_inf_nan=False)
    hasta: float = Field(le=MAX_SEGUNDOS, allow_inf_nan=False)

    @model_validator(mode="after")
    def _desde_antes_que_hasta(self) -> "Hueco":
        if self.desde >= self.hasta:
            raise ValueError("desde tiene que ser menor que hasta")
        return self


class Huecos(BaseModel):
    huecos: list[Hueco] = Field(max_length=MAX_HUECOS)


def mmss(segundos: float) -> str:
    """mm:ss, con los minutos que hagan falta (pasada la hora no se pasa a horas: 61:40)."""
    total = int(segundos)
    return f"{total // 60:02d}:{total % 60:02d}"


def marca(hueco: dict) -> str:
    return f"— sin audio {mmss(hueco['desde'])}–{mmss(hueco['hasta'])} —"


@router.post("")
def guardar(sid: str, body: Huecos, username: str = Depends(auth)):
    s = db.get_session(sid)
    if not s:
        raise HTTPException(404, "Sesión inexistente")
    if s.get("created_by") != username:
        raise HTTPException(403, "Solo quien grabó puede cambiar los huecos")
    lista = sorted(({"desde": h.desde, "hasta": h.hasta} for h in body.huecos), key=lambda h: (h["desde"], h["hasta"]))
    db.update_session(sid, huecos=lista)
    return {"huecos": lista}
