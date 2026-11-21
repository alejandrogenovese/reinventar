"""Endpoints del control de gastos (ver app/gastos.py). Todo exige sesión y cada persona ve solo lo suyo.

La foto del ticket entra por multipart (campo "foto"). Se lee con un tope de bytes y se parsea a mano en vez de sumar
python-multipart: es un solo campo y no vale una dependencia nueva.
"""
import logging
from datetime import date
from email.message import Message
from email.parser import BytesParser
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from . import cotizacion, gastos, limites, tickets_almacen
from .auth import auth

log = logging.getLogger("reinventar.gastos")

router = APIRouter(prefix="/api/gastos", dependencies=[Depends(auth)])

FOTO_MAX_BYTES = 2 * 1024 * 1024
MULTIPART_SOBRANTE = 64 * 1024             # encabezados y delimitadores del multipart, además de la foto
TIPOS_FOTO = ("image/jpeg", "image/png", "image/webp")
SYNCS_POR_VENTANA = 300                    # el teléfono sincroniza al abrir y al cargar un gasto; esto frena a un script
FOTOS_POR_HORA = 120
_syncs = limites.Limite(SYNCS_POR_VENTANA, limites.VENTANA_CORTA)
_fotos = limites.Limite(FOTOS_POR_HORA, limites.VENTANA_LARGA)


def tipo_por_firma(datos: bytes) -> str | None:
    """El tipo de imagen según los primeros bytes (no se confía en el Content-Type que declara el cliente)."""
    if datos.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _leer_cuerpo(request: Request, tope: int) -> bytes:
    """El cuerpo del pedido, cortando con 413 apenas pasa el tope (también si el cliente miente en Content-Length)."""
    declarado = request.headers.get("content-length", "")
    if declarado.isdigit() and int(declarado) > tope:
        raise HTTPException(413, "La foto pesa más de 2 MB")
    partes: list[bytes] = []
    total = 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > tope:
            raise HTTPException(413, "La foto pesa más de 2 MB")
        partes.append(trozo)
    return b"".join(partes)


def extraer_foto(content_type: str, cuerpo: bytes) -> tuple[str, bytes] | None:
    """(Content-Type declarado, bytes) de la parte "foto" de un multipart/form-data, o None si no está."""
    cabecera = Message()
    cabecera["content-type"] = content_type
    if cabecera.get_content_type() != "multipart/form-data" or not cabecera.get_param("boundary"):
        return None
    delimitador = b"--" + str(cabecera.get_param("boundary")).encode()
    for parte in cuerpo.split(delimitador)[1:]:
        parte = parte.removeprefix(b"\r\n")
        corte = parte.find(b"\r\n\r\n")
        if corte < 0:
            continue
        encabezados = BytesParser().parsebytes(parte[: corte + 4])
        if encabezados.get_param("name", header="content-disposition") != "foto":
            continue
        return encabezados.get_content_type(), parte[corte + 4:].removesuffix(b"\r\n")
    return None


def _gasto_o_404(username: str, client_id: UUID) -> dict:
    fila = gastos.obtener(username, client_id)
    if fila is None:
        raise HTTPException(404, "Gasto no encontrado")
    return fila


@router.get("/cotizacion")
def get_cotizacion():
    c = cotizacion.actual()
    return {"oficial": float(c["oficial"]), "blue": float(c["blue"]), "tarjeta": float(c["tarjeta"]), "at": c["at"]}


@router.get("/export.csv")
def exportar(request: Request, username: str = Depends(auth)):
    cuerpo = gastos.exportar_csv(username, str(request.base_url))
    return Response(cuerpo, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="gastos-reintegrables.csv"'})


@router.get("/compartidos")
def get_compartidos(username: str = Depends(auth)):
    return gastos.compartidos(username)


@router.put("/presupuesto")
def put_presupuesto(body: gastos.Presupuesto, username: str = Depends(auth)):
    return gastos.guardar_presupuesto(username, body)


@router.post("/sync")
def sync(body: gastos.SyncPedido, username: str = Depends(auth)):
    limites.exigir_cupo(_syncs, username, "sincronización de gastos")
    return gastos.sincronizar(username, body.cambios, body.desde)


@router.get("")
def listar(desde: date | None = None, hasta: date | None = None, username: str = Depends(auth)):
    return gastos.listar(username, desde, hasta)


@router.post("/{client_id}/foto")
async def subir_foto(client_id: UUID, request: Request, username: str = Depends(auth)):
    limites.exigir_cupo(_fotos, username, "fotos de tickets")
    cuerpo = await _leer_cuerpo(request, FOTO_MAX_BYTES + MULTIPART_SOBRANTE)
    parte = extraer_foto(request.headers.get("content-type", ""), cuerpo)
    if parte is None:
        raise HTTPException(422, "Falta el campo «foto»")
    declarado, datos = parte
    if len(datos) > FOTO_MAX_BYTES:
        raise HTTPException(413, "La foto pesa más de 2 MB")
    real = tipo_por_firma(datos)
    if declarado not in TIPOS_FOTO or real is None or real != declarado:
        raise HTTPException(415, "La foto tiene que ser una imagen JPEG, PNG o WebP")
    return await run_in_threadpool(_guardar_foto, username, client_id, real, datos)


def _guardar_foto(username: str, client_id: UUID, tipo: str, datos: bytes) -> dict:
    anterior = _gasto_o_404(username, client_id)["foto_clave"]
    clave = tickets_almacen.clave_foto(username, str(client_id), tipo)
    almacen = tickets_almacen.obtener()
    try:
        almacen.guardar(clave, datos, tipo)
        if anterior and anterior != clave:
            almacen.borrar(anterior)
    except (httpx.HTTPError, OSError) as e:
        log.error("No se pudo guardar la foto del gasto %s: %s", client_id, e)
        raise HTTPException(502, "No se pudo guardar la foto. Probá de nuevo en un rato.") from e
    gastos.poner_foto(username, client_id, clave)
    return {"foto_url": gastos.url_foto(client_id)}


@router.get("/{client_id}/foto")
def ver_foto(client_id: UUID, username: str = Depends(auth)):
    clave = _gasto_o_404(username, client_id)["foto_clave"]
    if not clave:
        raise HTTPException(404, "Este gasto no tiene foto")
    try:
        datos = tickets_almacen.obtener().leer(clave)
    except (httpx.HTTPError, OSError) as e:
        log.error("No se pudo leer la foto del gasto %s: %s", client_id, e)
        raise HTTPException(502, "No se pudo traer la foto. Probá de nuevo en un rato.") from e
    tipo = tipo_por_firma(datos) if datos else None
    if tipo is None:
        raise HTTPException(404, "Este gasto no tiene foto")
    return Response(datos, media_type=tipo, headers={"Cache-Control": "private, max-age=3600",
                                                     "X-Content-Type-Options": "nosniff"})
