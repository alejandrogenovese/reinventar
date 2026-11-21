"""API de ofertas: la lista de vigentes, el detalle, las preferencias de alertas y la carga manual (solo admin)."""
import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from . import ofertas, sandbox
from .auth import admin, auth, is_admin

router = APIRouter(prefix="/api/ofertas")

Categoria = Literal["shows", "comida", "compras", "otros"]


class OfertaManual(BaseModel):
    model_config = {"extra": "forbid"}
    titulo: str = Field(min_length=2, max_length=120)
    categoria: Categoria
    lugar: str | None = Field(default=None, max_length=120)
    desde: dt.datetime
    hasta: dt.datetime | None = None
    link: str | None = Field(default=None, max_length=2000, pattern=r"^https://\S+$")
    nota: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def _en_hora_de_las_vegas(self):
        """Sin zona horaria, la hora es la de Las Vegas (la de los eventos). La vigencia tiene que ser coherente."""
        desde = self.desde if self.desde.tzinfo else self.desde.replace(tzinfo=sandbox.EVENT_TZ)
        hasta = self.hasta.replace(tzinfo=sandbox.EVENT_TZ) if self.hasta and not self.hasta.tzinfo else self.hasta
        if hasta is not None and hasta <= desde:
            raise ValueError("La vigencia tiene que terminar después de empezar")
        self.desde, self.hasta = desde, hasta
        return self


class Preferencias(BaseModel):
    activas: bool
    categorias: list[Categoria] = Field(max_length=len(ofertas.CATEGORIAS))


@router.get("")
def listar(categoria: Categoria | None = None, username: str = Depends(auth)):
    lista = ofertas.vigentes(sandbox.ahora(), categoria)
    return {"ofertas": [o.a_json() for o in lista], "categorias": ofertas.CATEGORIAS, "es_admin": is_admin(username)}


@router.get("/preferencias")
def get_preferencias(username: str = Depends(auth)):
    return ofertas.preferencias(username)


@router.put("/preferencias")
def put_preferencias(body: Preferencias, username: str = Depends(auth)):
    return ofertas.guardar_preferencias(username, body.activas, body.categorias)


@router.get("/admin/lista")
def lista_admin(pasadas: bool = False, _admin: str = Depends(admin)):
    """Por defecto solo las que no vencieron; `pasadas=true` suma las vencidas. Con tope (ofertas.TOPE_LISTA_ADMIN)."""
    return {"ofertas": [o.a_json() for o in ofertas.lista_admin(sandbox.ahora(), pasadas)], "categorias": ofertas.CATEGORIAS}


@router.post("/admin", status_code=201)
def cargar(body: OfertaManual, _admin: str = Depends(admin)):
    return ofertas.crear_manual(body.model_dump(), sandbox.ahora()).a_json()


@router.delete("/admin/{id_oferta}")
def dar_de_baja(id_oferta: str, _admin: str = Depends(admin)):
    if not ofertas.borrar(id_oferta):
        raise HTTPException(404, "Oferta inexistente")
    return {"ok": True}


@router.get("/{id_oferta}")
def detalle(id_oferta: str, _username: str = Depends(auth)):
    o = ofertas.obtener(id_oferta)
    if not o:
        raise HTTPException(404, "Oferta inexistente")
    return o.a_json()
