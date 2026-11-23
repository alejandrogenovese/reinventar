"""API de «Charlas nuevas» (app/charlas_nuevas.py): la lista de la persona, agregar un horario a su itinerario (el mismo
agregado de siempre, que avisa con qué se superpone), descartar una charla y la preferencia del push."""
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from . import catalog, itinerary, sandbox
from . import charlas_nuevas as cn
from .auth import auth

router = APIRouter(prefix="/api/charlas-nuevas", dependencies=[Depends(auth)])

Base = Path(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9-]+$")
NO_ENCONTRADA = "No encontramos esa charla"


class Agregar(BaseModel):
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9-]+$")


class Preferencia(BaseModel):
    avisar: bool


@router.get("")
def listar(username: str = Depends(auth)):
    charlas = cn.pendientes(username, sandbox.ahora())
    return {"charlas": charlas, "total": len(charlas)}


@router.post("/agregar")
def agregar(body: Agregar, username: str = Depends(auth)):
    """Agrega ese horario al itinerario y la charla deja de aparecer en la lista. `choques`: los títulos de lo que se
    superpone ese día (vacío si no choca con nada)."""
    encontrada = catalog.get_instance(body.code)
    if not encontrada:
        raise HTTPException(404, NO_ENCONTRADA)
    actual = itinerary.add_manual(username, body.code, "Charla nueva del catálogo")
    cn.decidir(username, encontrada[0]["base"], cn.AGREGADA)
    agregada = next((c for d in actual["days"] for c in d["sessions"] if c.get("code") == body.code), {})
    return {"choques": agregada.get("overlaps") or []}


@router.post("/{base}/descartar")
def descartar(base: str = Base, username: str = Depends(auth)):
    if not catalog.get_session(base):
        raise HTTPException(404, NO_ENCONTRADA)
    cn.decidir(username, base, cn.DESCARTADA)
    return {"ok": True}


@router.get("/preferencia")
def preferencia(username: str = Depends(auth)):
    return {"avisar": cn.quiere_aviso(username)}


@router.put("/preferencia")
def guardar_preferencia(body: Preferencia, username: str = Depends(auth)):
    return {"avisar": cn.set_quiere_aviso(username, body.avisar)}
