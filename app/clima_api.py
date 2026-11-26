"""GET /api/clima: el clima de Las Vegas para Hoy (app/clima.py). Con sesión, como el resto. Devuelve null si está
apagado o NWS no respondió y no hay un resumen reciente: Hoy simplemente no lo muestra."""
from fastapi import APIRouter, Depends

from . import clima
from .auth import auth

router = APIRouter(prefix="/api/clima", dependencies=[Depends(auth)])


@router.get("")
def clima_hoy():
    return clima.obtener()
