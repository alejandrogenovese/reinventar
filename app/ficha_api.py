"""GET /api/ficha: «Mi ficha» de la persona (reglas en app/ficha.py).

Solo lee la base, siempre filtrando por el usuario de la sesión: nada de llamadas externas ni al LLM. Del viaje y los
documentos devuelve lo justo para la ficha (número y fecha del vuelo, nombre del hotel, cuántos documentos), nunca el
contenido de un documento ni sus notas.
"""
import datetime as dt

from fastapi import APIRouter, Depends

from . import db, estadia, vuelos
from . import ficha as reglas
from .auth import auth

router = APIRouter(prefix="/api/ficha", dependencies=[Depends(auth)])

MAX_INTERESES = 8

_CUENTAS = """
SELECT (SELECT count(*) FROM viajes_hoteles WHERE username=%(u)s) AS hoteles,
       (SELECT count(*) FROM viajes_documentos WHERE username=%(u)s) AS documentos,
       (SELECT count(*) FROM itinerary_items WHERE username=%(u)s AND kind='talk') AS charlas,
       (SELECT count(*) FROM codigos_deseados WHERE username=%(u)s) AS codigos_excel,
       (SELECT count(*) FROM passkeys WHERE username=%(u)s) AS passkeys,
       (SELECT count(*) FROM viajes_pendientes WHERE username=%(u)s AND borrado_en IS NULL) AS pendientes_total,
       (SELECT count(*) FROM viajes_pendientes WHERE username=%(u)s AND borrado_en IS NULL AND hecho_en IS NOT NULL)
         AS pendientes_hechos
"""


def _cuentas(username: str) -> dict:
    with db.conn() as c:
        return dict(c.execute(_CUENTAS, {"u": username}).fetchone())


def _perfil(p: dict | None) -> dict:
    """Rol, industria e intereses: la entrevista guiada si la hizo (más rica), si no el armado rápido."""
    p = p or {}
    rol = (p.get("respuestas") or {}).get("rol") or {}
    ficha = p.get("ficha") or {}
    temas = [x.get("tema") for x in ficha.get("prioridades") or [] if isinstance(x, dict) and x.get("tema")]
    intereses = temas or [x for x in p.get("interests") or [] if isinstance(x, str)]
    completo = bool(ficha) or bool(p.get("role") and p.get("interests"))
    return {"completo": completo, "rol": rol.get("texto") or p.get("role") or None,
            "industria": ficha.get("industria") or rol.get("industria") or None, "intereses": intereses[:MAX_INTERESES]}


def armar(username: str, ahora: dt.datetime) -> dict:
    perfil = _perfil(db.get_profile(username))
    lista_vuelos = vuelos.listar_vuelos(username)
    hoteles = vuelos.listar_hoteles(username)
    n = _cuentas(username)
    datos = reglas.DatosFicha(
        perfil_completo=perfil["completo"], fechas_vuelos=tuple(v["fecha"] for v in lista_vuelos),
        hoteles=n["hoteles"], documentos=n["documentos"], pendientes_hechos=n["pendientes_hechos"],
        pendientes_total=n["pendientes_total"], charlas=n["charlas"], codigos_excel=n["codigos_excel"], passkeys=n["passkeys"])
    faltantes = reglas.faltantes(datos)
    fase = reglas.fase(ahora)
    return {
        "usuario": username,
        "perfil": perfil,
        "viaje": {"vuelos": [{"id": v["id"], "numero": v["numero"], "fecha": v["fecha"]} for v in lista_vuelos],
                  "hoteles": [{"id": h["id"], "nombre": h["nombre"], "checkin": h["checkin"], "checkout": h["checkout"]}
                              for h in hoteles],
                  "ida": reglas.tiene_ida(datos.fechas_vuelos), "vuelta": reglas.tiene_vuelta(datos.fechas_vuelos)},
        "documentos": n["documentos"],
        "pendientes": {"hechos": n["pendientes_hechos"], "total": n["pendientes_total"]},
        "agenda": {"charlas": n["charlas"], "codigos_excel": n["codigos_excel"]},
        "passkeys": n["passkeys"],
        "fase": fase,
        "faltantes": [f.publico() for f in faltantes],
        "banner": [f.publico() for f in reglas.para_banner(faltantes, fase)],
    }


@router.get("")
def get_ficha(username: str = Depends(auth)):
    return armar(username, dt.datetime.now(estadia.TZ_VEGAS))
