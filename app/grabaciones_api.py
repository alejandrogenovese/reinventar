"""Grabaciones entre varios: aviso de grabación duplicada, quién puede tocar cada una, compartir el resumen y el link
público que vence.

- Se siguen compartiendo todas dentro de la app (ver y exportar, cualquiera con sesión). Reintentar, borrar y crear el
  link público: solo quien grabó o un admin; las viejas sin created_by, solo un admin.
- GET /api/sessions/activa?code=: si alguien más ya está grabando (o grabó hace un rato) esa charla, quién. La PWA lo
  consulta antes de empezar a grabar; si falla (sin señal), graba igual.
- GET /api/sessions/{sid}/resumen.md: el resumen para compartir (WhatsApp, copiar), sin lo personal.
- POST /api/sessions/{sid}/compartir: link /c/<token> de solo lectura que vence (app/grabaciones_links.py). En modo
  prueba responde 409: así un link nunca apunta a datos de prueba, y la ruta pública (que no tiene sesión) lee siempre
  las grabaciones reales.
- GET /c/<token>: la página pública (app/grabaciones_pagina.py). Cualquier falla, el mismo 404.
"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from . import db, grabaciones_links, grabaciones_pagina, limites, pipeline, push, sandbox, talks
from .auth import auth, is_admin
from .auth_api import ip_cliente

router = APIRouter()

NO_DUENO = "Solo quien grabó esta sesión (o un admin) puede hacer esto."
EN_PRUEBA = "Compartir por link no está disponible en modo prueba."
SIN_RESUMEN = "La grabación todavía no tiene resumen."


def puede_gestionar(s: dict, username: str) -> bool:
    """Reintentar, borrar y compartir por link: quien grabó o un admin. Las de antes de created_by (NULL), solo un admin."""
    return is_admin(username) or (s.get("created_by") is not None and s["created_by"] == username)


def sesion_gestionable(sid: str, username: str) -> dict:
    s = db.get_session(sid)
    if not s:
        raise HTTPException(404, "Sesión inexistente")
    if not puede_gestionar(s, username):
        raise HTTPException(403, NO_DUENO)
    return s


@router.get("/api/sessions/activa")
def activa(code: str = Query(min_length=1, max_length=40), username: str = Depends(auth)):
    """{"activa": {id, quien, status}} si otra persona ya graba (o grabó hace un rato) esa charla; {"activa": null} si no.
    Las propias no cuentan. Solo dice quién (el username, que es el nombre que se usa en la app)."""
    codigo = talks.normalize_code(code)
    s = push.grabacion_en_curso(codigo, excluir=username) if codigo else None
    if not s:
        return {"activa": None}
    return {"activa": {"id": s["id"], "quien": s["created_by"] or None, "status": s["status"]}}


@router.get("/api/sessions/{sid}/resumen.md", dependencies=[Depends(auth)])
def resumen_md(sid: str):
    s = db.get_session(sid)
    if not s:
        raise HTTPException(404, "Sesión inexistente")
    if s["status"] != "ready" or not s.get("summary"):
        raise HTTPException(409, SIN_RESUMEN)
    return PlainTextResponse(pipeline.to_markdown_publico(s), media_type="text/markdown; charset=utf-8")


@router.post("/api/sessions/{sid}/compartir")
def compartir(sid: str, request: Request, username: str = Depends(auth)):
    if sandbox.actual() is not None:
        raise HTTPException(409, EN_PRUEBA)
    s = sesion_gestionable(sid, username)
    if s["status"] != "ready" or not s.get("summary"):
        raise HTTPException(409, SIN_RESUMEN)
    token, vence = grabaciones_links.firmar(sid)
    return {"url": f"{str(request.base_url).rstrip('/')}{grabaciones_links.ruta(token)}",
            "vence": dt.datetime.fromtimestamp(vence, dt.UTC).isoformat()}


@router.get("/c/{token}", include_in_schema=False)
def pagina_publica(token: str, request: Request):
    if not limites.links_grabacion.consumir(ip_cliente(request)):
        return grabaciones_pagina.no_encontrado(429, "Demasiados pedidos. Esperá unos minutos y probá de nuevo.")
    sid = grabaciones_links.verificar(token)
    with sandbox.real():  # sin sesión no hay sandbox, pero por las dudas: siempre los datos reales
        s = db.get_session(sid) if sid else None
    if not s or s["status"] != "ready" or not s.get("summary"):
        return grabaciones_pagina.no_encontrado()
    return grabaciones_pagina.pagina(pipeline.resumen_publico(s))
