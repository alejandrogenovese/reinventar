"""API del conversor › «Leer con la cámara» (app/conversor.py). Apagada salvo CONVERSOR_FOTO=1: apagada, la foto da 503
y /estado dice que no, así el botón no se muestra. Solo imágenes JPEG, PNG o WebP de hasta 2 MB, con cupo por usuario.
La foto no se guarda ni se loguea: solo su tamaño y el tipo de error, si falla."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from . import config, conversor, limites, llm
from . import cuerpo as cuerpo_mod
from .auth import auth
from .gastos_api import MULTIPART_SOBRANTE, TIPOS_FOTO, tipo_por_firma

log = logging.getLogger("reinventar.conversor")

router = APIRouter(prefix="/api/conversor", dependencies=[Depends(auth)])

FOTO_MAX_BYTES = 2 * 1024 * 1024
MSG_GRANDE = "La foto pesa más de 2 MB"
MSG_APAGADO = "La lectura con cámara no está disponible."
MSG_NO_LEIDA = "No pude leer la foto. Probá de nuevo."


@router.get("/estado")
def estado():
    return {"foto": config.CONVERSOR_FOTO}


@router.post("/foto")
async def leer_foto(request: Request, username: str = Depends(auth)):
    if not config.CONVERSOR_FOTO:
        raise HTTPException(503, MSG_APAGADO)
    limites.exigir_cupo(limites.fotos_conversor, username, "lectura de fotos")
    cuerpo = await cuerpo_mod.leer_con_tope(request, FOTO_MAX_BYTES + MULTIPART_SOBRANTE, MSG_GRANDE)
    parte = (cuerpo_mod.partes_multipart(request.headers.get("content-type", ""), cuerpo) or {}).get("foto")
    if parte is None:
        raise HTTPException(422, "Falta el campo «foto»")
    declarado, datos = parte
    if len(datos) > FOTO_MAX_BYTES:
        raise HTTPException(413, MSG_GRANDE)
    real = tipo_por_firma(datos)
    if declarado not in TIPOS_FOTO or real is None or real != declarado:
        raise HTTPException(415, "La foto tiene que ser una imagen JPEG, PNG o WebP")
    try:
        return await run_in_threadpool(conversor.leer, llm.Imagen(real, datos))
    except Exception as e:  # el detalle puede traer la respuesta del proveedor: solo el tipo y el tamaño
        log.warning("No se pudo leer una foto del conversor (%s, %d bytes)", type(e).__name__, len(datos))
        raise HTTPException(502, MSG_NO_LEIDA) from None
