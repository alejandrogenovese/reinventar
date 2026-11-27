"""API de «Personas que conocí» (app/personas.py). Todo exige sesión y cada persona ve solo lo suyo: un id que no es de
ella da 404, igual que uno que no existe."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from . import limites
from . import personas as pc
from .auth import auth

router = APIRouter(prefix="/api/personas", dependencies=[Depends(auth)])

NO_ENCONTRADA = "No encontramos esa persona"


@router.get("")
def listar(username: str = Depends(auth)):
    return {"personas": pc.listar(username)}


@router.put("/{id_}")
def guardar(id_: UUID, body: pc.PersonaEntrada, username: str = Depends(auth)):
    """Alta o edición. Solo un id nuevo gasta cuota y cuenta para el tope; reenviar el mismo alta no."""
    if not pc.existe(username, id_):
        if pc.cantidad(username) >= pc.TOPE_POR_PERSONA:
            raise HTTPException(409, f"Ya tenés {pc.TOPE_POR_PERSONA} personas cargadas: borrá alguna")
        limites.exigir_cupo(limites.personas_nuevas, username, "altas de personas")
    return pc.guardar(username, id_, body)


@router.delete("/{id_}")
def borrar(id_: UUID, username: str = Depends(auth)):
    if not pc.borrar(username, id_):
        raise HTTPException(404, NO_ENCONTRADA)
    return {"ok": True}
