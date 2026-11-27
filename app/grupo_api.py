"""«También van»: quién más del grupo tiene un horario en su itinerario, para coordinar quién graba qué.

Privacidad: solo se devuelve el nombre de usuario de cada uno (nada del resto de su agenda, ni horarios que no se
pidieron), nunca el de quien pregunta, ni el de cuentas desactivadas, ni el de quienes apagaron «mostrar mi agenda al
grupo» en Ajustes (preferencias_avisos.agenda_visible; prendida por defecto). Se piden horarios concretos por código: no
hay forma de listar la agenda de otra persona.
"""
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from . import db
from .auth import auth

router = APIRouter(prefix="/api/grupo", dependencies=[Depends(auth)])

CODIGOS_POR_PEDIDO = 20     # una ficha de charla tiene unos pocos horarios
CODIGO = re.compile(r"^[A-Za-z0-9._-]{1,40}$")

_TAMBIEN_VAN = """
SELECT i.code, i.username
FROM itinerary_items i
JOIN users u ON u.username = i.username AND u.is_active
LEFT JOIN preferencias_avisos p ON p.username = i.username
WHERE i.code = ANY(%s) AND i.kind = 'talk' AND i.username <> %s AND COALESCE(p.agenda_visible, TRUE)
ORDER BY i.code, i.username
"""


class Preferencia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agenda_visible: bool


def tambien_van(codigos: list[str], username: str) -> dict[str, list[str]]:
    """{código: [usuarios]} solo de los códigos con alguien más; el que pregunta no se cuenta."""
    with db.conn() as c:
        filas = c.execute(_TAMBIEN_VAN, (codigos, username)).fetchall()
    out: dict[str, list[str]] = {}
    for f in filas:
        out.setdefault(f["code"], []).append(f["username"])
    return out


def agenda_visible(username: str) -> bool:
    with db.conn() as c:
        r = c.execute("SELECT agenda_visible FROM preferencias_avisos WHERE username=%s", (username,)).fetchone()
    return r["agenda_visible"] if r else True


def set_agenda_visible(username: str, visible: bool) -> bool:
    with db.conn() as c:
        c.execute("INSERT INTO preferencias_avisos (username,grabar,ubicacion,updated_at) VALUES (%s,TRUE,FALSE,%s) "
                  "ON CONFLICT DO NOTHING", (username, time.time()))
        c.execute("UPDATE preferencias_avisos SET agenda_visible=%s, updated_at=%s WHERE username=%s",
                  (visible, time.time(), username))
    return agenda_visible(username)


@router.get("/tambien-van")
def get_tambien_van(codes: str = Query(..., max_length=900), username: str = Depends(auth)):
    lista = list(dict.fromkeys(c.strip() for c in codes.split(",") if c.strip()))
    if not lista or len(lista) > CODIGOS_POR_PEDIDO or not all(CODIGO.match(c) for c in lista):
        raise HTTPException(422, f"Pasá entre 1 y {CODIGOS_POR_PEDIDO} códigos de horario válidos")
    return tambien_van(lista, username)


@router.get("/preferencia")
def get_preferencia(username: str = Depends(auth)):
    return {"agenda_visible": agenda_visible(username)}


@router.put("/preferencia")
def put_preferencia(body: Preferencia, username: str = Depends(auth)):
    return {"agenda_visible": set_agenda_visible(username, body.agenda_visible)}
