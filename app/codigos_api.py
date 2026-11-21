"""Endpoints de «Mis códigos de Excel»: subir la lista, ver el cruce con el catálogo y el itinerario, y borrarla.

El archivo viaja como cuerpo del pedido (igual que /api/itinerary/import-ics), con el nombre en `?nombre=`: no hace
falta python-multipart para un solo archivo. La lista se guarda por usuario en `codigos_deseados`; subir otra reemplaza."""
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from . import catalog, codigos_excel, cuerpo, db
from .auth import auth
from .codigos_excel import ArchivoInvalido, Codigo

router = APIRouter(prefix="/api/codigos", dependencies=[Depends(auth)])
SIN_LISTA = {"lista": False}


def _guardar(username: str, codigos: list[Codigo], archivo: str) -> None:
    """Reemplaza la lista de la persona (borrar e insertar en la misma transacción)."""
    ahora = time.time()
    filas = [(username, c.completo, c.base, i, archivo, ahora) for i, c in enumerate(codigos)]
    with db.conn() as c:
        c.execute("DELETE FROM codigos_deseados WHERE username=%s", (username,))
        c.cursor().executemany("INSERT INTO codigos_deseados (username, codigo, base, orden, archivo, subido_en) "
                               "VALUES (%s,%s,%s,%s,%s,%s)", filas)


def _leer(username: str) -> list[dict]:
    with db.conn() as c:
        rows = c.execute("SELECT codigo, base, archivo, subido_en FROM codigos_deseados WHERE username=%s ORDER BY orden",
                         (username,)).fetchall()
    return [dict(r) for r in rows]


def _registrados(username: str) -> list[dict]:
    """Las charlas del itinerario con la reserva marcada: lo que la persona ya registró en el portal de AWS."""
    return [{"code": it["code"], "base": it["base"]} for it in db.list_itinerary_items(username)
            if it.get("kind", "talk") == "talk" and it.get("reservada")]


def _resultado(username: str) -> dict:
    filas = _leer(username)
    if not filas:
        return SIN_LISTA
    try:
        sesiones = {s["base"]: s for s in catalog.all_sessions()}
    except catalog.CatalogUnavailable as e:
        raise HTTPException(503, "El catálogo no está disponible ahora. Probá de nuevo en un rato.") from e
    deseados = [Codigo(f["base"], f["codigo"]) for f in filas]
    return {"lista": True, "archivo": filas[0]["archivo"], "subido_en": filas[0]["subido_en"],
            **codigos_excel.cruzar(deseados, sesiones, _registrados(username))}


@router.post("")
async def subir(request: Request, nombre: str = Query("", max_length=255), username: str = Depends(auth)):
    datos = await cuerpo.leer_con_tope(request, codigos_excel.MAX_BYTES, "El archivo es demasiado grande (máximo 1 MB).")
    try:
        codigos = codigos_excel.extraer_codigos(datos, nombre)
    except ArchivoInvalido as e:
        raise HTTPException(422, str(e)) from e
    _guardar(username, codigos, nombre)
    return _resultado(username)


@router.get("")
def ver(username: str = Depends(auth)):
    return _resultado(username)


@router.delete("")
def borrar(username: str = Depends(auth)):
    with db.conn() as c:
        c.execute("DELETE FROM codigos_deseados WHERE username=%s", (username,))
    return SIN_LISTA
