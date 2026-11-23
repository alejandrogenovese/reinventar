"""GET /api/novedades?desde=X.Y.Z: las versiones del CHANGELOG posteriores a la que tiene la PWA (ver app/novedades.py)."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from . import novedades
from .auth import auth

log = logging.getLogger("reinventar.novedades")
router = APIRouter(prefix="/api/novedades", dependencies=[Depends(auth)])

SEMVER = r"^\d{1,6}\.\d{1,6}\.\d{1,6}$"


@router.get("")
def novedades_desde(desde: str = Query(..., pattern=SEMVER, max_length=20)):
    try:
        return novedades.posteriores(novedades.semver(desde))
    except OSError:
        log.exception("novedades: no se pudo leer %s", novedades.CHANGELOG)
        raise HTTPException(503, "Las novedades no están disponibles en este momento") from None
