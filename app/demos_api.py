"""API de la galería de demos: la lista pública con links firmados y la carga de videos e índice (solo admin)."""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Request

from . import cuerpo, demos
from .auth import admin

log = logging.getLogger("reinventar.demos")
router = APIRouter()

MAX_ARCHIVO_BYTES = 50 * 1024 * 1024  # un demo compuesto pesa 1-3 MB: sobra
SIN_BUCKET = "El bucket de demos no está configurado (DEMOS_S3_*)"
ERROR_BUCKET = "No pudimos cargar las demos: probá de nuevo en un rato"
RESPUESTAS_ADMIN = {502: {"description": "El bucket de demos no respondió"}, 503: {"description": SIN_BUCKET}}


def _bucket_o_503():
    almacen = demos.obtener()
    if almacen is None:
        raise HTTPException(503, SIN_BUCKET)
    return almacen


@router.get("/api/demos", responses={502: {"description": ERROR_BUCKET}})
def listar_demos():
    """Pública (la galería no pide login): sin bucket dice que no hay demos; con bucket, los links firmados."""
    almacen = demos.obtener()
    if almacen is None:
        return {"disponible": False, "demos": []}
    try:
        return {"disponible": True, "demos": demos.con_links(almacen, demos.leer_indice(almacen))}
    except (demos.IndiceInvalido, httpx.HTTPError) as e:
        log.exception("No se pudo leer el índice de demos")
        raise HTTPException(502, ERROR_BUCKET) from e


@router.put("/api/admin/demos/archivos/{nombre}", responses=RESPUESTAS_ADMIN)
async def subir_archivo(request: Request, nombre: str = Path(pattern=demos.NOMBRE_ARCHIVO.pattern),
                        _admin: str = Depends(admin)):
    almacen = _bucket_o_503()
    datos = await cuerpo.leer_con_tope(request, MAX_ARCHIVO_BYTES)
    try:
        almacen.guardar(nombre, datos, demos.tipo_de(nombre))
    except httpx.HTTPError as e:
        log.exception("No se pudo subir %s al bucket de demos", nombre)
        raise HTTPException(502, "No se pudo guardar el archivo en el bucket de demos") from e
    return {"ok": True, "nombre": nombre, "bytes": len(datos)}


@router.put("/api/admin/demos/indice", responses=RESPUESTAS_ADMIN)
def guardar_indice(lista: list[demos.Demo], _admin: str = Depends(admin)):
    almacen = _bucket_o_503()
    try:
        demos.guardar_indice(almacen, lista)
    except httpx.HTTPError as e:
        log.exception("No se pudo guardar el índice de demos")
        raise HTTPException(502, "No se pudo guardar el índice en el bucket de demos") from e
    return {"ok": True, "demos": len(lista)}
