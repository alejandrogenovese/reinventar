"""Endpoints de «Tu re:Invent en números»: agregados del catálogo y de la semana de cada persona (ver app/numeros.py)."""
from fastapi import APIRouter, Depends

from . import db, itinerary, numeros, sandbox
from .auth import auth

router = APIRouter(prefix="/api/numeros", dependencies=[Depends(auth)])


def _hoy() -> str:
    """El día de hoy en Las Vegas (o el del reloj simulado, en modo prueba), para resaltarlo en los gráficos."""
    return sandbox.ahora().date().isoformat()


@router.get("/catalogo")
def numeros_catalogo():
    return {**numeros.catalogo()["resumen"], "hoy": _hoy()}


@router.get("/mio")
def numeros_mio(username: str = Depends(auth)):
    cache = numeros.catalogo()
    agenda = itinerary.get_current(username)["days"]
    ficha = db.get_interview(username)["ficha"]
    return {**numeros.resumen_agenda(agenda, ficha, cache["textos"], cache["por_claves"]),
            "grabado": db.grabado_por(username), "hoy": _hoy()}
