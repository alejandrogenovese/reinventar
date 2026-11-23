"""Endpoints de «Cargar eventos desde Excel» (Eventos › Mis eventos): vista previa, confirmar y el Excel de ejemplo.

Sin estado en el servidor: la vista previa lee el archivo y no guarda nada; para confirmar se reenvía el mismo archivo
con `?confirmar=1`. El archivo viaja como cuerpo del pedido, con el nombre en `?nombre=` (igual que app/codigos_api.py).
Las filas con error no se guardan; un evento que ya no está en un archivo posterior se conserva."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool

from . import cuerpo, db, eventos_ejemplo, eventos_excel, limites, my_events, venues
from .auth import auth
from .eventos_excel import ACTUALIZA, ERROR, NUEVA, SIN_CAMBIOS, ArchivoInvalido

router = APIRouter(prefix="/api/my-events/excel", dependencies=[Depends(auth)])
SUBIDAS_POR_HORA = 20  # cuentan la vista previa y la confirmación
_subidas = limites.Limite(SUBIDAS_POR_HORA, limites.VENTANA_LARGA)


def _procesar(username: str, datos: bytes, nombre: str, confirmar: bool) -> dict:
    """Leer, comparar con lo guardado y, si confirma, guardar las filas sin error: bloqueante, va fuera del event loop."""
    try:
        filas = eventos_excel.leer_eventos(datos, nombre, venues.all_venues())
    except ArchivoInvalido as e:
        raise HTTPException(422, str(e)) from e
    estados = [eventos_excel.estado(f, db.get_user_event(username, f.id) if f.id else None) for f in filas]
    if confirmar:
        for fila, estado in zip(filas, estados, strict=True):
            if estado in (NUEVA, ACTUALIZA):
                my_events.guardar_con_id(username, fila.id, fila.evento)
    resumen = {k: estados.count(k) for k in (NUEVA, ACTUALIZA, SIN_CAMBIOS, ERROR)}
    return {"guardado": confirmar, "resumen": resumen,
            "filas": [eventos_excel.vista(f, e) for f, e in zip(filas, estados, strict=True)]}


@router.post("")
async def subir(request: Request, nombre: str = Query("", max_length=255), confirmar: bool = False,
                username: str = Depends(auth)):
    limites.exigir_cupo(_subidas, username, "carga de eventos desde Excel")
    datos = await cuerpo.leer_con_tope(request, eventos_excel.MAX_BYTES, "El archivo es demasiado grande (máximo 1 MB).")
    return await run_in_threadpool(_procesar, username, datos, nombre, confirmar)


@router.get("/ejemplo.xlsx")
def ejemplo():
    """Un Excel de ejemplo para completar y subir (ver app/eventos_ejemplo.py). Pide sesión como el resto del router."""
    return Response(eventos_ejemplo.generar(), media_type=eventos_ejemplo.MEDIA_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{eventos_ejemplo.NOMBRE}"'})
