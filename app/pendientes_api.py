"""API de los pendientes del viaje (app/viajes_pendientes.py). Un id que no es de la persona da 404, igual que uno que no
existe: no se distingue «no es tuyo» de «no está»."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field, field_validator

from . import viajes_pendientes as vp
from .auth import auth

router = APIRouter(prefix="/api/viajes/pendientes", dependencies=[Depends(auth)])

LARGO_MAX_ID = 32
IdPendiente = Path(min_length=1, max_length=LARGO_MAX_ID, pattern=r"^[0-9a-f]+$")
NO_ENCONTRADO = "No encontramos ese pendiente"


def _texto(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("Escribí el pendiente")
    return v


class PendienteIn(BaseModel):
    texto: str = Field(min_length=1, max_length=vp.LARGO_MAX_TEXTO)
    fecha_limite: dt.date | None = None

    @field_validator("texto")
    @classmethod
    def _limpiar(cls, v: str) -> str:
        return _texto(v)


class PendienteCambios(BaseModel):
    """Solo cambia lo que viene; fecha_limite: null la borra."""
    texto: str | None = Field(default=None, min_length=1, max_length=vp.LARGO_MAX_TEXTO)
    fecha_limite: dt.date | None = None
    orden: int | None = Field(default=None, ge=0, le=vp.ORDEN_MAX)

    @field_validator("texto")
    @classmethod
    def _limpiar(cls, v: str | None) -> str | None:
        return None if v is None else _texto(v)


def _o_404(item: dict | None) -> dict:
    if not item:
        raise HTTPException(404, NO_ENCONTRADO)
    return item


@router.get("")
def listar(username: str = Depends(auth)):
    return vp.listar(username)


@router.post("", status_code=201)
def agregar(body: PendienteIn, username: str = Depends(auth)):
    item = vp.agregar(username, body.texto, body.fecha_limite)
    if not item:
        raise HTTPException(409, "Ya tenés demasiados pendientes: borrá alguno")
    return item


@router.put("/{id_}")
def editar(body: PendienteCambios, id_: str = IdPendiente, username: str = Depends(auth)):
    campos = {k: getattr(body, k) for k in body.model_fields_set}
    if campos.get("texto", "") is None or campos.get("orden", 0) is None:
        raise HTTPException(422, "El texto y el orden no pueden quedar vacíos")
    return _o_404(vp.actualizar(username, id_, campos))


@router.post("/{id_}/hecho")
def marcar_hecho(id_: str = IdPendiente, username: str = Depends(auth)):
    return _o_404(vp.marcar_hecho(username, id_, True))


@router.delete("/{id_}/hecho")
def desmarcar_hecho(id_: str = IdPendiente, username: str = Depends(auth)):
    return _o_404(vp.marcar_hecho(username, id_, False))


@router.delete("/{id_}")
def borrar(id_: str = IdPendiente, username: str = Depends(auth)):
    if not vp.borrar(username, id_):
        raise HTTPException(404, NO_ENCONTRADO)
    return {"ok": True}
