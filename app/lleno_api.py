"""Avisos «está llena / hay mucha cola» por horario (app/lleno.py)."""
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from . import catalog, db, limites, lleno, lleno_alternativas, sandbox
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


def _avisados(codes: list[str]) -> dict[str, str]:
    """Horarios con algún aviso vigente: «lleno» si alguien dijo que está llena, si no «cola»."""
    filas = db.reportes_lleno(codes, time.time() - lleno.VIGENCIA_MIN * 60)
    out: dict[str, str] = {}
    for f in filas:
        if out.get(f["code"]) != "lleno":
            out[f["code"]] = f["estado"]
    return out


def _llenos(codes: list[str]) -> set[str]:
    """Horarios con algún aviso vigente de «está llena» («mucha cola» no cuenta: todavía se puede entrar)."""
    return {c for c, estado in _avisados(codes).items() if estado == "lleno"}


@router.get("/{code}/alternativas")
def alternativas(code: str, username: str = Depends(auth)):
    """Si avisaron que el horario está lleno o con mucha cola, otras charlas cerca que empiezan ahora o en un rato, sin
    las que también avisaron llenas (app/lleno_alternativas.py). `motivo`: «lleno», «cola» o None si no hay avisos."""
    found = catalog.get_instance(code)
    if not found:
        raise HTTPException(404, "No encontramos ese horario")
    motivo = _avisados([code]).get(code)
    if not motivo:
        return {"motivo": None, "alternativas": []}
    cercanas = lleno_alternativas.cercanas(catalog.card(*found), catalog.all_sessions(), sandbox.ahora())
    llenas = _llenos([c["code"] for c in cercanas]) if cercanas else set()
    libres = [c for c in cercanas if c["code"] not in llenas]
    return {"motivo": motivo, "alternativas": libres[:lleno_alternativas.MAX_SUGERENCIAS]}


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
