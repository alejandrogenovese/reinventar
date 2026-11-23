"""Endpoints de «Mis códigos de Excel»: subir la lista, ver el cruce con el catálogo y el itinerario, y borrarla.

El archivo viaja como cuerpo del pedido (igual que /api/itinerary/import-ics), con el nombre en `?nombre=`: no hace
falta python-multipart para un solo archivo. La lista se guarda por usuario en `codigos_deseados`; subir otra reemplaza."""
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool

from . import catalog, codigos_ejemplo, codigos_excel, cuerpo, db, itinerary, limites
from .auth import auth
from .codigos_excel import ArchivoInvalido, Codigo

router = APIRouter(prefix="/api/codigos", dependencies=[Depends(auth)])
SIN_LISTA = {"lista": False}
SUBIDAS_POR_HORA = 10
_subidas = limites.Limite(SUBIDAS_POR_HORA, limites.VENTANA_LARGA)


def _guardar(username: str, codigos: list[Codigo], archivo: str) -> None:
    """Reemplaza la lista de la persona (borrar e insertar en la misma transacción)."""
    ahora = time.time()
    filas = [(username, c.completo, c.base, i, archivo, ahora) for i, c in enumerate(codigos)]
    with db.conn() as c:
        # Un lock por usuario hasta el commit: dos subidas simultáneas se hacen una atrás de la otra y no chocan en la clave primaria.
        c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("codigos_deseados:" + username,))
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


def _bases_en_itinerario(username: str) -> set[str]:
    return {it["base"] for it in db.list_itinerary_items(username) if it.get("kind", "talk") == "talk"}


def _con_itinerario(cruce: dict, en_itinerario: set[str]) -> dict:
    """Marca qué charlas de la lista ya están en el itinerario y cuántas se pueden agregar (las que existen y no están)."""
    codigos = [{**e, "en_itinerario": e["base"] in en_itinerario} for e in cruce["codigos"]]
    para_agregar = sum(e["estado"] != "inexistente" and not e["en_itinerario"] for e in codigos)
    return {**cruce, "codigos": codigos, "resumen": {**cruce["resumen"], "para_agregar": para_agregar}}


def _resultado(username: str) -> dict:
    filas = _leer(username)
    if not filas:
        return SIN_LISTA
    try:
        sesiones = {s["base"]: s for s in catalog.all_sessions()}
    except catalog.CatalogUnavailable as e:
        raise HTTPException(503, "El catálogo no está disponible ahora. Probá de nuevo en un rato.") from e
    deseados = [Codigo(f["base"], f["codigo"]) for f in filas]
    cruce = codigos_excel.cruzar(deseados, sesiones, _registrados(username))
    return {"lista": True, "archivo": filas[0]["archivo"], "subido_en": filas[0]["subido_en"],
            **_con_itinerario(cruce, _bases_en_itinerario(username))}


def _agregar_al_itinerario(username: str) -> dict:
    """Las charlas de la lista que existen y no están en el itinerario, en el horario que muestra el cruce."""
    actual = _resultado(username)
    if not actual["lista"]:
        raise HTTPException(404, "Todavía no subiste una lista de códigos.")
    faltan = [e for e in actual["codigos"] if e["estado"] != "inexistente" and not e["en_itinerario"] and e["instancia"]]
    for e in faltan:
        itinerary.agregar_charla(username, e["instancia"], reason="De tu lista de Excel")
    return {**_resultado(username), "agregadas": len(faltan)}


def _procesar(username: str, datos: bytes, nombre: str) -> dict:
    """Leer el archivo, guardar la lista y armar el cruce: trabajo bloqueante, va fuera del event loop."""
    try:
        lectura = codigos_excel.leer_codigos(datos, nombre)
    except ArchivoInvalido as e:
        raise HTTPException(422, str(e)) from e
    _guardar(username, lectura.codigos, nombre)
    return {**_resultado(username), "codigos_descartados": [c.completo for c in lectura.descartados]}


@router.post("")
async def subir(request: Request, nombre: str = Query("", max_length=255), username: str = Depends(auth)):
    limites.exigir_cupo(_subidas, username, "subida de listas de códigos")
    datos = await cuerpo.leer_con_tope(request, codigos_excel.MAX_BYTES, "El archivo es demasiado grande (máximo 1 MB).")
    return await run_in_threadpool(_procesar, username, datos, nombre)


@router.post("/al-itinerario")
def al_itinerario(username: str = Depends(auth)):
    """«Agregar al itinerario»: suma las charlas de la lista que todavía no están, fijadas. No marca la reserva."""
    return _agregar_al_itinerario(username)


@router.get("/ejemplo.xlsx")
def ejemplo():
    """Un Excel de ejemplo para completar y subir (ver app/codigos_ejemplo.py). Pide sesión como el resto del router."""
    return Response(codigos_ejemplo.generar(), media_type=codigos_ejemplo.MEDIA_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{codigos_ejemplo.NOMBRE}"'})


@router.get("")
def ver(username: str = Depends(auth)):
    return _resultado(username)


@router.delete("")
def borrar(username: str = Depends(auth)):
    with db.conn() as c:
        c.execute("DELETE FROM codigos_deseados WHERE username=%s", (username,))
    return SIN_LISTA
