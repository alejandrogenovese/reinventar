"""Avisos «está llena / hay mucha cola» por horario (app/lleno.py)."""
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from . import catalog, db, limites, lleno, sandbox
from .auth import auth

router = APIRouter(prefix="/api/lleno")

AVISOS_POR_HORA = 20  # una persona avisa unas pocas veces por charla: esto frena a quien quiera inflar el contador
_avisos = limites.Limite(AVISOS_POR_HORA, ventana=3600)


class Aviso(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estado: Literal["lleno", "cola"]


def _estado(codes: list[str], username: str) -> dict:
    ahora_ts, ahora = time.time(), sandbox.ahora()
    filas = db.reportes_lleno(codes, ahora_ts - lleno.VIGENCIA_MIN * 60)
    out = {}
    for code in codes:
        found = catalog.get_instance(code)
        if not found:
            continue
        session, instance = found
        out[code] = {**lleno.resumen([f for f in filas if f["code"] == code], username, ahora_ts),
                     "abierto": lleno.abierto(session, instance, ahora),
                     "pista": lleno.pista(catalog.card(session, instance))}
    return out


@router.get("")
def estado(codes: str = Query(..., max_length=600), username: str = Depends(auth)):
    lista = list(dict.fromkeys(c.strip() for c in codes.split(",") if c.strip()))
    if not lista or len(lista) > lleno.CODIGOS_POR_PEDIDO:
        raise HTTPException(422, f"Pasá entre 1 y {lleno.CODIGOS_POR_PEDIDO} códigos")
    return _estado(lista, username)


@router.post("/{code}")
def avisar(code: str, body: Aviso, username: str = Depends(auth)):
    found = catalog.get_instance(code)
    if not found:
        raise HTTPException(404, "No encontramos ese horario")
    if not lleno.abierto(*found, sandbox.ahora()):
        raise HTTPException(409, "Se puede avisar desde 45 minutos antes de que empiece hasta que termina")
    if _avisos.excedido(username):
        raise HTTPException(429, "Demasiados avisos: probá en un rato")
    _avisos.sumar(username)
    db.set_reporte_lleno(code, username, body.estado)
    return _estado([code], username)[code]


@router.delete("/{code}")
def retirar(code: str, username: str = Depends(auth)):
    db.delete_reporte_lleno(code, username)
    return _estado([code], username).get(code, {})
