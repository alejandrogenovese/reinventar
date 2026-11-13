"""👍/👎 sobre el resumen de una grabación: si le sirvió a quien lo leyó.

- Un voto por persona y grabación (si lo cambia, se pisa; lo puede retirar). Se guarda en la base (voto_resumen) para
  mostrar qué votó cada uno y cuántos votaron.
- Además va a Langfuse como score "util" (1 = sirvió, 0 = no) sobre la traza de la grabación
  (trazas.id_grabacion): así el tablero de LLM muestra qué porcentaje de los resúmenes sirven, por versión del prompt.
  El id del score lleva un hash del usuario (no el nombre): uno por persona, y retirar el voto lo borra.
- Sin claves de Langfuse, el voto se guarda igual.
"""
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from . import db, langfuse_scores, limites, trazas
from .auth import auth

router = APIRouter(prefix="/api/sessions/{sid}/voto")

NOMBRE_SCORE = "util"  # el que ya espera el tablero de LLM (langfuse_metricas.SCORES)
VOTOS_POR_HORA = 60  # alcanza para votar todas las grabaciones del día; frena a quien quiera spamear Langfuse
LARGO_HASH_USUARIO = 12
_votos = limites.Limite(VOTOS_POR_HORA, ventana=3600)


class Voto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    util: bool


def id_score(sid: str, username: str) -> str:
    usuario = hashlib.sha256(username.encode()).hexdigest()[:LARGO_HASH_USUARIO]
    return f"{trazas.id_grabacion(sid)}-{NOMBRE_SCORE}-{usuario}"


def _con_resumen_o_error(sid: str) -> None:
    s = db.get_session(sid)
    if not s:
        raise HTTPException(404, "Sesión inexistente")
    if not s.get("summary"):
        raise HTTPException(409, "Esta grabación todavía no tiene resumen")


def _limite(username: str) -> None:
    if _votos.excedido(username):
        raise HTTPException(429, "Demasiados votos: probá en un rato")
    _votos.sumar(username)


@router.put("")
def votar(sid: str, body: Voto, username: str = Depends(auth)):
    _con_resumen_o_error(sid)
    _limite(username)
    db.set_voto_resumen(sid, username, body.util)
    langfuse_scores.enviar(trazas.id_grabacion(sid), NOMBRE_SCORE, 1.0 if body.util else 0.0,
                           id_score=id_score(sid, username))
    return db.votos_resumen(sid, username)


@router.delete("")
def retirar(sid: str, username: str = Depends(auth)):
    if not db.get_session(sid):
        raise HTTPException(404, "Sesión inexistente")
    _limite(username)
    db.delete_voto_resumen(sid, username)
    langfuse_scores.borrar(id_score(sid, username))
    return db.votos_resumen(sid, username)
