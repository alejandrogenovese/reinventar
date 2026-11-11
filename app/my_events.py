"""Mis eventos: los que dan los proveedores y no están en la sección Eventos; cada persona carga los suyos.

Se guardan en user_events y entran al itinerario como un ítem fijado con kind = "mine" (código "mine-<id>"): así
ocupan su horario en el armado guiado y aparecen en Hoy y en los avisos push igual que el resto. Son privados.
El lugar es una sede de re:Invent, un lugar de Google Places (se ubica una sola vez, al guardarlo) o una dirección
escrita a mano (sin coordenadas).
"""
import uuid

from pydantic import BaseModel, Field, model_validator

from . import db, itinerary, places, venues

PREFIJO = "mine-"
TIPO = "Mi evento"
_DIA = r"^\d{4}-\d{2}-\d{2}$"
_HORA = r"^([01]\d|2[0-3]):[0-5]\d$"


class MiEvento(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    dia: str = Field(pattern=_DIA)
    inicio: str = Field(pattern=_HORA)
    fin: str | None = Field(None, pattern=_HORA)
    id_sede: int | None = None
    place_id: str | None = Field(None, pattern=places.PLACE_ID.pattern)
    sesion: str | None = Field(None, max_length=64)  # sessionToken del autocompletar
    direccion: str | None = Field(None, max_length=200)
    nota: str = Field("", max_length=500)

    @model_validator(mode="after")
    def _con_lugar(self):
        if self.id_sede is None and not self.place_id and not (self.direccion or "").strip():
            raise ValueError("Elegí una sede, un lugar o escribí la dirección")
        return self


class EventoInexistente(LookupError):
    pass


def _ubicar(body: MiEvento, anterior: dict | None) -> dict:
    """lugar, direccion, id_sede, place_id, lat y lng según lo que eligió."""
    if body.id_sede is not None:
        sede = venues.by_id(body.id_sede)
        if not sede:
            raise ValueError("Sede inexistente")
        return {"lugar": sede["name"], "direccion": sede["address"], "id_sede": sede["id"], "place_id": None,
                "lat": sede["lat"], "lng": sede["lng"]}
    if body.place_id:
        if anterior and anterior.get("place_id") == body.place_id:  # ya estaba ubicado: no se vuelve a pedir
            return {k: anterior[k] for k in ("lugar", "direccion", "id_sede", "place_id", "lat", "lng")}
        p = places.details(body.place_id, body.sesion)
        return {"lugar": p["nombre"] or p["direccion"], "direccion": p["direccion"], "id_sede": None,
                "place_id": p["place_id"] or body.place_id, "lat": p["lat"], "lng": p["lng"]}
    texto = body.direccion.strip()
    return {"lugar": texto, "direccion": None, "id_sede": None, "place_id": None, "lat": None, "lng": None}


def card(row: dict) -> dict:
    """Misma forma que las tarjetas de charlas y eventos (day, start, end, venue con lat/lng)."""
    codigo = PREFIJO + row["id"]
    return {
        "kind": "mine", "code": codigo, "base": codigo, "id": row["id"], "title": row["nombre"], "type": TIPO,
        "day": row["dia"], "start": row["inicio"], "end": row["fin"], "note": row["nota"] or "",
        "venue": {"hotel": row["lugar"], "detail": row["direccion"] if row["direccion"] != row["lugar"] else "",
                  "lat": row["lat"], "lng": row["lng"], "address": row["direccion"], "place_id": row["place_id"],
                  "id_sede": row["id_sede"]},
    }


def card_for_item(username: str, code: str) -> dict | None:
    row = db.get_user_event(username, code[len(PREFIJO):])
    return card(row) if row else None


def listar(username: str) -> list[dict]:
    return [card(r) for r in db.list_user_events(username)]


def _guardar(username: str, id_: str, body: MiEvento, anterior: dict | None) -> dict:
    datos = {"nombre": body.nombre.strip(), "dia": body.dia, "inicio": body.inicio, "fin": body.fin,
             "nota": body.nota.strip(), **_ubicar(body, anterior)}
    db.save_user_event(username, id_, datos)
    c = card(db.get_user_event(username, id_))
    # Fijado en el itinerario, con la foto al día: si lo edita la persona, no es un cambio para avisarle.
    db.add_item(username, c["code"], c["code"], c["day"], c["start"], locked=True, kind="mine",
                snapshot=itinerary.snapshot(c))
    return c


def crear(username: str, body: MiEvento) -> dict:
    return _guardar(username, uuid.uuid4().hex[:12], body, None)


def editar(username: str, id_: str, body: MiEvento) -> dict:
    anterior = db.get_user_event(username, id_)
    if not anterior:
        raise EventoInexistente("Evento inexistente")
    return _guardar(username, id_, body, anterior)


def borrar(username: str, id_: str) -> None:
    if not db.delete_user_event(username, id_):
        raise EventoInexistente("Evento inexistente")
    db.remove_item(username, PREFIJO + id_)
