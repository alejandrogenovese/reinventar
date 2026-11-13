"""Sede reciente para el recordatorio "¿la grabás?" (app/recordatorio.py).

El celular calcula en qué sede está (web/js/location.js) y manda solo su número, o null si no está en ninguna: nunca
coordenadas. Se guarda una fila por persona que se sobreescribe, se ignora a los 45 min y se borra a las 2 h. Solo con la
preferencia "Usar en qué sede estoy" prendida (viene apagada).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from . import db, limites, venues
from .auth import auth

router = APIRouter(prefix="/api/ubicacion")

# El celular la manda como mucho cada 5 min; esto frena a un cliente que se desboque (cada pedido escribe en la base).
REPORTES_POR_HORA = 60
_reportes = limites.Limite(REPORTES_POR_HORA, ventana=3600)


class Ubicacion(BaseModel):
    model_config = ConfigDict(extra="forbid")  # un body con lat/lng se rechaza: acá no entran coordenadas

    id_sede: int | None


@router.post("")
def reportar(body: Ubicacion, username: str = Depends(auth)):
    if not db.get_preferencias_avisos(username)["ubicacion"]:
        raise HTTPException(403, "Prendé «Usar en qué sede estoy» en Ajustes › Notificaciones")
    if body.id_sede is not None and venues.by_id(body.id_sede) is None:
        raise HTTPException(422, "Sede desconocida")
    if _reportes.excedido(username):
        raise HTTPException(429, "Demasiados reportes de ubicación: probá en un rato")
    _reportes.sumar(username)
    db.set_ubicacion(username, body.id_sede)
    return {"ok": True}


@router.delete("")
def borrar(username: str = Depends(auth)):
    db.delete_ubicacion(username)
    return {"ok": True}
